"""
分镜图片生成任务
支持批量生成创作下所有分镜的图片
"""
import os
import uuid
import time
from typing import List, Dict, Any
from concurrent.futures import ThreadPoolExecutor, as_completed
import httpx

from app.core.celery_app import celery_app
from app.db.session import SessionLocal
from sqlalchemy.orm import Session, selectinload
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


def _generate_single_shot_image(shot_id: int, creation_id: int, freeze_record_id: int = None) -> dict:
    """
    生成单个分镜的图片（线程安全函数，使用图生图）
    
    Args:
        shot_id: 分镜ID
        creation_id: 创作ID（用于生成存储路径）
        
    Returns:
        包含分镜ID和处理结果的字典
        
    Raises:
        NotFoundError: 分镜不存在
        Exception: 生图失败
    """
    db: Session = SessionLocal()
    task_start = time.perf_counter()
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
        
        # 检查是否已有图片
        if shot.image_url:
            total_sec = round(time.perf_counter() - start_time, 3)
            logger.info(f"分镜 {shot_id} 已有图片，跳过生成 | total_sec={total_sec}s")
            return {
                "shot_id": shot_id,
                "shot_title": shot.title,
                "success": True,
                "image_url": shot.image_url,
                "skipped": True,
                "duration_sec": total_sec,
            }
        
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
        character_images = []
        character_profiles = []
        for character in shot.characters:
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
                previous_shot_description = previous_shot.image_prompt or previous_shot.narration
                if previous_shot_description:
                    logger.info(f"找到上一分镜上下文: {previous_shot.shot_id} (使用{'提示词' if previous_shot.image_prompt else '旁白'})")
        
        # 从创作配置中获取模型配置
        creation = shot.scene.creation
        extra_data = creation.extra_data or {}
        image_to_image_model = extra_data.get("image_to_image_model")
        text_to_image_model = extra_data.get("text_to_image_model")  # 兼容旧字段，实际不再区分
        
        # 使用LLM生成英文提示词
        llm_model = extra_data.get("llm_model")
        ai_client = AIClient(
            llm_model_name=llm_model,
            image_to_image_model=image_to_image_model,
            text_to_image_model=text_to_image_model
        )
        current_shot_description = shot.description or shot.image_prompt or ""
        
        # 生成提示词（即使没有参考图也用统一流程）
        logger.info(f"开始为分镜 {shot_id} 生成图片提示词（统一流程，参考图数量: {len(character_images)}）")
        prompt_start = time.perf_counter()
        english_prompt = ai_client.generate_shot_image_prompt(
            character_profiles=character_profiles,
            previous_shot_description=previous_shot_description,
            current_shot_description=current_shot_description,
            image_model=image_to_image_model  # 传入图片模型以确定输出语言
        )
        timings["prompt_sec"] = round(time.perf_counter() - prompt_start, 3)
        logger.info(f"生成的英文提示词长度: {len(english_prompt)}")
        
        # 使用同一模型生成图片；参考图可为空
        logger.info(f"开始为分镜 {shot_id} 调用图生图接口，参考图数量: {len(character_images)}")
        image_start = time.perf_counter()
        temp_image_url = ai_client.generate_image_by_reference(
            prompt=english_prompt,
            reference_images=character_images,  # 可为空
            model=image_to_image_model  # 使用配置的模型
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
            
            # 获取用户UUID用于构建上传路径
            creation = shot.scene.creation
            user_id = creation.owner_id
            user = db.query(User).filter(User.user_id == user_id).first()
            if not user:
                raise ValueError(f"用户不存在: user_id={user_id}")
            user_uuid = user.uuid
            
            # 获取环境变量和时间戳
            env = getattr(settings, 'ENV', 'dev')
            time_str = datetime.now().strftime('%Y%m%d')
            
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
            logger.info(f"图像流式上传US3成功，持久化URL: {image_url}")
            
            timings["persist_sec"] = round(time.perf_counter() - persist_start, 3)
            
        except Exception as e:
            # 如果US3上传失败，记录错误但继续使用临时URL（降级处理）
            error_msg = f"图像上传US3失败，使用临时URL: {str(e)}"
            logger.warning(error_msg, exc_info=True)
            image_url = temp_image_url
            timings["persist_sec"] = round(time.perf_counter() - persist_start, 3)
        
        # 更新分镜信息
        shot.image_url = image_url
        db.commit()
        db.refresh(shot)
        
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
            f"timings={timings} | total_sec={total_sec}s"
        )
        return {
            "shot_id": shot_id,
            "shot_title": shot.title,
            "success": True,
            "image_url": image_url,
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


@celery_app.task(bind=True, name="generate_single_shot_image_task")
def generate_single_shot_image_task(self, shot_id: int, creation_id: int, freeze_record_id: int = None) -> dict:
    """
    Celery任务：生成单个分镜的图片
    
    Args:
        shot_id: 分镜ID
        creation_id: 创作ID
        freeze_record_id: 冻结记录ID（可选，如果提供则使用冻结机制）
        
    Returns:
        包含分镜ID和处理结果的字典
    """
    logger.info(f"开始执行分镜图片生成任务: shot_id={shot_id}, creation_id={creation_id}, freeze_record_id={freeze_record_id}")
    
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
                extra_data.get("image_to_image_model")
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
    
    result = _generate_single_shot_image(shot_id, creation_id, freeze_record_id)
    result["task_type"] = TaskType.SHOT_IMAGE_GENERATION
    return result


@celery_app.task(bind=True, name="generate_creation_shots_task")
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
                    # 必须有 image_prompt 才能生成
                    if shot.image_prompt:
                        all_shots.append({
                            "shot_id": shot.shot_id,
                            "shot_title": shot.title,
                            "scene_id": scene.scene_id,
                            "scene_title": scene.title
                        })
        
        total_shots = len(all_shots)
        if total_shots == 0:
            logger.info(f"创作 {creation_id} 没有需要生成图片的分镜")
            creation.status = CreationStatus.SCENE_GENERATED
            creation.current_task_id = None
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
                    shot.get("freeze_record_id")
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
            else:
                creation.status = CreationStatus.FAILED
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
        raise BaseServiceException(message=error_msg)
    finally:
        db.close()


@celery_app.task(bind=True, name="generate_shots_by_ids_task")
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


