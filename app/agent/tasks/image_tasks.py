"""
Agent 专用图片生成 Tasks

⚠️ 核心原则：这些 Tasks 独立于现有的 step3_character_image_gen_task 等任务
使用 AIClient 调用图片生成服务
"""

import os
import time
import uuid
import math
import httpx
from typing import Dict, Any, Optional
from dataclasses import dataclass

from celery import group
from sqlalchemy.orm import selectinload

from app.core.celery_app import celery_app
from app.core.logger import logger
from app.core.config import settings
from app.utils.model_prices import ModelPrices
from app.services.points_service import PointsService, InsufficientPointsError


# ==================== 积分处理辅助函数 ====================

@dataclass
class PointsFreezeResult:
    """积分冻结结果"""
    success: bool
    freeze_record_id: Optional[int] = None
    required_points: int = 0
    error: Optional[str] = None


def freeze_points_for_image_generation(
    db,
    user_id: int,
    creation_id: int,
    image_model: str,
    image_count: int = 1,
    reference_image_count: int = 0,
    operation_type: str = "agent_generate_image",
    description: str = "",
) -> PointsFreezeResult:
    """
    为图片生成冻结积分
    
    Args:
        db: 数据库会话
        user_id: 用户 ID
        creation_id: 创作 ID
        image_model: 图片生成模型名称
        image_count: 生成图片数量
        reference_image_count: 参考图数量
        operation_type: 操作类型
        description: 描述
        
    Returns:
        PointsFreezeResult 包含冻结结果
    """
    try:
        cost = ModelPrices.calculate_image_cost(
            image_model, 
            image_count, 
            reference_image_count=reference_image_count
        )
        required_points = max(1, int(math.ceil(cost * 100)))
        
        freeze_record = PointsService.freeze_points(
            db=db,
            user_id=user_id,
            points=required_points,
            operation_type=operation_type,
            creation_id=creation_id,
            description=description,
        )
        
        return PointsFreezeResult(
            success=True,
            freeze_record_id=freeze_record.record_id,
            required_points=required_points,
        )
        
    except InsufficientPointsError as e:
        return PointsFreezeResult(
            success=False,
            error=f"积分不足: {e}",
        )
    except Exception as e:
        logger.error(f"[Points] 冻结积分失败: {e}")
        return PointsFreezeResult(
            success=False,
            error=f"积分冻结失败: {e}",
        )


def confirm_frozen_points(db, freeze_record_id: int) -> bool:
    """确认冻结的积分（扣除）"""
    try:
        PointsService.confirm_frozen_points(db=db, freeze_record_id=freeze_record_id)
        return True
    except Exception as e:
        logger.error(f"[Points] 确认积分失败: {e}")
        return False


def release_frozen_points(db, freeze_record_id: int, reason: str = "") -> bool:
    """释放冻结的积分（失败回滚）"""
    try:
        PointsService.release_frozen_points(
            db=db, 
            freeze_record_id=freeze_record_id, 
            reason=reason
        )
        return True
    except Exception as e:
        logger.error(f"[Points] 释放积分失败: {e}")
        return False


# ==================== 图片下载上传辅助函数 ====================

def _download_image(temp_url: str) -> Optional[bytes]:
    """下载临时图片"""
    if temp_url.startswith("local://"):
        temp_path = temp_url.replace("local://", "")
        if os.path.exists(temp_path):
            with open(temp_path, 'rb') as f:
                return f.read()
        return None
    
    with httpx.Client(timeout=60.0) as client:
        response = client.get(temp_url)
        response.raise_for_status()
        return response.content


def _upload_to_us3(
    image_data: bytes,
    path_prefix: str,
    creation_uuid: str,
    entity_id: int,
) -> str:
    """上传图片到 US3"""
    from app.utils.us3 import US3Client
    
    us3_client = US3Client()
    filename = f"{path_prefix}/{creation_uuid}/{entity_id}_{uuid.uuid4().hex[:8]}.png"
    us3_client.upload_file_stream(image_data, put_key=filename, content_type="image/png")
    return us3_client.get_file_url(filename)


def _download_and_upload_shot_image(
    temp_url: str,
    creation_id: int,
    shot_id: int,
    owner_uuid: str,
    suffix: str = "",
) -> Optional[str]:
    """下载临时图片并上传到云存储（分镜专用）"""
    from app.utils.upload_helper import UploadHelper
    
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
    
    filename = f"shots/{creation_id}/{shot_id}/{uuid.uuid4()}{suffix}{extension}"
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


# ==================== 角色图片生成 ====================

@celery_app.task(
    bind=True, 
    name="agent.generate_character_image",
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_backoff_max=60,
    max_retries=3,
)
def agent_generate_character_image_task(
    self,
    creation_uuid: str,
    character_id: int,
    prompt: str,
    style: Optional[Dict[str, Any]] = None,
    model: str = None,
) -> Dict[str, Any]:
    """
    Agent 专用角色图片生成任务
    
    Args:
        creation_uuid: 创作项目 UUID
        character_id: 角色 ID
        prompt: 图片生成提示词
        style: 风格参数（可选）
        model: 生成模型
        
    Returns:
        生成结果 {"status", "character_id", "image_url", "error"}
    """
    from app.utils.ai_client import AIClient
    from app.db.session import get_sync_session
    from app.models.character import Character
    from app.models.creation import Creation
    
    freeze_record_id = None
    
    try:
        logger.info(f"[Agent Task] 开始生成角色图片: character_id={character_id}")
        
        self.update_state(state='PROGRESS', meta={
            'progress': 10, 'status': '开始生成角色图片...', 'character_id': character_id,
        })
        
        # 1. 获取数据 & 冻结积分
        with get_sync_session() as db:
            character = db.query(Character).filter(Character.character_id == character_id).first()
            if not character:
                raise Exception(f"角色不存在: {character_id}")
            
            creation = db.query(Creation).filter(Creation.uuid == creation_uuid).first()
            if not creation:
                raise Exception(f"创作不存在: {creation_uuid}")
            
            extra_data = creation.extra_data or {}
            text_to_image_model = model or extra_data.get("text_to_image_model") or settings.IMAGE_MODEL_NAME
            
            freeze_result = freeze_points_for_image_generation(
                db=db,
                user_id=creation.owner_id,
                creation_id=creation.creation_id,
                image_model=text_to_image_model,
                image_count=1,
                operation_type="agent_generate_character",
                description=f"Agent 生成角色图片 (character_id={character_id})",
            )
            
            if not freeze_result.success:
                return {"status": "failed", "character_id": character_id, "error": freeze_result.error}
            
            freeze_record_id = freeze_result.freeze_record_id
        
        # 2. 生成图片
        self.update_state(state='PROGRESS', meta={
            'progress': 30, 'status': '调用图片生成服务...', 'character_id': character_id,
        })
        
        ai_client = AIClient(text_to_image_model=text_to_image_model)
        temp_image_url = ai_client.generate_image_by_prompt(
            prompt=prompt, model=text_to_image_model, aspectRatio="1536x864"  # 16:9 比例
        )
        
        # 3. 上传图片
        self.update_state(state='PROGRESS', meta={
            'progress': 70, 'status': '上传图片到云存储...', 'character_id': character_id,
        })
        
        image_data = _download_image(temp_image_url)
        if not image_data:
            raise Exception("图片下载失败")
        
        us3_url = _upload_to_us3(image_data, "characters", creation_uuid, character_id)
        
        # 4. 更新数据库 & 确认积分
        self.update_state(state='PROGRESS', meta={
            'progress': 90, 'status': '保存结果到数据库...', 'character_id': character_id,
        })
        
        with get_sync_session() as db:
            character = db.query(Character).filter(Character.character_id == character_id).first()
            if character:
                character.image_url = us3_url
                character.image_prompt = prompt
                character.status = "completed"
                
                # 保存视觉风格（与专业模式一致）
                visual_style = style.get("visual_style", "anime") if style else "anime"
                character.visual_style = visual_style
                
                # 保存图片生成历史（与专业模式一致）
                if character.status_detail is None:
                    character.status_detail = {}
                
                import uuid as uuid_lib
                from datetime import datetime
                image_history = character.status_detail.get('image_history', [])
                image_history.append({
                    "version_id": str(uuid_lib.uuid4()),
                    "image_url": us3_url,
                    "image_prompt": prompt,
                    "model_name": text_to_image_model,
                    "visual_style": visual_style,
                    "generated_at": datetime.now().isoformat(),
                    "success": True,
                    "file_size": len(image_data) if image_data else None,
                    "is_current": False,
                })
                character.status_detail['image_history'] = image_history
                from sqlalchemy.orm.attributes import flag_modified
                flag_modified(character, "status_detail")
                
                db.commit()
            
            if freeze_record_id:
                confirm_frozen_points(db, freeze_record_id)
        
        logger.info(f"[Agent Task] 角色图片生成成功: character_id={character_id}")
        return {"status": "success", "character_id": character_id, "image_url": us3_url}
        
    except Exception as e:
        logger.error(f"[Agent Task] 角色图片生成失败: {e}")
        
        if freeze_record_id:
            try:
                from app.db.session import get_sync_session
                with get_sync_session() as db:
                    release_frozen_points(db, freeze_record_id, reason=str(e))
            except Exception:
                pass
        
        return {"status": "failed", "character_id": character_id, "error": str(e), "recoverable": True}


# ==================== 场景图片生成 ====================

@celery_app.task(
    bind=True, 
    name="agent.generate_scene_image",
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_backoff_max=60,
    max_retries=3,
)
def agent_generate_scene_image_task(
    self,
    creation_uuid: str,
    scene_id: int,
    prompt: str,
    style: Optional[Dict[str, Any]] = None,
    model: str = None,
) -> Dict[str, Any]:
    """
    Agent 专用场景图片生成任务
    
    Args:
        creation_uuid: 创作项目 UUID
        scene_id: 场景 ID
        prompt: 图片生成提示词
        style: 风格参数（可选）
        model: 生成模型
        
    Returns:
        生成结果 {"status", "scene_id", "image_url", "error"}
    """
    from app.utils.ai_client import AIClient
    from app.db.session import get_sync_session
    from app.models.scene import Scene
    from app.models.creation import Creation
    
    freeze_record_id = None
    
    try:
        logger.info(f"[Agent Task] 开始生成场景图片: scene_id={scene_id}")
        
        self.update_state(state='PROGRESS', meta={
            'progress': 10, 'status': '开始生成场景图片...', 'scene_id': scene_id,
        })
        
        # 1. 获取数据 & 冻结积分
        with get_sync_session() as db:
            scene = db.query(Scene).filter(Scene.scene_id == scene_id).first()
            if not scene:
                raise Exception(f"场景不存在: {scene_id}")
            
            creation = db.query(Creation).filter(Creation.uuid == creation_uuid).first()
            if not creation:
                raise Exception(f"创作不存在: {creation_uuid}")
            
            extra_data = creation.extra_data or {}
            text_to_image_model = model or extra_data.get("text_to_image_model") or settings.IMAGE_MODEL_NAME
            
            freeze_result = freeze_points_for_image_generation(
                db=db,
                user_id=creation.owner_id,
                creation_id=creation.creation_id,
                image_model=text_to_image_model,
                image_count=1,
                operation_type="agent_generate_scene",
                description=f"Agent 生成场景图片 (scene_id={scene_id})",
            )
            
            if not freeze_result.success:
                return {"status": "failed", "scene_id": scene_id, "error": freeze_result.error}
            
            freeze_record_id = freeze_result.freeze_record_id
        
        # 2. 生成图片
        self.update_state(state='PROGRESS', meta={
            'progress': 30, 'status': '调用图片生成服务...', 'scene_id': scene_id,
        })
        
        ai_client = AIClient(text_to_image_model=text_to_image_model)
        temp_image_url = ai_client.generate_image_by_prompt(
            prompt=prompt, model=text_to_image_model, aspectRatio="1536x864"
        )
        
        # 3. 上传图片
        self.update_state(state='PROGRESS', meta={
            'progress': 70, 'status': '上传图片到云存储...', 'scene_id': scene_id,
        })
        
        image_data = _download_image(temp_image_url)
        if not image_data:
            raise Exception("图片下载失败")
        
        us3_url = _upload_to_us3(image_data, "scenes", creation_uuid, scene_id)
        
        # 4. 更新数据库 & 确认积分
        self.update_state(state='PROGRESS', meta={
            'progress': 90, 'status': '保存结果到数据库...', 'scene_id': scene_id,
        })
        
        with get_sync_session() as db:
            scene = db.query(Scene).filter(Scene.scene_id == scene_id).first()
            if scene:
                scene.image_url = us3_url
                scene.status = "completed"
                
                # 存储提示词到 extra_data
                if scene.extra_data is None:
                    scene.extra_data = {}
                scene.extra_data["image_prompt"] = prompt
                
                # 保存图片生成历史到 status_detail
                import uuid as uuid_lib
                from datetime import datetime
                visual_style = style.get("visual_style", "anime") if style else "anime"
                
                if scene.status_detail is None:
                    scene.status_detail = {}
                image_history = scene.status_detail.get('image_history', [])
                image_history.append({
                    "version_id": str(uuid_lib.uuid4()),
                    "image_url": us3_url,
                    "image_prompt": prompt,
                    "model_name": text_to_image_model,
                    "visual_style": visual_style,
                    "generated_at": datetime.now().isoformat(),
                    "success": True,
                    "file_size": len(image_data) if image_data else None,
                    "is_current": False,
                })
                scene.status_detail['image_history'] = image_history
                
                from sqlalchemy.orm.attributes import flag_modified
                flag_modified(scene, "extra_data")
                flag_modified(scene, "status_detail")
                
                db.commit()
            
            if freeze_record_id:
                confirm_frozen_points(db, freeze_record_id)
        
        logger.info(f"[Agent Task] 场景图片生成成功: scene_id={scene_id}")
        return {"status": "success", "scene_id": scene_id, "image_url": us3_url}
        
    except Exception as e:
        logger.error(f"[Agent Task] 场景图片生成失败: {e}")
        
        if freeze_record_id:
            try:
                from app.db.session import get_sync_session
                with get_sync_session() as db:
                    release_frozen_points(db, freeze_record_id, reason=str(e))
            except Exception:
                pass
        
        return {"status": "failed", "scene_id": scene_id, "error": str(e), "recoverable": True}


# ==================== 分镜图片生成 ====================

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
    
    支持角色参考图和场景参考图
    
    Args:
        shot_id: 分镜 ID
        creation_uuid: 创作 UUID
        generate_end_frame: 是否生成尾帧
    
    Returns:
        生成结果 {"shot_id", "success", "start_frame_url", "end_frame_url", "error"}
    """
    from app.utils.ai_client import AIClient
    from app.db.session import get_sync_session
    from app.models import Creation, Scene, Shot
    
    start_time = time.perf_counter()
    freeze_record_id = None
    
    try:
        # 1. 获取分镜数据 & 冻结积分
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
            
            # 获取参考图（角色 + 场景）
            reference_images = []
            if shot.characters:
                reference_images.extend([c.image_url for c in shot.characters if c.image_url])
            if shot.scene and shot.scene.image_url:
                reference_images.append(shot.scene.image_url)
            
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
            image_size = "864x1536" if aspect_ratio_type == "9:16" else "1536x864"
            
            creation_id = creation.creation_id
            owner_id = creation.owner_id
            owner_uuid = str(creation.owner_uuid) if hasattr(creation, 'owner_uuid') else str(owner_id)
            
            # 冻结积分（首帧 + 尾帧）
            image_count = 2 if end_frame_prompt else 1
            freeze_result = freeze_points_for_image_generation(
                db=db,
                user_id=owner_id,
                creation_id=creation_id,
                image_model=image_model,
                image_count=image_count,
                reference_image_count=len(reference_images),
                operation_type="agent_generate_shot",
                description=f"Agent 生成分镜图片 (shot_id={shot_id})",
            )
            
            if not freeze_result.success:
                return {"shot_id": shot_id, "success": False, "error": freeze_result.error}
            
            freeze_record_id = freeze_result.freeze_record_id
        
        # 2. 生成首帧图片
        self.update_state(state="PROGRESS", meta={"shot_id": shot_id, "status": "generating_start_frame"})
        
        ai_client = AIClient()
        logger.info(f"[AgentShotTask] 分镜 {shot_id} 开始生成首帧, 参考图数量: {len(reference_images)}")
        
        if reference_images:
            temp_url = ai_client.generate_image_by_reference(
                prompt=image_prompt, reference_images=reference_images,
                model=image_model, aspect_ratio=image_size
            )
        else:
            temp_url = ai_client.generate_image_by_prompt(
                prompt=image_prompt, model=image_model, aspectRatio=image_size
            )
        
        start_frame_url = _download_and_upload_shot_image(
            temp_url, creation_id, shot_id, owner_uuid, suffix="_start"
        )
        
        if not start_frame_url:
            raise Exception("首帧图片上传失败")
        
        logger.info(f"[AgentShotTask] 分镜 {shot_id} 首帧生成成功: {start_frame_url}")
        
        # 3. 生成尾帧图片（如果有提示词）
        end_frame_url = None
        if end_frame_prompt:
            self.update_state(state="PROGRESS", meta={"shot_id": shot_id, "status": "generating_end_frame"})
            
            logger.info(f"[AgentShotTask] 分镜 {shot_id} 开始生成尾帧")
            
            if reference_images:
                temp_url = ai_client.generate_image_by_reference(
                    prompt=end_frame_prompt, reference_images=reference_images,
                    model=image_model, aspect_ratio=image_size
                )
            else:
                temp_url = ai_client.generate_image_by_prompt(
                    prompt=end_frame_prompt, model=image_model, aspectRatio=image_size
                )
            
            end_frame_url = _download_and_upload_shot_image(
                temp_url, creation_id, shot_id, owner_uuid, suffix="_end"
            )
            
            if end_frame_url:
                logger.info(f"[AgentShotTask] 分镜 {shot_id} 尾帧生成成功: {end_frame_url}")
            else:
                logger.warning(f"[AgentShotTask] 分镜 {shot_id} 尾帧上传失败")
        
        # 4. 更新数据库 & 确认积分
        with get_sync_session() as db:
            from sqlalchemy.orm.attributes import flag_modified
            import uuid as uuid_lib
            from datetime import datetime
            
            shot = db.query(Shot).filter(Shot.shot_id == shot_id).first()
            if shot:
                shot.image_url = start_frame_url
                shot.status = "completed"
                
                if end_frame_url:
                    shot_extra = dict(shot.extra_data or {})
                    shot_extra["end_frame_image_url"] = end_frame_url
                    shot.extra_data = shot_extra
                    flag_modified(shot, "extra_data")
                
                # 保存图片生成历史到 status_detail
                if shot.status_detail is None:
                    shot.status_detail = {}
                image_history = shot.status_detail.get('image_history', [])
                image_history.append({
                    "version_id": str(uuid_lib.uuid4()),
                    "start_frame_url": start_frame_url,
                    "end_frame_url": end_frame_url,
                    "image_prompt": image_prompt,
                    "end_frame_prompt": end_frame_prompt,
                    "model_name": image_model,
                    "generated_at": datetime.now().isoformat(),
                    "success": True,
                    "is_current": False,
                })
                shot.status_detail['image_history'] = image_history
                flag_modified(shot, "status_detail")
                
                db.commit()
            
            if freeze_record_id:
                confirm_frozen_points(db, freeze_record_id)
        
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
        
        if freeze_record_id:
            try:
                from app.db.session import get_sync_session
                with get_sync_session() as db:
                    release_frozen_points(db, freeze_record_id, reason=str(e))
            except Exception:
                pass
        
        raise  # 让 Celery 重试


# ==================== 批量分镜图片生成 ====================

@celery_app.task(
    bind=True, 
    name="agent_generate_shot_images_task",
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_backoff_max=60,
    max_retries=3,
)
def agent_generate_shot_images_task(self, creation_uuid: str) -> Dict[str, Any]:
    """
    批量生成分镜图片
    
    使用 Celery group 为每个分镜创建独立任务，返回 group_id 用于轮询。
    
    Args:
        creation_uuid: 创作 UUID
    
    Returns:
        {"success", "creation_uuid", "total", "group_id", "shot_task_ids", "error"}
    """
    from app.db.session import get_sync_session
    from app.models import Creation, Scene, Shot
    
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
