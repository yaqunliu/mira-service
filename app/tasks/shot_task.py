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


def _generate_single_shot_image(shot_id: int, creation_id: int) -> dict:
    """
    生成单个分镜的图片（线程安全函数）
    
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
        shot = (
            db.query(Shot)
            .options(selectinload(Shot.scene))
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
        
        # 检查是否有图片生成提示词
        if not shot.image_prompt:
            logger.warning(f"分镜 {shot_id} 没有图片提示词，跳过生成")
            return {
                "shot_id": shot_id,
                "shot_title": shot.title,
                "success": False,
                "error": "没有图片提示词",
                "skipped": True
            }
        
        # 使用分镜的 image_prompt 调用生图 API
        logger.info(f"开始为分镜 {shot_id} 生成图片，提示词长度: {len(shot.image_prompt)}")
        
        # 调用生图API
        temp_image_url = AIClient().generate_image_by_prompt(
            prompt=shot.image_prompt,
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
        
        logger.info(f"分镜 {shot.title}(ID: {shot_id}) 图片生成成功")
        return {
            "shot_id": shot_id,
            "shot_title": shot.title,
            "success": True,
            "image_url": image_url
        }
    except Exception as e:
        logger.error(f"分镜 {shot_id} 图片生成失败: {str(e)}", exc_info=True)
        db.rollback()
        return {
            "shot_id": shot_id,
            "success": False,
            "error": str(e)
        }
    finally:
        db.close()


@celery_app.task(bind=True, name="generate_single_shot_image_task")
def generate_single_shot_image_task(self, shot_id: int, creation_id: int) -> dict:
    """
    Celery任务：生成单个分镜的图片
    
    Args:
        shot_id: 分镜ID
        creation_id: 创作ID
        
    Returns:
        包含分镜ID和处理结果的字典
    """
    logger.info(f"开始执行分镜图片生成任务: shot_id={shot_id}, creation_id={creation_id}")
    
    self.update_state(
        state="PROGRESS",
        meta={
            "task_type": TaskType.SHOT_IMAGE_GENERATION,
            "shot_id": shot_id,
            "creation_id": creation_id,
            "status": "生成中"
        }
    )
    
    result = _generate_single_shot_image(shot_id, creation_id)
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
        raise BaseServiceException(detail=error_msg)
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
        raise BaseServiceException(detail=error_msg)


