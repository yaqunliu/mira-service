"""
Regenerate Worker Tools - 资产重新生成 Worker 专用工具

提供原子化的查询和提交工具，供 AssetRegeneratorWorkerNode 使用。
所有提示词生成均使用模板文件，不硬编码在代码中。
"""

import asyncio
from typing import Dict, Any, List, Optional
from datetime import datetime

from langchain_core.tools import tool
from langchain_core.messages import HumanMessage
from pydantic import BaseModel, Field
from sqlalchemy.orm.attributes import flag_modified

from app.core.logger import logger
from app.core.config import settings


# ==================== 辅助函数 ====================

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
        
        if prompt_type == "video":
            shot.extra_data["video_prompt"] = new_prompt
        elif frame_type == "end":
            shot.extra_data["end_frame_prompt"] = new_prompt
        else:
            shot.image_prompt = new_prompt
        
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


# ==================== 知识库查询 ====================

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
    logger.info(f"[Knowledge Retrieval] 检索视频提示词知识: {shot_description[:50]}...")
    
    from app.agent.tools.knowledge_tools import query_knowledge_base
    
    try:
        # 查询多个相关知识库
        results = await asyncio.gather(
            query_knowledge_base.ainvoke({
                "query": shot_description,
                "knowledge_type": "camera_angles",
                "top_k": top_k,
            }),
            query_knowledge_base.ainvoke({
                "query": shot_description,
                "knowledge_type": "storyboard_techniques",
                "top_k": top_k,
            }),
            query_knowledge_base.ainvoke({
                "query": shot_description,
                "knowledge_type": "composition_rules",
                "top_k": top_k,
            }),
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
        
        # 按相关度排序
        all_knowledge.sort(key=lambda x: x["score"], reverse=True)
        
        return {
            "status": "success",
            "shot_description": shot_description,
            "knowledge_count": len(all_knowledge),
            "knowledge": all_knowledge[:top_k * 3],
        }
        
    except Exception as e:
        logger.error(f"[Knowledge Retrieval] 检索知识库失败: {e}")
        return {
            "status": "error",
            "error": str(e),
            "knowledge": [],
        }


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
                "extra_data": character.extra_data,
                "created_at": character.created_at.isoformat() if character.created_at else None,
                "updated_at": character.updated_at.isoformat() if character.updated_at else None,
            }
        }


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
                "image_url": scene.image_url,
                "status": scene.status,
                "status_detail": scene.status_detail,
                "extra_data": scene.extra_data,
                "created_at": scene.created_at.isoformat() if scene.created_at else None,
                "updated_at": scene.updated_at.isoformat() if scene.updated_at else None,
            }
        }


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
    
    from app.agent.tools.async_db import get_async_session
    from app.models.shot import Shot
    from app.models.scene import Scene
    from sqlalchemy import select
    from sqlalchemy.orm import selectinload
    
    async with get_async_session() as db:
        # 查询当前分镜，同时加载场景关系
        stmt = (
            select(Shot)
            .where(Shot.shot_id == shot_id)
            .options(selectinload(Shot.scene))
        )
        result = await db.execute(stmt)
        shot = result.scalar_one_or_none()
        
        if not shot:
            return {
                "success": False,
                "error": f"分镜不存在: {shot_id}",
            }
        
        # 构建当前分镜数据
        shot_data = {
            "shot_id": shot.shot_id,
            "shot_number": shot.shot_number,
            "title": shot.title,
            "description": shot.description,
            "narration": shot.narration,
            "image_prompt": shot.image_prompt,
            "image_url": shot.image_url,
            "audio_url": shot.audio_url,
            "video_url": shot.video_url,
            "video_status": shot.video_status,
            "video_duration": shot.video_duration,
            "status": shot.status,
            "status_detail": shot.status_detail,
            "extra_data": shot.extra_data or {},
            "scene_id": shot.scene_id,
            "creation_id": shot.creation_id,
            "created_at": shot.created_at.isoformat() if shot.created_at else None,
            "updated_at": shot.updated_at.isoformat() if shot.updated_at else None,
        }
        
        # 构建场景数据
        scene_data = None
        if shot.scene:
            scene = shot.scene
            scene_data = {
                "scene_id": scene.scene_id,
                "title": scene.title,
                "duration": scene.duration,
                "time_setting": scene.time_setting,
                "location": scene.location,
                "space_type": scene.space_type,
                "atmosphere": scene.atmosphere,
                "image_url": scene.image_url,
                "status": scene.status,
                "extra_data": scene.extra_data,
            }
        
        # 查询上一个分镜（用于连贯性处理）
        previous_shot_data = None
        if shot.shot_number and shot.shot_number > 1:
            # 获取同一 creation 下的所有场景
            from app.models.creation import Creation
            creation_stmt = select(Creation).where(Creation.creation_id == shot.creation_id)
            creation_result = await db.execute(creation_stmt)
            creation = creation_result.scalar_one_or_none()
            
            if creation:
                # 获取该 creation 下的所有场景 ID
                scene_stmt = select(Scene.scene_id).where(Scene.creation_id == creation.creation_id)
                scene_result = await db.execute(scene_stmt)
                scene_ids = [s[0] for s in scene_result.fetchall()]
                
                if scene_ids:
                    # 查询上一个分镜（shot_number - 1）
                    prev_stmt = (
                        select(Shot)
                        .where(
                            Shot.scene_id.in_(scene_ids),
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
                            "narration": prev_shot.narration,
                            "image_url": prev_shot.image_url,
                            "video_url": prev_shot.video_url,
                            "extra_data": prev_shot.extra_data or {},
                        }
        
        return {
            "success": True,
            "shot": shot_data,
            "scene": scene_data,
            "previous_shot": previous_shot_data,
        }


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
    
    from app.agent.tools.regenerate_tools import regenerate
    
    result = await regenerate.ainvoke({
        "target_type": "character",
        "target_id": character_id,
        "creation_uuid": creation_uuid,
        "save_version": True,
        "mode": mode,
    })
    
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
    char_result = await query_single_character.ainvoke({"character_id": character_id})
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
    
    from app.agent.tools.regenerate_tools import regenerate
    
    result = await regenerate.ainvoke({
        "target_type": "scene",
        "target_id": scene_id,
        "creation_uuid": creation_uuid,
        "save_version": True,
        "mode": "auto",
    })
    
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
    scene_result = await query_single_scene.ainvoke({"scene_id": scene_id})
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
    
    from app.agent.tools.regenerate_tools import regenerate
    
    results = []
    
    if frame_type in ["start", "both"]:
        result = await regenerate.ainvoke({
            "target_type": "shot_start",
            "target_id": shot_id,
            "creation_uuid": creation_uuid,
            "save_version": True,
            "mode": "auto",
        })
        results.append({"frame": "start", "result": result})
    
    if frame_type in ["end", "both"]:
        result = await regenerate.ainvoke({
            "target_type": "shot_end",
            "target_id": shot_id,
            "creation_uuid": creation_uuid,
            "save_version": True,
            "mode": "auto",
        })
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
    
    使用模板文件生成提示词，支持知识库查询（仅视频提示词）。
    
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
    shot_result = await query_single_shot.ainvoke({"shot_id": shot_id})
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
        from app.agent.tools.db_tools import query_characters
        char_result = await query_characters.ainvoke({
            "creation_uuid": creation_uuid,
            "include_images": False,
        })
        characters = char_result.get("characters", [])
        if characters:
            char_lines = []
            for char in characters:
                char_name = char.get("name", "未命名")
                char_basic = char.get("basic_info", "")
                char_appearance = char.get("appearance", "")
                char_lines.append(f"- {char_name}: {char_basic or '无基本信息'}，{char_appearance or '无外貌描述'}")
            character_profiles = "\n".join(char_lines)
        else:
            character_profiles = "无角色信息"
    except Exception as e:
        logger.warning(f"[Submit Tool] 获取角色信息失败: {e}")
        character_profiles = "无角色信息"

    # 如果是视频提示词，检索知识库
    knowledge_context = ""
    if prompt_type == "video" and operation_type == "regenerate":
        knowledge_result = await retrieve_video_prompt_knowledge(
            shot_description=shot.get("description", ""),
            top_k=3,
        )

        if knowledge_result.get("status") == "success":
            knowledge_items = knowledge_result.get("knowledge", [])
            if knowledge_items:
                knowledge_context = "\n\n## 参考知识\n"
                for i, item in enumerate(knowledge_items, 1):
                    knowledge_context += f"{i}. [{item['type']}] {item['content']}\n"

    # 读取提示词模板
    if operation_type == "regenerate":
        if prompt_type == "video":
            template = read_prompt_template("regenerate_video.md")
        else:
            template = read_prompt_template(f"regenerate_shot_{frame_type}.md")
    else:
        template = read_prompt_template("modify_prompt.md")

    # 填充模板变量
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
                        .replace("{{SCENE_TITLE}}", scene.get("title", "") if scene else "未指定") \
                        .replace("{{SCENE_LOCATION}}", scene.get("location", "") or "未指定") \
                        .replace("{{SCENE_TIME}}", scene.get("time_setting", "") or "未指定") \
                        .replace("{{SCENE_ATMOSPHERE}}", scene.get("atmosphere", "") or "未指定") \
                        .replace("{{PREVIOUS_SHOT_INFO}}", prev_shot_info) \
                        .replace("{{KNOWLEDGE_CONTEXT}}", knowledge_context) \
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
                           .replace("{{SCENE_TITLE}}", scene.get("title", "") if scene else "未指定") \
                           .replace("{{SCENE_LOCATION}}", scene.get("location", "") or "未指定") \
                           .replace("{{SCENE_TIME}}", scene.get("time_setting", "") or "未指定") \
                           .replace("{{SCENE_ATMOSPHERE}}", scene.get("atmosphere", "") or "未指定") \
                           .replace("{{PREVIOUS_SHOT_INFO}}", prev_shot_info if 'prev_shot_info' in locals() else "") \
                           .replace("{{KNOWLEDGE_CONTEXT}}", knowledge_context) \
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
        "knowledge_used": bool(knowledge_context),
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
    
    from app.agent.tools.regenerate_tools import regenerate
    
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
    result = await regenerate.ainvoke({
        "target_type": "shot_video",
        "target_id": shot_id,
        "creation_uuid": creation_uuid,
        "save_version": True,
        "mode": generation_mode,
    })
    
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
    submit_character_prompt_regeneration,
    submit_scene_image_regeneration,
    submit_scene_prompt_regeneration,
    submit_shot_image_regeneration,
    submit_shot_prompt_regeneration,
    submit_shot_video_regeneration,
]