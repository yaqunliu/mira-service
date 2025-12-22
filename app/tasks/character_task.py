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


def _generate_single_character_image(character_id: int, visual_style: str, force_regenerate: bool = True) -> dict:
    """
    生成单个角色的图片（线程安全函数）

    Args:
        character_id: 角色ID
        visual_style: 视觉风格
        force_regenerate: 是否强制重新生成（True: 强制生成，False: 如果已有图片则跳过）

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
            return {
                "character_id": character_id,
                "character_name": character.name,
                "success": True,
                "skipped": True,
                "image_url": character.image_url
            }
        
        # 生成提示词
        system_prompt = read_prompt_file("character.md")
        image_prompt = (
            f"{system_prompt}\n"
            # f"视觉风格：{visual_style}，"
            f"基本信息：{character.basic_info}，"
            f"外貌特征：{character.appearance}，"
            f"身材特征：{character.body}，"
            f"发型：{character.hair}，"
            f"服装：{character.clothing}，"
            f"特征标签：{character.tags}。"
        )
        # logger.info(f"{character.name}生成图片提示词: {image_prompt}")
        
        # 从创作配置中获取模型配置
        creation = character.creation
        extra_data = creation.extra_data or {} if creation else {}
        text_to_image_model = extra_data.get("text_to_image_model")
        
        # 调用生图API（使用配置的模型，aspect_ratio 会从模型配置中自动获取）
        ai_client = AIClient(text_to_image_model=text_to_image_model)
        image_start = time.perf_counter()
        temp_image_url = ai_client.generate_image_by_prompt(
            prompt=image_prompt,
            model=text_to_image_model
        )
        timings["image_api_sec"] = round(time.perf_counter() - image_start, 3)
        
        # 从临时URL下载图像并上传到US3进行持久化（使用流式上传）
        persist_start = time.perf_counter()
        try:
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


@celery_app.task(bind=True, name="generate_character_image_task")
def generate_character_image_task(
    self,
    character_ids: List[int],
    visual_style: str,
    creation_uuid: str,
    force_regenerate: bool = False,
    update_creation_task: bool = True
):
    """
    并发生成多个角色的图片

    Args:
        character_ids: 角色ID列表
        visual_style: 视觉风格
        creation_uuid: 创作UUID，用于获取creation并更新current_task_id
        force_regenerate: 是否强制重新生成（False: 跳过已有图片的角色，True: 强制生成所有）
        update_creation_task: 是否更新creation的current_task_id（False: 不更新，避免触发页面跳转）

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
                executor.submit(_generate_single_character_image, cid, visual_style, force_regenerate): cid
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
        
    except BaseServiceException as e:
        # 只有 update_creation_task=True 时才清除 current_task_id
        if update_creation_task:
            db = SessionLocal()
            try:
                creation = db.query(Creation).filter(Creation.uuid == creation_uuid).first()
                if creation:
                    creation.current_task_id = None
                    db.commit()
                    logger.info(f"任务失败，创作 {creation.creation_id} 的 current_task_id 已清除")
            except Exception as clear_error:
                logger.opt(exception=True).error("清除 current_task_id 失败: {}", str(clear_error))
                db.rollback()
            finally:
                db.close()
        else:
            logger.info(f"update_creation_task=False，跳过清除 current_task_id（单个角色重新生成失败）")

        # BaseServiceException 直接重新抛出，不进行包装
        error_msg = str(e)
        exc_type = type(e).__name__
        exc_module = type(e).__module__
        self.update_state(
            state="FAILURE",
            meta={
                "task_type": TaskType.CHARACTER_IMAGE_GENERATION,
                "character_ids": character_ids,
                "error": error_msg,
                "exc_type": f"{exc_module}.{exc_type}",
                "exc_message": error_msg,
            },
        )
        raise
    except Exception as e:
        # 只有 update_creation_task=True 时才清除 current_task_id
        if update_creation_task:
            db = SessionLocal()
            try:
                creation = db.query(Creation).filter(Creation.uuid == creation_uuid).first()
                if creation:
                    creation.current_task_id = None
                    db.commit()
                    logger.info(f"任务失败，创作 {creation.creation_id} 的 current_task_id 已清除")
            except Exception as clear_error:
                logger.opt(exception=True).error("清除 current_task_id 失败: {}", str(clear_error))
                db.rollback()
            finally:
                db.close()
        else:
            logger.info(f"update_creation_task=False，跳过清除 current_task_id（单个角色重新生成失败）")

        error_msg = f"角色图片生成任务失败: {str(e)}"
        logger.opt(exception=True).error("{}", error_msg)
        exc_type = type(e).__name__
        exc_module = type(e).__module__
        self.update_state(
            state="FAILURE",
            meta={
                "task_type": TaskType.CHARACTER_IMAGE_GENERATION,
                "character_ids": character_ids,
                "error": error_msg,
                "exc_type": f"{exc_module}.{exc_type}",
                "exc_message": error_msg,
            },
        )
        raise BaseServiceException(message=error_msg)
