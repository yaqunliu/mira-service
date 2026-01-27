from app.core.celery_app import celery_app
from app.db.session import SessionLocal
from sqlalchemy.orm import Session
from typing import List
from app.models.character import Character
from app.models.creation import Creation
from app.schemas.creation import CreationStatus
from app.core.exceptions import NotFoundError, BaseServiceException
from app.utils.task_types import TaskType
from app.utils.ai_client import AIClient
from app.core.logger import logger
from app.utils.file_utils import read_prompt_file
from app.utils.us3 import US3Client
from app.utils.upload_helper import upload_helper
from app.utils.points_deduction import deduct_points_for_image
from app.core.config import settings
from app.models.user import User
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed
import httpx
import uuid
import os
import time

# 风格映射
STYLE_MAPPING = {
    "realism": "写实摄影,摄影作品，真实的光影和材质，逼真的人物形象",
    "cyberpunk": "赛博朋克风格，霓虹灯效果，高科技与低生活的结合，未来主义",
    "ukiyoe": "浮世绘风格，传统日本绘画风格，平面化，鲜明的色彩",
    "watercolor": "水彩画风格，柔和的色彩过渡，透明感，自然的笔触",
    "anime": "日漫风格，典型的日本动画美学，夸张的表情和动作"
}

# 固定规范提示词文案
CHARACTER_NORM_PROMPT = (
    "横版构图，四视图布局(面部正面大特写、正面全身、侧面全身、背面全身)，纯白色背景，无文字水印。 "
    "Composition: Horizontal landscape layout containing four independent parts: one large facial close-up, one full body front view, one full body side view, and one full body back view. "
    "Background: Pure white background, clean and minimal. "
    "Quality: 8k resolution, highly detailed, masterwork, no text, no letters, no words, no watermarks."
)


def _generate_single_character_image(character_id: int, visual_style: str, force_regenerate: bool = True, task_id: str = None, model_name: str = None) -> dict:
    """
    生成单个角色的图片（线程安全函数）

    Args:
        character_id: 角色ID
        visual_style: 视觉风格
        force_regenerate: 是否强制重新生成（True: 强制生成，False: 如果已有图片则跳过）
        task_id: Celery任务ID，用于检查current_task_id
        model_name: 使用的模型名称

    Returns:
        包含角色ID和处理结果的字典

    Raises:
        NotFoundError: 角色不存在
        Exception: 生图失败
    """
    db: Session = SessionLocal()
    start_time = time.perf_counter()
    timings = {}
    try:
        character = (
            db.query(Character)
            .filter(Character.character_id == character_id)
            .first()
        )
        if not character:
            raise NotFoundError(detail=f"角色不存在: character_id={character_id}")

        # 如果不强制重新生成且已有图片，则跳过
        if not force_regenerate and character.image_url:
            logger.info(f"角色 {character.name}(ID: {character_id}) 已有图片，跳过生成")
            # 恢复状态为 completed（因为批量更新时被设置为 generating）
            character.status = "completed"
            db.commit()
            return {
                "character_id": character_id,
                "character_name": character.name,
                "success": True,
                "skipped": True,
                "image_url": character.image_url
            }
        
        # 从创作配置中获取模型配置
        creation = character.creation
        extra_data = creation.extra_data or {} if creation else {}
        text_to_image_model = model_name or extra_data.get("text_to_image_model") or settings.IMAGE_MODEL_NAME
        llm_model = extra_data.get("llm_model") or settings.LLM_MODEL_NAME

        # 获取风格描述
        style_description = STYLE_MAPPING.get(visual_style, STYLE_MAPPING["anime"])

        # 1. 获取提示词逻辑：
        # 如果数据库中已有提示词，则直接使用；否则使用 LLM 生成
        ai_client = AIClient(llm_model_name=llm_model, text_to_image_model=text_to_image_model)
        
        if character.image_prompt:
            image_prompt = character.image_prompt
            logger.info(f"Using existing prompt for character {character_id}: {image_prompt}")
            character_description = ""
        else:
            # 准备角色特征数据
            character_features = (
                f"角色姓名：{character.name}\n"
                f"基础信息：{character.basic_info}\n"
                f"容貌特征：{character.appearance}\n"
                f"身材特征：{character.body}\n"
                f"发型发色：{character.hair}\n"
                f"服装配饰：{character.clothing}\n"
                f"特征标签：{', '.join(character.tags) if character.tags and isinstance(character.tags, list) else character.tags}"
                f"视觉风格：{style_description}\n"
            )

            # 加载模板并替换变量
            system_prompt_template = read_prompt_file("character.md")
            system_prompt = system_prompt_template.replace("{{CHARACTER_FEATURES}}", character_features)
            system_prompt = system_prompt.replace("{{VISUAL_STYLE}}", style_description)
            
            # 准备用户消息
            user_content = f"请根据上述特征和指定的视觉风格，为角色 {character.name} 生成生图提示词。"
            
            try:
                prompt_start = time.perf_counter()
                messages = [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_content}
                ]
                
                # 调用 LLM 生成描述部分
                llm_res = ai_client.chat_completion(messages=messages, model=llm_model)
                llm_output = llm_res.get("content", "").strip()
                
                # 提取 <提示词> 标签内的内容
                import re
                match = re.search(r"<提示词>(.*?)</提示词>", llm_output, re.DOTALL)
                if match:
                    character_description = match.group(1).strip()
                else:
                    character_description = llm_output
                    
                timings["llm_prompt_sec"] = round(time.perf_counter() - prompt_start, 3)
                logger.info(f"LLM 生成的角色描述: {character_description[:100]}...")
                
            except Exception as e:
                logger.error(f"LLM 生成角色提示词失败，降级使用拼接方式: {str(e)}")
                character_description = f"{character.name}, {character.appearance}, {character.clothing}"
                timings["llm_prompt_sec"] = 0

            # 2. 组合最终提示词：固定规范文案 + 风格描述 + LLM 生成的角色描述
            image_prompt = f"{CHARACTER_NORM_PROMPT} {style_description} {character_description}"
            
            # 3. 保存新生成的提示词到数据库
            try:
                character.image_prompt = image_prompt
                db.add(character)
                db.commit()
                db.refresh(character)
                logger.info(f"Generated and saved new prompt for character {character_id}")
            except Exception as e:
                logger.error(f"Failed to save character prompt: {e}")
                db.rollback()
        
        logger.info(f"角色 {character.name}(ID: {character_id}) 最终生图提示词: {image_prompt}")
        
        # 调用生图API（明确设置横版 16:9 比例）
        image_start = time.perf_counter()
        temp_image_url = ai_client.generate_image_by_prompt(
            prompt=image_prompt,
            model=text_to_image_model,
        )
        timings["image_api_sec"] = round(time.perf_counter() - image_start, 3)
        
        # 从临时URL/本地文件获取图像并上传到US3进行持久化（使用流式上传）
        persist_start = time.perf_counter()
        try:
            image_data = None
            if temp_image_url.startswith("local://"):
                # 读取本地文件为字节流
                temp_file_path = temp_image_url.replace("local://", "")
                logger.info(f"使用本地文件路径: {temp_file_path}")
                if not os.path.exists(temp_file_path):
                    raise Exception(f"本地文件不存在: {temp_file_path}")
                with open(temp_file_path, 'rb') as f:
                    image_data = f.read()
                logger.info(f"本地图像读取成功，大小: {len(image_data)} 字节")
            else:
                logger.info(f"从URL下载图像: {temp_image_url}")
                # 下载图像 - 使用配置的超时时间
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
            user_id = None
            creation_id = character.creation_id
            novel_id = character.novel_id
            
            if creation_id:
                creation = db.query(Creation).filter(Creation.creation_id == creation_id).first()
                if creation:
                    user_id = creation.owner_id
                    novel_id = creation.novel_id or novel_id
            elif novel_id:
                from app.models.novel import Novel
                novel = db.query(Novel).filter(Novel.novel_id == novel_id).first()
                if novel:
                    user_id = novel.owner_id
            
            if not user_id:
                raise ValueError(f"无法获取用户ID（character_id={character_id}, creation_id={creation_id}, novel_id={novel_id}）")
            
            user = db.query(User).filter(User.user_id == user_id).first()
            if not user:
                raise ValueError(f"用户不存在: user_id={user_id}")
            user_uuid = user.uuid
            
            # 获取环境变量和时间戳
            env = getattr(settings, 'ENV', 'dev')
            time_str = datetime.now().strftime('%Y%m%d')
            
            # 使用流式上传
            # 文件名格式: characters/{character_id}/image_{uuid}{extension}
            image_extension = ".png"  # 默认使用png
            image_uuid = str(uuid.uuid4())
            filename = f"characters/{character_id}/image_{image_uuid}{image_extension}"
            
            upload_result = upload_helper.upload_file_stream(
                file_data=image_data,
                user_uuid=user_uuid,
                file_type="characters",  # 文件类型
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
            image_url = temp_image_url  # 降级使用临时URL
            timings["persist_sec"] = round(time.perf_counter() - persist_start, 3)
        
        # 更新角色信息
        character.image_url = image_url
        character.image_prompt = image_prompt
        # character.image_base64 = image_base64
        character.status = "completed"

        # 保存图片生成历史到 character.status_detail
        try:
            if character.status_detail is None:
                character.status_detail = {}
            
            image_history = character.status_detail.get('image_history', [])
            
            # 添加新的历史记录
            new_image_record = {
                "version_id": str(uuid.uuid4()),
                "image_url": image_url,
                "image_prompt": image_prompt,
                "model_name": text_to_image_model,
                "visual_style": visual_style,
                "generated_at": datetime.now().isoformat(),
                "success": True,
                "file_size": len(image_data) if image_data else None,
                "duration_sec": total_sec,
                "is_current": False  # 标记为非当前版本
            }
            
            image_history.append(new_image_record)
            character.status_detail['image_history'] = image_history
            
            db.commit()
            db.refresh(character)
            logger.info(f"角色 {character_id} 图片生成历史保存成功")
        except Exception as e:
            logger.error(f"保存角色 {character_id} 图片生成历史失败: {str(e)}")
            # 历史保存失败不影响主流程

        # 用户ID和相关信息已在上面获取，这里不需要重复获取
        
        # 扣除积分（按实际成本，带幂等性检查）
        # 角色生成使用文生图模型
        if user_id:
            try:
                deduct_points_for_image(
                    db=db,
                    user_id=user_id,
                    image_count=1,
                    model_name=settings.IMAGE_MODEL_TEXT_TO_IMAGE or settings.IMAGE_MODEL_NAME or "black-forest-labs/flux-kontext-pro/multi",
                    reference_image_count=0,
                    image_size="2K",
                    creation_id=creation_id,
                    novel_id=novel_id,
                    description=f"生成角色图片（{character.name}）",
                    character_id=character_id  # 用于幂等性检查，防止重试重复扣费
                )
                logger.info(f"角色 {character_id} 图片生成积分扣除成功")
            except Exception as e:
                logger.opt(exception=True).error("角色图片生成积分扣除失败: {}", str(e))
                # 积分扣除失败不影响图片生成流程，只记录错误
        else:
            logger.warning(f"角色 {character_id} 无法获取用户ID，跳过积分扣除（creation_id={creation_id}, novel_id={novel_id}）")

        # 清除 current_task_id
        # 只有在 current_task_id 等于当前任务 ID 时才清除，避免误删后续任务
        character = db.query(Character).filter(Character.character_id == character_id).first()
        if character and character.creation:
            creation = character.creation
            if task_id and creation.current_task_id == task_id:
                creation.current_task_id = None
                db.commit()
        
        db.refresh(character)
        if creation_id:
            db.refresh(creation)
        
        total_sec = round(time.perf_counter() - start_time, 3)
        logger.info(
            f"角色 {character.name}(ID: {character_id}) 图片生成成功 | "
            f"timings={timings} | total_sec={total_sec}s"
        )
        return {
            "character_id": character_id,
            "character_name": character.name,
            "success": True,
            "skipped": False,
            "image_url": image_url,
            "duration_sec": total_sec,
            "timings": timings,
        }
    except Exception as e:
        logger.opt(exception=True).error("角色 {} 图片生成失败: {}", character_id, str(e))
        db.rollback()
        
        # 尝试更新状态为 failed
        try:
             character = db.query(Character).filter(Character.character_id == character_id).first()
             if character:
                 character.status = "failed"

                 # 清除 current_task_id
                 if character.creation:
                     creation = character.creation
                     if task_id and creation.current_task_id == task_id:
                         creation.current_task_id = None

                 db.commit()
        except:
            pass

        total_sec = round(time.perf_counter() - start_time, 3)
        logger.warning(
            f"角色 {character_id} 图片生成失败 | total_sec={total_sec}s | timings={timings} | error={str(e)}"
        )
        return {
            "character_id": character_id,
            "success": False,
            "error": str(e),
            "duration_sec": total_sec,
            "timings": timings,
        }
    finally:
        db.close()


@celery_app.task(
    bind=True, 
    name="generate_character_image_task",
    autoretry_for=(Exception,),
    max_retries=3,
    retry_backoff=True,
    retry_backoff_max=60,
    retry_jitter=True
)
def generate_character_image_task(
    self,
    character_ids: List[int],
    visual_style: str,
    creation_uuid: str,
    force_regenerate: bool = False,
    update_creation_task: bool = True,
    model_name: str = None
):
    """
    并发生成多个角色的图片

    Args:
        character_ids: 角色ID列表
        visual_style: 视觉风格
        creation_uuid: 创作UUID，用于获取creation并更新current_task_id
        force_regenerate: 是否强制重新生成（False: 跳过已有图片的角色，True: 强制生成所有）
        update_creation_task: 是否更新 creation 的 current_task_id（用于页面跳转控制）
        model_name: 使用的模型名称

    Returns:
        包含所有角色处理结果的字典
    """
    if not character_ids:
        logger.warning("角色ID列表为空")
        return {
            "success": False,
            "message": "角色ID列表为空",
            "results": []
        }

    # 通过 creation_uuid 获取 creation
    db = SessionLocal()
    try:
        creation = db.query(Creation).filter(Creation.uuid == creation_uuid).first()
        if not creation:
            error_msg = f"创作不存在: creation_uuid={creation_uuid}"
            logger.error(error_msg)
            raise NotFoundError(detail=error_msg)

        # 只有在 update_creation_task=True 时才更新 current_task_id
        if update_creation_task:
            creation.current_task_id = self.request.id
            db.commit()
            logger.info(f"创作 {creation.creation_id} 的 current_task_id 已更新为 {self.request.id}")
        else:
            logger.info(f"跳过更新创作 {creation.creation_id} 的 current_task_id（单个角色重新生成）")
    except Exception as e:
        logger.opt(exception=True).error("获取创作信息失败: {}", str(e))
        db.rollback()
        raise
    finally:
        db.close()

    total_count = len(character_ids)
    task_start = time.perf_counter()
    logger.info(f"开始并发生成 {total_count} 个角色的图片: {character_ids}")
    
    # 批量更新角色状态为 generating
    try:
        db.query(Character).filter(Character.character_id.in_(character_ids)).update(
            {Character.status: "generating"}, synchronize_session=False
        )
        db.commit()
    except Exception as e:
        logger.error(f"更新角色状态为 generating 失败: {e}")
        db.rollback()

    # 更新状态为 processing
    if creation_uuid and update_creation_task:
        try:
            # 重新获取 creation_id
            db = SessionLocal()
            creation = db.query(Creation).filter(Creation.uuid == creation_uuid).first()
            if creation:
                from app.services.creation_service import CreationService
                CreationService.update_creation_step_status(
                    db=db,
                    creation_id=creation.creation_id,
                    step_name="characterImageGeneration",
                    status="processing",
                    task_id=self.request.id
                )
            db.close()
        except Exception as e:
            logger.error(f"更新创作状态失败: {e}")

    # 更新任务状态
    self.update_state(
        state="PROGRESS",
        meta={
            "task_type": TaskType.CHARACTER_IMAGE_GENERATION,
            "character_ids": character_ids,
            "total": total_count,
            "completed": 0,
            "failed": 0,
        },
    )
    
    results = []
    success_count = 0
    failed_count = 0
    skipped_count = 0
    
    try:
        ##X## Debug 模式下抛出测试异常 - 测试角色图片生成错误
        # if settings.DEBUG:
        #     raise Exception("测试角色图片生成错误")
        
        # 使用线程池并发执行（最多5个并发）
        max_workers = min(5, total_count)  # 限制最大并发数，避免过多请求
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            # 提交所有任务
            future_to_character_id = {
                executor.submit(_generate_single_character_image, cid, visual_style, force_regenerate, self.request.id, model_name): cid
                for cid in character_ids
            }
            
            # 收集结果
            for future in as_completed(future_to_character_id):
                character_id = future_to_character_id[future]
                try:
                    result = future.result()
                    results.append(result)

                    if result["success"]:
                        if result.get("skipped"):
                            skipped_count += 1
                            logger.info(f"角色 {character_id} 已有图片，跳过生成")
                        else:
                            success_count += 1
                            logger.info(f"角色 {character_id} 图片生成成功")
                    else:
                        failed_count += 1
                        logger.warning(f"角色 {character_id} 图片生成失败: {result.get('error')}")
                    
                    # 更新任务进度
                    self.update_state(
                        state="PROGRESS",
                        meta={
                            "task_type": TaskType.CHARACTER_IMAGE_GENERATION,
                            "character_ids": character_ids,
                            "total": total_count,
                            "completed": success_count + failed_count + skipped_count,
                            "success": success_count,
                            "failed": failed_count,
                            "skipped": skipped_count,
                        },
                    )
                except Exception as e:
                    failed_count += 1
                    error_msg = f"角色 {character_id} 处理异常: {str(e)}"
                    logger.opt(exception=True).error("{}", error_msg)
                    results.append({
                        "character_id": character_id,
                        "success": False,
                        "error": error_msg
                    })
        
        # 所有角色处理完成后，根据 update_creation_task 决定是否更新 creation 状态和清除 current_task_id
        db = SessionLocal()
        try:
            creation = db.query(Creation).filter(Creation.uuid == creation_uuid).first()

            if creation:
                # 只有 update_creation_task=True 时才更新状态和清除 current_task_id
                if update_creation_task:
                    # 只有状态是 CHARACTER_ANALYZED 时才更新状态
                    if creation.status == CreationStatus.CHARACTER_ANALYZED:
                        creation.status = CreationStatus.CHARACTER_GENERATED
                        logger.info(f"创作 {creation.creation_id} 状态已更新为 CHARACTER_GENERATED")
                    else:
                        logger.info(f"创作 {creation.creation_id} 当前状态为 {creation.status}，不更新状态")

                    # 清除 current_task_id
                    creation.current_task_id = None
                    logger.info(f"创作 {creation.creation_id} 的 current_task_id 已清除")
                    
                    # 更新状态为 success
                    from app.services.creation_service import CreationService
                    CreationService.update_creation_step_status(
                        db=db,
                        creation_id=creation.creation_id,
                        step_name="characterImageGeneration",
                        status="success"
                    )
                else:
                    logger.info(f"update_creation_task=False，跳过更新创作状态和清除 current_task_id（单个角色重新生成）")

                db.commit()
            else:
                logger.warning(f"未找到创作: creation_uuid={creation_uuid}")
        except Exception as e:
            logger.opt(exception=True).error("更新创作状态失败: {}", str(e))
            db.rollback()
        finally:
            db.close()

        # 任务完成
        total_sec = round(time.perf_counter() - task_start, 3)
        logger.info(
            f"角色图片生成任务完成: 总数={total_count}, "
            f"成功={success_count}, 跳过={skipped_count}, 失败={failed_count}, "
            f"total_sec={total_sec}s"
        )

        return {
            "success": failed_count == 0,  # 全部成功才算成功
            "total": total_count,
            "success_count": success_count,
            "failed_count": failed_count,
            "skipped_count": skipped_count,
            "results": results
        }
        
    except Exception as e:
        # 只有 update_creation_task=True 时才清除 current_task_id
        if update_creation_task:
            db = SessionLocal()
            try:
                creation = db.query(Creation).filter(Creation.uuid == creation_uuid).first()
                if creation:
                    creation.current_task_id = None
                    
                    # 更新状态为 failed
                    from app.services.creation_service import CreationService
                    CreationService.update_creation_step_status(
                        db=db,
                        creation_id=creation.creation_id,
                        step_name="characterImageGeneration",
                        status="failed",
                        error=str(e)
                    )
                    
                    db.commit()
                    logger.info(f"任务失败，创作 {creation.creation_id} 的 current_task_id 已清除")
            except Exception as clear_error:
                logger.opt(exception=True).error("清除 current_task_id 失败: {}", str(clear_error))
                db.rollback()
            finally:
                db.close()
        else:
            logger.info(f"update_creation_task=False，跳过清除 current_task_id（单个角色重新生成失败）")

        # 重新抛出异常
        logger.opt(exception=True).error("角色图片生成任务严重错误: {}", str(e))
        raise e
