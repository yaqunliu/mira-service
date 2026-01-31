"""
Agent 专用：分镜图片生成 Task

支持：
- 单个分镜图片生成（首帧 + 尾帧）
- 批量分镜使用 Celery group 并行生成
- 可单独重试某个分镜
"""

import time
import uuid as uuid_lib
import math
import httpx
import os
from typing import Dict, Any, Optional

from celery import group
from app.core.celery_app import celery_app
from sqlalchemy.orm import selectinload

from app.core.logger import logger
from app.core.config import settings
from app.models import Creation, Scene, Shot
from app.utils.ai_client import AIClient
from app.utils.model_prices import ModelPrices
from app.services.points_service import PointsService, InsufficientPointsError
from app.utils.upload_helper import UploadHelper


def _download_and_upload_image(
    temp_url: str,
    creation_id: int,
    shot_id: int,
    owner_uuid: str,
    suffix: str = "",
) -> Optional[str]:
    """下载临时图片并上传到云存储"""
    upload_helper = UploadHelper()
    time_str = time.strftime("%Y%m%d")
    
    image_data = None
    extension = ".png"
    
    if temp_url.startswith("local://"):
        temp_path = temp_url.replace("local://", "")
        if os.path.exists(temp_path):
            _, ext = os.path.splitext(temp_path)
            extension = ext or ".png"
            with open(temp_path, 'rb') as f:
                image_data = f.read()
    else:
        with httpx.Client(timeout=60.0) as client:
            response = client.get(temp_url)
            response.raise_for_status()
            image_data = response.content
    
    if not image_data:
        return None
    
    filename = f"shots/{creation_id}/{shot_id}/{uuid_lib.uuid4()}{suffix}{extension}"
    upload_result = upload_helper.upload_file_stream(
        file_data=image_data,
        user_uuid=owner_uuid,
        file_type="shots",
        filename=filename,
        time_str=time_str
    )
    
    if not upload_result.get('success'):
        logger.error(f"[AgentShotTask] 上传失败: {upload_result.get('message')}")
        return None
    
    return upload_result.get('external_url', upload_result.get('put_key'))


@celery_app.task(
    bind=True,
    name="agent_generate_single_shot_image_task",
    autoretry_for=(Exception,),
    max_retries=2,
    retry_backoff=True,
)
def agent_generate_single_shot_image_task(
    self,
    shot_id: int,
    creation_uuid: str,
    generate_end_frame: bool = True,
) -> Dict[str, Any]:
    """
    为单个分镜生成图片（首帧 + 可选尾帧）
    
    Args:
        shot_id: 分镜 ID
        creation_uuid: 创作 UUID
        generate_end_frame: 是否生成尾帧
    
    Returns:
        生成结果
    """
    from app.db.session import get_sync_session
    
    start_time = time.perf_counter()
    freeze_record_id = None
    
    try:
        # 1. 获取分镜数据
        with get_sync_session() as db:
            shot = (
                db.query(Shot)
                .options(
                    selectinload(Shot.characters),
                    selectinload(Shot.scene).selectinload(Scene.creation)
                )
                .filter(Shot.shot_id == shot_id)
                .first()
            )
            
            if not shot:
                return {"shot_id": shot_id, "success": False, "error": "分镜不存在"}
            
            creation = shot.scene.creation
            if not creation:
                return {"shot_id": shot_id, "success": False, "error": "创作不存在"}
            
            # 检查首帧提示词
            image_prompt = shot.image_prompt
            if not image_prompt:
                return {"shot_id": shot_id, "success": False, "error": "分镜缺少 image_prompt"}
            
            # 获取尾帧提示词
            shot_extra_data = shot.extra_data or {}
            end_frame_prompt = shot_extra_data.get("end_frame_prompt") if generate_end_frame else None
            
            # 获取参考图
            character_images = []
            if shot.characters:
                character_images = [c.image_url for c in shot.characters if c.image_url]
            
            # 获取模型配置
            extra_data = creation.extra_data or {}
            image_model = (
                extra_data.get("image_to_image_model")
                or extra_data.get("text_to_image_model")
                or settings.IMAGE_MODEL_IMAGE_TO_IMAGE
                or settings.IMAGE_MODEL_TEXT_TO_IMAGE
                or "black-forest-labs/flux-kontext-pro/multi"
            )
            
            # 获取 aspect ratio
            aspect_ratio_type = extra_data.get("aspect_ratio", "16:9")
            if aspect_ratio_type == "9:16":
                image_size = "864x1536"
            else:
                image_size = "1536x864"
            
            creation_id = creation.creation_id
            owner_id = creation.owner_id
            owner_uuid = str(creation.owner_uuid) if hasattr(creation, 'owner_uuid') else str(owner_id)
            
            # 冻结积分（首帧 + 尾帧）
            image_count = 2 if end_frame_prompt else 1
            ref_count = len(character_images)
            cost = ModelPrices.calculate_image_cost(image_model, image_count, reference_image_count=ref_count)
            required_points = max(1, int(math.ceil(cost * 100)))
            
            try:
                freeze_record = PointsService.freeze_points(
                    db=db,
                    user_id=owner_id,
                    points=required_points,
                    operation_type="agent_generate_shot",
                    creation_id=creation_id,
                    description=f"Agent 生成分镜图片 (shot_id={shot_id})",
                )
                freeze_record_id = freeze_record.record_id
            except InsufficientPointsError as e:
                return {"shot_id": shot_id, "success": False, "error": f"积分不足: {e}"}
        
        # 2. 更新任务状态
        self.update_state(state="PROGRESS", meta={
            "shot_id": shot_id,
            "status": "generating_start_frame",
        })
        
        # 3. 生成首帧图片
        ai_client = AIClient()
        logger.info(f"[AgentShotTask] 分镜 {shot_id} 开始生成首帧: prompt={image_prompt[:50]}...")
        
        if character_images:
            temp_url = ai_client.generate_image_by_reference(
                prompt=image_prompt,
                reference_images=character_images,
                model=image_model,
                aspect_ratio=image_size
            )
        else:
            temp_url = ai_client.generate_image_by_prompt(
                prompt=image_prompt,
                model=image_model,
                aspectRatio=image_size
            )
        
        start_frame_url = _download_and_upload_image(
            temp_url, creation_id, shot_id, owner_uuid, suffix="_start"
        )
        
        if not start_frame_url:
            raise Exception("首帧图片上传失败")
        
        logger.info(f"[AgentShotTask] 分镜 {shot_id} 首帧生成成功: {start_frame_url}")
        
        # 4. 生成尾帧图片（如果有提示词）
        end_frame_url = None
        if end_frame_prompt:
            self.update_state(state="PROGRESS", meta={
                "shot_id": shot_id,
                "status": "generating_end_frame",
            })
            
            logger.info(f"[AgentShotTask] 分镜 {shot_id} 开始生成尾帧: prompt={end_frame_prompt[:50]}...")
            
            if character_images:
                temp_url = ai_client.generate_image_by_reference(
                    prompt=end_frame_prompt,
                    reference_images=character_images,
                    model=image_model,
                    aspect_ratio=image_size
                )
            else:
                temp_url = ai_client.generate_image_by_prompt(
                    prompt=end_frame_prompt,
                    model=image_model,
                    aspectRatio=image_size
                )
            
            end_frame_url = _download_and_upload_image(
                temp_url, creation_id, shot_id, owner_uuid, suffix="_end"
            )
            
            if end_frame_url:
                logger.info(f"[AgentShotTask] 分镜 {shot_id} 尾帧生成成功: {end_frame_url}")
            else:
                logger.warning(f"[AgentShotTask] 分镜 {shot_id} 尾帧上传失败")
        
        # 5. 更新数据库
        with get_sync_session() as db:
            from sqlalchemy.orm.attributes import flag_modified
            
            shot = db.query(Shot).filter(Shot.shot_id == shot_id).first()
            if shot:
                shot.image_url = start_frame_url
                shot.status = "completed"
                
                # 保存尾帧 - 需要 flag_modified 让 SQLAlchemy 检测到 JSON 变化
                if end_frame_url:
                    shot_extra = dict(shot.extra_data or {})
                    shot_extra["end_frame_image_url"] = end_frame_url
                    shot.extra_data = shot_extra
                    flag_modified(shot, "extra_data")
                
                db.commit()
            
            # 确认积分
            if freeze_record_id:
                try:
                    PointsService.confirm_frozen_points(db=db, freeze_record_id=freeze_record_id)
                except Exception as e:
                    logger.error(f"[AgentShotTask] 确认积分失败: {e}")
        
        total_sec = round(time.perf_counter() - start_time, 3)
        logger.info(f"[AgentShotTask] 分镜 {shot_id} 完成, 耗时 {total_sec}s")
        
        return {
            "shot_id": shot_id,
            "success": True,
            "start_frame_url": start_frame_url,
            "end_frame_url": end_frame_url,
            "duration_sec": total_sec,
        }
        
    except Exception as e:
        logger.error(f"[AgentShotTask] 分镜 {shot_id} 生成失败: {e}")
        
        # 释放积分
        if freeze_record_id:
            try:
                from app.db.session import get_sync_session
                with get_sync_session() as db:
                    PointsService.release_frozen_points(db=db, freeze_record_id=freeze_record_id, reason=str(e))
            except Exception:
                pass
        
        raise  # 让 Celery 重试


@celery_app.task(bind=True, name="agent_generate_shot_images_task")
def agent_generate_shot_images_task(self, creation_uuid: str) -> Dict[str, Any]:
    """
    批量生成分镜图片
    
    使用 Celery group 为每个分镜创建独立任务，返回 group_id 用于轮询。
    
    Args:
        creation_uuid: 创作 UUID
    
    Returns:
        包含 group_id 和 shot_task_ids 的结果
    """
    from app.db.session import get_sync_session
    
    try:
        with get_sync_session() as db:
            creation = db.query(Creation).filter(Creation.uuid == creation_uuid).first()
            if not creation:
                raise Exception(f"创作不存在: {creation_uuid}")
            
            creation_id = creation.creation_id
            
            # 获取需要生成图片的分镜
            shots = (
                db.query(Shot)
                .join(Scene, Shot.scene_id == Scene.scene_id)
                .filter(Scene.creation_id == creation_id)
                .filter(Shot.image_prompt.isnot(None))
                .filter(Shot.image_url.is_(None))
                .all()
            )
            
            if not shots:
                logger.info(f"[AgentShotTask] 创作 {creation_uuid} 没有需要生成图片的分镜")
                return {
                    "success": True,
                    "creation_uuid": creation_uuid,
                    "total": 0,
                    "shot_task_ids": {},
                    "message": "没有需要生成图片的分镜",
                }
            
            shot_ids = [s.shot_id for s in shots]
        
        logger.info(f"[AgentShotTask] 创作 {creation_uuid} 开始生成 {len(shot_ids)} 个分镜图片")
        
        # 为每个分镜创建独立任务
        tasks = group([
            agent_generate_single_shot_image_task.s(
                shot_id=sid,
                creation_uuid=creation_uuid,
                generate_end_frame=True,
            )
            for sid in shot_ids
        ])
        
        # 派发任务组
        group_result = tasks.apply_async()
        
        # 保存每个子任务的 ID
        shot_task_ids = {}
        for i, async_result in enumerate(group_result.results):
            shot_task_ids[shot_ids[i]] = async_result.id
        
        logger.info(f"[AgentShotTask] 已派发 {len(shot_ids)} 个分镜任务, group_id={group_result.id}")
        
        return {
            "success": True,
            "creation_uuid": creation_uuid,
            "total": len(shot_ids),
            "group_id": group_result.id,
            "shot_task_ids": shot_task_ids,
            "message": f"已启动 {len(shot_ids)} 个分镜图片生成任务",
        }
        
    except Exception as e:
        logger.error(f"[AgentShotTask] 批量生成失败: {e}")
        return {
            "success": False,
            "creation_uuid": creation_uuid,
            "error": str(e),
        }
