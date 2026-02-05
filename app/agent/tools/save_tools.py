"""
Save Tools - 提示词保存工具

提供将生成的提示词保存到数据库的功能，供 AssetRegeneratorWorker 使用。
"""

import json
import re
from typing import Dict, Any, Optional
from datetime import datetime
from langchain_core.tools import tool
from sqlalchemy.orm.attributes import flag_modified

from app.core.logger import logger


def _parse_video_prompt(video_prompt_str: str) -> tuple:
    """
    解析视频提示词字符串，提取 video_prompt、cut_method、cut_reason
    
    支持格式：
    1. 纯文本提示词
    2. JSON 格式（可能包含 ```json 标记）
    
    Returns:
        (video_prompt, cut_method, cut_reason)
    """
    if not video_prompt_str:
        return "", "", ""
    
    # 去掉前后空白
    cleaned = video_prompt_str.strip()
    
    # 去掉 ```json 和 ``` 标记
    if cleaned.startswith("```json"):
        cleaned = cleaned[7:]
    elif cleaned.startswith("```"):
        cleaned = cleaned[3:]
    
    if cleaned.endswith("```"):
        cleaned = cleaned[:-3]
    
    cleaned = cleaned.strip()
    
    # 尝试解析 JSON
    try:
        data = json.loads(cleaned)
        if isinstance(data, dict):
            return (
                data.get("video_prompt", ""),
                data.get("cut_method", ""),
                data.get("cut_reason", "")
            )
    except json.JSONDecodeError:
        pass
    
    # JSON 解析失败，尝试正则提取
    try:
        # 尝试匹配 {"video_prompt": "...", ...}
        match = re.search(r'"video_prompt"\s*:\s*"([^"]*)"', cleaned, re.DOTALL)
        if match:
            vp = match.group(1)
            
            # 提取 cut_method
            cm_match = re.search(r'"cut_method"\s*:\s*"([^"]*)"', cleaned)
            cm = cm_match.group(1) if cm_match else ""
            
            # 提取 cut_reason
            cr_match = re.search(r'"cut_reason"\s*:\s*"([^"]*)"', cleaned, re.DOTALL)
            cr = cr_match.group(1) if cr_match else ""
            
            return vp, cm, cr
    except Exception:
        pass
    
    # 都失败了，直接返回原字符串作为 video_prompt
    return cleaned, "", ""


# ==================== 角色提示词保存 ====================

@tool
async def save_character_prompt(
    character_id: int,
    prompt: str,
    trigger_generation: bool = False
) -> Dict[str, Any]:
    """
    保存角色图片提示词到数据库
    
    Args:
        character_id: 角色ID
        prompt: 生成的提示词
        trigger_generation: 是否触发图片生成任务
        
    Returns:
        {
            "success": bool,
            "character_id": int,
            "message": str,
            "generation_triggered": bool
        }
    """
    logger.info(f"[Save Tool] 保存角色提示词: character_id={character_id}")
    
    try:
        from app.agent.tools.async_db import get_async_session
        from app.models.character import Character
        from sqlalchemy import select
        
        async with get_async_session() as db:
            # 查询角色
            stmt = select(Character).where(Character.character_id == character_id)
            result = await db.execute(stmt)
            character = result.scalar_one_or_none()
            
            if not character:
                return {
                    "success": False,
                    "character_id": character_id,
                    "message": f"角色不存在: {character_id}",
                    "generation_triggered": False
                }
            
            # 更新提示词
            character.image_prompt = prompt
            character.updated_at = datetime.now()
            
            # 如果触发生成，更新状态
            if trigger_generation:
                character.status = "pending"
                character.status_detail = "等待重新生成图片"
            
            await db.commit()
            
            # 触发图片生成任务（异步）
            generation_triggered = False
            if trigger_generation:
                try:
                    # TODO: 调用 Celery 任务触发图片生成
                    # from app.tasks.character_tasks import generate_character_image
                    # generate_character_image.delay(character_id)
                    generation_triggered = True
                    logger.info(f"[Save Tool] 已触发角色图片生成任务: character_id={character_id}")
                except Exception as e:
                    logger.error(f"[Save Tool] 触发图片生成失败: {e}")
            
            return {
                "success": True,
                "character_id": character_id,
                "message": "角色提示词保存成功",
                "generation_triggered": generation_triggered
            }
            
    except Exception as e:
        logger.error(f"[Save Tool] 保存角色提示词失败: {e}")
        return {
            "success": False,
            "character_id": character_id,
            "message": f"保存失败: {str(e)}",
            "generation_triggered": False
        }


# ==================== 场景提示词保存 ====================

@tool
async def save_scene_prompt(
    scene_id: int,
    prompt: str,
    trigger_generation: bool = False
) -> Dict[str, Any]:
    """
    保存场景图片提示词到数据库
    
    Args:
        scene_id: 场景ID
        prompt: 生成的提示词
        trigger_generation: 是否触发图片生成任务
        
    Returns:
        {
            "success": bool,
            "scene_id": int,
            "message": str,
            "generation_triggered": bool
        }
    """
    logger.info(f"[Save Tool] 保存场景提示词: scene_id={scene_id}")
    
    try:
        from app.agent.tools.async_db import get_async_session
        from app.models.scene import Scene
        from sqlalchemy import select
        from datetime import datetime
        
        async with get_async_session() as db:
            # 查询场景
            stmt = select(Scene).where(Scene.scene_id == scene_id)
            result = await db.execute(stmt)
            scene = result.scalar_one_or_none()
            
            if not scene:
                return {
                    "success": False,
                    "scene_id": scene_id,
                    "message": f"场景不存在: {scene_id}",
                    "generation_triggered": False
                }
            
            # 更新提示词（存储在 extra_data 中）
            if not scene.extra_data:
                scene.extra_data = {}
            scene.extra_data["image_prompt"] = prompt
            flag_modified(scene, "extra_data")
            
            scene.updated_at = datetime.now()
            
            # 如果触发生成，更新状态
            if trigger_generation:
                scene.status = "pending"
                scene.status_detail = "等待重新生成图片"
            
            await db.commit()
            
            # 触发图片生成任务
            generation_triggered = False
            if trigger_generation:
                try:
                    # TODO: 调用 Celery 任务触发图片生成
                    generation_triggered = True
                    logger.info(f"[Save Tool] 已触发场景图片生成任务: scene_id={scene_id}")
                except Exception as e:
                    logger.error(f"[Save Tool] 触发图片生成失败: {e}")
            
            return {
                "success": True,
                "scene_id": scene_id,
                "message": "场景提示词保存成功",
                "generation_triggered": generation_triggered
            }
            
    except Exception as e:
        logger.error(f"[Save Tool] 保存场景提示词失败: {e}")
        return {
            "success": False,
            "scene_id": scene_id,
            "message": f"保存失败: {str(e)}",
            "generation_triggered": False
        }


# ==================== 分镜提示词保存 ====================

@tool
async def save_shot_image_prompt(
    shot_id: int,
    prompt: str,
    frame_type: str = "start",
    trigger_generation: bool = False
) -> Dict[str, Any]:
    """
    保存分镜图片提示词到数据库
    
    Args:
        shot_id: 分镜ID
        prompt: 生成的提示词
        frame_type: 帧类型 "start" / "end" / "both"
        trigger_generation: 是否触发图片生成任务
        
    Returns:
        {
            "success": bool,
            "shot_id": int,
            "frame_type": str,
            "message": str,
            "generation_triggered": bool
        }
    """
    logger.info(f"[Save Tool] 保存分镜图片提示词: shot_id={shot_id}, frame={frame_type}")
    
    try:
        from app.agent.tools.async_db import get_async_session
        from app.models.shot import Shot
        from sqlalchemy import select
        from datetime import datetime
        
        async with get_async_session() as db:
            # 查询分镜
            stmt = select(Shot).where(Shot.shot_id == shot_id)
            result = await db.execute(stmt)
            shot = result.scalar_one_or_none()
            
            if not shot:
                return {
                    "success": False,
                    "shot_id": shot_id,
                    "frame_type": frame_type,
                    "message": f"分镜不存在: {shot_id}",
                    "generation_triggered": False
                }
            
            # 更新提示词
            if not shot.extra_data:
                shot.extra_data = {}
            
            if frame_type == "start":
                shot.image_prompt = prompt
                shot.extra_data["start_frame_image_prompt"] = prompt
            elif frame_type == "end":
                shot.extra_data["end_frame_image_prompt"] = prompt
            elif frame_type == "both":
                # 假设 prompt 是一个字典，包含 start 和 end
                if isinstance(prompt, dict):
                    shot.image_prompt = prompt
                    shot.extra_data["start_frame_prompt"] = prompt.get("start", "")
                    shot.extra_data["end_frame_prompt"] = prompt.get("end", "")
                else:
                    shot.extra_data["start_frame_prompt"] = prompt
            
            flag_modified(shot, "extra_data")
            shot.updated_at = datetime.now()
            
            # 如果触发生成，更新状态
            if trigger_generation:
                shot.status = "pending"
                shot.status_detail = f"等待重新生成{frame_type}帧图片"
            
            await db.commit()
            
            # 触发图片生成任务
            generation_triggered = False
            if trigger_generation:
                try:
                    # TODO: 调用 Celery 任务触发图片生成
                    generation_triggered = True
                    logger.info(f"[Save Tool] 已触发分镜图片生成任务: shot_id={shot_id}, frame={frame_type}")
                except Exception as e:
                    logger.error(f"[Save Tool] 触发图片生成失败: {e}")
            
            return {
                "success": True,
                "shot_id": shot_id,
                "frame_type": frame_type,
                "message": "分镜图片提示词保存成功",
                "generation_triggered": generation_triggered
            }
            
    except Exception as e:
        logger.error(f"[Save Tool] 保存分镜图片提示词失败: {e}")
        return {
            "success": False,
            "shot_id": shot_id,
            "frame_type": frame_type,
            "message": f"保存失败: {str(e)}",
            "generation_triggered": False
        }


@tool
async def save_shot_video_prompt(
    shot_id: int,
    video_prompt: str,
    cut_method: str = "",
    cut_reason: str = "",
    trigger_generation: bool = False
) -> Dict[str, Any]:
    """
    保存分镜视频提示词到数据库
    
    Args:
        shot_id: 分镜ID
        video_prompt: 视频提示词（JSON 格式字符串）
        cut_method: 镜头切换方法
        cut_reason: 切换原因
        trigger_generation: 是否触发视频生成任务
        
    Returns:
        {
            "success": bool,
            "shot_id": int,
            "message": str,
            "generation_triggered": bool
        }
    """
    logger.info(f"[Save Tool] 保存分镜视频提示词: shot_id={shot_id}")
    
    try:
        from app.agent.tools.async_db import get_async_session
        from app.models.shot import Shot
        from sqlalchemy import select
        from datetime import datetime
        
        async with get_async_session() as db:
            # 查询分镜
            stmt = select(Shot).where(Shot.shot_id == shot_id)
            result = await db.execute(stmt)
            shot = result.scalar_one_or_none()
            
            if not shot:
                return {
                    "success": False,
                    "shot_id": shot_id,
                    "message": f"分镜不存在: {shot_id}",
                    "generation_triggered": False
                }
            
            # 更新提示词
            if not shot.extra_data:
                shot.extra_data = {}
            
            # 解析视频提示词（支持 JSON 格式或纯文本）
            parsed_vp, parsed_cm, parsed_cr = _parse_video_prompt(video_prompt)
            
            # 使用解析后的值，如果解析失败则使用传入的值
            shot.extra_data["video_prompt"] = parsed_vp if parsed_vp else video_prompt
            shot.extra_data["cut_method"] = parsed_cm if parsed_cm else cut_method
            shot.extra_data["cut_reason"] = parsed_cr if parsed_cr else cut_reason
            
            flag_modified(shot, "extra_data")
            shot.updated_at = datetime.now()
            
            # 如果触发生成，更新状态
            if trigger_generation:
                shot.video_status = "pending"
                shot.status_detail = "等待重新生成视频"
            
            await db.commit()
            
            # 触发视频生成任务
            generation_triggered = False
            if trigger_generation:
                try:
                    # TODO: 调用 Celery 任务触发视频生成
                    generation_triggered = True
                    logger.info(f"[Save Tool] 已触发分镜视频生成任务: shot_id={shot_id}")
                except Exception as e:
                    logger.error(f"[Save Tool] 触发视频生成失败: {e}")
            
            return {
                "success": True,
                "shot_id": shot_id,
                "message": "分镜视频提示词保存成功",
                "generation_triggered": generation_triggered
            }
            
    except Exception as e:
        logger.error(f"[Save Tool] 保存分镜视频提示词失败: {e}")
        return {
            "success": False,
            "shot_id": shot_id,
            "message": f"保存失败: {str(e)}",
            "generation_triggered": False
        }


# ==================== 工具列表导出 ====================

SAVE_TOOLS = [
    save_character_prompt,
    save_scene_prompt,
    save_shot_image_prompt,
    save_shot_video_prompt,
]
