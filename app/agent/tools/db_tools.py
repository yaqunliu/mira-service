"""
数据库查询和更新 Tools

提供给 Agent 查询和更新创作资产的工具
"""

import json
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
    
    通过 Creation.character_ids 字段获取角色ID列表，然后查询角色详情
    
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
        
        # 从 creation.character_ids 获取角色ID列表
        character_ids = creation.character_ids or []
        logger.info(f"[DB Tool] creation.character_ids: {character_ids}")
        
        if not character_ids:
            return {"total": 0, "characters": [], "message": "创作项目没有关联角色"}
        
        # 查询角色
        stmt = select(Character).where(Character.character_id.in_(character_ids))
        result = await db.execute(stmt)
        characters = result.scalars().all()
        
        logger.info(f"[DB Tool] 查询到 {len(characters)} 个角色")
        
        return {
            "success": True,
            "total": len(characters),
            "characters": [
                {
                    "id": c.character_id,
                    "name": c.name,
                    "basic_info": c.basic_info,
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
    
    通过 Creation.scene_ids 字段获取场景ID列表，然后查询场景详情
    
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
        
        # 从 creation.scene_ids 获取场景ID列表
        scene_ids = creation.scene_ids or []
        logger.info(f"[DB Tool] creation.scene_ids: {scene_ids}")
        
        if not scene_ids:
            return {"total": 0, "scenes": [], "message": "创作项目没有关联场景"}
        
        stmt = select(Scene).where(Scene.scene_id.in_(scene_ids))
        result = await db.execute(stmt)
        scenes = result.scalars().all()
        
        logger.info(f"[DB Tool] 查询到 {len(scenes)} 个场景")
        
        return {
            "total": len(scenes),
            "scenes": [
                {
                    "id": s.scene_id,
                    "title": s.title,
                    "location": s.location,
                    "image_url": s.image_url if include_images else None,
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
            "success": True,
            "total": len(shots),
            "with_image": with_image,
            "with_video": with_video,
            "shots": [
                {
                    "id": s.shot_id,
                    "shot_id": s.shot_id,  # 同时提供两个字段名供兼容
                    "shot_number": s.shot_number,  # 添加 shot_number 字段
                    "sequence": s.shot_number,
                    "title": s.title,  # 添加 title 字段
                    "scene_id": s.scene_id,
                    "description": s.description if include_details else None,
                    "narration": s.narration if include_details else None,
                    "image_url": s.image_url,
                    "video_url": s.video_url,
                    "image_prompt": s.image_prompt if include_details else None,
                    "video_duration": s.video_duration,
                    "extra_data": s.extra_data or {},
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


# ==================== 单个资源查询 Tools ====================

@tool
async def query_single_character(character_id: int) -> Dict[str, Any]:
    """
    查询单个角色详情
    
    获取角色的完整信息，包括基本信息、外貌、状态、提示词等。
    
    Args:
        character_id: 角色ID
        
    Returns:
        {
            "success": bool,
            "character_id": int,
            "name": str,
            "basic_info": str,
            "appearance": str,
            "image_prompt": str,
            "image_url": str,
            ...
        }
    """
    logger.info(f"[DB Tool] 查询单个角色: character_id={character_id}")
    
    from app.agent.tools.async_db import get_async_session
    from app.models.character import Character
    from sqlalchemy import select
    
    async with get_async_session() as db:
        stmt = select(Character).where(Character.character_id == character_id)
        result = await db.execute(stmt)
        character = result.scalar_one_or_none()
        
        if not character:
            return {
                "success": False,
                "error": f"角色不存在: {character_id}",
            }
        
        return {
            "success": True,
            "character_id": character.character_id,
            "name": character.name,
            "basic_info": character.basic_info,
            "appearance": character.appearance,
            "image_prompt": character.image_prompt,
            "image_url": character.image_url,
            "status": character.status,
            "status_detail": character.status_detail,
            "voice_id": character.voice_id,
            "voice_speed": character.voice_speed,
        }


@tool
async def query_single_scene(scene_id: int) -> Dict[str, Any]:
    """
    查询单个场景详情
    
    获取场景的完整信息，包括场景设置、状态、提示词等。
    
    Args:
        scene_id: 场景ID
        
    Returns:
        {
            "success": bool,
            "scene_id": int,
            "title": str,
            "location": str,
            "time_setting": str,
            "atmosphere": str,
            ...
        }
    """
    logger.info(f"[DB Tool] 查询单个场景: scene_id={scene_id}")
    
    from app.agent.tools.async_db import get_async_session
    from app.models.scene import Scene
    from sqlalchemy import select
    
    async with get_async_session() as db:
        stmt = select(Scene).where(Scene.scene_id == scene_id)
        result = await db.execute(stmt)
        scene = result.scalar_one_or_none()
        
        if not scene:
            return {
                "success": False,
                "error": f"场景不存在: {scene_id}",
            }
        
        return {
            "success": True,
            "scene_id": scene.scene_id,
            "title": scene.title,
            "location": scene.location,
            "time_setting": scene.time_setting,
            "space_type": scene.space_type,
            "atmosphere": scene.atmosphere,
            "image_url": scene.image_url,
            "status": scene.status,
            "extra_data": scene.extra_data or {},
        }


@tool
async def query_single_shot(shot_id: int) -> Dict[str, Any]:
    """
    查询单个分镜详情
    
    获取分镜的完整信息，包括分镜内容、关联场景、上一个分镜信息（用于连贯性处理）等。
    
    Args:
        shot_id: 分镜ID
        
    Returns:
        {
            "success": bool,
            "shot_id": int,
            "shot_number": int,
            "title": str,
            "description": str,
            "scene_info": {...},
            "previous_shot": {...},  # 上一个分镜信息
            ...
        }
    """
    logger.info(f"[DB Tool] 查询单个分镜: shot_id={shot_id}")
    
    from app.agent.tools.async_db import get_async_session
    from app.models.shot import Shot
    from app.models.scene import Scene
    from sqlalchemy import select
    
    async with get_async_session() as db:
        # 查询当前分镜
        stmt = select(Shot).where(Shot.shot_id == shot_id)
        result = await db.execute(stmt)
        shot = result.scalar_one_or_none()
        
        if not shot:
            return {
                "success": False,
                "error": f"分镜不存在: {shot_id}",
            }
        
        # 查询关联场景
        scene_stmt = select(Scene).where(Scene.scene_id == shot.scene_id)
        scene_result = await db.execute(scene_stmt)
        scene = scene_result.scalar_one_or_none()
        
        scene_info = {
            "scene_id": scene.scene_id if scene else None,
            "title": scene.title if scene else "",
            "location": scene.location if scene else "",
            "time_setting": scene.time_setting if scene else "",
            "atmosphere": scene.atmosphere if scene else "",
        } if scene else None
        
        # 查询上一个分镜（用于连贯性）
        previous_shot = None
        if shot.shot_number > 1:
            prev_stmt = select(Shot).where(
                Shot.scene_id == shot.scene_id,
                Shot.shot_number == shot.shot_number - 1
            )
            prev_result = await db.execute(prev_stmt)
            prev_shot = prev_result.scalar_one_or_none()
            
            if prev_shot:
                previous_shot = {
                    "shot_id": prev_shot.shot_id,
                    "shot_number": prev_shot.shot_number,
                    "description": prev_shot.description,
                    "image_url": prev_shot.image_url,
                }
        
        return {
            "success": True,
            "shot_id": shot.shot_id,
            "shot_number": shot.shot_number,
            "title": shot.title,
            "description": shot.description,
            "narration": shot.narration,
            "video_duration": shot.video_duration,
            "image_url": shot.image_url,
            "video_url": shot.video_url,
            "extra_data": shot.extra_data or {},
            "scene_info": scene_info,
            "previous_shot": previous_shot,
        }


@tool
async def query_creation_info(creation_uuid: str) -> Dict[str, Any]:
    """
    查询创作项目基本信息
    
    Args:
        creation_uuid: 创作项目 UUID
        
    Returns:
        {
            "success": bool,
            "creation_id": int,
            "title": str,
            "status": str,
            "visual_style": str,
            ...
        }
    """
    logger.info(f"[DB Tool] 查询创作信息: creation_uuid={creation_uuid}")
    
    from app.agent.tools.async_db import get_async_session
    from app.models.creation import Creation
    from sqlalchemy import select
    
    async with get_async_session() as db:
        stmt = select(Creation).where(Creation.uuid == creation_uuid)
        result = await db.execute(stmt)
        creation = result.scalar_one_or_none()
        
        if not creation:
            return {
                "success": False,
                "error": f"创作项目不存在: {creation_uuid}",
            }
        
        return {
            "success": True,
            "creation_id": creation.creation_id,
            "creation_uuid": creation_uuid,
            "title": creation.title,
            "status": creation.status,
            "visual_style": creation.extra_data.get("visual_style", "日本动漫风格") if creation.extra_data else "日本动漫风格",
            "extra_data": creation.extra_data or {},
        }


async def query_creation_data(creation_uuid: str) -> Optional[Dict[str, Any]]:
    """
    加载创作项目的完整数据（用于填充 Graph State）
    
    注意：这不是一个 @tool 装饰的函数，而是供节点直接调用的辅助函数
    
    剧本文本获取优先级：
    1. Chapter.content_url - 章节关联的剧本文件 URL
    2. Creation.text_content_url - 创作关联的文本内容 URL
    3. Creation.extra_data.script_text - 直接存储的剧本文本
    
    Args:
        creation_uuid: 创作项目 UUID
        
    Returns:
        创作数据字典，包含 script_text, characters, scenes, shots 等
    """
    logger.info(f"[DB Helper] 加载创作数据: creation_uuid={creation_uuid}")
    
    from app.agent.tools.async_db import get_async_session
    from app.models.creation import Creation
    from app.models.character import Character
    from app.models.scene import Scene
    from app.models.shot import Shot
    from app.models.chapter import Chapter
    from sqlalchemy import select
    from sqlalchemy.orm import selectinload
    
    async with get_async_session() as db:
        # 获取 creation（同时加载 chapter 关系）
        creation_stmt = select(Creation).where(Creation.uuid == creation_uuid).options(
            selectinload(Creation.chapter)
        )
        creation_result = await db.execute(creation_stmt)
        creation = creation_result.scalar_one_or_none()
        
        if not creation:
            logger.warning(f"[DB Helper] 创作项目不存在: {creation_uuid}")
            return None
        
        # 获取剧本文本 - 按优先级获取
        script_text = None
        script_url = None
        
        # 优先级1: 从 Chapter.content_url 获取
        if creation.chapter and creation.chapter.content_url:
            script_url = creation.chapter.content_url
            logger.info(f"[DB Helper] 从 Chapter.content_url 获取剧本: {script_url}")
            script_text = await _download_text_content(script_url)
        
        # 优先级2: 从 Creation.text_content_url 获取
        if not script_text and creation.text_content_url:
            script_url = creation.text_content_url
            logger.info(f"[DB Helper] 从 Creation.text_content_url 获取剧本: {script_url}")
            script_text = await _download_text_content(script_url)
        
        # 优先级3: 从 extra_data 获取
        if not script_text and creation.extra_data:
            script_text = creation.extra_data.get("script_text")
            script_url = creation.extra_data.get("script_url")
            if script_text:
                logger.info(f"[DB Helper] 从 extra_data 获取剧本文本")
        
        # 获取角色
        char_stmt = select(Character).where(Character.creation_id == creation.creation_id)
        char_result = await db.execute(char_stmt)
        characters = [
            {
                "id": c.character_id,
                "name": c.name,
                "appearance": c.appearance,  # 外貌描述
                "basic_info": c.basic_info,   # 基本信息描述
                "image_url": c.image_url,
                "image_prompt": c.image_prompt,
            }
            for c in char_result.scalars().all()
        ]
        
        # 获取场景
        scene_stmt = select(Scene).where(Scene.creation_id == creation.creation_id)
        scene_result = await db.execute(scene_stmt)
        scenes = [
            {
                "id": s.scene_id,
                "title": s.title,            # 场景标题
                "location": s.location,      # 地点
                "atmosphere": s.atmosphere,  # 氛围描述
                "image_url": s.image_url,
            }
            for s in scene_result.scalars().all()
        ]
        
        # 获取分镜
        scene_ids = [s["id"] for s in scenes]
        shots = []
        if scene_ids:
            shot_stmt = select(Shot).where(Shot.scene_id.in_(scene_ids)).order_by(Shot.shot_number)
            shot_result = await db.execute(shot_stmt)
            shots = [
                {
                    "id": s.shot_id,
                    "scene_id": s.scene_id,
                    "shot_number": s.shot_number,    # 分镜编号
                    "title": s.title,
                    "description": s.description,
                    "narration": s.narration,
                    "image_url": s.image_url,
                    "video_url": s.video_url,
                    "extra_data": s.extra_data or {},  # 包含 video_prompt 等
                }
                for s in shot_result.scalars().all()
            ]
        
        logger.info(f"[DB Helper] 创作数据加载完成: script={'有' if script_text else '无'}, "
                   f"characters={len(characters)}, scenes={len(scenes)}, shots={len(shots)}")
        
        # 获取视频模型配置
        extra_data = creation.extra_data or {}
        video_model = extra_data.get("video_model", "doubao-seedance-1-5-pro-251215")
        
        # 根据视频模型判断生成类型
        from app.core.model_config import ModelConfigFactory
        video_generation_type = ModelConfigFactory.get_video_generation_type(video_model)
        
        return {
            "creation_id": creation.creation_id,
            "creation_uuid": creation_uuid,
            "title": creation.title,
            "status": creation.status,
            "script_text": script_text,
            "script_url": script_url,
            "characters": characters,
            "scenes": scenes,
            "shots": shots,
            "final_video_url": extra_data.get("final_video_url"),
            "video_model": video_model,
            "video_generation_type": video_generation_type,
        }


async def _download_text_content(url: str) -> Optional[str]:
    """
    从 URL 下载文本内容
    
    Args:
        url: 文件 URL
        
    Returns:
        文件文本内容，下载失败返回 None
    """
    import tempfile
    import os
    import asyncio
    from functools import partial
    
    try:
        # 使用 httpx 异步下载
        import httpx
        
        logger.info(f"[DB Helper] 开始下载文本文件: {url}")
        
        timeout_config = httpx.Timeout(
            connect=10.0,
            read=30.0,
            write=10.0,
            pool=10.0,
        )
        
        async with httpx.AsyncClient(timeout=timeout_config, follow_redirects=True) as client:
            response = await client.get(url)
            response.raise_for_status()
            
            # 尝试检测编码
            content_type = response.headers.get("content-type", "")
            charset = "utf-8"
            if "charset=" in content_type:
                charset = content_type.split("charset=")[-1].split(";")[0].strip()
            
            # 读取文本内容
            try:
                text_content = response.content.decode(charset)
            except UnicodeDecodeError:
                # 尝试其他常见编码
                for encoding in ["gbk", "gb2312", "utf-16", "latin-1"]:
                    try:
                        text_content = response.content.decode(encoding)
                        break
                    except UnicodeDecodeError:
                        continue
                else:
                    logger.error(f"[DB Helper] 无法解码文本内容: {url}")
                    return None
            
            logger.info(f"[DB Helper] 文本文件下载成功: {len(text_content)} 字符")
            return text_content
            
    except httpx.HTTPStatusError as e:
        logger.error(f"[DB Helper] HTTP 下载失败，状态码 {e.response.status_code}: {url}")
        return None
    except Exception as e:
        logger.error(f"[DB Helper] 下载文本内容失败: {e}", exc_info=True)
        return None


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
async def update_character_voice(
    character_id: int,
    voice_id: str,
    voice_speed: Optional[float] = 1.0
) -> Dict[str, Any]:
    """
    更新角色音色信息
    
    Args:
        character_id: 角色 ID
        voice_id: Fish Audio 音色 ID
        voice_speed: 语速（可选，默认 1.0）
        
    Returns:
        更新结果
    """
    logger.info(f"[DB Tool] 更新角色音色: character_id={character_id}, voice_id={voice_id}")
    
    from app.agent.tools.async_db import get_async_session
    from app.models.character import Character
    from sqlalchemy import select
    
    async with get_async_session() as db:
        stmt = select(Character).where(Character.character_id == character_id)
        result = await db.execute(stmt)
        character = result.scalar_one_or_none()
        
        if not character:
            return {"success": False, "error": "角色不存在"}
        
        # 更新音色信息
        character.voice_id = voice_id
        character.voice_speed = voice_speed
        
        await db.commit()
        
        return {
            "success": True,
            "character_id": character_id,
            "voice_id": voice_id,
            "voice_speed": voice_speed,
            "updated_fields": ["voice_id", "voice_speed"],
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


# ==================== 批量保存 Tools ====================

@tool
async def save_characters(
    creation_uuid: str,
    characters: List[Dict[str, Any]]
) -> Dict[str, Any]:
    """
    批量保存角色到数据库（跳过已存在的）
    
    Args:
        creation_uuid: 创作项目 UUID
        characters: 角色列表，每个角色包含 name, basic_info, appearance 等字段
        
    Returns:
        保存结果，包含 saved（新增）和 skipped（已存在）的角色列表
    """
    from app.agent.tools.async_db import get_async_db_session
    from app.models.creation import Creation
    from app.models.character import Character
    from sqlalchemy import select
    
    try:
        async with get_async_db_session() as db:
            # 获取 creation_id
            stmt = select(Creation).where(Creation.uuid == creation_uuid)
            result = await db.execute(stmt)
            creation = result.scalar_one_or_none()
            
            if not creation:
                return {
                    "success": False,
                    "error": f"创作项目不存在: {creation_uuid}",
                    "saved": [],
                    "skipped": [],
                }
            
            creation_id = creation.creation_id
            
            # 查询已存在的角色名称
            existing_stmt = select(Character.name).where(
                Character.creation_id == creation_id,
                Character.deleted_at.is_(None)
            )
            existing_result = await db.execute(existing_stmt)
            existing_names = {row[0] for row in existing_result}
            
            saved = []
            skipped = []
            
            for char_data in characters:
                char_name = char_data.get("name", "未命名")
                
                if char_name in existing_names:
                    skipped.append(char_name)
                    continue
                
                character = Character(
                    creation_id=creation_id,
                    name=char_name,
                    basic_info=char_data.get("basic_info", char_data.get("description", "")),
                    appearance=char_data.get("appearance", ""),
                    status="pending",
                )
                db.add(character)
                saved.append(char_name)
            
            await db.commit()
            
            # 更新 Creation.character_ids（重新查询所有角色ID）
            all_chars_stmt = select(Character.character_id).where(
                Character.creation_id == creation_id,
                Character.deleted_at.is_(None)
            )
            all_chars_result = await db.execute(all_chars_stmt)
            all_char_ids = [row[0] for row in all_chars_result]
            
            creation.character_ids = all_char_ids
            await db.commit()
            
            logger.info(f"[save_characters] 新增: {saved}, 跳过: {skipped}")
            
            return {
                "success": True,
                "saved": saved,
                "skipped": skipped,
                "saved_count": len(saved),
                "skipped_count": len(skipped),
            }
            
    except Exception as e:
        logger.error(f"[save_characters] 保存失败: {e}")
        return {
            "success": False,
            "error": str(e),
            "saved": [],
            "skipped": [],
        }


@tool
async def save_scenes(
    creation_uuid: str,
    scenes: List[Dict[str, Any]]
) -> Dict[str, Any]:
    """
    批量保存场景到数据库（跳过已存在的）
    
    Args:
        creation_uuid: 创作项目 UUID
        scenes: 场景列表，每个场景包含 title, location, atmosphere, time_setting 等字段
        
    Returns:
        保存结果，包含 saved（新增）和 skipped（已存在）的场景列表
    """
    from app.agent.tools.async_db import get_async_db_session
    from app.models.creation import Creation
    from app.models.scene import Scene
    from sqlalchemy import select
    
    try:
        async with get_async_db_session() as db:
            # 获取 creation_id
            stmt = select(Creation).where(Creation.uuid == creation_uuid)
            result = await db.execute(stmt)
            creation = result.scalar_one_or_none()
            
            if not creation:
                return {
                    "success": False,
                    "error": f"创作项目不存在: {creation_uuid}",
                    "saved": [],
                    "skipped": [],
                }
            
            creation_id = creation.creation_id
            
            # 查询已存在的场景标题
            existing_stmt = select(Scene.title).where(
                Scene.creation_id == creation_id,
                Scene.deleted_at.is_(None)
            )
            existing_result = await db.execute(existing_stmt)
            existing_titles = {row[0] for row in existing_result}
            
            saved = []
            skipped = []
            
            for scene_data in scenes:
                scene_title = scene_data.get("title", scene_data.get("name", "未命名"))
                
                if scene_title in existing_titles:
                    skipped.append(scene_title)
                    continue
                
                # 构建 extra_data（保存背景元素和空间描述等扩展信息）
                extra_data = {}
                if scene_data.get("env_description"):
                    extra_data["env_description"] = scene_data.get("env_description")
                if scene_data.get("space_description"):
                    extra_data["space_description"] = scene_data.get("space_description")
                
                scene = Scene(
                    creation_id=creation_id,
                    title=scene_title,
                    location=scene_data.get("location", ""),
                    space_type=scene_data.get("space_type", ""),
                    atmosphere=scene_data.get("atmosphere", ""),
                    time_setting=scene_data.get("time_setting", ""),
                    extra_data=extra_data if extra_data else None,
                    status="pending",
                )
                db.add(scene)
                saved.append(scene_title)
            
            await db.commit()
            
            # 更新 Creation.scene_ids（重新查询所有场景ID）
            all_scenes_stmt = select(Scene.scene_id).where(
                Scene.creation_id == creation_id,
                Scene.deleted_at.is_(None)
            )
            all_scenes_result = await db.execute(all_scenes_stmt)
            all_scene_ids = [row[0] for row in all_scenes_result]
            
            creation.scene_ids = all_scene_ids
            await db.commit()
            
            logger.info(f"[save_scenes] 新增: {saved}, 跳过: {skipped}")
            
            return {
                "success": True,
                "saved": saved,
                "skipped": skipped,
                "saved_count": len(saved),
                "skipped_count": len(skipped),
            }
            
    except Exception as e:
        logger.error(f"[save_scenes] 保存失败: {e}")
        return {
            "success": False,
            "error": str(e),
            "saved": [],
            "skipped": [],
        }


@tool
async def save_shots(
    creation_uuid: str,
    shots: List[Dict[str, Any]]
) -> Dict[str, Any]:
    """
    批量保存分镜到数据库
    
    Args:
        creation_uuid: 创作项目 UUID
        shots: 分镜列表，每个分镜包含 scene_name, title, description, narration, duration 等字段
        
    Returns:
        保存结果，包含保存的分镜数量
    """
    from app.agent.tools.async_db import get_async_db_session
    from app.models.creation import Creation
    from app.models.scene import Scene
    from app.models.shot import Shot
    from sqlalchemy import select
    import json as json_lib
    
    try:
        async with get_async_db_session() as db:
            # 获取 creation_id
            stmt = select(Creation).where(Creation.uuid == creation_uuid)
            result = await db.execute(stmt)
            creation = result.scalar_one_or_none()
            
            if not creation:
                return {
                    "success": False,
                    "error": f"创作项目不存在: {creation_uuid}",
                    "saved_count": 0,
                }
            
            creation_id = creation.creation_id
            
            # 获取场景 ID 映射
            scene_stmt = select(Scene).where(
                Scene.creation_id == creation_id,
                Scene.deleted_at.is_(None),
            )
            result = await db.execute(scene_stmt)
            scenes = result.scalars().all()
            scene_map = {s.title: s.scene_id for s in scenes}
            default_scene_id = scenes[0].scene_id if scenes else None
            
            # 获取角色 ID 映射
            from app.models.character import Character
            char_stmt = select(Character).where(
                Character.creation_id == creation_id,
                Character.deleted_at.is_(None),
            )
            result = await db.execute(char_stmt)
            characters = result.scalars().all()
            char_map = {c.name: c for c in characters}
            
            saved_count = 0
            for i, shot_data in enumerate(shots):
                scene_id = scene_map.get(shot_data.get("scene_name"), default_scene_id)
                
                # narration 处理
                narration = shot_data.get("narration", [])
                if isinstance(narration, list):
                    narration = json_lib.dumps(narration, ensure_ascii=False)
                
                shot = Shot(
                    scene_id=scene_id,
                    creation_id=creation_id,
                    title=shot_data.get("title", f"分镜 {i+1}"),
                    shot_number=i + 1,
                    description=shot_data.get("description", ""),
                    narration=narration,
                    video_duration=shot_data.get("duration", 5),
                    status="pending",
                )
                
                # 关联角色
                char_names = shot_data.get("characters", [])
                if char_names:
                    for char_name in char_names:
                        char = char_map.get(char_name)
                        if char:
                            shot.characters.append(char)
                
                db.add(shot)
                saved_count += 1
            
            await db.commit()
            
            logger.info(f"[save_shots] 保存 {saved_count} 个分镜")
            
            return {
                "success": True,
                "saved_count": saved_count,
            }
            
    except Exception as e:
        logger.error(f"[save_shots] 保存失败: {e}")
        return {
            "success": False,
            "error": str(e),
            "saved_count": 0,
        }


@tool
async def save_shot_prompts(
    creation_uuid: str,
    prompts: List[Dict[str, Any]]
) -> Dict[str, Any]:
    """
    批量保存分镜图片提示词到数据库
    
    Args:
        creation_uuid: 创作项目 UUID
        prompts: 提示词列表，每项包含 shot_id/shot_number, image_prompt, end_frame_prompt
        
    Returns:
        保存结果
    """
    from app.agent.tools.async_db import get_async_db_session
    from app.models.creation import Creation
    from app.models.scene import Scene
    from app.models.shot import Shot
    from sqlalchemy import select
    from sqlalchemy.orm import selectinload
    
    try:
        async with get_async_db_session() as db:
            # 获取 creation
            stmt = select(Creation).where(Creation.uuid == creation_uuid)
            result = await db.execute(stmt)
            creation = result.scalar_one_or_none()
            
            if not creation:
                return {
                    "success": False,
                    "error": f"创作项目不存在: {creation_uuid}",
                }
            
            # 获取所有分镜
            shot_stmt = (
                select(Shot)
                .join(Scene, Shot.scene_id == Scene.scene_id)
                .where(Scene.creation_id == creation.creation_id)
                .order_by(Shot.shot_number)
            )
            result = await db.execute(shot_stmt)
            shots = result.scalars().all()
            
            # 建立索引映射
            shot_by_id = {s.shot_id: s for s in shots}
            shot_by_number = {s.shot_number: s for s in shots}
            
            updated_count = 0
            for prompt_data in prompts:
                shot = None
                
                # 支持通过 shot_id 或 shot_number 匹配
                if "shot_id" in prompt_data:
                    shot = shot_by_id.get(prompt_data["shot_id"])
                elif "shot_number" in prompt_data:
                    shot = shot_by_number.get(prompt_data["shot_number"])
                
                if not shot:
                    logger.warning(f"[save_shot_prompts] 未找到分镜: {prompt_data}")
                    continue
                
                # 更新提示词
                if "image_prompt" in prompt_data:
                    shot.image_prompt = prompt_data["image_prompt"]
                
                if "end_frame_prompt" in prompt_data:
                    if shot.extra_data is None:
                        shot.extra_data = {}
                    shot.extra_data["end_frame_prompt"] = prompt_data["end_frame_prompt"]
                
                updated_count += 1
            
            await db.commit()
            
            logger.info(f"[save_shot_prompts] 更新 {updated_count} 个分镜提示词")
            
            return {
                "success": True,
                "updated_count": updated_count,
                "total_prompts": len(prompts),
            }
            
    except Exception as e:
        logger.error(f"[save_shot_prompts] 保存失败: {e}")
        return {
            "success": False,
            "error": str(e),
        }

@tool
async def query_pending_assets(
    creation_uuid: str
) -> Dict[str, Any]:
    """
    查询待生成图片的角色和场景（image_url 为空的）
    
    Args:
        creation_uuid: 创作项目 UUID
        
    Returns:
        待生成图片的角色和场景列表
    """
    from app.agent.tools.async_db import get_async_db_session
    from app.models.creation import Creation
    from app.models.character import Character
    from app.models.scene import Scene
    from sqlalchemy import select
    
    try:
        async with get_async_db_session() as db:
            stmt = select(Creation).where(Creation.uuid == creation_uuid)
            result = await db.execute(stmt)
            creation = result.scalar_one_or_none()
            
            if not creation:
                return {"success": False, "error": "创作项目不存在"}
            
            creation_id = creation.creation_id
            
            # 查询待生成图片的角色
            char_stmt = select(Character).where(
                Character.creation_id == creation_id,
                Character.image_url.is_(None),
                Character.deleted_at.is_(None),
            )
            result = await db.execute(char_stmt)
            characters = result.scalars().all()
            
            # 查询待生成图片的场景
            scene_stmt = select(Scene).where(
                Scene.creation_id == creation_id,
                Scene.image_url.is_(None),
                Scene.deleted_at.is_(None),
            )
            result = await db.execute(scene_stmt)
            scenes = result.scalars().all()
            
            return {
                "success": True,
                "creation_id": creation_id,
                "pending_characters": [
                    {"id": c.character_id, "name": c.name, "appearance": c.appearance or c.basic_info}
                    for c in characters
                ],
                "pending_scenes": [
                    {"id": s.scene_id, "title": s.title, "description": f"{s.location} {s.atmosphere}"}
                    for s in scenes
                ],
            }
            
    except Exception as e:
        logger.error(f"[query_pending_assets] 查询失败: {e}")
        return {"success": False, "error": str(e)}


@tool
async def query_pending_audio_shots(
    creation_uuid: str
) -> Dict[str, Any]:
    """
    查询待生成音频的分镜
    
    解析 narration JSON 格式，返回每个说话者的音频项
    
    Args:
        creation_uuid: 创作项目 UUID
        
    Returns:
        待生成音频的分镜列表和角色列表
    """
    from app.agent.tools.async_db import get_async_db_session
    from app.models.creation import Creation
    from app.models.shot import Shot
    from app.models.character import Character
    from app.models.scene import Scene
    from sqlalchemy import select
    
    def parse_narration(narration_json: str) -> list:
        """解析旁白 JSON"""
        if not narration_json:
            return []
        try:
            if isinstance(narration_json, str):
                return json.loads(narration_json)
            return narration_json
        except (json.JSONDecodeError, TypeError):
            # 如果不是 JSON，作为纯文本返回
            return [{"角色": "旁白", "内容": narration_json}]
    
    try:
        async with get_async_db_session() as db:
            stmt = select(Creation).where(Creation.uuid == creation_uuid)
            result = await db.execute(stmt)
            creation = result.scalar_one_or_none()
            
            if not creation:
                return {"success": False, "error": "创作项目不存在"}
            
            creation_id = creation.creation_id
            
            # 查询所有角色（用于音色选择）
            char_stmt = select(Character).where(
                Character.creation_id == creation_id,
                Character.deleted_at.is_(None),
            )
            result = await db.execute(char_stmt)
            characters = result.scalars().all()
            
            # 构建角色列表
            character_list = [
                {
                    "id": c.character_id,
                    "name": c.name,
                    "basic_info": c.basic_info or "",
                    "appearance": c.appearance or "",
                    "voice_id": c.voice_id,
                    "voice_speed": c.voice_speed,
                }
                for c in characters
            ]
            
            # 查询所有分镜
            shot_stmt = select(Shot).where(
                Shot.creation_id == creation_id,
            ).order_by(Shot.shot_number)
            result = await db.execute(shot_stmt)
            shots = result.scalars().all()
            
            audio_items = []
            for shot in shots:
                extra_data = shot.extra_data or {}
                
                # 检查是否已有音频
                has_audio = extra_data.get("dialogue_audio_url") or extra_data.get("narration_audio_url")
                if has_audio:
                    continue
                
                # 解析 narration JSON
                narration_list = parse_narration(shot.narration)
                
                for narration in narration_list:
                    speaker = narration.get("角色", "旁白")
                    content = narration.get("内容", "")
                    
                    if not content:
                        continue
                    
                    audio_items.append({
                        "shot_id": shot.shot_id,
                        "speaker": speaker,
                        "text": content,
                        "shot_number": shot.shot_number,
                    })
            
            return {
                "success": True,
                "creation_id": creation_id,
                "audio_items": audio_items,
                "characters": character_list,
                "total_items": len(audio_items),
            }
            
    except Exception as e:
        logger.error(f"[query_pending_audio_shots] 查询失败: {e}")
        return {"success": False, "error": str(e)}


@tool
async def query_pending_video_shots(
    creation_uuid: str
) -> Dict[str, Any]:
    """
    查询待生成视频的分镜（有图片但无视频的）
    
    Args:
        creation_uuid: 创作项目 UUID
        
    Returns:
        待生成视频的分镜列表
    """
    from app.agent.tools.async_db import get_async_db_session
    from app.models.creation import Creation
    from app.models.shot import Shot
    from sqlalchemy import select
    
    try:
        async with get_async_db_session() as db:
            stmt = select(Creation).where(Creation.uuid == creation_uuid)
            result = await db.execute(stmt)
            creation = result.scalar_one_or_none()
            
            if not creation:
                return {"success": False, "error": "创作项目不存在"}
            
            creation_id = creation.creation_id
            
            shot_stmt = select(Shot).where(
                Shot.creation_id == creation_id,
                Shot.video_url.is_(None),
                Shot.image_url.isnot(None),
            ).order_by(Shot.shot_number)
            result = await db.execute(shot_stmt)
            shots = result.scalars().all()
            
            pending_shots = []
            for shot in shots:
                extra_data = shot.extra_data or {}
                pending_shots.append({
                    "shot_id": shot.shot_id,
                    "start_image_url": shot.image_url,
                    "end_image_url": extra_data.get("end_frame_image_url"),
                    "prompt": shot.description,
                    "duration": shot.video_duration or 5.0,
                })
            
            return {
                "success": True,
                "creation_id": creation_id,
                "pending_shots": pending_shots,
            }
            
    except Exception as e:
        logger.error(f"[query_pending_video_shots] 查询失败: {e}")
        return {"success": False, "error": str(e)}


@tool
async def query_scene_titles(
    creation_uuid: str
) -> Dict[str, Any]:
    """
    查询创作项目的场景标题列表
    
    Args:
        creation_uuid: 创作项目 UUID
        
    Returns:
        场景标题列表
    """
    from app.agent.tools.async_db import get_async_db_session
    from app.models.creation import Creation
    from app.models.scene import Scene
    from sqlalchemy import select
    
    try:
        async with get_async_db_session() as db:
            stmt = select(Creation).where(Creation.uuid == creation_uuid)
            result = await db.execute(stmt)
            creation = result.scalar_one_or_none()
            
            if not creation:
                return {"success": False, "error": "创作项目不存在"}
            
            creation_id = creation.creation_id
            
            scene_stmt = select(Scene).where(
                Scene.creation_id == creation_id,
                Scene.deleted_at.is_(None),
            )
            result = await db.execute(scene_stmt)
            scenes = result.scalars().all()
            
            return {
                "success": True,
                "creation_id": creation_id,
                "scene_titles": [s.title for s in scenes],
            }
            
    except Exception as e:
        logger.error(f"[query_scene_titles] 查询失败: {e}")
        return {"success": False, "error": str(e)}



# ==================== 视频生成工具 ===================

@tool
async def save_video_prompts(
    creation_uuid: str,
    prompts: List[Dict],
) -> Dict[str, Any]:
    """
    保存视频提示词和生成模式到数据库
    
    Args:
        creation_uuid: 创作 UUID
        prompts: 提示词列表，每项包含 shot_id, video_prompt, generation_mode, mode_reason
        
    Returns:
        {
            "success": True/False,
            "saved_count": int,
            "message": str,
        }
    """
    from sqlalchemy.orm.attributes import flag_modified
    from app.agent.tools.async_db import get_async_session
    from app.models import Creation, Scene, Shot
    
    logger.info(f"[save_video_prompts] 保存视频提示词: creation_uuid={creation_uuid}, count={len(prompts)}")
    
    try:
        async with get_async_session() as db:
            # 查询创作
            from sqlalchemy import select
            result = await db.execute(
                select(Creation).where(Creation.uuid == creation_uuid)
            )
            creation = result.scalar_one_or_none()
            
            if not creation:
                return {"success": False, "error": f"创作不存在: {creation_uuid}"}
            
            saved_count = 0
            
            for prompt_data in prompts:
                shot_id = prompt_data.get("shot_id")
                video_prompt = prompt_data.get("video_prompt")
                generation_mode = prompt_data.get("generation_mode", "first_frame_only")
                mode_reason = prompt_data.get("mode_reason", "")
                
                if not shot_id or not video_prompt:
                    logger.warning(f"[save_video_prompts] 跳过无效数据: {prompt_data}")
                    continue
                
                # 查询分镜
                shot_result = await db.execute(
                    select(Shot).where(Shot.shot_id == shot_id)
                )
                shot = shot_result.scalar_one_or_none()
                
                if not shot:
                    logger.warning(f"[save_video_prompts] 分镜不存在: shot_id={shot_id}")
                    continue
                
                # 更新 extra_data
                if not shot.extra_data:
                    shot.extra_data = {}
                
                shot.extra_data["video_prompt"] = video_prompt
                shot.extra_data["generation_mode"] = generation_mode
                shot.extra_data["mode_reason"] = mode_reason
                flag_modified(shot, "extra_data")
                
                saved_count += 1
                logger.debug(f"[save_video_prompts] 保存成功: shot_id={shot_id}, mode={generation_mode}")
            
            await db.commit()
            
            logger.info(f"[save_video_prompts] 完成，保存了 {saved_count} 个视频提示词")
            
            return {
                "success": True,
                "saved_count": saved_count,
                "total_prompts": len(prompts),
                "message": f"成功保存 {saved_count} 个视频提示词",
            }
            
    except Exception as e:
        logger.error(f"[save_video_prompts] 保存失败: {e}")
        return {"success": False, "error": str(e)}


# ==================== 资源定位工具 ====================

@tool
async def find_resources_by_identifier(
    creation_uuid: str,
    resource_type: str,
    identifier: str,
) -> Dict[str, Any]:
    """
    根据用户提到的编号或名称查找资源
    
    支持模糊匹配，如：
    - "11" -> 匹配 shot_number=11 或 id=11
    - "幽影" -> 匹配角色名称包含"幽影"
    - "客栈" -> 匹配场景标题包含"客栈"
    
    Args:
        creation_uuid: 创作项目 UUID
        resource_type: 资源类型 (character/scene/shot)
        identifier: 标识符（编号或名称关键词）
        
    Returns:
        匹配的资源列表
    """
    logger.info(f"[DB Tool] 查找资源: creation_uuid={creation_uuid}, type={resource_type}, identifier={identifier}")
    
    from app.agent.tools.async_db import get_async_session
    from app.models.creation import Creation
    from sqlalchemy import select
    
    async with get_async_session() as db:
        # 获取 creation
        creation_stmt = select(Creation).where(Creation.uuid == creation_uuid)
        creation_result = await db.execute(creation_stmt)
        creation = creation_result.scalar_one_or_none()
        
        if not creation:
            return {"success": False, "error": "创作项目不存在"}
        
        creation_id = creation.creation_id
        
        try:
            if resource_type == "character":
                from app.models.character import Character
                # 尝试作为ID匹配，也尝试作为名称模糊匹配
                stmt = select(Character).where(
                    Character.creation_id == creation_id,
                    Character.deleted_at.is_(None)
                )
                result = await db.execute(stmt)
                characters = result.scalars().all()
                
                matched = []
                for char in characters:
                    # 精确ID匹配或名称包含
                    if str(char.character_id) == identifier or identifier in char.name:
                        matched.append({
                            "id": char.character_id,
                            "name": char.name,
                            "image_url": char.image_url,
                            "has_image": bool(char.image_url),
                        })
                
                return {
                    "success": True,
                    "resource_type": "character",
                    "identifier": identifier,
                    "matched_count": len(matched),
                    "resources": matched,
                }
                
            elif resource_type == "scene":
                from app.models.scene import Scene
                stmt = select(Scene).where(
                    Scene.creation_id == creation_id,
                    Scene.deleted_at.is_(None)
                )
                result = await db.execute(stmt)
                scenes = result.scalars().all()
                
                matched = []
                for i, scene in enumerate(scenes, 1):
                    # 序号匹配（第N个场景）或ID匹配或标题包含
                    scene_number = i
                    if str(scene.scene_id) == identifier or str(scene_number) == identifier or identifier in scene.title:
                        matched.append({
                            "id": scene.scene_id,
                            "number": scene_number,
                            "title": scene.title,
                            "image_url": scene.image_url,
                            "has_image": bool(scene.image_url),
                        })
                
                return {
                    "success": True,
                    "resource_type": "scene",
                    "identifier": identifier,
                    "matched_count": len(matched),
                    "resources": matched,
                }
                
            elif resource_type == "shot":
                from app.models.scene import Scene
                from app.models.shot import Shot
                
                # 获取所有场景ID
                scene_stmt = select(Scene.scene_id).where(Scene.creation_id == creation_id)
                scene_result = await db.execute(scene_stmt)
                scene_ids = [s[0] for s in scene_result.fetchall()]
                
                if not scene_ids:
                    return {"success": True, "resource_type": "shot", "matched_count": 0, "resources": []}
                
                # 查询分镜
                shot_stmt = select(Shot).where(
                    Shot.scene_id.in_(scene_ids)
                ).order_by(Shot.shot_number)
                result = await db.execute(shot_stmt)
                shots = result.scalars().all()
                
                matched = []
                for shot in shots:
                    # 1. shot_number 精确匹配（如 "11"）
                    # 2. shot_id 精确匹配
                    # 3. description 模糊匹配（如 "幽影" 匹配 "近景居中：幽影额头渗出冷汗..."）
                    # 4. title 模糊匹配（如果有 title）
                    is_match = (
                        str(shot.shot_number) == identifier or 
                        str(shot.shot_id) == identifier or
                        (shot.description and identifier in shot.description) or
                        (shot.title and identifier in shot.title)
                    )
                    
                    if is_match:
                        extra_data = shot.extra_data or {}
                        matched.append({
                            "id": shot.shot_id,
                            "shot_number": shot.shot_number,
                            "title": shot.title,
                            "description": shot.description,
                            "image_url": shot.image_url,
                            "video_url": shot.video_url,
                            "end_frame_url": extra_data.get("end_frame_url"),
                            "has_image": bool(shot.image_url),
                            "has_video": bool(shot.video_url),
                        })
                
                return {
                    "success": True,
                    "resource_type": "shot",
                    "identifier": identifier,
                    "matched_count": len(matched),
                    "resources": matched,
                }
            else:
                return {"success": False, "error": f"不支持的资源类型: {resource_type}"}
                
        except Exception as e:
            logger.error(f"[find_resources_by_identifier] 查询失败: {e}")
            return {"success": False, "error": str(e)}


@tool
async def query_failed_resources(
    creation_uuid: str,
    resource_type: str,
    resource_subtype: str = "video",
) -> Dict[str, Any]:
    """
    查询所有生成失败的资源
    
    Args:
        creation_uuid: 创作项目 UUID
        resource_type: 资源类型 (character/scene/shot)
        resource_subtype: 子类型 (image/video)，对 shot 有效
        
    Returns:
        失败的资源列表
    """
    logger.info(f"[DB Tool] 查询失败资源: creation_uuid={creation_uuid}, type={resource_type}, subtype={resource_subtype}")
    
    from app.agent.tools.async_db import get_async_session
    from app.models.creation import Creation
    from sqlalchemy import select
    
    async with get_async_session() as db:
        creation_stmt = select(Creation).where(Creation.uuid == creation_uuid)
        creation_result = await db.execute(creation_stmt)
        creation = creation_result.scalar_one_or_none()
        
        if not creation:
            return {"success": False, "error": "创作项目不存在"}
        
        creation_id = creation.creation_id
        
        try:
            if resource_type == "character":
                from app.models.character import Character
                # 查询有 image_prompt 但没有 image_url 的角色（生成失败或未生成）
                stmt = select(Character).where(
                    Character.creation_id == creation_id,
                    Character.deleted_at.is_(None),
                    Character.image_prompt.isnot(None),
                    Character.image_url.is_(None)
                )
                result = await db.execute(stmt)
                characters = result.scalars().all()
                
                failed = [
                    {
                        "id": c.character_id,
                        "name": c.name,
                        "image_prompt": c.image_prompt,
                    }
                    for c in characters
                ]
                
                return {
                    "success": True,
                    "resource_type": "character",
                    "failed_count": len(failed),
                    "resources": failed,
                }
                
            elif resource_type == "scene":
                from app.models.scene import Scene
                stmt = select(Scene).where(
                    Scene.creation_id == creation_id,
                    Scene.deleted_at.is_(None),
                    Scene.image_prompt.isnot(None),
                    Scene.image_url.is_(None)
                )
                result = await db.execute(stmt)
                scenes = result.scalars().all()
                
                failed = [
                    {
                        "id": s.scene_id,
                        "title": s.title,
                        "image_prompt": s.image_prompt,
                    }
                    for s in scenes
                ]
                
                return {
                    "success": True,
                    "resource_type": "scene",
                    "failed_count": len(failed),
                    "resources": failed,
                }
                
            elif resource_type == "shot":
                from app.models.scene import Scene
                from app.models.shot import Shot
                
                # 获取场景ID
                scene_stmt = select(Scene.scene_id).where(Scene.creation_id == creation_id)
                scene_result = await db.execute(scene_stmt)
                scene_ids = [s[0] for s in scene_result.fetchall()]
                
                if not scene_ids:
                    return {"success": True, "resource_type": "shot", "failed_count": 0, "resources": []}
                
                if resource_subtype == "video":
                    # 查询有图片但没有视频的分镜
                    stmt = select(Shot).where(
                        Shot.scene_id.in_(scene_ids),
                        Shot.image_url.isnot(None),
                        Shot.video_url.is_(None)
                    ).order_by(Shot.shot_number)
                else:  # image
                    # 查询没有图片的分镜
                    stmt = select(Shot).where(
                        Shot.scene_id.in_(scene_ids),
                        Shot.image_url.is_(None)
                    ).order_by(Shot.shot_number)
                
                result = await db.execute(stmt)
                shots = result.scalars().all()
                
                failed = [
                    {
                        "id": s.shot_id,
                        "shot_number": s.shot_number,
                        "description": s.description,
                        "image_url": s.image_url,
                        "video_url": s.video_url,
                    }
                    for s in shots
                ]
                
                return {
                    "success": True,
                    "resource_type": "shot",
                    "resource_subtype": resource_subtype,
                    "failed_count": len(failed),
                    "resources": failed,
                }
            else:
                return {"success": False, "error": f"不支持的资源类型: {resource_type}"}
                
        except Exception as e:
            logger.error(f"[query_failed_resources] 查询失败: {e}")
            return {"success": False, "error": str(e)}


@tool
async def save_shot_video_prompt(
    shot_id: int,
    video_prompt: str,
    cut_method: str = "",
    cut_reason: str = "",
) -> Dict[str, Any]:
    """
    保存分镜视频提示词到数据库
    
    将生成的视频提示词保存到分镜的 extra_data 字段中。
    
    Args:
        shot_id: 分镜 ID
        video_prompt: 生成的视频提示词
        cut_method: 镜头切换方式（如：push_in, whip_pan, smooth_transition 等）
        cut_reason: 镜头切换原因
        
    Returns:
        保存结果
    """
    from app.agent.tools.async_db import get_async_db_session
    from sqlalchemy import select
    from sqlalchemy.orm.attributes import flag_modified
    from app.models.shot import Shot
    
    logger.info(f"[save_shot_video_prompt] 保存视频提示词: shot_id={shot_id}")
    
    try:
        async with get_async_db_session() as db:
            stmt = select(Shot).where(Shot.shot_id == shot_id)
            result = await db.execute(stmt)
            shot = result.scalar_one_or_none()
            
            if not shot:
                return {
                    "success": False,
                    "error": f"分镜不存在: {shot_id}",
                    "shot_id": shot_id,
                }
            
            if shot.extra_data is None:
                shot.extra_data = {}
            
            shot.extra_data["video_prompt"] = video_prompt
            shot.extra_data["cut_method"] = cut_method
            shot.extra_data["cut_reason"] = cut_reason
            shot.extra_data["video_prompt_updated_at"] = datetime.now().isoformat()
            
            flag_modified(shot, "extra_data")
            await db.commit()
            
            logger.info(f"[save_shot_video_prompt] 成功保存: shot_id={shot_id}")
            
            return {
                "success": True,
                "shot_id": shot_id,
                "video_prompt": video_prompt,
                "cut_method": cut_method,
                "cut_reason": cut_reason,
            }
            
    except Exception as e:
        logger.error(f"[save_shot_video_prompt] 保存失败: {e}")
        return {
            "success": False,
            "error": str(e),
            "shot_id": shot_id,
        }


@tool
async def batch_save_video_prompts(
    prompts: List[Dict[str, Any]]
) -> Dict[str, Any]:
    """
    批量保存分镜视频提示词
    
    Args:
        prompts: 提示词列表，每个包含：
            - shot_id: 分镜 ID
            - video_prompt: 视频提示词
            - cut_method: 镜头切换方式（可选）
            - cut_reason: 切换原因（可选）
            
    Returns:
        保存结果统计
    """
    from app.agent.tools.async_db import get_async_db_session
    from sqlalchemy import select
    from sqlalchemy.orm.attributes import flag_modified
    from app.models.shot import Shot
    
    logger.info(f"[batch_save_video_prompts] 批量保存: {len(prompts)} 个提示词")
    
    try:
        shot_ids = [p["shot_id"] for p in prompts]
        
        async with get_async_db_session() as db:
            stmt = select(Shot).where(Shot.shot_id.in_(shot_ids))
            result = await db.execute(stmt)
            shots = result.scalars().all()
            
            shot_by_id = {s.shot_id: s for s in shots}
            
            saved_count = 0
            failed_count = 0
            
            for prompt_data in prompts:
                shot_id = prompt_data["shot_id"]
                shot = shot_by_id.get(shot_id)
                
                if not shot:
                    logger.warning(f"[batch_save_video_prompts] 未找到分镜: {shot_id}")
                    failed_count += 1
                    continue
                
                if shot.extra_data is None:
                    shot.extra_data = {}
                
                shot.extra_data["video_prompt"] = prompt_data["video_prompt"]
                shot.extra_data["cut_method"] = prompt_data.get("cut_method", "")
                shot.extra_data["cut_reason"] = prompt_data.get("cut_reason", "")
                shot.extra_data["video_prompt_updated_at"] = datetime.now().isoformat()
                
                flag_modified(shot, "extra_data")
                saved_count += 1
            
            await db.commit()
            
            logger.info(f"[batch_save_video_prompts] 保存完成: 成功={saved_count}, 失败={failed_count}")
            
            return {
                "success": True,
                "total": len(prompts),
                "saved_count": saved_count,
                "failed_count": failed_count,
            }
            
    except Exception as e:
        logger.error(f"[batch_save_video_prompts] 保存失败: {e}")
        return {
            "success": False,
            "error": str(e),
            "total": len(prompts),
            "saved_count": 0,
            "failed_count": len(prompts),
        }

