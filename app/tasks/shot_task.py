"""
分镜图片生成任务
支持批量生成创作下所有分镜的图片
"""
import os
import uuid
import time
import json
from typing import List, Dict, Any
from concurrent.futures import ThreadPoolExecutor, as_completed
import httpx

from app.core.celery_app import celery_app
from app.db.session import SessionLocal
from sqlalchemy.orm import Session, selectinload
from sqlalchemy.orm.attributes import flag_modified
from app.models.creation import Creation
from app.models.scene import Scene
from app.models.shot import Shot
from app.schemas.creation import CreationStatus
from app.core.exceptions import NotFoundError, BaseServiceException
from app.utils.task_types import TaskType
from app.utils.ai_client import AIClient
from app.core.logger import logger
from app.utils.us3 import US3Client
from app.utils.upload_helper import upload_helper
from app.utils.points_deduction import deduct_points_for_image
from app.core.config import settings
from app.models.user import User
from datetime import datetime
from app.services.points_service import PointsService
from app.core.exceptions import InsufficientPointsError
from app.utils.model_prices import ModelPrices
from app.services.model_config_service import ModelConfigService
import math



def _generate_single_shot_image(shot_id: int, creation_id: int, freeze_record_id: int = None, force_regen_prompt: bool = False, model_name: str = None, frame_type: str = "both") -> dict:
    """
    生成单个分镜的图片（线程安全函数，使用图生图）
    
    Args:
        shot_id: 分镜ID
        creation_id: 创作ID（用于生成存储路径）
        freeze_record_id: 冻结记录ID
        force_regen_prompt: 是否强制重新生成提示词
        model_name: 使用的模型名称
        frame_type: 生成帧类型 - "start"=仅首帧, "end"=仅尾帧, "both"=首尾帧
        包含分镜ID和处理结果的字典
        
    Raises:
        NotFoundError: 分镜不存在
        Exception: 生图失败
    """
    db: Session = SessionLocal()
    temp_file_path = None
    start_time = time.perf_counter()
    timings: Dict[str, float] = {}
    try:
        # 加载shot及其关联的角色和场景
        shot = (
            db.query(Shot)
            .options(
                selectinload(Shot.scene),
                selectinload(Shot.characters)
            )
            .filter(Shot.shot_id == shot_id)
            .first()
        )
        if not shot:
            raise NotFoundError(detail=f"分镜不存在: shot_id={shot_id}")
        # 记录初始加载状态
        initial_image_url = shot.image_url
        initial_image_prompt = shot.image_prompt
        logger.info(f"DEBUG: Shot loaded. shot_id={shot_id}, frame_type={frame_type}")
        logger.info(f"DEBUG: initial image_url={initial_image_url}, image_prompt_len={len(initial_image_prompt) if initial_image_prompt else 0}")
        
        # 注意：不再根据已有图片提前返回，因为用户可能想重新生成特定帧
        
        # 检查是否有分镜描述（用于生成prompt）
        if not shot.description and not shot.image_prompt:
            total_sec = round(time.perf_counter() - start_time, 3)
            logger.warning(f"分镜 {shot_id} 没有分镜描述或图片提示词，跳过生成 | total_sec={total_sec}s")
            return {
                "shot_id": shot_id,
                "shot_title": shot.title,
                "success": False,
                "error": "没有分镜描述或图片提示词",
                "skipped": True,
                "duration_sec": total_sec,
            }
        
        # 获取关联的角色及其图片URL
        # 只处理出镜角色，跳过声音角色（声音角色 basic_info == "声音角色"）
        character_images = []
        character_profiles = []
        for character in shot.characters:
            # 跳过声音角色
            if character.basic_info == "声音角色":
                logger.info(f"跳过声音角色 {character.name}，不加入图片提示词生成")
                continue

            if character.image_url:
                character_images.append(character.image_url)
                # 构建角色档案描述
                profile_parts = []
                if character.name:
                    profile_parts.append(f"姓名: {character.name}")
                if character.appearance:
                    profile_parts.append(f"外貌: {character.appearance}")
                if character.body:
                    profile_parts.append(f"身材: {character.body}")
                if character.hair:
                    profile_parts.append(f"发型: {character.hair}")
                if character.clothing:
                    profile_parts.append(f"服装: {character.clothing}")
                if profile_parts:
                    character_profiles.append("，".join(profile_parts))
        
        # 添加场景图片作为参考图（如果有）
        if shot.scene and shot.scene.image_url:
            logger.info(f"分镜 {shot_id} 添加场景图片作为参考: {shot.scene.image_url}")
            character_images.append(shot.scene.image_url)
        
        # 统一使用同一个模型生成图片；参考图列表可为空
        logger.info(f"分镜 {shot_id} 参考图片数量: {len(character_images)}，统一使用图生图模型")
        
        # 获取上一分镜的描述（用于上下文连贯性）
        # 优先使用提示词，如果不存在则使用旁白，如果上一分镜不存在则留空
        previous_shot_description = None
        if shot.shot_number > 1:
            # 查找同一场景中上一个分镜
            previous_shot = (
                db.query(Shot)
                .filter(
                    Shot.scene_id == shot.scene_id,
                    Shot.shot_number < shot.shot_number
                )
                .order_by(Shot.shot_number.desc())
                .first()
            )
            if previous_shot:
                # 优先使用image_prompt（提示词），如果不存在则使用narration（旁白）
                # 不使用description（描述）
                # 修改：对于上一个分镜，我们更需要它的最终提示词内容作为视觉参考，如果没有，则使用旁白。
                # 同时我们不仅传递内容，还明确这是上一分镜的视觉描述
                if previous_shot.image_prompt:
                    previous_shot_description = f"上一分镜视觉描述：{previous_shot.image_prompt}"
                elif previous_shot.narration:
                    # narration 可能是一个 JSON 列表，需要处理
                    if isinstance(previous_shot.narration, list):
                        narration_text = " ".join([item.get("内容", "") for item in previous_shot.narration if isinstance(item, dict)])
                    else:
                        narration_text = str(previous_shot.narration)
                    previous_shot_description = f"上一分镜内容描述：{narration_text}"
                
                if previous_shot_description:
                    logger.info(f"找到上一分镜上下文: {previous_shot.shot_id} (使用{'提示词' if previous_shot.image_prompt else '旁白'})")
        
        # 从创作配置中获取模型配置
        creation = shot.scene.creation
        extra_data = creation.extra_data or {}
        image_to_image_model = model_name or extra_data.get("image_to_image_model") or settings.IMAGE_MODEL_NAME
        text_to_image_model = model_name or extra_data.get("text_to_image_model") or settings.IMAGE_MODEL_NAME # 兼容旧字段，实际不再区分
        
        # 使用LLM生成英文提示词
        llm_model = extra_data.get("llm_model") or settings.LLM_MODEL_NAME
        ai_client = AIClient(
            llm_model_name=llm_model,
            image_to_image_model=image_to_image_model,
            text_to_image_model=text_to_image_model
        )
        
        # 获取创作的宽高比设置
        creation = shot.scene.creation
        extra_data = creation.extra_data or {}
        aspect_ratio_type = extra_data.get("aspect_ratio", "16:9")
        
        # 提示词逻辑：
        # - both: 检查首帧和尾帧提示词是否都存在，有一个不存在则两个都重新生成
        # - start: 检查首帧提示词是否存在，不存在则重新生成首尾帧提示词
        # - end: 检查尾帧提示词是否存在，不存在则重新生成首尾帧提示词
        image_prompt = shot.image_prompt or ""
        end_frame_prompt = (shot.extra_data or {}).get("end_frame_image_prompt")
        
        # 根据 frame_type 决定是否需要重新生成提示词
        need_regen_prompt = force_regen_prompt
        if not need_regen_prompt:
            if frame_type == "both":
                # both: 首帧或尾帧提示词缺失则重新生成
                if not image_prompt or not end_frame_prompt:
                    need_regen_prompt = True
                    logger.info(f"分镜 {shot_id} [both] 提示词不完整（首帧: {'有' if image_prompt else '无'}, 尾帧: {'有' if end_frame_prompt else '无'}），重新生成")
            elif frame_type == "start":
                # start: 首帧提示词缺失则重新生成
                if not image_prompt:
                    need_regen_prompt = True
                    logger.info(f"分镜 {shot_id} [start] 首帧提示词缺失，重新生成")
            elif frame_type == "end":
                # end: 尾帧提示词缺失则重新生成
                if not end_frame_prompt:
                    need_regen_prompt = True
                    logger.info(f"分镜 {shot_id} [end] 尾帧提示词缺失，重新生成")
        
        if not need_regen_prompt:
            logger.info(f"分镜 {shot_id} [{frame_type}] 提示词已存在，无需重新生成")
            logger.info(f"DEBUG: 使用现有提示词，image_prompt_len={len(image_prompt)}, end_frame_prompt_len={len(end_frame_prompt) if end_frame_prompt else 0}")
            timings["prompt_sec"] = 0
        else:
            logger.info(f"DEBUG: 需要重新生成提示词，当前 shot.image_url={shot.image_url}")
            # 重新生成提示词（首帧和尾帧同时生成）
            current_shot_description = shot.description or ""
            
            # 构建环境设定描述
            environment_desc = "无"
            if shot.scene:
                env_config = {
                    "时间": shot.scene.time_setting or "未知",
                    "地点": shot.scene.location or "未知",
                    "空间": shot.scene.space_type or "未知",
                    "氛围": shot.scene.atmosphere or "未知"
                }
                environment_desc = json.dumps(env_config, ensure_ascii=False, indent=2)
            
            # 获取分镜中的出镜元素
            appearance_elements = (shot.extra_data or {}).get("appearance_elements", [])
            
            # 生成提示词
            logger.info(f"分镜 {shot_id} [{frame_type}] 开始生成提示词（参考图数量: {len(character_images)}，出镜元素数量: {len(appearance_elements)}，宽高比: {aspect_ratio_type}）")
            prompt_start = time.perf_counter()
            # 获取创作风格
            visual_style = extra_data.get("visual_style")
            
            prompt_result = ai_client.generate_shot_image_prompt(
                character_profiles=character_profiles,
                previous_shot_description=previous_shot_description,
                current_shot_description=current_shot_description,
                environment_desc=environment_desc,
                appearance_elements=appearance_elements,
                image_model=image_to_image_model,
                aspect_ratio=aspect_ratio_type,
                visual_style=visual_style
            )
            timings["prompt_sec"] = round(time.perf_counter() - prompt_start, 3)
            
            # 兼容处理：V2 返回字符串，V3 返回字典
            if isinstance(prompt_result, dict):
                image_prompt = prompt_result.get("prompt") or prompt_result.get("start_frame_prompt", "")
                end_frame_prompt = prompt_result.get("end_frame_prompt")
                logger.info(f"V3 提示词生成成功：首帧长度={len(image_prompt)}, 尾帧长度={len(end_frame_prompt) if end_frame_prompt else 0}")
            else:
                image_prompt = prompt_result
                end_frame_prompt = None
                logger.info(f"V2 提示词生成成功：长度={len(image_prompt)}")
            
            # 保存生成的提示词到数据库
            # 注意：根据 frame_type 决定更新哪些字段
            try:
                # 保存当前的 image_url，避免 refresh 后丢失
                preserved_image_url = shot.image_url
                
                # 只有在 frame_type 为 "start" 或 "both" 时才更新首帧提示词
                if frame_type in ("start", "both"):
                    shot.image_prompt = image_prompt
                    logger.info(f"分镜 {shot_id} [{frame_type}] 更新首帧提示词")
                
                # 如果有尾帧提示词，保存到 extra_data
                if end_frame_prompt:
                    if shot.extra_data is None:
                        shot.extra_data = {}
                    shot.extra_data["end_frame_image_prompt"] = end_frame_prompt
                    flag_modified(shot, "extra_data")
                    logger.info(f"分镜 {shot_id} [{frame_type}] 更新尾帧提示词")
                
                # 详细日志：commit 前的状态
                logger.info(f"DEBUG [提示词commit前]: shot.image_url={shot.image_url}, shot.image_prompt长度={len(shot.image_prompt) if shot.image_prompt else 0}")
                logger.info(f"DEBUG [提示词commit前]: preserved_image_url={preserved_image_url}, initial_image_url={initial_image_url}")
                
                db.add(shot)
                db.commit()
                
                # 详细日志：commit 后、refresh 前的状态
                logger.info(f"DEBUG [commit后refresh前]: shot.image_url={shot.image_url}")
                
                db.refresh(shot)
                
                # 详细日志：refresh 后的状态
                logger.info(f"DEBUG [refresh后]: shot.image_url={shot.image_url}, shot.image_prompt长度={len(shot.image_prompt) if shot.image_prompt else 0}")
                
                # 恢复 preserved_image_url（防止 refresh 加载了错误值）
                if preserved_image_url and shot.image_url != preserved_image_url:
                    logger.warning(f"分镜 {shot_id} refresh 后 image_url 变化：{shot.image_url} -> {preserved_image_url}，恢复原值")
                    shot.image_url = preserved_image_url
                
                # 额外保障：使用 initial_image_url
                if initial_image_url and shot.image_url != initial_image_url:
                    logger.warning(f"分镜 {shot_id} 使用 initial_image_url 恢复：{shot.image_url} -> {initial_image_url}")
                    shot.image_url = initial_image_url
                
                logger.info(f"分镜 {shot_id} 提示词已保存到数据库（含尾帧提示词: {'是' if end_frame_prompt else '否'}）")
            except Exception as e:
                logger.error(f"分镜 {shot_id} 提示词保存失败: {str(e)}")
                # 保存失败不影响图片生成，继续执行


        # 打印详细的生图信息方便调试
        logger.info("=" * 50)
        logger.info(f"【分镜 {shot_id} 生图信息】")
        logger.info(f"提示词 (Prompt): {image_prompt}")
        logger.info(f"参考图列表 ({len(character_images)}张):")
        for idx, img_url in enumerate(character_images):
            logger.info(f"  {idx + 1}. {img_url}")
        logger.info("=" * 50)
        
        # 使用同一模型生成图片；参考图可为空
        logger.info(f"开始为分镜 {shot_id} 调用图生图接口，参考图数量: {len(character_images)}")
        
        # 根据创作比例确定图片尺寸
        creation = shot.scene.creation
        extra_data = creation.extra_data or {}
        aspect_ratio_type = extra_data.get("aspect_ratio", "16:9")
        if aspect_ratio_type == "9:16":
            image_size = "864x1536"
        else:
            image_size = "1536x864"
            
        logger.info(f"分镜图片生成，比例: {aspect_ratio_type}, 尺寸: {image_size}, 帧类型: {frame_type}")

        # 获取用户UUID和时间戳用于构建上传路径（供首帧和尾帧使用）
        user_id = creation.owner_id
        user = db.query(User).filter(User.user_id == user_id).first()
        if not user:
            raise ValueError(f"用户不存在: user_id={user_id}")
        user_uuid = user.uuid
        time_str = datetime.now().strftime('%Y%m%d')

        # 根据 frame_type 决定生成逻辑
        # 重要：保留现有的首帧 URL，避免在仅生成尾帧时丢失
        # 关键修复：当 frame_type="end" 时，需要从数据库重新查询最新的 image_url
        # 因为可能在当前任务加载 shot 后，其他任务已经更新了 image_url
        if frame_type == "end":
            # 强制从数据库获取最新的 image_url，避免使用过时的缓存值
            db.expire(shot, ['image_url'])
            db.refresh(shot, ['image_url'])
            logger.info(f"分镜 {shot_id} [end] 刷新后 image_url={shot.image_url}")
        
        preserved_start_frame_url = shot.image_url  # 保存原始的首帧 URL
        image_url = shot.image_url  # 保留现有的首帧 URL
        logger.info(f"分镜 {shot_id} [{frame_type}] 开始生成图片，当前 image_url={image_url}")
        
        # 生成首帧图片（frame_type 为 "start" 或 "both"）
        if frame_type in ("start", "both"):
            image_start = time.perf_counter()
            temp_image_url = ai_client.generate_image_by_reference(
                prompt=image_prompt,
                reference_images=character_images,  # 可为空
                model=image_to_image_model,  # 使用配置的模型
                aspect_ratio=image_size
            )
            timings["image_api_sec"] = round(time.perf_counter() - image_start, 3)
        
            # 从本地/URL 获取图像并上传到US3进行持久化（使用流式上传）
            try:
                persist_start = time.perf_counter()
                image_data = None
                image_extension = ".png"
                
                # 检查是否为本地文件标识（Nano Banana2 返回格式为 "local://..."）
                if temp_image_url.startswith("local://"):
                    # 读取本地文件为字节流
                    temp_file_path = temp_image_url.replace("local://", "")
                    logger.info(f"使用本地文件路径: {temp_file_path}")
                    if not os.path.exists(temp_file_path):
                        raise Exception(f"本地文件不存在: {temp_file_path}")
                    # 从文件后缀推断扩展名，兜底为 .png
                    _, ext = os.path.splitext(temp_file_path)
                    image_extension = ext or ".png"
                    # 读取文件为字节流
                    with open(temp_file_path, 'rb') as f:
                        image_data = f.read()
                    logger.info(f"本地图像读取成功，大小: {len(image_data)} 字节")
                else:
                    # 从URL下载图像
                    logger.info(f"从URL下载图像: {temp_image_url}")
                    # 使用配置的超时时间，而不是硬编码的30秒
                    timeout_config = httpx.Timeout(
                        connect=10.0,
                        read=settings.AI_IMAGE_DOWNLOAD_TIMEOUT,  # 使用配置的超时时间（默认60秒）
                        write=10.0,
                        pool=10.0,
                    )
                    with httpx.Client(timeout=timeout_config) as client:
                        response = client.get(temp_image_url)
                        response.raise_for_status()
                        image_data = response.content
                    logger.info(f"图像下载成功，大小: {len(image_data)} 字节")
                
                
                # 使用流式上传
                # 文件名格式: shots/{creation_id}/{shot_id}/image_{uuid}{extension}
                image_uuid = str(uuid.uuid4())
                filename = f"shots/{creation_id}/{shot_id}/image_{image_uuid}{image_extension}"
                
                upload_result = upload_helper.upload_file_stream(
                    file_data=image_data,
                    user_uuid=user_uuid,
                    file_type="shots",  # 文件类型
                    filename=filename,
                    time_str=time_str
                )
                
                if not upload_result.get('success'):
                    error_msg = f"图像上传US3失败: {upload_result.get('message')}"
                    logger.error(error_msg)
                    raise Exception(error_msg)
                
                # 使用外网URL保存到数据库
                image_url = upload_result.get('external_url', upload_result.get('put_key'))
                logger.info(f"首帧图像流式上传US3成功，持久化URL: {image_url}")
                
                timings["persist_sec"] = round(time.perf_counter() - persist_start, 3)
                
            except Exception as e:
                # 如果US3上传失败，必须抛出异常，因为临时URL（特别是local://）无法被前端访问
                error_msg = f"首帧图像上传US3失败: {str(e)}"
                logger.error(error_msg, exc_info=True)
                raise Exception(error_msg)
            
            # 更新分镜信息（首帧）
            shot.image_url = image_url
            logger.info(f"分镜 {shot_id} 首帧生成完成，image_url={image_url}")
        
        # ============ 尾帧图片生成（frame_type 为 "end" 或 "both" 且有尾帧提示词）============
        end_frame_image_url = (shot.extra_data or {}).get("end_frame_image_url")  # 保留现有尾帧 URL
        should_generate_end_frame = frame_type in ("end", "both") and end_frame_prompt
        if should_generate_end_frame:
            logger.info(f"DEBUG: 开始生成尾帧。当前 shot.image_url={shot.image_url}")
            logger.info(f"分镜 {shot_id} 开始生成尾帧图片...")
            try:
                end_frame_start = time.perf_counter()
                end_frame_temp_url = ai_client.generate_image_by_reference(
                    prompt=end_frame_prompt,
                    reference_images=character_images,
                    model=image_to_image_model,
                    aspect_ratio=image_size
                )
                timings["end_frame_image_api_sec"] = round(time.perf_counter() - end_frame_start, 3)
                
                # 下载并上传尾帧图片
                end_frame_persist_start = time.perf_counter()
                end_frame_image_data = None
                end_frame_extension = ".png"
                
                if end_frame_temp_url.startswith("local://"):
                    end_frame_temp_path = end_frame_temp_url.replace("local://", "")
                    logger.info(f"尾帧使用本地文件路径: {end_frame_temp_path}")
                    if os.path.exists(end_frame_temp_path):
                        _, ext = os.path.splitext(end_frame_temp_path)
                        end_frame_extension = ext or ".png"
                        with open(end_frame_temp_path, 'rb') as f:
                            end_frame_image_data = f.read()
                        logger.info(f"尾帧本地图像读取成功，大小: {len(end_frame_image_data)} 字节")
                else:
                    logger.info(f"从URL下载尾帧图像: {end_frame_temp_url}")
                    timeout_config = httpx.Timeout(
                        connect=10.0,
                        read=settings.AI_IMAGE_DOWNLOAD_TIMEOUT,
                        write=10.0,
                        pool=10.0,
                    )
                    with httpx.Client(timeout=timeout_config) as client:
                        response = client.get(end_frame_temp_url)
                        response.raise_for_status()
                        end_frame_image_data = response.content
                    logger.info(f"尾帧图像下载成功，大小: {len(end_frame_image_data)} 字节")
                
                if end_frame_image_data:
                    # 上传尾帧图片
                    end_frame_uuid = str(uuid.uuid4())
                    end_frame_filename = f"shots/{creation_id}/{shot_id}/end_frame_{end_frame_uuid}{end_frame_extension}"
                    
                    end_frame_upload_result = upload_helper.upload_file_stream(
                        file_data=end_frame_image_data,
                        user_uuid=user_uuid,
                        file_type="shots",
                        filename=end_frame_filename,
                        time_str=time_str
                    )
                    
                    if end_frame_upload_result.get('success'):
                        end_frame_image_url = end_frame_upload_result.get('external_url', end_frame_upload_result.get('put_key'))
                        logger.info(f"尾帧图像上传US3成功: {end_frame_image_url}")
                        
                        # 保存尾帧 URL 到 extra_data
                        if shot.extra_data is None:
                            shot.extra_data = {}
                        shot.extra_data["end_frame_image_url"] = end_frame_image_url
                        flag_modified(shot, "extra_data")
                    else:
                        logger.warning(f"尾帧图像上传US3失败: {end_frame_upload_result.get('message')}")
                
                timings["end_frame_persist_sec"] = round(time.perf_counter() - end_frame_persist_start, 3)
                
            except Exception as e:
                # 尾帧生成失败不影响整体任务，只记录警告
                logger.warning(f"分镜 {shot_id} 尾帧图片生成失败: {str(e)}")
                timings["end_frame_error"] = str(e)
        
        shot.status = "completed"
        
        # 确保 frame_type="end" 时首帧 URL 不丢失
        # 关键修复：使用多个来源确保首帧 URL 不丢失
        if frame_type == "end":
            # 优先级：preserved_start_frame_url > initial_image_url > 当前 shot.image_url
            # preserved_start_frame_url 是在生成图片前刷新数据库后保存的值，最可靠
            if preserved_start_frame_url:
                if shot.image_url != preserved_start_frame_url:
                    logger.warning(f"分镜 {shot_id} [end] 使用 preserved_start_frame_url 恢复首帧 URL: {shot.image_url} -> {preserved_start_frame_url}")
                    shot.image_url = preserved_start_frame_url
            elif initial_image_url:
                if shot.image_url != initial_image_url:
                    logger.warning(f"分镜 {shot_id} [end] 使用 initial_image_url 恢复首帧 URL: {shot.image_url} -> {initial_image_url}")
                    shot.image_url = initial_image_url
            # 如果两个保存的值都是 None，说明首帧确实还没生成，保持 shot.image_url 不变
            elif not shot.image_url:
                logger.info(f"分镜 {shot_id} [end] 首帧 URL 为空，首帧可能尚未生成")
        
        logger.info(f"Commit前的状态检查: shot.image_url={shot.image_url}, preserved_start_frame_url={preserved_start_frame_url}, initial_image_url={initial_image_url}")
        
        db.commit()
        db.refresh(shot)
        
        # 保存图片生成历史到 shot.extra_data
        try:
            if shot.extra_data is None:
                shot.extra_data = {}
            
            image_history = shot.extra_data.get('image_history', [])
            
            new_image_record = {
                "version_id": str(uuid.uuid4()),
                "image_url": image_url,
                "end_frame_image_url": end_frame_image_url,
                "image_prompt": shot.image_prompt,
                "model_name": image_to_image_model,
                "visual_style": visual_style,
                "generated_at": datetime.now().isoformat(),
                "success": True,
                "file_size": len(image_data) if image_data else None,
                "duration_sec": total_sec,
                "character_refs": len(character_images),
                "is_current": False  # 标记为非当前版本
            }
            
            image_history.append(new_image_record)
            shot.extra_data['image_history'] = image_history
            
            db.commit()
            db.refresh(shot)
            logger.info(f"分镜 {shot_id} 图片生成历史保存成功")
        except Exception as e:
            logger.error(f"保存分镜 {shot_id} 图片生成历史失败: {str(e)}")
            # 历史保存失败不影响主流程
        
        # 确认扣除冻结的积分（任务成功）
        if freeze_record_id:
            try:
                PointsService.confirm_frozen_points(
                    db=db,
                    freeze_record_id=freeze_record_id
                )
                logger.info(f"分镜 {shot_id} 图片生成成功，已确认扣除冻结积分: freeze_record_id={freeze_record_id}")
            except Exception as e:
                logger.opt(exception=True).error("确认扣除冻结积分失败: {}", str(e))
                # 确认失败不影响任务完成，但需要记录错误
        
        total_sec = round(time.perf_counter() - start_time, 3)
        logger.info(
            f"分镜 {shot.title}(ID: {shot_id}) 图片生成成功 | "
            f"model={image_to_image_model} | refs={len(character_images)} | "
            f"timings={timings} | total_sec={total_sec}s | 尾帧={'有' if end_frame_image_url else '无'}"
        )
        return {
            "shot_id": shot_id,
            "shot_title": shot.title,
            "success": True,
            "image_url": image_url,
            "end_frame_image_url": end_frame_image_url,
            "duration_sec": total_sec,
            "timings": timings,
        }
    except Exception as e:
        logger.opt(exception=True).error("分镜 {} 图片生成失败: {}", shot_id, str(e))
        
        # 任务失败，释放冻结的积分
        if freeze_record_id:
            try:
                PointsService.release_frozen_points(
                    db=db,
                    freeze_record_id=freeze_record_id,
                    reason=f"图片生成失败：{str(e)}"
                )
                logger.info(f"分镜 {shot_id} 图片生成失败，已释放冻结积分: freeze_record_id={freeze_record_id}")
            except Exception as release_error:
                logger.opt(exception=True).error("释放冻结积分失败: {}", str(release_error))
        
        # 尝试更新状态为 failed
        try:
            shot = db.query(Shot).filter(Shot.shot_id == shot_id).first()
            if shot:
                shot.status = "failed"
                db.commit()
        except:
            pass

        db.rollback()
        total_sec = round(time.perf_counter() - start_time, 3)
        logger.warning(
            f"分镜 {shot_id} 图片生成失败 | total_sec={total_sec}s | timings={timings} | error={str(e)}"
        )
        return {
            "shot_id": shot_id,
            "success": False,
            "error": str(e),
            "duration_sec": total_sec,
            "timings": timings,
        }
    finally:
        db.close()


@celery_app.task(
    bind=True,
    name="generate_single_shot_image_task",
    autoretry_for=(Exception,),
    max_retries=1,
    retry_backoff=True,
)
def generate_single_shot_image_task(self, shot_id: int, creation_id: int, freeze_record_id: int = None, force_regen_prompt: bool = False, model_name: str = None, frame_type: str = "both") -> dict:
    """
    Celery任务：生成单个分镜的图片
    
    Args:
        shot_id: 分镜ID
        creation_id: 创作ID
        freeze_record_id: 冻结记录ID（可选，如果提供则使用冻结机制）
        force_regen_prompt: 是否强制重新生成提示词
        model_name: 使用的模型名称
        frame_type: 生成帧类型 - "start"=仅首帧, "end"=仅尾帧, "both"=首尾帧
        
    Returns:
        包含分镜ID和处理结果的字典
    """
    logger.info(f"开始执行分镜图片生成任务: shot_id={shot_id}, creation_id={creation_id}, freeze_record_id={freeze_record_id}, force_regen_prompt={force_regen_prompt}, model_name={model_name}, frame_type={frame_type}")
    
    # 如未传入冻结记录，则在这里计算并冻结积分（单张生成）
    if not freeze_record_id:
        db: Session = SessionLocal()
        try:
            shot_obj = (
                db.query(Shot)
                .options(selectinload(Shot.characters), selectinload(Shot.scene).selectinload(Scene.creation))
                .filter(Shot.shot_id == shot_id)
                .first()
            )
            if not shot_obj:
                return {
                    "shot_id": shot_id,
                    "creation_id": creation_id,
                    "success": False,
                    "error": "分镜不存在",
                }
            
            creation = shot_obj.scene.creation
            if not creation:
                return {
                    "shot_id": shot_id,
                    "creation_id": creation_id,
                    "success": False,
                    "error": "创作不存在",
                }
            
            extra_data = creation.extra_data or {}
            image_model = (
                model_name
                or extra_data.get("image_to_image_model")
                or extra_data.get("text_to_image_model")
                or settings.IMAGE_MODEL_IMAGE_TO_IMAGE
                or settings.IMAGE_MODEL_TEXT_TO_IMAGE
                or settings.IMAGE_MODEL_NAME
                or "black-forest-labs/flux-kontext-pro/multi"
            )
            try:
                model_config = ModelConfigService.get_model_config(image_model, "image_to_image")
                image_size = model_config.get("image_size", "2K") if model_config else "2K"
            except Exception:
                image_size = "2K"
            
            # 参考图数量
            ref_count = 0
            if shot_obj.characters:
                ref_count = sum(1 for c in shot_obj.characters if getattr(c, "image_url", None))
            
            cost_per_image = ModelPrices.calculate_image_cost(
                image_model,
                1,
                reference_image_count=ref_count,
                image_size=image_size
            )
            required_points = int(math.ceil(cost_per_image * 100))
            if required_points <= 0:
                required_points = 1
            
            freeze_record = PointsService.freeze_points(
                db=db,
                user_id=creation.owner_id,
                points=required_points,
                operation_type="generate_shot",
                creation_id=creation_id,
                novel_id=creation.novel_id,
                description=f"生成分镜图片（{shot_obj.title}）",
                extra_data={
                    "shot_id": shot_id,
                    "task_type": "shot_image_generation",
                    "reference_image_count": ref_count,
                    "image_size": image_size,
                    "image_model": image_model,
                }
            )
            freeze_record_id = freeze_record.record_id
            logger.info(f"单张分镜 {shot_id} 积分已冻结: {required_points}，freeze_record_id={freeze_record_id}")
        except InsufficientPointsError as e:
            return {
                "shot_id": shot_id,
                "creation_id": creation_id,
                "success": False,
                "error": f"积分不足: {str(e)}",
                "skipped": True
            }
        except Exception as e:
            logger.opt(exception=True).error("单张分镜 {} 冻结积分失败: {}", shot_id, str(e))
            return {
                "shot_id": shot_id,
                "creation_id": creation_id,
                "success": False,
                "error": f"冻结积分失败: {str(e)}",
                "skipped": True
            }
        finally:
            db.close()
    
    self.update_state(
        state="PROGRESS",
        meta={
            "task_type": TaskType.SHOT_IMAGE_GENERATION,
            "shot_id": shot_id,
            "creation_id": creation_id,
            "status": "生成中"
        }
    )
    
    result = _generate_single_shot_image(
        shot_id, 
        creation_id, 
        freeze_record_id, 
        force_regen_prompt=force_regen_prompt, 
        model_name=model_name,
        frame_type=frame_type
    )
    
    # 清除 current_task_id
    db = SessionLocal()
    try:
        creation = db.query(Creation).filter(Creation.creation_id == creation_id).first()
        if creation and str(creation.current_task_id) == str(self.request.id):
            creation.current_task_id = None
            db.commit()
    except Exception as e:
        logger.error(f"Failed to clear current_task_id: {str(e)}")
    finally:
        db.close()
        
    result["task_type"] = TaskType.SHOT_IMAGE_GENERATION
    return result


@celery_app.task(
    bind=True, 
    name="generate_creation_shots_task",
    autoretry_for=(Exception,),
    max_retries=2,
    retry_backoff=True,
    retry_backoff_max=60,
    retry_jitter=True
)
def generate_creation_shots_task(self, creation_id: int, force_regenerate: bool = False):
    """
    生成创作下所有分镜的图片（主任务）
    
    这是一个协调任务，负责：
    1. 查询创作下所有场景和分镜
    2. 使用线程池并发执行所有分镜的图片生成
    3. 汇总结果并更新创作状态
    
    Args:
        creation_id: 创作ID
        force_regenerate: 是否强制重新生成已有图片的分镜
        
    Returns:
        包含所有分镜处理结果的字典
    """
    db: Session = SessionLocal()
    task_start = time.perf_counter()
    try:
        ##X## Debug 模式下抛出测试异常 - 测试分镜图片生成错误
        # if settings.DEBUG:
        #     raise Exception("测试分镜图片生成错误")
        
        # 验证创作是否存在
        creation = db.query(Creation).filter(Creation.creation_id == creation_id).first()
        if not creation:
            raise NotFoundError(detail=f"创作不存在: creation_id={creation_id}")
        
        # 查询所有场景和分镜
        scenes = (
            db.query(Scene)
            .options(selectinload(Scene.shots))
            .filter(Scene.creation_id == creation_id)
            .order_by(Scene.scene_id)
            .all()
        )
        
        # 收集所有需要生成图片的分镜
        all_shots: List[Dict[str, Any]] = []
        for scene in scenes:
            for shot in scene.shots:
                # 如果强制重新生成，或者分镜没有图片，则加入列表
                if force_regenerate or not shot.image_url:
                    # 如果没有 image_prompt，也会加入列表，在生成任务中会自动生成提示词
                    all_shots.append({
                        "shot_id": shot.shot_id,
                        "shot_title": shot.title,
                        "scene_id": scene.scene_id,
                        "scene_title": scene.title
                    })
                else:
                    logger.info(f"分镜 {shot.shot_id} 已有图片且非强制重新生成，跳过")
        
        total_shots = len(all_shots)
        if total_shots == 0:
            logger.info(f"创作 {creation_id} 没有需要生成图片的分镜")
            creation.status = CreationStatus.SCENE_GENERATED
            creation.current_task_id = None
            
            # 更新状态为 success
            from app.services.creation_service import CreationService
            CreationService.update_creation_step_status(
                db=db,
                creation_id=creation_id,
                step_name="shotImageGeneration",
                status="success"
            )
            
            db.commit()
            return {
                "success": True,
                "task_type": TaskType.BATCH_SHOT_IMAGE_GENERATION,
                "creation_id": creation_id,
                "total": 0,
                "message": "没有需要生成图片的分镜",
                "results": []
            }
        
        logger.info(f"开始为创作 {creation_id} 生成 {total_shots} 个分镜的图片")
        
        # 更新状态为 processing
        from app.services.creation_service import CreationService
        CreationService.update_creation_step_status(
            db=db,
            creation_id=creation_id,
            step_name="shotImageGeneration",
            status="processing",
            task_id=self.request.id
        )
        
        # 计算每个分镜需要的积分并冻结积分
        # 优先使用 creation.extra_data 中的 image_to_image_model（如果不存在则回退到 text_to_image，再回退到 settings）
        image_model = (
            (creation.extra_data or {}).get("image_to_image_model")
            or (creation.extra_data or {}).get("text_to_image_model")
            or settings.IMAGE_MODEL_IMAGE_TO_IMAGE
            or settings.IMAGE_MODEL_TEXT_TO_IMAGE
            or settings.IMAGE_MODEL_NAME
            or "black-forest-labs/flux-kontext-pro/multi"
        )
        try:
            model_config = ModelConfigService.get_model_config(image_model, "image_to_image")
            image_size = model_config.get("image_size", "2K") if model_config else "2K"
        except Exception:
            image_size = "2K"
        
        # 为每个分镜冻结积分
        shots_with_freeze_records = []
        user_id = creation.owner_id
        novel_id = creation.novel_id
        results = []  # 初始化结果列表，用于记录因积分不足而跳过的分镜
        
        for shot_info in all_shots:
            shot_id = shot_info["shot_id"]
            # 计算该分镜的参考图数量
            ref_count = 0
            try:
                shot_obj = db.query(Shot).options(selectinload(Shot.characters)).filter(Shot.shot_id == shot_id).first()
                if shot_obj and shot_obj.characters:
                    ref_count = sum(1 for c in shot_obj.characters if getattr(c, "image_url", None))
            except Exception:
                ref_count = 0
            
            # 基于实际参考图和分辨率计算成本/积分
            cost_per_image = ModelPrices.calculate_image_cost(
                image_model,
                1,
                reference_image_count=ref_count,
                image_size=image_size
            )
            required_points_per_shot = int(math.ceil(cost_per_image * 100))
            if required_points_per_shot <= 0:
                required_points_per_shot = 1
            
            try:
                freeze_record = PointsService.freeze_points(
                    db=db,
                    user_id=user_id,
                    points=required_points_per_shot,
                    operation_type="generate_shot",
                    creation_id=creation_id,
                    novel_id=novel_id,
                    description=f"生成分镜图片（{shot_info['shot_title']}）",
                    extra_data={
                        "shot_id": shot_info["shot_id"],
                        "task_type": "shot_image_generation",
                        "reference_image_count": ref_count,
                        "image_size": image_size
                    }
                )
                shot_info["freeze_record_id"] = freeze_record.record_id
                shots_with_freeze_records.append(shot_info)
                logger.info(f"分镜 {shot_info['shot_id']} 积分已冻结: {required_points_per_shot} 积分, freeze_record_id={freeze_record.record_id}")
            except InsufficientPointsError as e:
                logger.warning(f"分镜 {shot_info['shot_id']} ({shot_info['shot_title']}) 积分不足，跳过生成: {str(e)}")
                # 记录跳过原因，但不影响其他分镜的生成
                results.append({
                    "shot_id": shot_info["shot_id"],
                    "shot_title": shot_info["shot_title"],
                    "success": False,
                    "error": f"积分不足: {str(e)}",
                    "skipped": True
                })
            except Exception as e:
                logger.opt(exception=True).error("分镜 {} 冻结积分失败: {}", shot_info['shot_id'], str(e))
                # 记录错误，但不影响其他分镜的生成
                results.append({
                    "shot_id": shot_info["shot_id"],
                    "shot_title": shot_info["shot_title"],
                    "success": False,
                    "error": f"冻结积分失败: {str(e)}",
                    "skipped": True
                })
        
        # 更新实际需要生成的分镜数量（排除积分不足的分镜）
        actual_total_shots = len(shots_with_freeze_records)
        if actual_total_shots == 0:
            logger.warning(f"创作 {creation_id} 所有分镜都因积分不足而跳过生成")
            creation.current_task_id = None
            db.commit()
            return {
                "success": False,
                "task_type": TaskType.BATCH_SHOT_IMAGE_GENERATION,
                "creation_id": creation_id,
                "total": total_shots,
                "success_count": 0,
                "failed_count": total_shots - actual_total_shots,
                "message": "所有分镜都因积分不足而跳过生成",
                "results": results
            }
        
        logger.info(f"成功冻结 {actual_total_shots}/{total_shots} 个分镜的积分，开始生成图片")
        
        # 更新任务状态
        self.update_state(
            state="PROGRESS",
            meta={
                "task_type": TaskType.BATCH_SHOT_IMAGE_GENERATION,
                "creation_id": creation_id,
                "total": actual_total_shots,
                "completed": 0,
                "success_count": 0,
                "failed_count": total_shots - actual_total_shots,
                "status": f"开始生成 {actual_total_shots} 个分镜图片（{total_shots - actual_total_shots} 个因积分不足跳过）",
                "stage": "generating",
                "shots": shots_with_freeze_records
            }
        )
        
        # 使用线程池并发执行（最多5个并发，避免过载）
        success_count = 0
        failed_count = total_shots - actual_total_shots  # 包含因积分不足而跳过的分镜
        
        max_workers = min(5, actual_total_shots)
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            # 提交所有任务（传递 freeze_record_id）
            future_to_shot = {
                executor.submit(
                    _generate_single_shot_image, 
                    shot["shot_id"], 
                    creation_id,
                    shot.get("freeze_record_id"),
                    force_regen_prompt=force_regenerate
                ): shot
                for shot in shots_with_freeze_records
            }
            
            # 收集结果
            for future in as_completed(future_to_shot):
                shot_info = future_to_shot[future]
                try:
                    result = future.result()
                    results.append(result)
                    
                    if result.get("success"):
                        success_count += 1
                        logger.info(f"分镜 {shot_info['shot_id']} ({shot_info['shot_title']}) 图片生成成功")
                    else:
                        failed_count += 1
                        logger.warning(f"分镜 {shot_info['shot_id']} ({shot_info['shot_title']}) 图片生成失败: {result.get('error')}")
                    
                    # 更新任务进度
                    self.update_state(
                        state="PROGRESS",
                        meta={
                            "task_type": TaskType.BATCH_SHOT_IMAGE_GENERATION,
                            "creation_id": creation_id,
                            "total": total_shots,
                            "completed": success_count + failed_count,
                            "success_count": success_count,
                            "failed_count": failed_count,
                            "status": f"已完成 {success_count + failed_count}/{total_shots}",
                            "stage": "generating",
                            "shots": all_shots
                        }
                    )
                except Exception as e:
                    failed_count += 1
                    error_msg = f"分镜 {shot_info['shot_id']} 处理异常: {str(e)}"
                    logger.opt(exception=True).error("{}", error_msg)
                    results.append({
                        "shot_id": shot_info["shot_id"],
                        "shot_title": shot_info["shot_title"],
                        "success": False,
                        "error": error_msg
                    })
        
        # 更新创作状态
        creation = db.query(Creation).filter(Creation.creation_id == creation_id).first()
        if creation:
            # 生成完成后，状态统一落到 SCENE_GENERATED，若全部失败则标记为 FAILED，避免前端一直显示“生成中”
            if success_count > 0:
                creation.status = CreationStatus.SCENE_GENERATED
                # 更新状态为 success
                from app.services.creation_service import CreationService
                CreationService.update_creation_step_status(
                    db=db,
                    creation_id=creation_id,
                    step_name="shotImageGeneration",
                    status="success"
                )
            else:
                creation.status = CreationStatus.FAILED
                # 更新状态为 failed
                from app.services.creation_service import CreationService
                CreationService.update_creation_step_status(
                    db=db,
                    creation_id=creation_id,
                    step_name="shotImageGeneration",
                    status="failed",
                    error="所有分镜生成失败"
                )
            creation.current_task_id = None
            db.commit()

        # 主任务完成后推送最终进度，防止前端停留在“生成中”
        try:
            self.update_state(
                state="SUCCESS",
                meta={
                    "task_type": TaskType.BATCH_SHOT_IMAGE_GENERATION,
                    "creation_id": creation_id,
                    "total": total_shots,
                    "success_count": success_count,
                    "failed_count": failed_count,
                    "status": f"已完成 {success_count}/{total_shots}，失败 {failed_count}",
                    "stage": "completed",
                    "results": results
                }
            )
        except Exception:
            # 更新状态失败不影响最终返回
            logger.warning("更新最终进度状态失败，继续返回结果")
        
        total_sec = round(time.perf_counter() - task_start, 3)
        logger.info(
            f"创作 {creation_id} 分镜图片生成完成: "
            f"总数={total_shots}, 成功={success_count}, 失败={failed_count}, "
            f"total_sec={total_sec}s"
        )
        
        return {
            "success": success_count > 0,
            "task_type": TaskType.BATCH_SHOT_IMAGE_GENERATION,
            "creation_id": creation_id,
            "total": total_shots,
            "success_count": success_count,
            "failed_count": failed_count,
            "all_success": failed_count == 0,
            "results": results
        }
        
    except BaseServiceException as e:
        # BaseServiceException 直接重新抛出，不进行包装
        try:
            creation = db.query(Creation).filter(Creation.creation_id == creation_id).first()
            if creation:
                creation.current_task_id = None
                db.commit()
        except Exception as cleanup_error:
            logger.opt(exception=True).error("清理 current_task_id 失败: {}", str(cleanup_error))
            db.rollback()
        
        error_msg = str(e)
        exc_type = type(e).__name__
        exc_module = type(e).__module__
        self.update_state(
            state="FAILURE",
            meta={
                "task_type": TaskType.BATCH_SHOT_IMAGE_GENERATION,
                "creation_id": creation_id,
                "error": error_msg,
                "exc_type": f"{exc_module}.{exc_type}",
                "exc_message": error_msg,
            }
        )
        raise
    except Exception as e:
        error_msg = str(e)
        logger.opt(exception=True).error("创作分镜图片生成任务失败: {}", error_msg)
        
        # 更新创作状态
        try:
            creation = db.query(Creation).filter(Creation.creation_id == creation_id).first()
            if creation:
                creation.current_task_id = None
                
                # 更新状态为 failed
                from app.services.creation_service import CreationService
                CreationService.update_creation_step_status(
                    db=db,
                    creation_id=creation_id,
                    step_name="shotImageGeneration",
                    status="failed",
                    error=error_msg
                )
                
                db.commit()
        except Exception as cleanup_error:
            logger.opt(exception=True).error("清理 current_task_id 失败: {}", str(cleanup_error))
            db.rollback()
        
        exc_type = type(e).__name__
        exc_module = type(e).__module__
        self.update_state(
            state="FAILURE",
            meta={
                "task_type": TaskType.BATCH_SHOT_IMAGE_GENERATION,
                "creation_id": creation_id,
                "error": error_msg,
                "exc_type": f"{exc_module}.{exc_type}",
                "exc_message": error_msg,
            }
        )
        # 更新任务状态：失败
        from app.services.creation_service import CreationService
        CreationService.update_creation_step_status(
            db=db,
            creation_id=creation_id,
            step_name="shotImageGeneration",
            status="failed",
            error=str(e)
        )
        raise BaseServiceException(message=error_msg)
    finally:
        db.close()


@celery_app.task(
    bind=True, 
    name="generate_shots_by_ids_task",
    autoretry_for=(Exception,),
    max_retries=2,
    retry_backoff=True,
    retry_backoff_max=60,
    retry_jitter=True
)
def generate_shots_by_ids_task(self, shot_ids: List[int], creation_id: int):
    """
    并发生成指定分镜的图片
    
    Args:
        shot_ids: 分镜ID列表
        creation_id: 创作ID
        
    Returns:
        包含所有分镜处理结果的字典
    """
    if not shot_ids:
        logger.warning("分镜ID列表为空")
        return {
            "success": False,
            "task_type": TaskType.BATCH_SHOT_IMAGE_GENERATION,
            "message": "分镜ID列表为空",
            "results": []
        }
    
    total_count = len(shot_ids)
    task_start = time.perf_counter()
    logger.info(f"开始并发生成 {total_count} 个分镜的图片: {shot_ids}")
    
    db: Session = SessionLocal()
    try:
        # 验证创作是否存在并获取用户信息
        creation = db.query(Creation).filter(Creation.creation_id == creation_id).first()
        if not creation:
            raise NotFoundError(detail=f"创作不存在: creation_id={creation_id}")
        
        # 更新任务状态：开始处理
        from app.services.creation_service import CreationService
        CreationService.update_creation_step_status(
            db=db,
            creation_id=creation_id,
            step_name="shotImageGeneration",
            status="processing",
            task_id=self.request.id
        )
        
        # 查询所有分镜信息
        shots = db.query(Shot).filter(Shot.shot_id.in_(shot_ids)).all()
        shot_dict = {shot.shot_id: shot for shot in shots}
        
        # 计算每个分镜需要的积分并冻结积分
        # 分镜图片生成：优先使用图生图模型（因为通常有角色图片），如果没有配置则使用文生图模型
        image_model = settings.IMAGE_MODEL_IMAGE_TO_IMAGE or settings.IMAGE_MODEL_TEXT_TO_IMAGE or settings.IMAGE_MODEL_NAME or "black-forest-labs/flux-kontext-pro/multi"
        try:
            model_config = ModelConfigService.get_model_config(image_model, "image_to_image")
            image_size = model_config.get("image_size", "2K") if model_config else "2K"
        except Exception:
            image_size = "2K"
        
        # 为每个分镜冻结积分
        shots_with_freeze_records = []
        user_id = creation.owner_id
        novel_id = creation.novel_id
        results = []
        
        for shot_id in shot_ids:
            shot = shot_dict.get(shot_id)
            if not shot:
                logger.warning(f"分镜 {shot_id} 不存在，跳过")
                results.append({
                    "shot_id": shot_id,
                    "success": False,
                    "error": "分镜不存在",
                    "skipped": True
                })
                continue
            
            # 计算参考图数量
            ref_count = 0
            try:
                shot_obj = db.query(Shot).options(selectinload(Shot.characters)).filter(Shot.shot_id == shot_id).first()
                if shot_obj and shot_obj.characters:
                    ref_count = sum(1 for c in shot_obj.characters if getattr(c, "image_url", None))
            except Exception:
                ref_count = 0
            
            cost_per_image = ModelPrices.calculate_image_cost(
                image_model,
                1,
                reference_image_count=ref_count,
                image_size=image_size
            )
            required_points_per_shot = int(math.ceil(cost_per_image * 100))
            if required_points_per_shot <= 0:
                required_points_per_shot = 1
            
            try:
                freeze_record = PointsService.freeze_points(
                    db=db,
                    user_id=user_id,
                    points=required_points_per_shot,
                    operation_type="generate_shot",
                    creation_id=creation_id,
                    novel_id=novel_id,
                    description=f"生成分镜图片（{shot.title}）",
                    extra_data={
                        "shot_id": shot_id,
                        "task_type": "shot_image_generation",
                        "reference_image_count": ref_count,
                        "image_size": image_size
                    }
                )
                shots_with_freeze_records.append({
                    "shot_id": shot_id,
                    "freeze_record_id": freeze_record.record_id
                })
                logger.info(f"分镜 {shot_id} 积分已冻结: {required_points_per_shot} 积分, freeze_record_id={freeze_record.record_id}")
            except InsufficientPointsError as e:
                logger.warning(f"分镜 {shot_id} ({shot.title}) 积分不足，跳过生成: {str(e)}")
                results.append({
                    "shot_id": shot_id,
                    "success": False,
                    "error": f"积分不足: {str(e)}",
                    "skipped": True
                })
            except Exception as e:
                logger.opt(exception=True).error("分镜 {} 冻结积分失败: {}", shot_id, str(e))
                results.append({
                    "shot_id": shot_id,
                    "success": False,
                    "error": f"冻结积分失败: {str(e)}",
                    "skipped": True
                })
        
        # 更新实际需要生成的分镜数量（排除积分不足的分镜）
        actual_total_shots = len(shots_with_freeze_records)
        if actual_total_shots == 0:
            logger.warning(f"创作 {creation_id} 所有分镜都因积分不足而跳过生成")
            return {
                "success": False,
                "task_type": TaskType.BATCH_SHOT_IMAGE_GENERATION,
                "creation_id": creation_id,
                "total": total_count,
                "success_count": 0,
                "failed_count": total_count,
                "message": "所有分镜都因积分不足而跳过生成",
                "results": results
            }
        
        logger.info(f"成功冻结 {actual_total_shots}/{total_count} 个分镜的积分，开始生成图片")
        
        # 更新任务状态
        self.update_state(
            state="PROGRESS",
            meta={
                "task_type": TaskType.BATCH_SHOT_IMAGE_GENERATION,
                "creation_id": creation_id,
                "shot_ids": shot_ids,
                "total": actual_total_shots,
                "completed": 0,
                "success": 0,
                "failed": total_count - actual_total_shots,
            },
        )
        
        success_count = 0
        failed_count = total_count - actual_total_shots  # 包含因积分不足而跳过的分镜
        
        # 使用线程池并发执行（最多5个并发）
        max_workers = min(5, actual_total_shots)
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            # 提交所有任务（传递 freeze_record_id）
            future_to_shot_info = {
                executor.submit(
                    _generate_single_shot_image, 
                    shot_info["shot_id"], 
                    creation_id,
                    shot_info.get("freeze_record_id")
                ): shot_info
                for shot_info in shots_with_freeze_records
            }
            
            # 收集结果
            for future in as_completed(future_to_shot_info):
                shot_info = future_to_shot_info[future]
                shot_id = shot_info["shot_id"]
                try:
                    result = future.result()
                    results.append(result)
                    
                    if result["success"]:
                        success_count += 1
                        logger.info(f"分镜 {shot_id} 图片生成成功")
                    else:
                        failed_count += 1
                        logger.warning(f"分镜 {shot_id} 图片生成失败: {result.get('error')}")
                    
                    # 更新任务进度
                    self.update_state(
                        state="PROGRESS",
                        meta={
                            "task_type": TaskType.BATCH_SHOT_IMAGE_GENERATION,
                            "creation_id": creation_id,
                            "shot_ids": shot_ids,
                            "total": actual_total_shots,
                            "completed": success_count + failed_count,
                            "success": success_count,
                            "failed": failed_count,
                        },
                    )
                except Exception as e:
                    failed_count += 1
                    error_msg = f"分镜 {shot_id} 处理异常: {str(e)}"
                    logger.opt(exception=True).error("{}", error_msg)
                    results.append({
                        "shot_id": shot_id,
                        "success": False,
                        "error": error_msg
                    })
        
        # 任务完成
        total_sec = round(time.perf_counter() - task_start, 3)
        logger.info(
            f"分镜图片生成任务完成: 总数={total_count}, "
            f"成功={success_count}, 失败={failed_count}, total_sec={total_sec}s"
        )
        
        # 更新任务状态：成功/失败
        CreationService.update_creation_step_status(
            db=db,
            creation_id=creation_id,
            step_name="shotImageGeneration",
            status="success" if success_count > 0 else "failed",
            error=f"生成失败: {failed_count}/{total_count}" if success_count == 0 else None
        )
        
        # 清除当前任务ID
        creation = db.query(Creation).filter(Creation.creation_id == creation_id).first()
        if creation:
            creation.current_task_id = None
            # 如果成功生成了分镜，且当前状态是 CHARACTER_GENERATED，则更新状态
            if success_count > 0 and creation.status == CreationStatus.CHARACTER_GENERATED:
                creation.status = CreationStatus.SCENE_GENERATED
            db.commit()
        
        return {
            "success": failed_count == 0,
            "task_type": TaskType.BATCH_SHOT_IMAGE_GENERATION,
            "creation_id": creation_id,
            "total": actual_total_shots,
            "success_count": success_count,
            "failed_count": failed_count,
            "results": results
        }
        
    except BaseServiceException as e:
        # BaseServiceException 直接重新抛出，不进行包装
        try:
            creation = db.query(Creation).filter(Creation.creation_id == creation_id).first()
            if creation:
                creation.current_task_id = None
                
                # 更新状态为 failed
                from app.services.creation_service import CreationService
                CreationService.update_creation_step_status(
                    db=db,
                    creation_id=creation_id,
                    step_name="shotImageGeneration",
                    status="failed",
                    error=str(e)
                )
                
                db.commit()
        except Exception as cleanup_error:
            logger.opt(exception=True).error("清理 current_task_id 失败: {}", str(cleanup_error))
            db.rollback()
        
        error_msg = str(e)
        exc_type = type(e).__name__
        exc_module = type(e).__module__
        self.update_state(
            state="FAILURE",
            meta={
                "task_type": TaskType.BATCH_SHOT_IMAGE_GENERATION,
                "creation_id": creation_id,
                "shot_ids": shot_ids,
                "error": error_msg,
                "exc_type": f"{exc_module}.{exc_type}",
                "exc_message": error_msg,
            },
        )
        raise
    except Exception as e:
        error_msg = f"分镜图片生成任务失败: {str(e)}"
        logger.opt(exception=True).error("{}", error_msg)
        
        try:
            creation = db.query(Creation).filter(Creation.creation_id == creation_id).first()
            if creation:
                creation.current_task_id = None
                
                # 更新状态为 failed
                from app.services.creation_service import CreationService
                CreationService.update_creation_step_status(
                    db=db,
                    creation_id=creation_id,
                    step_name="shotImageGeneration",
                    status="failed",
                    error=str(e)
                )
                
                db.commit()
        except Exception as cleanup_error:
            logger.opt(exception=True).error("清理 current_task_id 失败: {}", str(cleanup_error))
            db.rollback()
        
        exc_type = type(e).__name__
        exc_module = type(e).__module__
        self.update_state(
            state="FAILURE",
            meta={
                "task_type": TaskType.BATCH_SHOT_IMAGE_GENERATION,
                "creation_id": creation_id,
                "shot_ids": shot_ids,
                "error": error_msg,
                "exc_type": f"{exc_module}.{exc_type}",
                "exc_message": error_msg,
            },
        )
        raise BaseServiceException(message=error_msg)


