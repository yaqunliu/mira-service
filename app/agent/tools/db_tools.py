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
            "total": len(shots),
            "with_image": with_image,
            "with_video": with_video,
            "shots": [
                {
                    "id": s.shot_id,
                    "shot_id": s.shot_id,  # 同时提供两个字段名供兼容
                    "sequence": s.shot_number,
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
                }
                for s in shot_result.scalars().all()
            ]
        
        logger.info(f"[DB Helper] 创作数据加载完成: script={'有' if script_text else '无'}, "
                   f"characters={len(characters)}, scenes={len(scenes)}, shots={len(shots)}")
        
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
            "final_video_url": creation.extra_data.get("final_video_url") if creation.extra_data else None,
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
                
                scene = Scene(
                    creation_id=creation_id,
                    title=scene_title,
                    location=scene_data.get("location", ""),
                    atmosphere=scene_data.get("atmosphere", ""),
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


# ==================== 资产生成 Tools ====================

@tool
async def create_asset_generation_tasks(
    creation_uuid: str,
    assets: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """
    创建资产图片生成任务（角色和场景）
    
    Args:
        creation_uuid: 创作项目 UUID
        assets: 资产列表，每个资产包含 type (character/scene), id, prompt
        
    Returns:
        创建的任务列表
    """
    logger.info(f"[create_asset_generation_tasks] 创建资产生成任务: creation_uuid={creation_uuid}, assets={len(assets)}")
    
    from app.agent.tasks.image_tasks import (
        agent_generate_character_image_task,
        agent_generate_scene_image_task,
    )
    
    try:
        task_ids = []
        
        for asset in assets:
            asset_type = asset.get("type")
            asset_id = asset.get("id")
            prompt = asset.get("prompt", "")
            
            if asset_type == "character":
                task = agent_generate_character_image_task.delay(
                    creation_uuid=creation_uuid,
                    character_id=asset_id,
                    prompt=prompt,
                )
                task_ids.append({
                    "type": "character",
                    "id": asset_id,
                    "task_id": task.id,
                    "name": asset.get("name", ""),
                })
                logger.info(f"[create_asset_generation_tasks] 创建角色图片任务: id={asset_id}")
                
            elif asset_type == "scene":
                task = agent_generate_scene_image_task.delay(
                    creation_uuid=creation_uuid,
                    scene_id=asset_id,
                    prompt=prompt,
                )
                task_ids.append({
                    "type": "scene",
                    "id": asset_id,
                    "task_id": task.id,
                    "name": asset.get("name", ""),
                })
                logger.info(f"[create_asset_generation_tasks] 创建场景图片任务: id={asset_id}")
        
        return {
            "success": True,
            "task_ids": task_ids,
            "total": len(task_ids),
            "characters_count": len([t for t in task_ids if t["type"] == "character"]),
            "scenes_count": len([t for t in task_ids if t["type"] == "scene"]),
        }
        
    except Exception as e:
        logger.error(f"[create_asset_generation_tasks] 创建任务失败: {e}")
        return {
            "success": False,
            "error": str(e),
            "task_ids": [],
        }


# ==================== 分镜图片生成 Tools ====================

@tool
async def generate_shot_images(
    creation_uuid: str,
    force_regenerate: bool = False
) -> Dict[str, Any]:
    """
    触发创作项目的分镜图片批量生成任务
    
    Args:
        creation_uuid: 创作项目 UUID
        force_regenerate: 是否强制重新生成已有图片的分镜
    
    Returns:
        task_id: Celery 任务 ID
        shot_count: 待生成的分镜数量
    """
    from app.agent.tools.async_db import get_async_db_session
    from app.models import Creation, Scene, Shot
    from sqlalchemy import select
    from sqlalchemy.orm import selectinload
    
    try:
        async with get_async_db_session() as session:
            # 查询 creation
            stmt = select(Creation).where(Creation.uuid == creation_uuid)
            result = await session.execute(stmt)
            creation = result.scalar_one_or_none()
            
            if not creation:
                return {
                    "success": False,
                    "error": f"创作不存在: {creation_uuid}",
                }
            
            # 查询分镜数量
            shot_stmt = (
                select(Shot)
                .join(Scene, Shot.scene_id == Scene.scene_id)
                .where(Scene.creation_id == creation.creation_id)
            )
            shot_result = await session.execute(shot_stmt)
            shots = shot_result.scalars().all()
            
            # 统计需要生成图片的分镜
            shots_to_generate = [
                s for s in shots 
                if force_regenerate or not s.image_url
            ]
            
            if not shots_to_generate:
                return {
                    "success": True,
                    "task_id": None,
                    "shot_count": 0,
                    "message": "所有分镜已有图片，无需生成",
                }
            
            # 调用新的 Agent 专用 Celery Task
            from app.tasks.agent_shot_task import agent_generate_shot_images_task
            
            task = agent_generate_shot_images_task.delay(
                creation_uuid=creation_uuid,
            )
            
            logger.info(f"[generate_shot_images] 启动 Agent 分镜图片生成任务: task_id={task.id}, shot_count={len(shots_to_generate)}")
            
            # 等待批量任务返回 group_id 和 shot_task_ids（派发很快，约1秒）
            try:
                import asyncio
                # 使用 asyncio.to_thread 在异步环境中等待同步操作
                loop = asyncio.get_event_loop()
                task_result = await loop.run_in_executor(None, lambda: task.get(timeout=10))
                
                return {
                    "success": True,
                    "task_id": task.id,
                    "group_id": task_result.get("group_id"),
                    "shot_task_ids": task_result.get("shot_task_ids", {}),
                    "shot_count": task_result.get("total", len(shots_to_generate)),
                    "total_shots": len(shots),
                    "message": task_result.get("message", f"已启动分镜图片生成任务"),
                }
            except Exception as wait_err:
                logger.warning(f"[generate_shot_images] 等待任务派发结果失败: {wait_err}, 返回 task_id")
                return {
                    "success": True,
                    "task_id": task.id,
                    "shot_count": len(shots_to_generate),
                    "total_shots": len(shots),
                    "message": f"已启动分镜图片生成任务，共 {len(shots_to_generate)} 个分镜待生成",
                }
            
    except Exception as e:
        logger.error(f"[generate_shot_images] 启动任务失败: {e}")
        return {
            "success": False,
            "error": str(e),
        }


@tool
async def check_task_status(task_id: str) -> Dict[str, Any]:
    """
    查询 Celery 任务状态
    
    Args:
        task_id: 任务 ID
        
    Returns:
        任务状态信息，包括 status、result、error 等
    """
    from celery.result import AsyncResult
    from app.core.celery_app import celery_app
    
    try:
        result = AsyncResult(task_id, app=celery_app)
        
        response = {
            "task_id": task_id,
            "status": result.status,
            "ready": result.ready(),
        }
        
        if result.ready():
            if result.successful():
                response["result"] = result.result
            else:
                response["error"] = str(result.result) if result.result else "Unknown error"
        elif result.status == "PROGRESS":
            response["progress"] = result.info
            
        return response
        
    except Exception as e:
        logger.error(f"[check_task_status] 查询失败: {e}")
        return {"task_id": task_id, "status": "ERROR", "error": str(e)}


@tool
async def check_task_group_status(
    group_id: str,
    shot_task_ids: Dict[int, str],
) -> Dict[str, Any]:
    """
    查询任务组状态（用于批量分镜图片生成）
    
    Args:
        group_id: Celery group 任务 ID
        shot_task_ids: shot_id -> task_id 映射
        
    Returns:
        任务组状态统计
    """
    from celery.result import AsyncResult, GroupResult
    from app.core.celery_app import celery_app
    
    try:
        total = len(shot_task_ids)
        completed = 0
        failed = 0
        pending = 0
        failed_shots = []
        completed_shots = []
        
        for shot_id, task_id in shot_task_ids.items():
            result = AsyncResult(task_id, app=celery_app)
            
            if result.successful():
                # Celery 任务成功，但需要检查业务层结果
                task_result = result.result or {}
                if isinstance(task_result, dict) and task_result.get("success") == False:
                    # 业务层失败
                    failed += 1
                    failed_shots.append({
                        "shot_id": shot_id,
                        "error": task_result.get("error", "Unknown error"),
                    })
                else:
                    # 真正成功
                    completed += 1
                    completed_shots.append({
                        "shot_id": shot_id,
                        "result": task_result,
                    })
            elif result.failed():
                failed += 1
                failed_shots.append({
                    "shot_id": shot_id,
                    "error": str(result.result) if result.result else "Unknown error",
                })
            else:
                pending += 1
        
        all_done = (completed + failed) == total
        
        return {
            "group_id": group_id,
            "total": total,
            "completed": completed,
            "failed": failed,
            "pending": pending,
            "all_done": all_done,
            "success": all_done and failed == 0,
            "failed_shots": failed_shots if failed > 0 else None,
            "completed_shots": completed_shots[:3] if completed_shots else None,  # 只返回前3个示例
        }
        
    except Exception as e:
        logger.error(f"[check_task_group_status] 查询失败: {e}")
        return {"group_id": group_id, "status": "ERROR", "error": str(e)}


# ==================== 视频生成工具 ====================

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


@tool
async def generate_shot_videos(
    creation_uuid: str,
    force_regenerate: bool = False,
) -> Dict[str, Any]:
    """
    创建视频生成任务
    
    查询所有需要生成视频的分镜（有 video_prompt 但无 video_url），
    批量派发 Celery 任务。
    
    Args:
        creation_uuid: 创作 UUID
        force_regenerate: 是否强制重新生成已有视频的分镜
        
    Returns:
        {
            "success": True/False,
            "task_id": str,
            "group_id": str,
            "shot_task_ids": {shot_id: task_id, ...},
            "shot_count": int,
            "message": str,
        }
    """
    from app.tasks.agent_video_task import agent_generate_shot_videos_task
    
    logger.info(f"[generate_shot_videos] 创建视频生成任务: creation_uuid={creation_uuid}")
    
    try:
        # 派发批量任务
        task = agent_generate_shot_videos_task.delay(
            creation_uuid=creation_uuid,
        )
        
        # 等待批量任务返回 group_id 和 shot_task_ids（派发很快，约1秒）
        try:
            import asyncio
            loop = asyncio.get_event_loop()
            task_result = await loop.run_in_executor(None, lambda: task.get(timeout=10))
            
            if task_result.get("success"):
                return {
                    "success": True,
                    "task_id": task.id,
                    "group_id": task_result.get("group_id"),
                    "shot_task_ids": task_result.get("shot_task_ids", {}),
                    "shot_count": task_result.get("total", 0),
                    "message": task_result.get("message", "已启动视频生成任务"),
                }
            else:
                return {
                    "success": False,
                    "task_id": task.id,
                    "error": task_result.get("error", "未知错误"),
                }
                
        except Exception as wait_err:
            logger.warning(f"[generate_shot_videos] 等待任务派发结果失败: {wait_err}, 返回 task_id")
            return {
                "success": True,
                "task_id": task.id,
                "message": "已启动视频生成任务，请稍后查询状态",
            }
            
    except Exception as e:
        logger.error(f"[generate_shot_videos] 创建任务失败: {e}")
        return {"success": False, "error": str(e)}
