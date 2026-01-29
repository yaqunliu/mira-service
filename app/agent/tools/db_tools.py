"""
数据库查询和更新 Tools

提供给 Agent 查询和更新创作资产的工具
"""

from typing import Dict, Any, Optional, List

from langchain_core.tools import tool
from pydantic import BaseModel, Field

from app.core.logger import logger


# ==================== 输入模型定义 ====================

class QueryCharactersInput(BaseModel):
    """查询角色工具的输入参数"""
    creation_uuid: str = Field(..., description="创作项目 UUID")
    include_images: bool = Field(True, description="是否包含图片信息")
    status_filter: Optional[str] = Field(None, description="状态过滤: pending/completed/all")


class QueryScenesInput(BaseModel):
    """查询场景工具的输入参数"""
    creation_uuid: str = Field(..., description="创作项目 UUID")
    include_images: bool = Field(True, description="是否包含图片信息")


class QueryShotsInput(BaseModel):
    """查询分镜工具的输入参数"""
    creation_uuid: str = Field(..., description="创作项目 UUID")
    scene_id: Optional[int] = Field(None, description="场景 ID（可选，用于筛选特定场景的分镜）")
    include_details: bool = Field(True, description="是否包含详细信息")


class QueryCreationStatusInput(BaseModel):
    """查询创作整体状态工具的输入参数"""
    creation_uuid: str = Field(..., description="创作项目 UUID")


class UpdateCharacterInput(BaseModel):
    """更新角色工具的输入参数"""
    character_id: int = Field(..., description="角色 ID")
    name: Optional[str] = Field(None, description="角色名称")
    description: Optional[str] = Field(None, description="角色描述")
    image_prompt: Optional[str] = Field(None, description="图片生成提示词")


class UpdateSceneInput(BaseModel):
    """更新场景工具的输入参数"""
    scene_id: int = Field(..., description="场景 ID")
    name: Optional[str] = Field(None, description="场景名称")
    description: Optional[str] = Field(None, description="场景描述")
    image_prompt: Optional[str] = Field(None, description="图片生成提示词")


class UpdateShotInput(BaseModel):
    """更新分镜工具的输入参数"""
    shot_id: int = Field(..., description="分镜 ID")
    image_prompt: Optional[str] = Field(None, description="图片生成提示词")
    dialogue: Optional[str] = Field(None, description="对话文本")
    narration: Optional[str] = Field(None, description="旁白文本")


# ==================== 查询 Tools ====================

@tool
async def query_characters(
    creation_uuid: str,
    include_images: bool = True,
    status_filter: Optional[str] = None
) -> Dict[str, Any]:
    """
    查询创作项目的角色列表
    
    Args:
        creation_uuid: 创作项目 UUID
        include_images: 是否包含图片信息
        status_filter: 状态过滤（pending/completed/all）
        
    Returns:
        角色列表和统计信息
    """
    logger.info(f"[DB Tool] 查询角色: creation_uuid={creation_uuid}")
    
    from app.agent.tools.async_db import get_async_session
    from app.models.character import Character
    from app.models.creation import Creation
    from sqlalchemy import select
    
    async with get_async_session() as db:
        # 先获取 creation
        creation_stmt = select(Creation).where(Creation.uuid == creation_uuid)
        creation_result = await db.execute(creation_stmt)
        creation = creation_result.scalar_one_or_none()
        
        if not creation:
            return {"total": 0, "characters": [], "error": "创作项目不存在"}
        
        # 查询角色
        stmt = select(Character).where(Character.creation_id == creation.creation_id)
        result = await db.execute(stmt)
        characters = result.scalars().all()
        
        return {
            "total": len(characters),
            "characters": [
                {
                    "id": c.character_id,
                    "name": c.name,
                    "description": c.description,
                    "image_url": c.image_url if include_images else None,
                    "image_prompt": c.image_prompt,
                    "has_image": bool(c.image_url),
                }
                for c in characters
            ]
        }


@tool
async def query_scenes(
    creation_uuid: str,
    include_images: bool = True
) -> Dict[str, Any]:
    """
    查询创作项目的场景列表
    
    Args:
        creation_uuid: 创作项目 UUID
        include_images: 是否包含图片信息
        
    Returns:
        场景列表和统计信息
    """
    logger.info(f"[DB Tool] 查询场景: creation_uuid={creation_uuid}")
    
    from app.agent.tools.async_db import get_async_session
    from app.models.scene import Scene
    from app.models.creation import Creation
    from sqlalchemy import select
    
    async with get_async_session() as db:
        creation_stmt = select(Creation).where(Creation.uuid == creation_uuid)
        creation_result = await db.execute(creation_stmt)
        creation = creation_result.scalar_one_or_none()
        
        if not creation:
            return {"total": 0, "scenes": [], "error": "创作项目不存在"}
        
        stmt = select(Scene).where(Scene.creation_id == creation.creation_id)
        result = await db.execute(stmt)
        scenes = result.scalars().all()
        
        return {
            "total": len(scenes),
            "scenes": [
                {
                    "id": s.scene_id,
                    "name": s.name,
                    "description": s.description,
                    "image_url": s.image_url if include_images else None,
                    "image_prompt": s.image_prompt,
                    "has_image": bool(s.image_url),
                }
                for s in scenes
            ]
        }


@tool
async def query_shots(
    creation_uuid: str,
    scene_id: Optional[int] = None,
    include_details: bool = True
) -> Dict[str, Any]:
    """
    查询创作项目的分镜列表
    
    Args:
        creation_uuid: 创作项目 UUID
        scene_id: 场景 ID（可选，用于筛选特定场景）
        include_details: 是否包含详细信息
        
    Returns:
        分镜列表和统计信息
    """
    logger.info(f"[DB Tool] 查询分镜: creation_uuid={creation_uuid}, scene_id={scene_id}")
    
    from app.agent.tools.async_db import get_async_session
    from app.models.shot import Shot
    from app.models.creation import Creation
    from sqlalchemy import select
    
    async with get_async_session() as db:
        creation_stmt = select(Creation).where(Creation.uuid == creation_uuid)
        creation_result = await db.execute(creation_stmt)
        creation = creation_result.scalar_one_or_none()
        
        if not creation:
            return {"total": 0, "shots": [], "error": "创作项目不存在"}
        
        # Shot 没有直接的 creation_id，需要通过 Scene 关联
        from app.models.scene import Scene
        
        # 先获取该创作的所有场景 ID
        scene_stmt = select(Scene.scene_id).where(Scene.creation_id == creation.creation_id)
        scene_result = await db.execute(scene_stmt)
        scene_ids = [s[0] for s in scene_result.fetchall()]
        
        if not scene_ids:
            return {"total": 0, "shots": [], "with_image": 0, "with_video": 0}
        
        stmt = select(Shot).where(Shot.scene_id.in_(scene_ids))
        if scene_id:
            stmt = stmt.where(Shot.scene_id == scene_id)
        stmt = stmt.order_by(Shot.shot_number)
        
        result = await db.execute(stmt)
        shots = result.scalars().all()
        
        # 统计
        with_image = sum(1 for s in shots if s.image_url)
        with_video = sum(1 for s in shots if s.video_url)
        
        return {
            "total": len(shots),
            "with_image": with_image,
            "with_video": with_video,
            "shots": [
                {
                    "id": s.shot_id,
                    "sequence": s.sequence_number,
                    "scene_id": s.scene_id,
                    "dialogue": s.dialogue if include_details else None,
                    "narration": s.narration if include_details else None,
                    "image_url": s.image_url,
                    "video_url": s.video_url,
                    "image_prompt": s.image_prompt if include_details else None,
                    "has_image": bool(s.image_url),
                    "has_video": bool(s.video_url),
                }
                for s in shots
            ]
        }


@tool
async def query_creation_status(creation_uuid: str) -> Dict[str, Any]:
    """
    查询创作项目的整体状态
    
    Args:
        creation_uuid: 创作项目 UUID
        
    Returns:
        创作项目的综合状态信息
    """
    logger.info(f"[DB Tool] 查询创作状态: creation_uuid={creation_uuid}")
    
    from app.agent.tools.async_db import get_async_session
    from app.models.creation import Creation
    from app.models.character import Character
    from app.models.scene import Scene
    from app.models.shot import Shot
    from sqlalchemy import select, func
    
    async with get_async_session() as db:
        creation_stmt = select(Creation).where(Creation.uuid == creation_uuid)
        creation_result = await db.execute(creation_stmt)
        creation = creation_result.scalar_one_or_none()
        
        if not creation:
            return {"error": "创作项目不存在"}
        
        # 角色统计
        char_stmt = select(func.count()).select_from(Character).where(
            Character.creation_id == creation.creation_id
        )
        char_count = (await db.execute(char_stmt)).scalar()
        
        char_with_image_stmt = select(func.count()).select_from(Character).where(
            Character.creation_id == creation.creation_id,
            Character.image_url.isnot(None)
        )
        char_with_image = (await db.execute(char_with_image_stmt)).scalar()
        
        # 场景统计
        scene_stmt = select(func.count()).select_from(Scene).where(
            Scene.creation_id == creation.creation_id
        )
        scene_count = (await db.execute(scene_stmt)).scalar()
        
        scene_with_image_stmt = select(func.count()).select_from(Scene).where(
            Scene.creation_id == creation.creation_id,
            Scene.image_url.isnot(None)
        )
        scene_with_image = (await db.execute(scene_with_image_stmt)).scalar()
        
        # 分镜统计（Shot 没有直接 creation_id，需要通过 Scene 关联）
        # 先获取该创作的所有场景 ID
        scene_ids_stmt = select(Scene.scene_id).where(Scene.creation_id == creation.creation_id)
        scene_ids_result = await db.execute(scene_ids_stmt)
        scene_ids = [s[0] for s in scene_ids_result.fetchall()]
        
        if scene_ids:
            shot_stmt = select(func.count()).select_from(Shot).where(
                Shot.scene_id.in_(scene_ids)
            )
            shot_count = (await db.execute(shot_stmt)).scalar()
            
            shot_with_image_stmt = select(func.count()).select_from(Shot).where(
                Shot.scene_id.in_(scene_ids),
                Shot.image_url.isnot(None)
            )
            shot_with_image = (await db.execute(shot_with_image_stmt)).scalar()
            
            shot_with_video_stmt = select(func.count()).select_from(Shot).where(
                Shot.scene_id.in_(scene_ids),
                Shot.video_url.isnot(None)
            )
            shot_with_video = (await db.execute(shot_with_video_stmt)).scalar()
        else:
            shot_count = 0
            shot_with_image = 0
            shot_with_video = 0
        
        return {
            "creation_uuid": creation_uuid,
            "title": creation.title,
            "status": creation.status,
            "characters": {
                "total": char_count,
                "with_image": char_with_image,
                "progress": f"{char_with_image}/{char_count}" if char_count else "0/0",
            },
            "scenes": {
                "total": scene_count,
                "with_image": scene_with_image,
                "progress": f"{scene_with_image}/{scene_count}" if scene_count else "0/0",
            },
            "shots": {
                "total": shot_count,
                "with_image": shot_with_image,
                "with_video": shot_with_video,
                "image_progress": f"{shot_with_image}/{shot_count}" if shot_count else "0/0",
                "video_progress": f"{shot_with_video}/{shot_count}" if shot_count else "0/0",
            },
        }


# ==================== 更新 Tools ====================

@tool
async def update_character(
    character_id: int,
    name: Optional[str] = None,
    description: Optional[str] = None,
    image_prompt: Optional[str] = None
) -> Dict[str, Any]:
    """
    更新角色信息
    
    Args:
        character_id: 角色 ID
        name: 新名称（可选）
        description: 新描述（可选）
        image_prompt: 新提示词（可选）
        
    Returns:
        更新结果
    """
    logger.info(f"[DB Tool] 更新角色: character_id={character_id}")
    
    from app.agent.tools.async_db import get_async_session
    from app.models.character import Character
    from sqlalchemy import select
    
    async with get_async_session() as db:
        stmt = select(Character).where(Character.character_id == character_id)
        result = await db.execute(stmt)
        character = result.scalar_one_or_none()
        
        if not character:
            return {"success": False, "error": "角色不存在"}
        
        updated_fields = []
        if name is not None:
            character.name = name
            updated_fields.append("name")
        if description is not None:
            character.description = description
            updated_fields.append("description")
        if image_prompt is not None:
            character.image_prompt = image_prompt
            updated_fields.append("image_prompt")
        
        await db.commit()
        
        return {
            "success": True,
            "character_id": character_id,
            "updated_fields": updated_fields,
        }


@tool
async def update_scene(
    scene_id: int,
    name: Optional[str] = None,
    description: Optional[str] = None,
    image_prompt: Optional[str] = None
) -> Dict[str, Any]:
    """
    更新场景信息
    
    Args:
        scene_id: 场景 ID
        name: 新名称（可选）
        description: 新描述（可选）
        image_prompt: 新提示词（可选）
        
    Returns:
        更新结果
    """
    logger.info(f"[DB Tool] 更新场景: scene_id={scene_id}")
    
    from app.agent.tools.async_db import get_async_session
    from app.models.scene import Scene
    from sqlalchemy import select
    
    async with get_async_session() as db:
        stmt = select(Scene).where(Scene.scene_id == scene_id)
        result = await db.execute(stmt)
        scene = result.scalar_one_or_none()
        
        if not scene:
            return {"success": False, "error": "场景不存在"}
        
        updated_fields = []
        if name is not None:
            scene.name = name
            updated_fields.append("name")
        if description is not None:
            scene.description = description
            updated_fields.append("description")
        if image_prompt is not None:
            scene.image_prompt = image_prompt
            updated_fields.append("image_prompt")
        
        await db.commit()
        
        return {
            "success": True,
            "scene_id": scene_id,
            "updated_fields": updated_fields,
        }


@tool
async def update_shot(
    shot_id: int,
    image_prompt: Optional[str] = None,
    dialogue: Optional[str] = None,
    narration: Optional[str] = None
) -> Dict[str, Any]:
    """
    更新分镜信息
    
    Args:
        shot_id: 分镜 ID
        image_prompt: 新图片提示词（可选）
        dialogue: 新对话文本（可选）
        narration: 新旁白文本（可选）
        
    Returns:
        更新结果
    """
    logger.info(f"[DB Tool] 更新分镜: shot_id={shot_id}")
    
    from app.agent.tools.async_db import get_async_session
    from app.models.shot import Shot
    from sqlalchemy import select
    
    async with get_async_session() as db:
        stmt = select(Shot).where(Shot.shot_id == shot_id)
        result = await db.execute(stmt)
        shot = result.scalar_one_or_none()
        
        if not shot:
            return {"success": False, "error": "分镜不存在"}
        
        updated_fields = []
        if image_prompt is not None:
            shot.image_prompt = image_prompt
            updated_fields.append("image_prompt")
        if dialogue is not None:
            shot.dialogue = dialogue
            updated_fields.append("dialogue")
        if narration is not None:
            shot.narration = narration
            updated_fields.append("narration")
        
        await db.commit()
        
        return {
            "success": True,
            "shot_id": shot_id,
            "updated_fields": updated_fields,
        }
