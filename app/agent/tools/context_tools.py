"""
上下文工具 - Context Tools

提供获取剧本上下文、前后分镜、知识库查询等工具
用于生成更连贯一致的图片/视频提示词
"""

from typing import Dict, Any, Optional, List

from langchain_core.tools import tool

from app.core.logger import logger


@tool
async def get_script_context(
    creation_uuid: str,
) -> Dict[str, Any]:
    """
    获取剧本和故事背景上下文
    
    Args:
        creation_uuid: 创作项目 UUID
        
    Returns:
        剧本文本、故事梗概、风格设定等
    """
    logger.info(f"[Context Tool] 获取剧本上下文: creation_uuid={creation_uuid}")
    
    from app.agent.tools.async_db import get_async_session
    from app.models.creation import Creation
    from app.models.chapter import Chapter
    from sqlalchemy import select
    from sqlalchemy.orm import selectinload
    
    async with get_async_session() as db:
        try:
            stmt = select(Creation).where(Creation.uuid == creation_uuid).options(
                selectinload(Creation.chapter)
            )
            result = await db.execute(stmt)
            creation = result.scalar_one_or_none()
            
            if not creation:
                return {"success": False, "error": "创作项目不存在"}
            
            # 获取剧本文本
            script_text = None
            extra_data = creation.extra_data or {}
            
            if creation.chapter and creation.chapter.content_url:
                # 从章节下载剧本
                from app.agent.tools.db_tools import _download_text_content
                script_text = await _download_text_content(creation.chapter.content_url)
            elif creation.text_content_url:
                from app.agent.tools.db_tools import _download_text_content
                script_text = await _download_text_content(creation.text_content_url)
            else:
                script_text = extra_data.get("script_text")
            
            return {
                "success": True,
                "creation_uuid": creation_uuid,
                "title": creation.title,
                "script_text": script_text,
                "synopsis": extra_data.get("synopsis", ""),
                "style": extra_data.get("style", {}),
                "aspect_ratio": extra_data.get("aspect_ratio", "16:9"),
            }
            
        except Exception as e:
            logger.error(f"[Context Tool] 获取剧本上下文失败: {e}")
            return {"success": False, "error": str(e)}


@tool
async def get_adjacent_shots(
    shot_id: int,
    range: int = 2,
) -> Dict[str, Any]:
    """
    获取前后分镜信息，用于保持画面连贯性
    
    Args:
        shot_id: 当前分镜 ID
        range: 获取前后各几个分镜（默认 2）
        
    Returns:
        前后分镜列表
    """
    logger.info(f"[Context Tool] 获取前后分镜: shot_id={shot_id}, range={range}")
    
    from app.agent.tools.async_db import get_async_session
    from app.models.shot import Shot
    from sqlalchemy import select
    
    async with get_async_session() as db:
        try:
            # 获取当前分镜
            stmt = select(Shot).where(Shot.shot_id == shot_id)
            result = await db.execute(stmt)
            current_shot = result.scalar_one_or_none()
            
            if not current_shot:
                return {"success": False, "error": f"分镜不存在: {shot_id}"}
            
            # 获取同场景的所有分镜
            all_shots_stmt = select(Shot).where(
                Shot.scene_id == current_shot.scene_id
            ).order_by(Shot.shot_number)
            all_shots_result = await db.execute(all_shots_stmt)
            all_shots = all_shots_result.scalars().all()
            
            # 找到当前分镜的位置
            current_index = None
            for i, shot in enumerate(all_shots):
                if shot.shot_id == shot_id:
                    current_index = i
                    break
            
            if current_index is None:
                return {"success": False, "error": "无法定位分镜位置"}
            
            # 获取前后分镜
            start = max(0, current_index - range)
            end = min(len(all_shots), current_index + range + 1)
            
            prev_shots = []
            next_shots = []
            
            for i in range(start, current_index):
                shot = all_shots[i]
                prev_shots.append({
                    "shot_id": shot.shot_id,
                    "shot_number": shot.shot_number,
                    "description": shot.description,
                    "image_prompt": shot.image_prompt,
                    "image_url": shot.image_url,
                })
            
            for i in range(current_index + 1, end):
                shot = all_shots[i]
                next_shots.append({
                    "shot_id": shot.shot_id,
                    "shot_number": shot.shot_number,
                    "description": shot.description,
                    "image_prompt": shot.image_prompt,
                    "image_url": shot.image_url,
                })
            
            return {
                "success": True,
                "current_shot": {
                    "shot_id": current_shot.shot_id,
                    "shot_number": current_shot.shot_number,
                    "description": current_shot.description,
                },
                "prev_shots": prev_shots,
                "next_shots": next_shots,
            }
            
        except Exception as e:
            logger.error(f"[Context Tool] 获取前后分镜失败: {e}")
            return {"success": False, "error": str(e)}


@tool
async def get_character_scene_for_shot(
    shot_id: int,
) -> Dict[str, Any]:
    """
    获取分镜涉及的角色和场景信息
    
    Args:
        shot_id: 分镜 ID
        
    Returns:
        涉及的角色列表和场景信息
    """
    logger.info(f"[Context Tool] 获取分镜角色场景: shot_id={shot_id}")
    
    from app.agent.tools.async_db import get_async_session
    from app.models.shot import Shot
    from app.models.scene import Scene
    from app.models.character import Character
    from sqlalchemy import select
    
    async with get_async_session() as db:
        try:
            # 获取分镜和关联的场景
            stmt = select(Shot).where(Shot.shot_id == shot_id)
            result = await db.execute(stmt)
            shot = result.scalar_one_or_none()
            
            if not shot:
                return {"success": False, "error": f"分镜不存在: {shot_id}"}
            
            # 获取场景
            scene_stmt = select(Scene).where(Scene.scene_id == shot.scene_id)
            scene_result = await db.execute(scene_stmt)
            scene = scene_result.scalar_one_or_none()
            
            scene_info = None
            if scene:
                scene_info = {
                    "scene_id": scene.scene_id,
                    "title": scene.title,
                    "location": scene.location,
                    "atmosphere": scene.atmosphere,
                    "image_url": scene.image_url,
                    "image_prompt": scene.image_prompt,
                }
            
            # 获取分镜涉及的角色（从 shot.extra_data 或描述中解析）
            extra_data = shot.extra_data or {}
            character_ids = extra_data.get("character_ids", [])
            
            characters = []
            if character_ids:
                char_stmt = select(Character).where(Character.character_id.in_(character_ids))
                char_result = await db.execute(char_stmt)
                for char in char_result.scalars().all():
                    characters.append({
                        "character_id": char.character_id,
                        "name": char.name,
                        "appearance": char.appearance,
                        "image_url": char.image_url,
                        "image_prompt": char.image_prompt,
                    })
            
            return {
                "success": True,
                "shot_id": shot_id,
                "scene": scene_info,
                "characters": characters,
                "shot_description": shot.description,
                "shot_narration": shot.narration,
            }
            
        except Exception as e:
            logger.error(f"[Context Tool] 获取分镜角色场景失败: {e}")
            return {"success": False, "error": str(e)}


@tool
async def check_constraints(
    creation_uuid: str,
    action: str,
    target_type: Optional[str] = None,
) -> Dict[str, Any]:
    """
    检查操作是否被约束规则允许
    
    Args:
        creation_uuid: 创作项目 UUID
        action: 操作类型 (modify | regenerate | clear)
        target_type: 目标类型 (character | scene | shot)
        
    Returns:
        是否允许操作
    """
    logger.info(f"[Context Tool] 检查约束: action={action}, target={target_type}")
    
    from app.agent.tools.async_db import get_async_session
    from app.models.creation import Creation
    from app.models.scene import Scene
    from app.models.shot import Shot
    from sqlalchemy import select, func
    
    async with get_async_session() as db:
        try:
            # 获取 creation
            creation_stmt = select(Creation).where(Creation.uuid == creation_uuid)
            creation_result = await db.execute(creation_stmt)
            creation = creation_result.scalar_one_or_none()
            
            if not creation:
                return {"allowed": False, "reason": "创作项目不存在"}
            
            # 检查是否有分镜图片
            scene_ids_stmt = select(Scene.scene_id).where(Scene.creation_id == creation.creation_id)
            scene_ids_result = await db.execute(scene_ids_stmt)
            scene_ids = [s[0] for s in scene_ids_result.fetchall()]
            
            has_storyboard = False
            if scene_ids:
                shot_count_stmt = select(func.count()).select_from(Shot).where(
                    Shot.scene_id.in_(scene_ids),
                    Shot.image_url.isnot(None)
                )
                shot_count = (await db.execute(shot_count_stmt)).scalar()
                has_storyboard = shot_count > 0
            
            # 约束规则：分镜生成后不能修改角色/场景
            if has_storyboard and action in ["modify", "regenerate"] and target_type in ["character", "scene"]:
                return {
                    "allowed": False,
                    "reason": "分镜已生成，修改角色/场景会导致画面不一致。",
                    "suggestion": "您可以：1. 清空分镜后重新修改 2. 保持现状继续",
                    "has_storyboard": has_storyboard,
                }
            
            return {
                "allowed": True,
                "has_storyboard": has_storyboard,
            }
            
        except Exception as e:
            logger.error(f"[Context Tool] 检查约束失败: {e}")
            return {"allowed": False, "reason": str(e)}


# ==================== 导出 ====================

CONTEXT_TOOLS = [
    get_script_context,
    get_adjacent_shots,
    get_character_scene_for_shot,
    check_constraints,
]
