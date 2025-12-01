"""
分镜图片生成任务
支持批量生成创作下所有分镜的图片
"""
import os
import uuid
import tempfile
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
from app.utils.points_deduction import deduct_points_for_image
from app.core.config import settings
from app.services.points_service import PointsService


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
    temp_file_path = None
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
            logger.info(f"分镜 {shot_id} 已有图片，跳过生成")
            return {
                "shot_id": shot_id,
                "shot_title": shot.title,
                "success": True,
                "image_url": shot.image_url,
                "skipped": True
            }
        
        # 检查是否有分镜描述（用于生成prompt）
        if not shot.description and not shot.image_prompt:
            logger.warning(f"分镜 {shot_id} 没有分镜描述或图片提示词，跳过生成")
            return {
                "shot_id": shot_id,
                "shot_title": shot.title,
                "success": False,
                "error": "没有分镜描述或图片提示词",
                "skipped": True
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
        
        # 如果没有角色图片，使用文生图；如果有角色图片，使用图生图
        use_reference_images = len(character_images) > 0
        if use_reference_images:
            logger.info(f"分镜 {shot_id} 关联了 {len(character_images)} 个角色的图片，使用图生图")
        else:
            logger.info(f"分镜 {shot_id} 没有关联角色或角色没有图片，使用文生图")
        
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
        
        # 使用LLM生成英文提示词
        ai_client = AIClient()
        current_shot_description = shot.description or shot.image_prompt or ""
        
        if use_reference_images:
            # 有角色图片时，使用完整的提示词生成流程（包含角色档案）
            logger.info(f"开始为分镜 {shot_id} 生成图片提示词（包含角色档案）")
            english_prompt = ai_client.generate_shot_image_prompt(
                character_profiles=character_profiles,
                previous_shot_description=previous_shot_description,
                current_shot_description=current_shot_description
            )
            logger.info(f"生成的英文提示词长度: {len(english_prompt)}")
            
            # 使用图生图API生成图片
            logger.info(f"开始为分镜 {shot_id} 进行图生图，参考图片数量: {len(character_images)}")
            temp_image_url = ai_client.generate_image_by_reference(
                prompt=english_prompt,
                reference_images=character_images,
                aspect_ratio="16:9"
            )
        else:
            # 没有角色图片时，直接使用分镜的描述或提示词，使用文生图
            logger.info(f"开始为分镜 {shot_id} 使用文生图")
            # 如果有image_prompt，直接使用；否则使用description
            prompt_text = shot.image_prompt or shot.description or ""
            if not prompt_text:
                logger.warning(f"分镜 {shot_id} 没有可用的提示词或描述")
                return {
                    "shot_id": shot_id,
                    "shot_title": shot.title,
                    "success": False,
                    "error": "没有可用的提示词或描述",
                    "skipped": True
                }
            
            temp_image_url = ai_client.generate_image_by_prompt(
                prompt=prompt_text,
                aspectRatio="1920x1080"  # 16:9 比例
            )
        
        # 从临时URL下载图像并上传到US3进行持久化
        try:
            logger.info(f"从URL下载图像: {temp_image_url}")
            # 下载图像
            with httpx.Client(timeout=30.0) as client:
                response = client.get(temp_image_url)
                response.raise_for_status()
                image_data = response.content
            logger.info(f"图像下载成功，大小: {len(image_data)} 字节")
            
            # 将图像数据保存到临时文件（US3 SDK 需要文件路径）
            image_extension = ".png"
            temp_fd, temp_file_path = tempfile.mkstemp(suffix=image_extension)
            try:
                with os.fdopen(temp_fd, 'wb') as tmp_file:
                    tmp_file.write(image_data)
                logger.info(f"图像已保存到临时文件: {temp_file_path}")
            except Exception as e:
                os.close(temp_fd)
                raise
            
            # 上传到US3
            # 生成US3存储路径: creations/{creation_id}/shots/{shot_id}/image_{uuid}.png
            image_uuid = str(uuid.uuid4())
            put_key = f"creations/{creation_id}/shots/{shot_id}/image_{image_uuid}{image_extension}"
            
            us3_client = US3Client()
            upload_result = us3_client.upload_file(
                local_file=temp_file_path,
                bucket=None,
                put_key=put_key
            )
            
            if not upload_result['success']:
                error_msg = f"图像上传US3失败: {upload_result.get('message')}"
                logger.error(error_msg)
                raise Exception(error_msg)
            
            # 生成US3持久化URL
            persistent_image_url = us3_client.get_file_url(put_key)
            logger.info(f"图像上传US3成功，持久化URL: {persistent_image_url}")
            
            image_url = persistent_image_url
            
        except Exception as e:
            # 如果US3上传失败，记录错误但继续使用临时URL（降级处理）
            error_msg = f"图像上传US3失败，使用临时URL: {str(e)}"
            logger.warning(error_msg, exc_info=True)
            image_url = temp_image_url
        finally:
            # 清理临时文件
            if temp_file_path and os.path.exists(temp_file_path):
                try:
                    os.remove(temp_file_path)
                    logger.debug(f"已清理临时文件: {temp_file_path}")
                except Exception as e:
                    logger.warning(f"删除临时文件失败: {str(e)}")
        
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
                logger.error(f"确认扣除冻结积分失败: {str(e)}", exc_info=True)
                # 确认失败不影响任务完成，但需要记录错误
        
        logger.info(f"分镜 {shot.title}(ID: {shot_id}) 图片生成成功")
        return {
            "shot_id": shot_id,
            "shot_title": shot.title,
            "success": True,
            "image_url": image_url
        }
    except Exception as e:
        logger.error(f"分镜 {shot_id} 图片生成失败: {str(e)}", exc_info=True)
        
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
                logger.error(f"释放冻结积分失败: {str(release_error)}", exc_info=True)
        
        db.rollback()
        return {
            "shot_id": shot_id,
            "success": False,
            "error": str(e)
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
    try:
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
        
        # 更新任务状态
        self.update_state(
            state="PROGRESS",
            meta={
                "task_type": TaskType.BATCH_SHOT_IMAGE_GENERATION,
                "creation_id": creation_id,
                "total": total_shots,
                "completed": 0,
                "success_count": 0,
                "failed_count": 0,
                "status": f"开始生成 {total_shots} 个分镜图片",
                "stage": "generating",
                "shots": all_shots
            }
        )
        
        # 使用线程池并发执行（最多5个并发，避免过载）
        results = []
        success_count = 0
        failed_count = 0
        
        max_workers = min(5, total_shots)
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            # 提交所有任务
            future_to_shot = {
                executor.submit(_generate_single_shot_image, shot["shot_id"], creation_id): shot
                for shot in all_shots
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
                    logger.error(error_msg, exc_info=True)
                    results.append({
                        "shot_id": shot_info["shot_id"],
                        "shot_title": shot_info["shot_title"],
                        "success": False,
                        "error": error_msg
                    })
        
        # 更新创作状态
        creation = db.query(Creation).filter(Creation.creation_id == creation_id).first()
        if creation:
            if failed_count == 0:
                creation.status = CreationStatus.SCENE_GENERATED
            creation.current_task_id = None
            db.commit()
        
        logger.info(
            f"创作 {creation_id} 分镜图片生成完成: "
            f"总数={total_shots}, 成功={success_count}, 失败={failed_count}"
        )
        
        return {
            "success": failed_count == 0,
            "task_type": TaskType.BATCH_SHOT_IMAGE_GENERATION,
            "creation_id": creation_id,
            "total": total_shots,
            "success_count": success_count,
            "failed_count": failed_count,
            "results": results
        }
        
    except Exception as e:
        error_msg = f"创作分镜图片生成任务失败: {str(e)}"
        logger.error(error_msg, exc_info=True)
        
        # 更新创作状态
        try:
            creation = db.query(Creation).filter(Creation.creation_id == creation_id).first()
            if creation:
                creation.current_task_id = None
                db.commit()
        except Exception:
            pass
        
        self.update_state(
            state="FAILURE",
            meta={
                "task_type": TaskType.BATCH_SHOT_IMAGE_GENERATION,
                "creation_id": creation_id,
                "error": error_msg,
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
    logger.info(f"开始并发生成 {total_count} 个分镜的图片: {shot_ids}")
    
    # 更新任务状态
    self.update_state(
        state="PROGRESS",
        meta={
            "task_type": TaskType.BATCH_SHOT_IMAGE_GENERATION,
            "creation_id": creation_id,
            "shot_ids": shot_ids,
            "total": total_count,
            "completed": 0,
            "failed": 0,
        },
    )
    
    results = []
    success_count = 0
    failed_count = 0
    
    try:
        # 使用线程池并发执行（最多5个并发）
        max_workers = min(5, total_count)
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            # 提交所有任务
            future_to_shot_id = {
                executor.submit(_generate_single_shot_image, sid, creation_id): sid
                for sid in shot_ids
            }
            
            # 收集结果
            for future in as_completed(future_to_shot_id):
                shot_id = future_to_shot_id[future]
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
                            "total": total_count,
                            "completed": success_count + failed_count,
                            "success": success_count,
                            "failed": failed_count,
                        },
                    )
                except Exception as e:
                    failed_count += 1
                    error_msg = f"分镜 {shot_id} 处理异常: {str(e)}"
                    logger.error(error_msg, exc_info=True)
                    results.append({
                        "shot_id": shot_id,
                        "success": False,
                        "error": error_msg
                    })
        
        # 任务完成
        logger.info(
            f"分镜图片生成任务完成: 总数={total_count}, "
            f"成功={success_count}, 失败={failed_count}"
        )
        
        return {
            "success": failed_count == 0,
            "task_type": TaskType.BATCH_SHOT_IMAGE_GENERATION,
            "creation_id": creation_id,
            "total": total_count,
            "success_count": success_count,
            "failed_count": failed_count,
            "results": results
        }
        
    except Exception as e:
        error_msg = f"分镜图片生成任务失败: {str(e)}"
        logger.error(error_msg, exc_info=True)
        self.update_state(
            state="FAILURE",
            meta={
                "task_type": TaskType.BATCH_SHOT_IMAGE_GENERATION,
                "creation_id": creation_id,
                "shot_ids": shot_ids,
                "error": error_msg,
            },
        )
        raise BaseServiceException(message=error_msg)


