"""
Agent 专用图片生成 Tasks

⚠️ 核心原则：这些 Tasks 独立于现有的 step3_character_image_gen_task 等任务
使用 AIClient 调用图片生成服务
"""

import os
import uuid
import httpx
from typing import Dict, Any, Optional

from app.core.celery_app import celery_app
from app.core.logger import logger
from app.core.config import settings


@celery_app.task(bind=True, name="agent.generate_character_image")
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
        {
            "status": "success" | "failed",
            "character_id": int,
            "image_url": str,
            "error": str  # 仅失败时
        }
    """
    try:
        logger.info(f"[Agent Task] 开始生成角色图片: character_id={character_id}")
        
        # 更新进度
        self.update_state(state='PROGRESS', meta={
            'progress': 10,
            'status': '开始生成角色图片...',
            'character_id': character_id,
        })
        
        # 导入服务（延迟导入避免循环依赖）
        from app.utils.ai_client import AIClient
        from app.utils.us3 import US3Client
        from app.db.session import get_sync_session
        from app.models.character import Character
        from app.models.creation import Creation
        
        # 获取创作配置
        with get_sync_session() as db:
            character = db.query(Character).filter(
                Character.character_id == character_id
            ).first()
            
            if not character:
                raise Exception(f"角色不存在: {character_id}")
            
            creation = db.query(Creation).filter(
                Creation.uuid == creation_uuid
            ).first()
            
            extra_data = creation.extra_data or {} if creation else {}
            text_to_image_model = model or extra_data.get("text_to_image_model") or settings.IMAGE_MODEL_NAME
        
        # 初始化客户端
        ai_client = AIClient(text_to_image_model=text_to_image_model)
        us3_client = US3Client()
        
        self.update_state(state='PROGRESS', meta={
            'progress': 30,
            'status': '调用图片生成服务...',
            'character_id': character_id,
        })
        
        # 生成图片（角色图使用 1:1 尺寸）
        image_size = "1024x1024"
        temp_image_url = ai_client.generate_image_by_prompt(
            prompt=prompt,
            model=text_to_image_model,
            aspectRatio=image_size
        )
        
        self.update_state(state='PROGRESS', meta={
            'progress': 70,
            'status': '上传图片到云存储...',
            'character_id': character_id,
        })
        
        # 下载并上传到 US3
        image_data = None
        if temp_image_url.startswith("local://"):
            temp_file_path = temp_image_url.replace("local://", "")
            with open(temp_file_path, 'rb') as f:
                image_data = f.read()
        else:
            with httpx.Client(timeout=60.0) as client:
                resp = client.get(temp_image_url)
                resp.raise_for_status()
                image_data = resp.content
        
        # 上传 US3
        filename = f"characters/{creation_uuid}/{character_id}_{uuid.uuid4().hex[:8]}.png"
        us3_client.upload_file_stream(image_data, put_key=filename, content_type="image/png")
        us3_url = us3_client.get_file_url(filename)
        
        self.update_state(state='PROGRESS', meta={
            'progress': 90,
            'status': '保存结果到数据库...',
            'character_id': character_id,
        })
        
        # 更新数据库
        with get_sync_session() as db:
            character = db.query(Character).filter(
                Character.character_id == character_id
            ).first()
            if character:
                character.image_url = us3_url
                character.image_prompt = prompt
                character.status = "completed"
                db.commit()
        
        logger.info(f"[Agent Task] 角色图片生成成功: character_id={character_id}")
        
        return {
            "status": "success",
            "character_id": character_id,
            "image_url": us3_url,
        }
        
    except Exception as e:
        logger.error(f"[Agent Task] 角色图片生成失败: {e}")
        return {
            "status": "failed",
            "character_id": character_id,
            "error": str(e),
            "recoverable": True,
        }


@celery_app.task(bind=True, name="agent.generate_scene_image")
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
        生成结果
    """
    try:
        logger.info(f"[Agent Task] 开始生成场景图片: scene_id={scene_id}")
        
        self.update_state(state='PROGRESS', meta={
            'progress': 10,
            'status': '开始生成场景图片...',
            'scene_id': scene_id,
        })
        
        from app.utils.ai_client import AIClient
        from app.utils.us3 import US3Client
        from app.db.session import get_sync_session
        from app.models.scene import Scene
        from app.models.creation import Creation
        
        # 获取创作配置
        with get_sync_session() as db:
            scene = db.query(Scene).filter(Scene.scene_id == scene_id).first()
            
            if not scene:
                raise Exception(f"场景不存在: {scene_id}")
            
            creation = db.query(Creation).filter(
                Creation.uuid == creation_uuid
            ).first()
            
            extra_data = creation.extra_data or {} if creation else {}
            text_to_image_model = model or extra_data.get("text_to_image_model") or settings.IMAGE_MODEL_NAME
        
        # 初始化客户端
        ai_client = AIClient(text_to_image_model=text_to_image_model)
        us3_client = US3Client()
        
        self.update_state(state='PROGRESS', meta={
            'progress': 30,
            'status': '调用图片生成服务...',
            'scene_id': scene_id,
        })
        
        # 生成图片（场景图使用 16:9 尺寸）
        image_size = "1536x864"
        temp_image_url = ai_client.generate_image_by_prompt(
            prompt=prompt,
            model=text_to_image_model,
            aspectRatio=image_size
        )
        
        self.update_state(state='PROGRESS', meta={
            'progress': 70,
            'status': '上传图片到云存储...',
            'scene_id': scene_id,
        })
        
        # 下载并上传到 US3
        image_data = None
        if temp_image_url.startswith("local://"):
            temp_file_path = temp_image_url.replace("local://", "")
            with open(temp_file_path, 'rb') as f:
                image_data = f.read()
        else:
            with httpx.Client(timeout=60.0) as client:
                resp = client.get(temp_image_url)
                resp.raise_for_status()
                image_data = resp.content
        
        # 上传 US3
        filename = f"scenes/{creation_uuid}/{scene_id}_{uuid.uuid4().hex[:8]}.png"
        us3_client.upload_file_stream(image_data, put_key=filename, content_type="image/png")
        us3_url = us3_client.get_file_url(filename)
        
        self.update_state(state='PROGRESS', meta={
            'progress': 90,
            'status': '保存结果到数据库...',
            'scene_id': scene_id,
        })
        
        # 更新数据库
        with get_sync_session() as db:
            scene = db.query(Scene).filter(Scene.scene_id == scene_id).first()
            if scene:
                scene.image_url = us3_url
                scene.image_prompt = prompt
                scene.status = "completed"
                db.commit()
        
        logger.info(f"[Agent Task] 场景图片生成成功: scene_id={scene_id}")
        
        return {
            "status": "success",
            "scene_id": scene_id,
            "image_url": us3_url,
        }
        
    except Exception as e:
        logger.error(f"[Agent Task] 场景图片生成失败: {e}")
        return {
            "status": "failed",
            "scene_id": scene_id,
            "error": str(e),
            "recoverable": True,
        }


@celery_app.task(bind=True, name="agent.generate_shot_image")
def agent_generate_shot_image_task(
    self,
    creation_uuid: str,
    shot_id: int,
    prompt: str,
    frame_type: str = "both",  # "start", "end", "both"
    style: Optional[Dict[str, Any]] = None,
    model: str = "doubao",
) -> Dict[str, Any]:
    """
    Agent 专用分镜图片生成任务
    
    Args:
        creation_uuid: 创作项目 UUID
        shot_id: 分镜 ID
        prompt: 图片生成提示词
        frame_type: 帧类型（start=首帧, end=尾帧, both=双帧）
        style: 风格参数（可选）
        model: 生成模型（默认 doubao）
        
    Returns:
        生成结果
    """
    try:
        logger.info(f"[Agent Task] 开始生成分镜图片: shot_id={shot_id}, frame_type={frame_type}")
        
        self.update_state(state='PROGRESS', meta={
            'progress': 10,
            'status': '开始生成分镜图片...',
            'shot_id': shot_id,
            'frame_type': frame_type,
        })
        
        from app.services.image_generation import ImageGenerationService
        
        image_service = ImageGenerationService()
        results = {}
        
        if frame_type in ["start", "both"]:
            self.update_state(state='PROGRESS', meta={
                'progress': 30,
                'status': '生成首帧图片...',
                'shot_id': shot_id,
            })
            
            start_result = image_service.generate(
                prompt=prompt,
                style=style or {},
                model=model,
            )
            results["start_image_url"] = start_result["url"]
        
        if frame_type in ["end", "both"]:
            self.update_state(state='PROGRESS', meta={
                'progress': 60,
                'status': '生成尾帧图片...',
                'shot_id': shot_id,
            })
            
            # 尾帧可能需要不同的提示词
            end_prompt = prompt  # 这里可以根据需求修改
            end_result = image_service.generate(
                prompt=end_prompt,
                style=style or {},
                model=model,
            )
            results["end_image_url"] = end_result["url"]
        
        self.update_state(state='PROGRESS', meta={
            'progress': 90,
            'status': '保存结果到数据库...',
            'shot_id': shot_id,
        })
        
        # 更新数据库
        from app.db.session import get_sync_session
        from app.models.shot import Shot
        
        with get_sync_session() as db:
            shot = db.query(Shot).filter(Shot.shot_id == shot_id).first()
            if shot:
                if "start_image_url" in results:
                    shot.image_url = results["start_image_url"]
                    shot.image_prompt = prompt
                if "end_image_url" in results:
                    extra_data = shot.extra_data or {}
                    extra_data["end_frame_image_url"] = results["end_image_url"]
                    shot.extra_data = extra_data
                db.commit()
        
        logger.info(f"[Agent Task] 分镜图片生成成功: shot_id={shot_id}")
        
        return {
            "status": "success",
            "shot_id": shot_id,
            "frame_type": frame_type,
            **results,
        }
        
    except Exception as e:
        logger.error(f"[Agent Task] 分镜图片生成失败: {e}")
        return {
            "status": "failed",
            "shot_id": shot_id,
            "error": str(e),
            "recoverable": True,
        }
