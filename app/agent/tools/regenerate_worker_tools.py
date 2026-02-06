"""
Regenerate Worker Tools - 资产重新生成 Worker 专用工具

提供原子化的查询和提交工具，供 AssetRegeneratorWorkerNode 使用。
所有提示词生成均使用模板文件，不硬编码在代码中。
"""

import asyncio
import json
import re
from typing import Dict, Any, List, Optional
from datetime import datetime

from langchain_core.tools import tool
from langchain_core.messages import HumanMessage
from pydantic import BaseModel, Field
from sqlalchemy.orm.attributes import flag_modified

from app.core.logger import logger
from app.core.config import settings


# ==================== Core Database Functions (非工具，可被内部调用) ====================

async def _get_character_from_db(character_id: int) -> Dict[str, Any]:
    """从数据库获取角色详情的核心函数"""
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
            "character": {
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
                "created_at": character.created_at.isoformat() if character.created_at else None,
                "updated_at": character.updated_at.isoformat() if character.updated_at else None,
            }
        }


async def _get_scene_from_db(scene_id: int) -> Dict[str, Any]:
    """从数据库获取场景详情的核心函数"""
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
            "scene": {
                "scene_id": scene.scene_id,
                "title": scene.title,
                "duration": scene.duration,
                "time_setting": scene.time_setting,
                "location": scene.location,
                "space_type": scene.space_type,
                "atmosphere": scene.atmosphere,
                "image_prompt": scene.extra_data.get("image_prompt") if scene.extra_data else None,
                "image_url": scene.image_url,
                "status": scene.status,
                "status_detail": scene.status_detail,
                "extra_data": scene.extra_data,
                "created_at": scene.created_at.isoformat() if scene.created_at else None,
                "updated_at": scene.updated_at.isoformat() if scene.updated_at else None,
            }
        }


async def _get_shot_from_db(shot_id: int) -> Dict[str, Any]:
    """从数据库获取分镜详情的核心函数"""
    from app.agent.tools.async_db import get_async_session
    from app.models.shot import Shot
    from app.models.scene import Scene
    from sqlalchemy import select, and_
    
    async with get_async_session() as db:
        stmt = select(Shot).where(Shot.shot_id == shot_id)
        result = await db.execute(stmt)
        shot = result.scalar_one_or_none()
        
        if not shot:
            return {
                "success": False,
                "error": f"分镜不存在: {shot_id}",
            }
        
        shot_dict = {
            "shot_id": shot.shot_id,
            "scene_id": shot.scene_id,
            "shot_number": shot.shot_number,
            "title": shot.title,
            "description": shot.description,
            "image_prompt": shot.image_prompt,
            "image_url": shot.image_url,
            "video_prompt": shot.extra_data.get("video_prompt") if shot.extra_data else None,
            "status": shot.status,
            "status_detail": shot.status_detail,
            "extra_data": shot.extra_data,
            "created_at": shot.created_at.isoformat() if shot.created_at else None,
            "updated_at": shot.updated_at.isoformat() if shot.updated_at else None,
        }
        
        scene_data = None
        if shot.scene_id:
            scene_stmt = select(Scene).where(Scene.scene_id == shot.scene_id)
            scene_result = await db.execute(scene_stmt)
            scene = scene_result.scalar_one_or_none()
            if scene:
                scene_data = {
                    "scene_id": scene.scene_id,
                    "title": scene.title,
                    "duration": scene.duration,
                    "time_setting": scene.time_setting,
                    "location": scene.location,
                    "space_type": scene.space_type,
                    "atmosphere": scene.atmosphere,
                    "image_prompt": scene.extra_data.get("image_prompt") if scene.extra_data else None,
                    "image_url": scene.image_url,
                    "status": scene.status,
                    "extra_data": scene.extra_data,
                }
        
        previous_shot_data = None
        if shot.shot_number and shot.shot_number > 1:
            prev_stmt = (
                select(Shot)
                .where(
                    Shot.scene_id == shot.scene_id,
                    Shot.shot_number == shot.shot_number - 1
                )
            )
            prev_result = await db.execute(prev_stmt)
            prev_shot = prev_result.scalar_one_or_none()
            if prev_shot:
                previous_shot_data = {
                    "shot_id": prev_shot.shot_id,
                    "shot_number": prev_shot.shot_number,
                    "title": prev_shot.title,
                    "description": prev_shot.description,
                    "image_url": prev_shot.image_url,
                    "video_url": prev_shot.extra_data.get("video_url") if prev_shot.extra_data else None,
                    "extra_data": prev_shot.extra_data,
                }
        
        return {
            "success": True,
            "shot": shot_dict,
            "scene": scene_data,
            "previous_shot": previous_shot_data,
        }

def read_prompt_template(template_name: str) -> str:
    """读取提示词模板文件"""
    from app.utils.file_utils import read_prompt_file
    return read_prompt_file(template_name)


def get_visual_style_description(visual_style: str) -> str:
    """
    获取视觉风格的中文描述
    
    将 visual_style 的 key (如 "anime", "realism") 映射为中文描述
    """
    style_description_map = {
        "realism": "写实摄影风格，摄影作品，真实的光影和材质，逼真的人物形象，高清晰度",
        "cyberpunk": "赛博朋克风格，未来科幻，高科技低生活，霓虹灯光，赛博朋克美学",
        "ukiyoe": "浮世绘风格，传统日本浮世绘，葛饰北斋风格，平面化，鲜明色彩，传统日本元素",
        "watercolor": "水彩画风格，柔和细腻，色彩透明，笔触柔和，艺术感强",
        "anime": "日漫风格，经典日本动漫，鲜明色彩，夸张表情，典型日本动画美学",
        "cel_shading": "赛璐璐风格，平涂风格，清晰线条，鲜明色块，日式动画",
        "oil_painting": "油画风格，厚重质感，丰富色彩层次，古典绘画技法",
        "sketch": "素描风格，铅笔线条，黑白灰调，手绘质感",
        "3d_render": "3D渲染风格，立体建模，真实材质，CG效果",
    }
    return style_description_map.get(visual_style, f"{visual_style}风格")


def _get_old_prompt(shot: Dict, prompt_type: str, frame_type: str) -> str:
    """获取旧提示词"""
    extra_data = shot.get("extra_data", {}) or {}
    
    if prompt_type == "video":
        return extra_data.get("video_prompt", "")
    elif frame_type == "end":
        return extra_data.get("end_frame_prompt", "")
    else:
        return shot.get("image_prompt", "")


async def _save_shot_prompt(shot_id: int, new_prompt: str, prompt_type: str, frame_type: str) -> bool:
    """保存提示词到数据库"""
    import json
    
    from app.agent.tools.async_db import get_async_session
    from app.models.shot import Shot
    from sqlalchemy import select
    
    async with get_async_session() as db:
        stmt = select(Shot).where(Shot.shot_id == shot_id)
        result = await db.execute(stmt)
        shot = result.scalar_one_or_none()
        
        if not shot:
            return False
        
        if shot.extra_data is None:
            shot.extra_data = {}
        
        # 处理视频提示词
        if prompt_type == "video":
            cleaned_prompt = new_prompt.strip()
            if cleaned_prompt.startswith("```json"):
                cleaned_prompt = cleaned_prompt[7:]
            if cleaned_prompt.endswith("```"):
                cleaned_prompt = cleaned_prompt[:-3]
            cleaned_prompt = cleaned_prompt.strip()
            
            json_match = re.search(r'\{[\s\S]*\}', cleaned_prompt)
            if json_match:
                json_str = json_match.group()
                json_str = json_str.replace('\n', '\\n').replace('\r', '\\r').replace('\t', '\\t')
                try:
                    prompt_json = json.loads(json_str)
                    if "video_prompt" in prompt_json:
                        shot.extra_data["video_prompt"] = prompt_json["video_prompt"]
                        logger.info(f"[Save] 解析JSON video_prompt成功，长度={len(prompt_json.get('video_prompt', ''))}")
                    else:
                        video_match = re.search(r'"video_prompt":\s*"([^"]+)"', json_str)
                        if video_match:
                            shot.extra_data["video_prompt"] = video_match.group(1)
                            logger.info(f"[Save] 正则提取video_prompt成功")
                        else:
                            shot.extra_data["video_prompt"] = cleaned_prompt
                except json.JSONDecodeError:
                    logger.warning(f"[Save] 视频JSON解析失败，尝试正则提取")
                    video_match = re.search(r'"video_prompt":\s*"([^"]+)"', json_str)
                    if video_match:
                        shot.extra_data["video_prompt"] = video_match.group(1)
                        logger.info(f"[Save] 正则提取video_prompt成功")
                    else:
                        shot.extra_data["video_prompt"] = cleaned_prompt
            else:
                shot.extra_data["video_prompt"] = new_prompt
        
        # 处理图片提示词（可能返回JSON格式）
        elif prompt_type == "image":
            prompt_to_save = new_prompt
            
            if frame_type == "both":
                cleaned_prompt = new_prompt.strip()
                if cleaned_prompt.startswith("```json"):
                    cleaned_prompt = cleaned_prompt[7:]
                if cleaned_prompt.endswith("```"):
                    cleaned_prompt = cleaned_prompt[:-3]
                cleaned_prompt = cleaned_prompt.strip()
                
                json_match = re.search(r'\{[\s\S]*\}', cleaned_prompt)
                if json_match:
                    json_str = json_match.group()
                    json_str = json_str.replace('\n', '\\n').replace('\r', '\\r').replace('\t', '\\t')
                    try:
                        prompt_json = json.loads(json_str)
                        if "start_frame_prompt" in prompt_json:
                            shot.image_prompt = prompt_json["start_frame_prompt"]
                        if "end_frame_prompt" in prompt_json:
                            shot.extra_data["end_frame_image_prompt"] = prompt_json["end_frame_prompt"]
                        logger.info(f"[Save] 解析JSON成功: start_frame长度={len(prompt_json.get('start_frame_prompt', ''))}, end_frame长度={len(prompt_json.get('end_frame_prompt', ''))}")
                        prompt_to_save = None
                    except json.JSONDecodeError:
                        logger.warning(f"[Save] JSON解析失败，使用正则表达式兜底提取")
                        start_match = re.search(r'"start_frame_prompt":\s*"([^"]+)"', json_str)
                        end_match = re.search(r'"end_frame_prompt":\s*"([^"]+)"', json_str)
                        if start_match:
                            shot.image_prompt = start_match.group(1)
                            logger.info(f"[Save] 正则提取start_frame成功")
                        if end_match:
                            shot.extra_data["end_frame_image_prompt"] = end_match.group(1)
                            logger.info(f"[Save] 正则提取end_frame成功")
                        prompt_to_save = None
                else:
                    prompt_to_save = cleaned_prompt
            
            if prompt_to_save:
                if frame_type == "end":
                    shot.extra_data["end_frame_prompt"] = prompt_to_save
                else:
                    shot.image_prompt = prompt_to_save
        
        flag_modified(shot, "extra_data")
        await db.commit()
        return True


async def _save_character_prompt(character_id: int, new_prompt: str) -> bool:
    """保存角色提示词到数据库"""
    from app.agent.tools.async_db import get_async_session
    from app.models.character import Character
    from sqlalchemy import select
    
    async with get_async_session() as db:
        stmt = select(Character).where(Character.character_id == character_id)
        result = await db.execute(stmt)
        character = result.scalar_one_or_none()
        
        if not character:
            return False
        
        character.image_prompt = new_prompt
        await db.commit()
        return True


async def _save_scene_prompt(scene_id: int, new_prompt: str) -> bool:
    """保存场景提示词到数据库"""
    from app.agent.tools.async_db import get_async_session
    from app.models.scene import Scene
    from sqlalchemy import select
    
    async with get_async_session() as db:
        stmt = select(Scene).where(Scene.scene_id == scene_id)
        result = await db.execute(stmt)
        scene = result.scalar_one_or_none()
        
        if not scene:
            return False
        
        if scene.extra_data is None:
            scene.extra_data = {}
        
        scene.extra_data["image_prompt"] = new_prompt
        flag_modified(scene, "extra_data")
        await db.commit()
        return True


# ==================== 知识库查询核心函数 ====================

async def _retrieve_knowledge_from_db(
    shot_description: str,
    top_k: int = 3,
) -> Dict[str, Any]:
    """检索视频提示词相关知识库内容的核心函数"""
    logger.info(f"[Knowledge Retrieval] 检索视频提示词知识: {shot_description[:50]}...")
    
    from app.agent.tools.knowledge_tools import KNOWLEDGE_BASE_TYPES
    
    try:
        from app.services.vector_store import VectorStoreService
        
        vector_store = VectorStoreService()
        knowledge_types = ["camera_angles", "storyboard_techniques", "composition_rules"]
        
        async def query_single_knowledge(ktype: str):
            results = await vector_store.similarity_search(
                collection_name=f"knowledge_{ktype}",
                query=shot_description,
                top_k=top_k,
            )
            return {
                "status": "success",
                "knowledge_type": ktype,
                "knowledge_type_desc": KNOWLEDGE_BASE_TYPES.get(ktype, ktype),
                "results": [
                    {
                        "content": r["content"],
                        "metadata": r.get("metadata", {}),
                        "score": r.get("score", 0),
                    }
                    for r in results
                ],
            }
        
        results = await asyncio.gather(
            query_single_knowledge("camera_angles"),
            query_single_knowledge("storyboard_techniques"),
            query_single_knowledge("composition_rules"),
            return_exceptions=True
        )
        
        all_knowledge = []
        
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                logger.warning(f"[Knowledge Retrieval] 查询知识库失败: {result}")
                continue
                
            if result.get("status") == "success":
                knowledge_type = ["镜头语言", "分镜技巧", "构图规则"][i]
                for item in result.get("results", []):
                    all_knowledge.append({
                        "type": knowledge_type,
                        "content": item["content"],
                        "score": item.get("score", 0),
                    })
        
        all_knowledge.sort(key=lambda x: x["score"], reverse=True)
        
        return {
            "status": "success",
            "shot_description": shot_description,
            "knowledge_count": len(all_knowledge),
            "knowledge": all_knowledge[:top_k * 3],
        }
        
    except ImportError:
        logger.warning("[Knowledge Retrieval] 向量存储服务未实现，返回空知识")
        return {
            "status": "success",
            "shot_description": shot_description,
            "knowledge_count": 0,
            "knowledge": [],
        }
        
    except Exception as e:
        logger.error(f"[Knowledge Retrieval] 检索知识库失败: {e}")
        return {
            "status": "error",
            "error": str(e),
            "knowledge": [],
        }


# ==================== 知识库查询工具 ====================

@tool
async def retrieve_video_prompt_knowledge(
    shot_description: str,
    top_k: int = 3,
) -> Dict[str, Any]:
    """
    检索视频提示词相关的知识库内容
    
    在生成分镜视频提示词前调用，获取运镜技巧、镜头语言等相关知识，
    帮助生成更专业的视频提示词。
    
    Args:
        shot_description: 分镜描述（用于检索相关知识）
        top_k: 返回的知识条目数量
        
    Returns:
        相关知识列表
    """
    return await _retrieve_knowledge_from_db(shot_description, top_k)


# ==================== 查询类 Tools ====================

@tool
async def query_single_character(character_id: int) -> Dict[str, Any]:
    """
    查询单个角色详情
    
    获取角色的完整信息，包括基本信息、状态、提示词等。
    
    Args:
        character_id: 角色ID
        
    Returns:
        角色完整信息
    """
    logger.info(f"[Query Tool] 查询角色详情: character_id={character_id}")
    return await _get_character_from_db(character_id)


@tool
async def query_single_scene(scene_id: int) -> Dict[str, Any]:
    """
    查询单个场景详情
    
    获取场景的完整信息，包括场景设置、状态、提示词等。
    
    Args:
        scene_id: 场景ID
        
    Returns:
        场景完整信息
    """
    logger.info(f"[Query Tool] 查询场景详情: scene_id={scene_id}")
    return await _get_scene_from_db(scene_id)


@tool
async def query_single_shot(shot_id: int) -> Dict[str, Any]:
    """
    查询单个分镜详情
    
    获取分镜的完整信息，包括分镜内容、关联场景、上一个分镜信息（用于连贯性处理）等。
    
    Args:
        shot_id: 分镜ID
        
    Returns:
        分镜完整信息，包含：
        - 当前分镜的所有字段
        - 关联场景的完整信息
        - 上一个分镜的信息（如果 shot_number > 1）
    """
    logger.info(f"[Query Tool] 查询分镜详情: shot_id={shot_id}")
    return await _get_shot_from_db(shot_id)


async def _get_all_shots_from_db(creation_uuid: str) -> Dict[str, Any]:
    """从数据库获取指定创作项目的所有分镜、角色和场景（去重）"""
    from app.agent.tools.async_db import get_async_db_session
    from app.models.shot import Shot
    from app.models.scene import Scene
    from app.models.creation import Creation
    from app.models.character import Character
    from app.models.shot_characters import shot_characters
    from sqlalchemy import select

    try:
        async with get_async_db_session() as db:
            stmt = select(Creation).where(Creation.uuid == creation_uuid)
            result = await db.execute(stmt)
            creation = result.scalar_one_or_none()

            if not creation:
                return {
                    "success": False,
                    "error": f"创作项目不存在: {creation_uuid}",
                }

            shot_stmt = (
                select(Shot)
                .join(Scene, Shot.scene_id == Scene.scene_id)
                .where(Scene.creation_id == creation.creation_id)
                .order_by(Shot.shot_number)
            )
            result = await db.execute(shot_stmt)
            shots = result.scalars().all()

            scene_ids = list(set(shot.scene_id for shot in shots if shot.scene_id))
            scene_stmt = select(Scene).where(Scene.scene_id.in_(scene_ids))
            scenes_result = await db.execute(scene_stmt)
            scenes = {s.scene_id: s for s in scenes_result.scalars().all()}

            all_character_ids = set()
            for shot in shots:
                query = select(shot_characters.c.character_id).where(shot_characters.c.shot_id == shot.shot_id)
                chars_result = await db.execute(query)
                all_character_ids.update(row[0] for row in chars_result.fetchall())

            char_stmt = select(Character).where(Character.character_id.in_(all_character_ids))
            chars_result = await db.execute(char_stmt)
            characters = {c.character_id: c for c in chars_result.scalars().all()}

            shot_list = []
            for shot in shots:
                query = (
                    select(shot_characters.c.character_id)
                    .where(shot_characters.c.shot_id == shot.shot_id)
                )
                chars_result = await db.execute(query)
                shot_character_ids = [row[0] for row in chars_result.fetchall()]

                shot_dict = {
                    "shot_id": shot.shot_id,
                    "shot_number": shot.shot_number,
                    "title": shot.title,
                    "description": shot.description,
                    "image_prompt": shot.image_prompt,
                    "image_url": shot.image_url,
                    "status": shot.status,
                    "status_detail": shot.status_detail,
                    "extra_data": shot.extra_data or {},
                    "scene_id": shot.scene_id,
                    "character_ids": shot_character_ids,
                }
                shot_list.append(shot_dict)

            scene_list = [
                {
                    "scene_id": s.scene_id,
                    "title": s.title,
                    "location": s.location,
                    "time_setting": s.time_setting,
                    "atmosphere": s.atmosphere,
                    "space_type": s.space_type,
                }
                for s in scenes.values()
            ]

            character_list = [
                {
                    "character_id": c.character_id,
                    "name": c.name,
                    "basic_info": c.basic_info,
                    "appearance": c.appearance,
                }
                for c in characters.values()
            ]

            return {
                "success": True,
                "shots": shot_list,
                "scenes": scene_list,
                "characters": character_list,
                "total": len(shot_list),
            }
    except Exception as e:
        logger.error(f"[_get_all_shots_from_db] 获取数据失败: {e}")
        return {
            "success": False,
            "error": str(e),
        }


@tool
async def query_all_shots(creation_uuid: str) -> Dict[str, Any]:
    """
    查询指定创作项目的所有分镜、角色和场景

    批量获取所有资源信息，用于一次性处理多个分镜任务。

    Args:
        creation_uuid: 创作项目 UUID

    Returns:
        {
            "success": True,
            "shots": [...],       # 所有分镜列表
            "scenes": [...],      # 所有场景列表（去重）
            "characters": [...], # 所有角色列表（去重）
            "total": 10          # 分镜总数
        }

        其中每个 shot 包含：
        - shot_id, shot_number, title, description
        - image_prompt, image_url
        - status, status_detail, extra_data
        - scene_id, character_ids

        每个 scene 包含：
        - scene_id, title, location, time_setting, atmosphere, space_type

        每个 character 包含：
        - character_id, name, basic_info, appearance
    """
    logger.info(f"[Query Tool] 查询所有分镜: creation_uuid={creation_uuid}")
    return await _get_all_shots_from_db(creation_uuid)


# ==================== 提交重新生成 Tools ====================

@tool
async def submit_character_image_regeneration(
    character_id: int,
    creation_uuid: str,
    mode: str = "auto",
) -> Dict[str, Any]:
    """
    提交角色图片重新生成任务
    
    当用户要求重新生成角色图片时调用此工具。
    
    Args:
        character_id: 角色ID
        creation_uuid: 创作项目UUID
        mode: 生成模式 (auto/txt2img/img2img)
        
    Returns:
        提交结果
    """
    logger.info(f"[Submit Tool] 提交角色图片重新生成: character_id={character_id}")
    
    result = await _execute_regeneration(
        target_type="character",
        target_id=character_id,
        creation_uuid=creation_uuid,
        save_version=True,
        mode=mode,
    )
    
    return {
        "success": result.get("success", False),
        "character_id": character_id,
        "task_id": result.get("task_id"),
        "error": result.get("error"),
    }


@tool
async def submit_character_prompt_regeneration(
    character_id: int,
    creation_uuid: str,
    operation_type: str = "regenerate",
    feedback: str = "",
) -> Dict[str, Any]:
    """
    提交角色提示词重新生成/修改任务
    
    使用模板文件生成提示词，不硬编码在代码中。
    
    Args:
        character_id: 角色ID
        creation_uuid: 创作项目UUID
        operation_type: 操作类型 (regenerate-重新生成/modify-修改)
        feedback: 修改意见（operation_type="modify"时必填）
        
    Returns:
        提交结果
    """
    logger.info(f"[Submit Tool] 提交角色提示词重新生成: character_id={character_id}, operation={operation_type}")
    
    # 查询角色信息
    char_result = await _get_character_from_db(character_id)
    if not char_result.get("success"):
        return char_result
    
    character = char_result["character"]

    # 从 creation 获取视觉风格
    visual_style_key = "anime"  # 默认 key
    try:
        from app.agent.tools.async_db import get_async_session
        from app.models.creation import Creation
        from sqlalchemy import select

        async with get_async_session() as db:
            stmt = select(Creation).where(Creation.uuid == creation_uuid)
            result = await db.execute(stmt)
            creation = result.scalar_one_or_none()
            if creation and creation.extra_data:
                visual_style_key = creation.extra_data.get("visual_style", "anime")
    except Exception as e:
        logger.warning(f"[Submit Tool] 获取视觉风格失败，使用默认值: {e}")

    # 将 visual_style key 转换为中文描述
    visual_style = get_visual_style_description(visual_style_key)

    # 读取提示词模板
    if operation_type == "regenerate":
        template = read_prompt_template("regenerate_character.md")
    else:
        template = read_prompt_template("modify_prompt.md")

    # 准备资源上下文（用于 modify 模式）
    resource_context = f"""角色名称: {character.get('name', '')}
基本信息: {character.get('basic_info', '') or '无'}
外貌描述: {character.get('appearance', '') or '无'}
视觉风格: {visual_style}"""

    # 填充模板变量
    if operation_type == "regenerate":
        prompt = template.replace("{{CHARACTER_NAME}}", character.get("name", "")) \
                        .replace("{{BASIC_INFO}}", character.get("basic_info", "") or "无") \
                        .replace("{{APPEARANCE}}", character.get("appearance", "") or "无") \
                        .replace("{{VISUAL_STYLE}}", visual_style)
    else:  # modify
        old_prompt = character.get("image_prompt", "")
        prompt = template.replace("{{OLD_PROMPT}}", old_prompt or "（无原提示词）") \
                        .replace("{{MODIFICATION_TYPE}}", "style") \
                        .replace("{{FEEDBACK}}", feedback) \
                        .replace("{{RESOURCE_CONTEXT}}", resource_context)

    # 调用 LLM 生成新提示词
    from langchain_openai import ChatOpenAI

    llm = ChatOpenAI(
        model=settings.LLM_MODEL_DEFAULT,
        api_key=settings.OPENAI_API_KEY,
        base_url=settings.OPENAI_BASE_URL,
        temperature=0.7,
    )

    response = await llm.ainvoke([HumanMessage(content=prompt)])
    new_prompt = response.content.strip()

    # 确保所有模板变量都被替换（防止LLM输出中仍包含变量）
    if operation_type == "regenerate":
        new_prompt = new_prompt.replace("{{CHARACTER_NAME}}", character.get("name", "")) \
                               .replace("{{BASIC_INFO}}", character.get("basic_info", "") or "无") \
                               .replace("{{APPEARANCE}}", character.get("appearance", "") or "无") \
                               .replace("{{VISUAL_STYLE}}", visual_style)
    else:  # modify
        new_prompt = new_prompt.replace("{{OLD_PROMPT}}", old_prompt or "（无原提示词）") \
                               .replace("{{MODIFICATION_TYPE}}", "style") \
                               .replace("{{FEEDBACK}}", feedback) \
                               .replace("{{RESOURCE_CONTEXT}}", resource_context)

    # 保存到数据库
    success = await _save_character_prompt(character_id, new_prompt)
    
    return {
        "success": success,
        "character_id": character_id,
        "operation_type": operation_type,
        "visual_style": visual_style,
        "new_prompt": new_prompt[:100] + "..." if len(new_prompt) > 100 else new_prompt,
    }


@tool
async def submit_scene_image_regeneration(
    scene_id: int,
    creation_uuid: str,
) -> Dict[str, Any]:
    """
    提交场景图片重新生成任务
    
    Args:
        scene_id: 场景ID
        creation_uuid: 创作项目UUID
        
    Returns:
        提交结果
    """
    logger.info(f"[Submit Tool] 提交场景图片重新生成: scene_id={scene_id}")
    
    result = await _execute_regeneration(
        target_type="scene",
        target_id=scene_id,
        creation_uuid=creation_uuid,
        save_version=True,
        mode="auto",
    )
    
    return {
        "success": result.get("success", False),
        "scene_id": scene_id,
        "task_id": result.get("task_id"),
        "error": result.get("error"),
    }


@tool
async def submit_scene_prompt_regeneration(
    scene_id: int,
    creation_uuid: str,
    operation_type: str = "regenerate",
    feedback: str = "",
) -> Dict[str, Any]:
    """
    提交场景提示词重新生成/修改任务

    使用模板文件生成提示词，不硬编码在代码中。

    Args:
        scene_id: 场景ID
        creation_uuid: 创作项目UUID
        operation_type: 操作类型 (regenerate-重新生成/modify-修改)
        feedback: 修改意见（operation_type="modify"时必填）

    Returns:
        提交结果
    """
    # 添加入口日志
    logger.info(f"[submit_scene_prompt_regeneration] 被调用: scene_id={scene_id}, operation_type={operation_type}, feedback={feedback}")
    logger.info(f"[Submit Tool] 提交场景提示词重新生成: scene_id={scene_id}, operation={operation_type}")
    
    # 查询场景信息
    scene_result = await _get_scene_from_db(scene_id)
    if not scene_result.get("success"):
        return scene_result
    
    scene = scene_result["scene"]

    # 从 creation 获取视觉风格
    visual_style_key = "anime"  # 默认 key
    try:
        from app.agent.tools.async_db import get_async_session
        from app.models.creation import Creation
        from sqlalchemy import select

        async with get_async_session() as db:
            stmt = select(Creation).where(Creation.uuid == creation_uuid)
            result = await db.execute(stmt)
            creation = result.scalar_one_or_none()
            if creation and creation.extra_data:
                visual_style_key = creation.extra_data.get("visual_style", "anime")
    except Exception as e:
        logger.warning(f"[Submit Tool] 获取视觉风格失败，使用默认值: {e}")

    # 将 visual_style key 转换为中文描述
    visual_style = get_visual_style_description(visual_style_key)

    # 读取提示词模板
    if operation_type == "regenerate":
        template = read_prompt_template("regenerate_scene.md")
    else:
        template = read_prompt_template("modify_prompt.md")

    # 准备资源上下文（用于 modify 模式）
    resource_context = f"""场景标题: {scene.get('title', '')}
地点: {scene.get('location', '') or '未指定'}
时间: {scene.get('time_setting', '') or '未指定'}
氛围: {scene.get('atmosphere', '') or '未指定'}
空间类型: {scene.get('space_type', '') or '未指定'}
视觉风格: {visual_style}"""

    # 填充模板变量
    if operation_type == "regenerate":
        prompt = template.replace("{{SCENE_TITLE}}", scene.get("title", "")) \
                        .replace("{{LOCATION}}", scene.get("location", "") or "未指定") \
                        .replace("{{TIME_SETTING}}", scene.get("time_setting", "") or "未指定") \
                        .replace("{{ATMOSPHERE}}", scene.get("atmosphere", "") or "未指定") \
                        .replace("{{SPACE_TYPE}}", scene.get("space_type", "") or "未指定") \
                        .replace("{{VISUAL_STYLE}}", visual_style)
    else:  # modify
        old_prompt = ""
        if scene.get("extra_data"):
            old_prompt = scene["extra_data"].get("image_prompt", "")
        prompt = template.replace("{{OLD_PROMPT}}", old_prompt or "（无原提示词）") \
                        .replace("{{MODIFICATION_TYPE}}", "style") \
                        .replace("{{FEEDBACK}}", feedback) \
                        .replace("{{RESOURCE_CONTEXT}}", resource_context)

    # 调试日志：检查变量是否被正确替换
    logger.info(f"[Submit Tool] 场景提示词生成 - operation_type={operation_type}")
    logger.info(f"[Submit Tool] 场景数据: title={scene.get('title')}, location={scene.get('location')}, time={scene.get('time_setting')}")
    has_scene_title = "{{SCENE_TITLE}}" in prompt
    has_location = "{{LOCATION}}" in prompt
    has_visual_style = "{{VISUAL_STYLE}}" in prompt
    logger.info(f"[Submit Tool] 模板变量检查 - 包含SCENE_TITLE: {has_scene_title}, 包含LOCATION: {has_location}, 包含VISUAL_STYLE: {has_visual_style}")
    # 打印prompt的前500字符用于调试
    logger.info(f"[Submit Tool] Prompt前500字符: {prompt[:500]}")

    # 调用 LLM 生成新提示词
    from langchain_openai import ChatOpenAI

    llm = ChatOpenAI(
        model=settings.LLM_MODEL_DEFAULT,
        api_key=settings.OPENAI_API_KEY,
        base_url=settings.OPENAI_BASE_URL,
        temperature=0.7,
    )

    response = await llm.ainvoke([HumanMessage(content=prompt)])
    new_prompt = response.content.strip()

    # 确保所有模板变量都被替换（防止LLM输出中仍包含变量）
    if operation_type == "regenerate":
        new_prompt = new_prompt.replace("{{SCENE_TITLE}}", scene.get("title", "")) \
                               .replace("{{LOCATION}}", scene.get("location", "") or "未指定") \
                               .replace("{{TIME_SETTING}}", scene.get("time_setting", "") or "未指定") \
                               .replace("{{ATMOSPHERE}}", scene.get("atmosphere", "") or "未指定") \
                               .replace("{{SPACE_TYPE}}", scene.get("space_type", "") or "未指定") \
                               .replace("{{VISUAL_STYLE}}", visual_style)
    else:  # modify
        new_prompt = new_prompt.replace("{{OLD_PROMPT}}", old_prompt or "（无原提示词）") \
                               .replace("{{MODIFICATION_TYPE}}", "style") \
                               .replace("{{FEEDBACK}}", feedback) \
                               .replace("{{RESOURCE_CONTEXT}}", resource_context)
    
    # 保存到数据库
    success = await _save_scene_prompt(scene_id, new_prompt)
    
    return {
        "success": success,
        "scene_id": scene_id,
        "operation_type": operation_type,
        "visual_style": visual_style,
        "new_prompt": new_prompt[:100] + "..." if len(new_prompt) > 100 else new_prompt,
    }


@tool
async def submit_shot_image_regeneration(
    shot_id: int,
    creation_uuid: str,
    frame_type: str = "both",
) -> Dict[str, Any]:
    """
    提交分镜图片重新生成任务
    
    Args:
        shot_id: 分镜ID
        creation_uuid: 创作项目UUID
        frame_type: 帧类型 (start-首帧/end-尾帧/both-全部)
        
    Returns:
        提交结果
    """
    logger.info(f"[Submit Tool] 提交分镜图片重新生成: shot_id={shot_id}, frame_type={frame_type}")
    
    results = []
    
    if frame_type in ["start", "both"]:
        result = await _execute_regeneration(
            target_type="shot_start",
            target_id=shot_id,
            creation_uuid=creation_uuid,
            save_version=True,
            mode="auto",
        )
        results.append({"frame": "start", "result": result})
    
    if frame_type in ["end", "both"]:
        result = await _execute_regeneration(
            target_type="shot_end",
            target_id=shot_id,
            creation_uuid=creation_uuid,
            save_version=True,
            mode="auto",
        )
        results.append({"frame": "end", "result": result})
    
    success = all(r["result"].get("success", False) for r in results)
    
    return {
        "success": success,
        "shot_id": shot_id,
        "frame_type": frame_type,
        "results": results,
    }


@tool
async def submit_shot_prompt_regeneration(
    shot_id: int,
    creation_uuid: str,
    prompt_type: str = "image",
    frame_type: str = "both",
    operation_type: str = "regenerate",
    feedback: str = "",
) -> Dict[str, Any]:
    """
    提交分镜提示词重新生成/修改任务
    
    使用模板文件生成提示词。
    
    Args:
        shot_id: 分镜ID
        creation_uuid: 创作项目UUID
        prompt_type: 提示词类型 "image"(图片) 或 "video"(视频)
        frame_type: 帧类型 "start"(首帧)/"end"(尾帧)/"both"(全部)
        operation_type: 操作类型 "regenerate"(重新生成)/"modify"(修改)
        feedback: 修改意见（operation_type="modify"时必填）
        
    Returns:
        提交结果
    """
    logger.info(f"[Submit Tool] 提交分镜提示词重新生成: shot_id={shot_id}, prompt_type={prompt_type}, operation={operation_type}")

    # 查询分镜信息（包含场景和上一个分镜信息）
    shot_result = await _get_shot_from_db(shot_id)
    if not shot_result.get("success"):
        return shot_result

    shot = shot_result["shot"]
    scene = shot_result.get("scene")
    previous_shot = shot_result.get("previous_shot")

    # 从 creation 获取视觉风格
    visual_style_key = "anime"  # 默认 key
    try:
        from app.agent.tools.async_db import get_async_session
        from app.models.creation import Creation
        from sqlalchemy import select

        async with get_async_session() as db:
            stmt = select(Creation).where(Creation.uuid == creation_uuid)
            result = await db.execute(stmt)
            creation = result.scalar_one_or_none()
            if creation and creation.extra_data:
                visual_style_key = creation.extra_data.get("visual_style", "anime")
    except Exception as e:
        logger.warning(f"[Submit Tool] 获取视觉风格失败，使用默认值: {e}")

    # 将 visual_style key 转换为中文描述
    visual_style = get_visual_style_description(visual_style_key)

    # 查询角色信息（用于填充 CHARACTER_PROFILES）
    character_profiles = ""
    try:
        from app.agent.tools.async_db import get_async_session
        from app.models.character import Character
        from app.models.creation import Creation
        from sqlalchemy import select
        
        async with get_async_session() as db:
            creation_stmt = select(Creation).where(Creation.uuid == creation_uuid)
            creation_result = await db.execute(creation_stmt)
            creation = creation_result.scalar_one_or_none()
            
            if creation and creation.character_ids:
                stmt = select(Character).where(Character.character_id.in_(creation.character_ids))
                result = await db.execute(stmt)
                characters = result.scalars().all()
                
                if characters:
                    char_lines = []
                    for char in characters:
                        char_name = char.name or "未命名"
                        char_basic = char.basic_info or ""
                        char_appearance = char.appearance or ""
                        char_lines.append(f"- {char_name}: {char_basic or '无基本信息'}，{char_appearance or '无外貌描述'}")
                    character_profiles = "\n".join(char_lines)
                else:
                    character_profiles = "无角色信息"
            else:
                character_profiles = "无角色信息"
    except Exception as e:
        logger.warning(f"[Submit Tool] 获取角色信息失败: {e}")
        character_profiles = "无角色信息"

    # 读取提示词模板
    if operation_type == "regenerate":
        if prompt_type == "video":
            template = read_prompt_template("regenerate_video.md")
        else:
            template = read_prompt_template(f"regenerate_shot_{frame_type}.md")
    else:
        template = read_prompt_template("modify_prompt.md")

    # 填充模板变量（不包括 KNOWLEDGE_CONTEXT，由调用方负责注入）
    if operation_type == "regenerate":
        # 构建上一个分镜信息
        prev_shot_info = ""
        if previous_shot:
            prev_shot_info = f"""
上一个分镜信息（保持连贯性）：
- 分镜编号: {previous_shot.get('shot_number', '')}
- 描述: {previous_shot.get('description', '')}
- 注意: 当前分镜的画面应该与上一个分镜保持视觉连贯性
"""

        prompt = template.replace("{{SHOT_NUMBER}}", str(shot.get("shot_number", ""))) \
                    .replace("{{SHOT_TITLE}}", shot.get("title", "") or f"分镜{shot.get('shot_number', '')}") \
                    .replace("{{SHOT_DESCRIPTION}}", shot.get("description", "") or "无") \
                    .replace("{{SHOT_NARRATION}}", shot.get("narration", "") or "无") \
                    .replace("{{SHOT_VIDEO_DURATION}}", str(shot.get("video_duration", "5"))) \
                    .replace("{{SCENE_TITLE}}", scene.get("title", "") if scene else "未指定") \
                    .replace("{{SCENE_LOCATION}}", scene.get("location", "") or "未指定") \
                    .replace("{{SCENE_TIME}}", scene.get("time_setting", "") or "未指定") \
                    .replace("{{SCENE_ATMOSPHERE}}", scene.get("atmosphere", "") or "未指定") \
                    .replace("{{PREVIOUS_SHOT_INFO}}", prev_shot_info) \
                    .replace("{{KNOWLEDGE_CONTEXT}}", "") \
                    .replace("{{CHARACTER_PROFILES}}", character_profiles) \
                    .replace("{{VISUAL_STYLE}}", visual_style)
    else:  # modify
        old_prompt = _get_old_prompt(shot, prompt_type, frame_type)
        prompt = template.replace("{{OLD_PROMPT}}", old_prompt or "（无原提示词）") \
                        .replace("{{MODIFICATION_TYPE}}", "custom") \
                        .replace("{{FEEDBACK}}", feedback)

    # 调用 LLM 生成新提示词
    from langchain_openai import ChatOpenAI

    llm = ChatOpenAI(
        model=settings.LLM_MODEL_DEFAULT,
        api_key=settings.OPENAI_API_KEY,
        base_url=settings.OPENAI_BASE_URL,
        temperature=0.7,
    )

    response = await llm.ainvoke([HumanMessage(content=prompt)])
    new_prompt = response.content.strip()

    # 确保所有模板变量都被替换（防止LLM输出中仍包含变量）
    new_prompt = new_prompt.replace("{{SHOT_NUMBER}}", str(shot.get("shot_number", ""))) \
                           .replace("{{SHOT_TITLE}}", shot.get("title", "") or f"分镜{shot.get('shot_number', '')}") \
                           .replace("{{SHOT_DESCRIPTION}}", shot.get("description", "") or "无") \
                           .replace("{{SHOT_NARRATION}}", shot.get("narration", "") or "无") \
                           .replace("{{SHOT_VIDEO_DURATION}}", str(shot.get("video_duration", "5"))) \
                           .replace("{{SCENE_TITLE}}", scene.get("title", "") if scene else "未指定") \
                           .replace("{{SCENE_LOCATION}}", scene.get("location", "") or "未指定") \
                           .replace("{{SCENE_TIME}}", scene.get("time_setting", "") or "未指定") \
                           .replace("{{SCENE_ATMOSPHERE}}", scene.get("atmosphere", "") or "未指定") \
                           .replace("{{PREVIOUS_SHOT_INFO}}", prev_shot_info if 'prev_shot_info' in locals() else "") \
                           .replace("{{KNOWLEDGE_CONTEXT}}", "") \
                           .replace("{{CHARACTER_PROFILES}}", character_profiles) \
                           .replace("{{VISUAL_STYLE}}", visual_style)

    # 保存到数据库
    success = await _save_shot_prompt(shot_id, new_prompt, prompt_type, frame_type)
    
    return {
        "success": success,
        "shot_id": shot_id,
        "prompt_type": prompt_type,
        "frame_type": frame_type,
        "operation_type": operation_type,
        "new_prompt": new_prompt[:100] + "..." if len(new_prompt) > 100 else new_prompt,
    }


@tool
async def submit_shot_video_regeneration(
    shot_id: int,
    creation_uuid: str,
    generation_mode: str = "first_last_frame",
) -> Dict[str, Any]:
    """
    提交分镜视频重新生成任务
    
    Args:
        shot_id: 分镜ID
        creation_uuid: 创作项目UUID
        generation_mode: 生成模式 (first_frame_only-只用首帧/first_last_frame-用首尾帧)
        
    Returns:
        提交结果
    """
    logger.info(f"[Submit Tool] 提交分镜视频重新生成: shot_id={shot_id}, mode={generation_mode}")
    
    # 先更新 generation_mode 到数据库
    from app.agent.tools.async_db import get_async_session
    from app.models.shot import Shot
    from sqlalchemy import select
    
    async with get_async_session() as db:
        stmt = select(Shot).where(Shot.shot_id == shot_id)
        result = await db.execute(stmt)
        shot = result.scalar_one_or_none()
        
        if shot:
            if shot.extra_data is None:
                shot.extra_data = {}
            shot.extra_data["generation_mode"] = generation_mode
            flag_modified(shot, "extra_data")
            await db.commit()
    
    # 提交视频生成任务
    result = await _execute_regeneration(
        target_type="shot_video",
        target_id=shot_id,
        creation_uuid=creation_uuid,
        save_version=True,
        mode=generation_mode,
    )
    
    return {
        "success": result.get("success", False),
        "shot_id": shot_id,
        "generation_mode": generation_mode,
        "task_id": result.get("task_id"),
        "error": result.get("error"),
    }


# ==================== 导出 ====================

REGENERATE_WORKER_TOOLS = [
    # 知识库查询
    retrieve_video_prompt_knowledge,
    # 查询类
    query_single_character,
    query_single_scene,
    query_single_shot,
    # 提交重新生成类
    submit_character_image_regeneration,
    submit_scene_image_regeneration,
    submit_shot_image_regeneration,
    submit_shot_video_regeneration,
]


# ==================== 资源生成工具（已合并） ====================

@tool
async def clear_asset(
    target_type: str,
    target_id: int,
    save_version: bool = True,
) -> Dict[str, Any]:
    """
    清空单个资源的图片/视频（原子操作）
    
    Args:
        target_type: 资源类型 (character | scene | shot_start | shot_end | shot_video)
        target_id: 资源 ID
        save_version: 是否保存历史版本到 status_detail
        
    Returns:
        操作结果
    """
    logger.info(f"[Regenerate Tool] 清空资源: type={target_type}, id={target_id}, save_version={save_version}")
    
    from app.agent.tools.async_db import get_async_session
    from app.models.character import Character
    from app.models.scene import Scene
    from app.models.shot import Shot
    from sqlalchemy import select
    
    async with get_async_session() as db:
        try:
            # 根据类型获取资源
            if target_type == "character":
                stmt = select(Character).where(Character.character_id == target_id)
                result = await db.execute(stmt)
                resource = result.scalar_one_or_none()
                if not resource:
                    return {"success": False, "error": f"角色不存在: {target_id}"}
                field_name = "image_url"
                old_value = resource.image_url
                resource.image_url = None
                resource.status = "pending"
                
            elif target_type == "scene":
                stmt = select(Scene).where(Scene.scene_id == target_id)
                result = await db.execute(stmt)
                resource = result.scalar_one_or_none()
                if not resource:
                    return {"success": False, "error": f"场景不存在: {target_id}"}
                field_name = "image_url"
                old_value = resource.image_url
                resource.image_url = None
                resource.status = "pending"
                
            elif target_type in ["shot_start", "shot_end"]:
                stmt = select(Shot).where(Shot.shot_id == target_id)
                result = await db.execute(stmt)
                resource = result.scalar_one_or_none()
                if not resource:
                    return {"success": False, "error": f"分镜不存在: {target_id}"}
                field_name = "image_url"
                old_value = resource.image_url
                resource.image_url = None
                resource.status = "pending"
                
            elif target_type == "shot_video":
                stmt = select(Shot).where(Shot.shot_id == target_id)
                result = await db.execute(stmt)
                resource = result.scalar_one_or_none()
                if not resource:
                    return {"success": False, "error": f"分镜不存在: {target_id}"}
                field_name = "video_url"
                old_value = resource.video_url
                resource.video_url = None
                resource.video_status = "pending"
                resource.status = "pending"
                
            else:
                return {"success": False, "error": f"不支持的资源类型: {target_type}"}
            
            # 保存版本
            if save_version:
                import json
                status_detail = resource.status_detail or {}
                # 如果 status_detail 是字符串，解析为字典
                if isinstance(status_detail, str):
                    try:
                        status_detail = json.loads(status_detail) if status_detail else {}
                    except json.JSONDecodeError:
                        status_detail = {}
                versions = status_detail.get("versions", []) if isinstance(status_detail, dict) else []
                version_record = {
                    "version": len(versions) + 1,
                    "created_at": datetime.now().isoformat(),
                    "field": field_name,
                    "value": old_value,
                    "trigger": "clear",
                }
                versions.append(version_record)
                status_detail["versions"] = versions
                resource.status_detail = status_detail
            
            await db.commit()
            
            return {
                "success": True,
                "target_type": target_type,
                "target_id": target_id,
                "field_cleared": field_name,
                "version_saved": save_version,
            }
            
        except Exception as e:
            logger.error(f"[Regenerate Tool] 清空资源失败: {e}")
            return {"success": False, "error": str(e)}


async def submit_generation(
    target_type: str,
    target_id: int,
    creation_uuid: str,
    mode: str = "auto",
    reference_image_url: Optional[str] = None,
) -> Dict[str, Any]:
    """
    提交生成任务（原子操作）
    
    Args:
        target_type: 资源类型 (character | scene | shot_start | shot_end | shot_video)
        target_id: 资源 ID
        creation_uuid: 创作项目 UUID
        mode: 生成模式 (txt2img | img2img | auto)
        reference_image_url: 参考图片 URL（img2img 模式需要）
        
    Returns:
        任务提交结果
    """
    logger.info(f"[Regenerate Tool] 提交生成任务: type={target_type}, id={target_id}, mode={mode}")
    logger.info(f"[Regenerate Tool] DEBUG: target_type={target_type}, 将决定 frame_type")
    
    from app.agent.tools.async_db import get_async_session
    from app.models.character import Character
    from app.models.scene import Scene
    from app.models.shot import Shot
    from sqlalchemy import select
    
    try:
        # 获取创建任务的函数
        from app.tasks.character_task import generate_character_image_task
        from app.tasks.step4_scene_image_gen_task import generate_single_scene_image_task
        from app.tasks.shot_task import generate_single_shot_image_task
        
        async with get_async_session() as db:
            if target_type == "character":
                # 获取 Character 的 creation_id 和 visual_style
                stmt = select(Character).where(Character.character_id == target_id)
                result = await db.execute(stmt)
                resource = result.scalar_one_or_none()
                if not resource:
                    return {"success": False, "error": f"角色不存在: {target_id}"}
                creation_id = resource.creation_id
                
                # 获取 creation 的 visual_style（从 extra_data 中获取）
                from app.models.creation import Creation
                creation_stmt = select(Creation).where(Creation.creation_id == creation_id)
                creation_result = await db.execute(creation_stmt)
                creation_obj = creation_result.scalar_one_or_none()
                if creation_obj and creation_obj.extra_data:
                    visual_style = creation_obj.extra_data.get("visual_style", "anime")
                else:
                    visual_style = "anime"
                
                logger.info(f"[Regenerate Tool] 调用 generate_character_image_task: character_ids=[{target_id}], creation_uuid={creation_uuid}")
                task = generate_character_image_task.delay(
                    character_ids=[target_id],  # 注意：是列表
                    visual_style=visual_style,
                    creation_uuid=creation_uuid,
                    force_regenerate=True,
                )
                
            elif target_type == "scene":
                # 获取 Scene 的 creation_id
                stmt = select(Scene).where(Scene.scene_id == target_id)
                result = await db.execute(stmt)
                resource = result.scalar_one_or_none()
                if not resource:
                    return {"success": False, "error": f"场景不存在: {target_id}"}
                creation_id = resource.creation_id
                logger.info(f"[Regenerate Tool] 调用 generate_single_scene_image_task: scene_id={target_id}, creation_id={creation_id}")
                task = generate_single_scene_image_task.delay(
                    scene_id=target_id,
                    creation_id=creation_id,
                )
                
            elif target_type == "shot_start":
                # 首帧
                stmt = select(Shot).where(Shot.shot_id == target_id)
                result = await db.execute(stmt)
                resource = result.scalar_one_or_none()
                if not resource:
                    return {"success": False, "error": f"分镜不存在: {target_id}"}
                
                # 获取 creation_id
                from app.models.creation import Creation
                creation_stmt = select(Creation).where(Creation.uuid == creation_uuid)
                creation_result = await db.execute(creation_stmt)
                creation_obj = creation_result.scalar_one_or_none()
                creation_id = creation_obj.creation_id if creation_obj else resource.creation_id
                
                logger.info(f"[Regenerate Tool] 调用 generate_single_shot_image_task: shot_id={target_id}, frame_type=start")
                task = generate_single_shot_image_task.delay(
                    shot_id=target_id,
                    creation_id=creation_id,
                    frame_type="start",
                )
                
            elif target_type == "shot_end":
                logger.info(f"[Regenerate Tool] 进入 shot_end 分支: target_id={target_id}")
                stmt = select(Shot).where(Shot.shot_id == target_id)
                result = await db.execute(stmt)
                resource = result.scalar_one_or_none()
                if not resource:
                    return {"success": False, "error": f"分镜不存在: {target_id}"}
                
                # 获取 creation_id
                from app.models.creation import Creation
                creation_stmt = select(Creation).where(Creation.uuid == creation_uuid)
                creation_result = await db.execute(creation_stmt)
                creation_obj = creation_result.scalar_one_or_none()
                creation_id = creation_obj.creation_id if creation_obj else resource.creation_id
                
                logger.info(f"[Regenerate Tool] 调用 generate_single_shot_image_task: shot_id={target_id}, frame_type=end")
                task = generate_single_shot_image_task.delay(
                    shot_id=target_id,
                    creation_id=creation_id,
                    frame_type="end",
                )
                
            elif target_type == "shot_image":
                # 同时生成首帧和尾帧
                stmt = select(Shot).where(Shot.shot_id == target_id)
                result = await db.execute(stmt)
                resource = result.scalar_one_or_none()
                if not resource:
                    return {"success": False, "error": f"分镜不存在: {target_id}"}
                
                # 获取 creation_id
                from app.models.creation import Creation
                creation_stmt = select(Creation).where(Creation.uuid == creation_uuid)
                creation_result = await db.execute(creation_stmt)
                creation_obj = creation_result.scalar_one_or_none()
                creation_id = creation_obj.creation_id if creation_obj else resource.creation_id
                
                logger.info(f"[Regenerate Tool] 调用 generate_single_shot_image_task: shot_id={target_id}, frame_type=both")
                task = generate_single_shot_image_task.delay(
                    shot_id=target_id,
                    creation_id=creation_id,
                    frame_type="both",
                )
                
            elif target_type == "shot_video":
                stmt = select(Shot).where(Shot.shot_id == target_id)
                result = await db.execute(stmt)
                resource = result.scalar_one_or_none()
                if not resource:
                    return {"success": False, "error": f"分镜不存在: {target_id}"}
                
                # 获取 extra_data 并更新 generation_mode
                extra_data = resource.extra_data or {}
                generation_mode = mode if mode in ["first_frame_only", "first_last_frame"] else "first_frame_only"
                extra_data["generation_mode"] = generation_mode
                resource.extra_data = extra_data

                # 标记修改
                flag_modified(resource, "extra_data")
                await db.commit()
                
                logger.info(f"[Regenerate Tool] 调用 agent_generate_single_shot_video_task: shot_id={target_id}, generation_mode={generation_mode}")
                
                from app.agent.tasks.video_tasks import agent_generate_single_shot_video_task
                task = agent_generate_single_shot_video_task.delay(
                    creation_uuid=creation_uuid,
                    shot_id=target_id,
                )
            else:
                return {"success": False, "error": f"不支持的资源类型: {target_type}"}
            
            return {
                "success": True,
                "target_type": target_type,
                "target_id": target_id,
                "task_id": task.id,
                "mode": mode,
            }
            
    except Exception as e:
        logger.error(f"[Regenerate Tool] 提交生成任务失败: {e}")
        return {"success": False, "error": str(e)}


async def update_resource_status(
    target_type: str,
    target_id: int,
    status: str,
    save_version: bool = True,
) -> Dict[str, Any]:
    """
    更新资源状态（重新生成时不清空历史，只修改状态）
    
    Args:
        target_type: 资源类型 (character | scene | shot_start | shot_end | shot_video)
        target_id: 资源 ID
        status: 新状态 (pending/generating/completed/failed)
        save_version: 是否保存当前版本到历史
        
    Returns:
        操作结果
    """
    logger.info(f"[Regenerate Tool] 更新状态: type={target_type}, id={target_id}, status={status}")
    
    from app.agent.tools.async_db import get_async_session
    from app.models.character import Character
    from app.models.scene import Scene
    from app.models.shot import Shot
    from sqlalchemy import select
    
    async with get_async_session() as db:
        try:
            # 根据类型获取资源
            if target_type == "character":
                stmt = select(Character).where(Character.character_id == target_id)
                result = await db.execute(stmt)
                resource = result.scalar_one_or_none()
                if not resource:
                    return {"success": False, "error": f"角色不存在: {target_id}"}
                old_status = resource.status
                resource.status = status
                
            elif target_type == "scene":
                stmt = select(Scene).where(Scene.scene_id == target_id)
                result = await db.execute(stmt)
                resource = result.scalar_one_or_none()
                if not resource:
                    return {"success": False, "error": f"场景不存在: {target_id}"}
                old_status = resource.status
                resource.status = status
                
            elif target_type in ["shot_start", "shot_end"]:
                stmt = select(Shot).where(Shot.shot_id == target_id)
                result = await db.execute(stmt)
                resource = result.scalar_one_or_none()
                if not resource:
                    return {"success": False, "error": f"分镜不存在: {target_id}"}
                old_status = resource.status
                resource.status = status
                
            elif target_type == "shot_video":
                stmt = select(Shot).where(Shot.shot_id == target_id)
                result = await db.execute(stmt)
                resource = result.scalar_one_or_none()
                if not resource:
                    return {"success": False, "error": f"分镜不存在: {target_id}"}
                old_status = resource.video_status
                resource.video_status = status
                
            else:
                return {"success": False, "error": f"不支持的资源类型: {target_type}"}
            
            
            await db.commit()
            
            return {
                "success": True,
                "target_type": target_type,
                "target_id": target_id,
                "old_status": old_status,
                "new_status": status,
                "version_saved": save_version,
            }
            
        except Exception as e:
            logger.error(f"[Regenerate Tool] 更新状态失败: {e}")
            return {"success": False, "error": str(e)}


async def _poll_task_status(task_id: str, max_wait: int = 300, poll_interval: int = 3) -> Dict[str, Any]:
    """
    轮询 Celery 任务状态
    
    Args:
        task_id: Celery 任务 ID
        max_wait: 最大等待时间（秒）
        poll_interval: 轮询间隔（秒）
        
    Returns:
        任务最终状态
    """
    from celery.result import AsyncResult
    from app.core.celery_app import celery_app
    
    elapsed = 0
    logger.info(f"[_poll_task_status] 开始轮询任务: {task_id}, max_wait={max_wait}s")
    
    while elapsed < max_wait:
        try:
            task = AsyncResult(task_id, app=celery_app)
            state = task.state
            
            if state == 'SUCCESS':
                result = task.result or {}
                logger.info(f"[_poll_task_status] 任务完成: {task_id}")
                return {
                    "status": "completed",
                    "task_id": task_id,
                    "result": result,
                }
            elif state == 'FAILURE':
                error_msg = str(task.info) if task.info else "Unknown error"
                logger.error(f"[_poll_task_status] 任务失败: {task_id}, error={error_msg}")
                return {
                    "status": "failed",
                    "task_id": task_id,
                    "error": error_msg,
                }
            else:
                logger.debug(f"[_poll_task_status] 任务 {task_id} 状态: {state}, 已等待 {elapsed}s")
                await asyncio.sleep(poll_interval)
                elapsed += poll_interval
                
        except Exception as e:
            logger.error(f"[_poll_task_status] 轮询任务状态失败: {e}")
            return {
                "status": "error",
                "task_id": task_id,
                "error": str(e),
            }
    
    logger.warning(f"[_poll_task_status] 达到最大等待时间: {task_id}")
    return {
        "status": "timeout",
        "task_id": task_id,
        "elapsed": elapsed,
        "error": "达到最大等待时间",
    }


async def _execute_regeneration(
    target_type: str,
    target_id: int,
    creation_uuid: str,
    save_version: bool = True,
    mode: str = "auto",
) -> Dict[str, Any]:
    """执行资源重新生成操作的核心函数"""
    logger.info(f"[Regenerate Tool] 重新生成: type={target_type}, id={target_id}")
    
    status_result = await update_resource_status(
        target_type=target_type,
        target_id=target_id,
        status="generating",
        save_version=save_version,
    )
    
    if not status_result.get("success"):
        return status_result
    
    submit_result = await submit_generation(
        target_type=target_type,
        target_id=target_id,
        creation_uuid=creation_uuid,
        mode=mode,
    )
    
    if not submit_result.get("success"):
        return submit_result
    
    return {
        "success": True,
        "target_type": target_type,
        "target_id": target_id,
        "task_id": submit_result.get("task_id"),
        "version_saved": save_version,
        "mode": mode,
    }


@tool
async def regenerate(
    target_type: str,
    target_id: int,
    creation_uuid: str,
    save_version: bool = True,
    mode: str = "auto",
) -> Dict[str, Any]:
    """
    重新生成资源（组合操作：更新状态为 generating + 提交生成任务）
    
    Args:
        target_type: 资源类型 (character | scene | shot_start | shot_end | shot_video | shot_image)
        target_id: 资源 ID
        creation_uuid: 创作项目 UUID
        save_version: 是否保存历史版本
        mode: 生成模式 (txt2img | img2img | auto)
        
    Returns:
        操作结果
    """
    return await _execute_regeneration(target_type, target_id, creation_uuid, save_version, mode)


@tool
async def regenerate_with_poll(
    target_type: str,
    target_id: int,
    creation_uuid: str,
    save_version: bool = True,
    mode: str = "auto",
    max_wait: int = 300,
) -> Dict[str, Any]:
    """
    重新生成资源并轮询等待完成（带状态轮询的完整版本）
    
    Args:
        target_type: 资源类型
        target_id: 资源 ID
        creation_uuid: 创作项目 UUID
        save_version: 是否保存历史版本
        mode: 生成模式
        max_wait: 最大等待时间（秒）
        
    Returns:
        包含任务执行结果的字典
    """
    logger.info(f"[Regenerate Tool] 重新生成并轮询: type={target_type}, id={target_id}")
    
    # Step 1: 执行重新生成（更新状态 + 提交任务）
    result = await _execute_regeneration(
        target_type=target_type,
        target_id=target_id,
        creation_uuid=creation_uuid,
        save_version=save_version,
        mode=mode,
    )
    
    if not result.get("success"):
        return result
    
    # Step 2: 轮询等待任务完成
    task_id = result.get("task_id")
    logger.info(f"[Regenerate Tool] 开始轮询任务: {task_id}")
    
    poll_result = await _poll_task_status(task_id, max_wait=max_wait)
    
    return {
        "success": poll_result.get("status") == "completed",
        "task_id": task_id,
        "poll_status": poll_result.get("status"),
        "poll_result": poll_result,
    }


@tool
async def clear_all(
    creation_uuid: str,
    target_types: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """
    清空创作项目下所有或指定类型资源
    
    Args:
        creation_uuid: 创作项目 UUID
        target_types: 要清空的资源类型列表，默认清空所有
        
    Returns:
        清空结果汇总
    """
    logger.info(f"[Regenerate Tool] 清空所有资源: creation_uuid={creation_uuid}, types={target_types}")
    
    from app.agent.tools.async_db import get_async_session
    from sqlalchemy import select
    from app.models.character import Character
    from app.models.scene import Scene
    from app.models.shot import Shot
    
    default_types = ["character", "scene", "shot_start", "shot_end", "shot_video"]
    target_types = target_types or default_types
    
    results = []
    
    async with get_async_session() as db:
        try:
            for target_type in target_types:
                if target_type == "character":
                    stmt = select(Character).where(Character.creation_uuid == creation_uuid)
                    result = await db.execute(stmt)
                    resources = result.scalars().all()
                    
                elif target_type == "scene":
                    stmt = select(Scene).where(Scene.creation_uuid == creation_uuid)
                    result = await db.execute(stmt)
                    resources = result.scalars().all()
                    
                elif target_type == "shot":
                    stmt = select(Shot).where(Shot.creation_uuid == creation_uuid)
                    result = await db.execute(stmt)
                    resources = result.scalars().all()
                    
                else:
                    results.append({
                        "type": target_type,
                        "success": False,
                        "error": f"不支持的资源类型: {target_type}",
                        "cleared_count": 0,
                    })
                    continue
                
                cleared_count = 0
                for resource in resources:
                    if target_type == "character":
                        resource.status = "pending"
                        resource.image_url = None
                        cleared_count += 1
                    elif target_type == "scene":
                        resource.status = "pending"
                        resource.image_url = None
                        cleared_count += 1
                    elif target_type == "shot":
                        resource.status = "pending"
                        resource.image_url = None
                        resource.video_url = None
                        resource.video_status = "pending"
                        cleared_count += 1
                
                results.append({
                    "type": target_type,
                    "success": True,
                    "cleared_count": cleared_count,
                })
            
            await db.commit()
            
            return {
                "success": all(r.get("success") for r in results),
                "results": results,
            }
            
        except Exception as e:
            logger.error(f"[Regenerate Tool] 清空所有资源失败: {e}")
            return {
                "success": False,
                "error": str(e),
                "results": results,
            }


@tool
async def query_generation_tasks_status(
    task_ids: List[str],
    target_info: Optional[List[Dict[str, Any]]] = None,
    timeout: int = 1000,
    poll_interval: float = 2.0,
) -> Dict[str, Any]:
    """
    查询生成任务状态，阻塞等待直到所有任务完成或超时
    
    用于在提交图片/视频生成任务后，轮询查询任务状态，直到所有任务都完成（成功或失败）
    
    Args:
        task_ids: Celery 任务 ID 列表
        target_info: 任务对应的资源信息列表（可选，用于返回结果时标识资源）
            每个元素包含: {"target_type": str, "target_id": int}
        timeout: 最大等待时间（秒），默认 1000 秒
        poll_interval: 轮询间隔（秒），默认 2 秒
        
    Returns:
        {
            "success": bool,  # 是否成功查询（不表示任务都成功）
            "all_completed": bool,  # 是否全部完成
            "timed_out": bool,  # 是否超时
            "tasks": [
                {
                    "task_id": str,
                    "target_type": str,  # character/scene/shot
                    "target_id": int,
                    "status": str,  # SUCCESS/FAILED/PENDING/PROGRESS/TIMEOUT
                    "result": dict,  # 任务结果（成功时）
                    "error": str,    # 错误信息（失败时）
                }
            ],
            "summary": {
                "total": int,
                "success": int,
                "failed": int,
                "pending": int,
            }
        }
    """
    from celery.result import AsyncResult
    from app.core.celery_app import celery_app
    
    logger.info(f"[Query Tasks Status] 开始查询 {len(task_ids)} 个任务状态, timeout={timeout}s")
    
    if not task_ids:
        return {
            "success": True,
            "all_completed": True,
            "timed_out": False,
            "tasks": [],
            "summary": {"total": 0, "success": 0, "failed": 0, "pending": 0},
        }
    
    # 初始化任务信息
    target_info = target_info or [{}] * len(task_ids)
    tasks_info = []
    for i, task_id in enumerate(task_ids):
        info = target_info[i] if i < len(target_info) else {}
        tasks_info.append({
            "task_id": task_id,
            "target_type": info.get("target_type", "unknown"),
            "target_id": info.get("target_id", 0),
            "status": "PENDING",
            "result": None,
            "error": None,
        })
    
    elapsed = 0
    all_completed = False
    
    while elapsed < timeout and not all_completed:
        all_completed = True
        pending_count = 0
        
        for task_info in tasks_info:
            if task_info["status"] in ["SUCCESS", "FAILED", "TIMEOUT"]:
                continue
            
            try:
                task = AsyncResult(task_info["task_id"], app=celery_app)
                state = task.state
                
                if state == 'SUCCESS':
                    task_info["status"] = "SUCCESS"
                    task_info["result"] = task.result
                    logger.info(f"[Query Tasks Status] 任务完成: {task_info['task_id']}")
                elif state == 'FAILURE':
                    task_info["status"] = "FAILED"
                    task_info["error"] = str(task.info) if task.info else "Unknown error"
                    logger.error(f"[Query Tasks Status] 任务失败: {task_info['task_id']}, error={task_info['error']}")
                elif state == 'PENDING':
                    task_info["status"] = "PENDING"
                    all_completed = False
                    pending_count += 1
                else:
                    # PROGRESS 或其他状态
                    task_info["status"] = state
                    all_completed = False
                    pending_count += 1
                    
            except Exception as e:
                logger.error(f"[Query Tasks Status] 查询任务状态失败: {task_info['task_id']}, error={e}")
                task_info["status"] = "ERROR"
                task_info["error"] = str(e)
        
        if not all_completed:
            success_count_current = sum(1 for t in tasks_info if t["status"] == "SUCCESS")
            failed_count_current = sum(1 for t in tasks_info if t["status"] in ["FAILED", "ERROR"])
            pending_count_current = sum(1 for t in tasks_info if t["status"] in ["PENDING", "PROGRESS"])
            
            logger.info(f"[Query Tasks Status] 进度: {success_count_current}成功/{failed_count_current}失败/{pending_count_current}进行中, 已等待 {elapsed}s/{timeout}s")
            await asyncio.sleep(poll_interval)
            elapsed += poll_interval
    
    # 检查是否超时
    timed_out = elapsed >= timeout and not all_completed
    
    if timed_out:
        logger.warning(f"[Query Tasks Status] 达到最大等待时间 {timeout}s, 还有任务未完成")
        for task_info in tasks_info:
            if task_info["status"] not in ["SUCCESS", "FAILED"]:
                task_info["status"] = "TIMEOUT"
                task_info["error"] = f"达到最大等待时间 {timeout}s"
    
    # 统计结果
    success_count = sum(1 for t in tasks_info if t["status"] == "SUCCESS")
    failed_count = sum(1 for t in tasks_info if t["status"] in ["FAILED", "ERROR", "TIMEOUT"])
    pending_count = sum(1 for t in tasks_info if t["status"] in ["PENDING", "PROGRESS"])
    
    logger.info(f"[Query Tasks Status] 查询结束: total={len(tasks_info)}, success={success_count}, failed={failed_count}, timed_out={timed_out}")
    
    return {
        "success": True,
        "all_completed": all_completed or timed_out,
        "timed_out": timed_out,
        "tasks": tasks_info,
        "summary": {
            "total": len(tasks_info),
            "success": success_count,
            "failed": failed_count,
            "pending": pending_count,
        }
    }


# ==================== 批量生成工具（AssetGenerationWorkerNode 专用） ====================

@tool
async def batch_submit_character_images(
    character_ids: List[int],
    creation_uuid: str,
) -> Dict[str, Any]:
    """
    批量提交角色图片生成任务
    
    一次性为多个角色提交图片生成任务，返回所有 task_id 列表
    
    Args:
        character_ids: 角色 ID 列表
        creation_uuid: 创作项目 UUID
        
    Returns:
        包含所有 task_id 的结果
    """
    logger.info(f"[Batch Tool] 批量提交角色图片生成: character_ids={character_ids}, creation_uuid={creation_uuid}")
    
    task_ids = []
    results = []
    
    for character_id in character_ids:
        try:
            result = await _execute_regeneration(
                target_type="character",
                target_id=character_id,
                creation_uuid=creation_uuid,
                save_version=True,
                mode="auto",
            )
            
            if result.get("success"):
                task_ids.append(result.get("task_id"))
                results.append({
                    "character_id": character_id,
                    "success": True,
                    "task_id": result.get("task_id"),
                })
            else:
                results.append({
                    "character_id": character_id,
                    "success": False,
                    "error": result.get("error"),
                })
        except Exception as e:
            logger.error(f"[Batch Tool] 提交角色 {character_id} 图片生成失败: {e}")
            results.append({
                "character_id": character_id,
                "success": False,
                "error": str(e),
            })
    
    return {
        "success": len(task_ids) > 0,
        "task_ids": task_ids,
        "results": results,
        "total": len(character_ids),
        "submitted": len(task_ids),
        "failed": len(character_ids) - len(task_ids),
    }


@tool
async def batch_submit_scene_images(
    scene_ids: List[int],
    creation_uuid: str,
) -> Dict[str, Any]:
    """
    批量提交场景图片生成任务
    
    一次性为多个场景提交图片生成任务，返回所有 task_id 列表
    
    Args:
        scene_ids: 场景 ID 列表
        creation_uuid: 创作项目 UUID
        
    Returns:
        包含所有 task_id 的结果
    """
    logger.info(f"[Batch Tool] 批量提交场景图片生成: scene_ids={scene_ids}, creation_uuid={creation_uuid}")
    
    task_ids = []
    results = []
    
    for scene_id in scene_ids:
        try:
            result = await _execute_regeneration(
                target_type="scene",
                target_id=scene_id,
                creation_uuid=creation_uuid,
                save_version=True,
            )
            
            if result.get("success"):
                task_ids.append(result.get("task_id"))
                results.append({
                    "scene_id": scene_id,
                    "success": True,
                    "task_id": result.get("task_id"),
                })
            else:
                results.append({
                    "scene_id": scene_id,
                    "success": False,
                    "error": result.get("error"),
                })
        except Exception as e:
            logger.error(f"[Batch Tool] 提交场景 {scene_id} 图片生成失败: {e}")
            results.append({
                "scene_id": scene_id,
                "success": False,
                "error": str(e),
            })
    
    return {
        "success": len(task_ids) > 0,
        "task_ids": task_ids,
        "results": results,
        "total": len(scene_ids),
        "submitted": len(task_ids),
        "failed": len(scene_ids) - len(task_ids),
    }


@tool
async def batch_save_character_prompts(
    prompts_data: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """
    批量保存角色提示词
    
    一次性保存多个角色的提示词
    
    Args:
        prompts_data: 提示词数据列表，每个元素包含：
            - character_id: 角色 ID
            - prompt: 提示词内容
            
    Returns:
        保存结果汇总
    """
    logger.info(f"[Batch Tool] 批量保存角色提示词: count={len(prompts_data)}")
    
    from app.agent.tools.async_db import get_async_session
    from app.models.character import Character
    from sqlalchemy import select
    
    results = []
    
    async with get_async_session() as db:
        for item in prompts_data:
            character_id = item.get("character_id")
            prompt = item.get("prompt")
            
            try:
                stmt = select(Character).where(Character.character_id == character_id)
                result = await db.execute(stmt)
                character = result.scalar_one_or_none()
                
                if not character:
                    results.append({
                        "character_id": character_id,
                        "success": False,
                        "error": "角色不存在",
                    })
                    continue
                
                character.image_prompt = prompt
                character.updated_at = datetime.now()
                
                results.append({
                    "character_id": character_id,
                    "success": True,
                })
            except Exception as e:
                logger.error(f"[Batch Tool] 保存角色 {character_id} 提示词失败: {e}")
                results.append({
                    "character_id": character_id,
                    "success": False,
                    "error": str(e),
                })
        
        await db.commit()
    
    success_count = sum(1 for r in results if r.get("success"))
    
    return {
        "success": success_count > 0,
        "results": results,
        "total": len(prompts_data),
        "saved": success_count,
        "failed": len(prompts_data) - success_count,
    }


@tool
async def batch_save_shot_image_prompts(
    prompts_data: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """
    批量保存分镜图片提示词
    
    一次性保存多个分镜的图片提示词
    
    Args:
        prompts_data: 提示词数据列表，每个元素包含：
            - shot_id: 分镜 ID
            - prompt: 图片提示词内容
            - frame_type: 帧类型 ("start", "end", "both")，默认为 "start"
            
    Returns:
        保存结果汇总
    """
    logger.info(f"[Batch Tool] 批量保存分镜图片提示词: count={len(prompts_data)}")
    
    results = []
    saved_count = 0
    
    for item in prompts_data:
        shot_id = item.get("shot_id")
        prompt = item.get("prompt")
        frame_type = item.get("frame_type", "start")
        
        try:
            success = await _save_shot_prompt(
                shot_id=shot_id,
                new_prompt=prompt,
                prompt_type="image",
                frame_type=frame_type,
            )
            
            if success:
                saved_count += 1
                results.append({
                    "shot_id": shot_id,
                    "success": True,
                    "frame_type": frame_type,
                })
            else:
                results.append({
                    "shot_id": shot_id,
                    "success": False,
                    "error": "保存失败",
                    "frame_type": frame_type,
                })
        except Exception as e:
            logger.error(f"[Batch Tool] 保存分镜 {shot_id} 图片提示词失败: {e}")
            results.append({
                "shot_id": shot_id,
                "success": False,
                "error": str(e),
                "frame_type": frame_type,
            })
    
    return {
        "success": saved_count > 0,
        "results": results,
        "total": len(prompts_data),
        "saved": saved_count,
        "failed": len(prompts_data) - saved_count,
    }


@tool
async def batch_save_shot_video_prompts(
    prompts_data: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """
    批量保存分镜视频提示词
    
    一次性保存多个分镜的视频提示词
    
    Args:
        prompts_data: 提示词数据列表，每个元素包含：
            - shot_id: 分镜 ID
            - prompt: 视频提示词内容
            
    Returns:
        保存结果汇总
    """
    logger.info(f"[Batch Tool] 批量保存分镜视频提示词: count={len(prompts_data)}")
    
    results = []
    saved_count = 0
    
    for item in prompts_data:
        shot_id = item.get("shot_id")
        prompt = item.get("prompt")
        
        try:
            success = await _save_shot_prompt(
                shot_id=shot_id,
                new_prompt=prompt,
                prompt_type="video",
                frame_type="start",
            )
            
            if success:
                saved_count += 1
                results.append({
                    "shot_id": shot_id,
                    "success": True,
                })
            else:
                results.append({
                    "shot_id": shot_id,
                    "success": False,
                    "error": "保存失败",
                })
        except Exception as e:
            logger.error(f"[Batch Tool] 保存分镜 {shot_id} 视频提示词失败: {e}")
            results.append({
                "shot_id": shot_id,
                "success": False,
                "error": str(e),
            })
    
    return {
        "success": saved_count > 0,
        "results": results,
        "total": len(prompts_data),
        "saved": saved_count,
        "failed": len(prompts_data) - saved_count,
    }


@tool
async def batch_submit_shot_images(
    shot_ids: List[int],
    creation_uuid: str,
) -> Dict[str, Any]:
    """
    批量提交分镜图片生成任务
    
    一次性为多个分镜提交图片生成任务，返回所有 task_id 列表
    
    Args:
        shot_ids: 分镜 ID 列表
        creation_uuid: 创作项目 UUID
        
    Returns:
        包含所有 task_id 的结果
    """
    logger.info(f"[Batch Tool] 批量提交分镜图片生成: shot_ids={shot_ids}, creation_uuid={creation_uuid}")
    
    task_ids = []
    results = []
    
    for shot_id in shot_ids:
        try:
            result = await _execute_regeneration(
                target_type="shot",
                target_id=shot_id,
                creation_uuid=creation_uuid,
                save_version=True,
                mode="auto",
            )
            
            if result.get("success"):
                task_ids.append(result.get("task_id"))
                results.append({
                    "shot_id": shot_id,
                    "success": True,
                    "task_id": result.get("task_id"),
                })
            else:
                results.append({
                    "shot_id": shot_id,
                    "success": False,
                    "error": result.get("error"),
                })
        except Exception as e:
            logger.error(f"[Batch Tool] 提交分镜 {shot_id} 图片生成失败: {e}")
            results.append({
                "shot_id": shot_id,
                "success": False,
                "error": str(e),
            })
    
    return {
        "success": len(task_ids) > 0,
        "task_ids": task_ids,
        "results": results,
        "total": len(shot_ids),
        "submitted": len(task_ids),
        "failed": len(shot_ids) - len(task_ids),
    }


@tool
async def batch_submit_shot_videos(
    shot_ids: List[int],
    creation_uuid: str,
) -> Dict[str, Any]:
    """
    批量提交分镜视频生成任务
    
    一次性为多个分镜提交视频生成任务，返回所有 task_id 列表
    
    Args:
        shot_ids: 分镜 ID 列表
        creation_uuid: 创作项目 UUID
        
    Returns:
        包含所有 task_id 的结果
    """
    logger.info(f"[Batch Tool] 批量提交分镜视频生成: shot_ids={shot_ids}, creation_uuid={creation_uuid}")
    
    task_ids = []
    results = []
    
    for shot_id in shot_ids:
        try:
            result = await _execute_regeneration(
                target_type="shot_video",
                target_id=shot_id,
                creation_uuid=creation_uuid,
                save_version=True,
                mode="auto",
            )
            
            if result.get("success"):
                task_ids.append(result.get("task_id"))
                results.append({
                    "shot_id": shot_id,
                    "success": True,
                    "task_id": result.get("task_id"),
                })
            else:
                results.append({
                    "shot_id": shot_id,
                    "success": False,
                    "error": result.get("error"),
                })
        except Exception as e:
            logger.error(f"[Batch Tool] 提交分镜 {shot_id} 视频生成失败: {e}")
            results.append({
                "shot_id": shot_id,
                "success": False,
                "error": str(e),
            })
    
    return {
        "success": len(task_ids) > 0,
        "task_ids": task_ids,
        "results": results,
        "total": len(shot_ids),
        "submitted": len(task_ids),
        "failed": len(shot_ids) - len(task_ids),
    }


@tool
async def batch_save_scene_prompts(
    prompts_data: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """
    批量保存场景提示词
    
    一次性保存多个场景的提示词
    
    Args:
        prompts_data: 提示词数据列表，每个元素包含：
            - scene_id: 场景 ID
            - prompt: 提示词内容
            
    Returns:
        保存结果汇总
    """
    logger.info(f"[Batch Tool] 批量保存场景提示词: count={len(prompts_data)}")
    
    from app.agent.tools.async_db import get_async_session
    from app.models.scene import Scene
    from sqlalchemy import select
    
    results = []
    
    async with get_async_session() as db:
        for item in prompts_data:
            scene_id = item.get("scene_id")
            prompt = item.get("prompt")
            
            try:
                stmt = select(Scene).where(Scene.scene_id == scene_id)
                result = await db.execute(stmt)
                scene = result.scalar_one_or_none()
                
                if not scene:
                    results.append({
                        "scene_id": scene_id,
                        "success": False,
                        "error": "场景不存在",
                    })
                    continue
                
                # 保存到 extra_data
                extra_data = scene.extra_data or {}
                extra_data["image_prompt"] = prompt
                scene.extra_data = extra_data
                scene.updated_at = datetime.now()
                flag_modified(scene, "extra_data")
                
                results.append({
                    "scene_id": scene_id,
                    "success": True,
                })
            except Exception as e:
                logger.error(f"[Batch Tool] 保存场景 {scene_id} 提示词失败: {e}")
                results.append({
                    "scene_id": scene_id,
                    "success": False,
                    "error": str(e),
                })
        
        await db.commit()
    
    success_count = sum(1 for r in results if r.get("success"))
    
    return {
        "success": success_count > 0,
        "results": results,
        "total": len(prompts_data),
        "saved": success_count,
        "failed": len(prompts_data) - success_count,
    }