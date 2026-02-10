"""
Video Prompt Builder Tools - 视频提示词构建工具

提供分镜连续性分析和视频提示词保存功能，供 VideoPromptBuilderNode 使用。
"""

import json
from typing import Dict, Any, List, Optional

from langchain_core.tools import tool
from sqlalchemy.orm.attributes import flag_modified

from app.core.logger import logger


# ==================== 连续性分析工具 ====================

@tool
async def analyze_shot_continuity(
    creation_uuid: str,
    current_shot_number: int,
    previous_shot_number: int,
) -> Dict[str, Any]:
    """
    分析两个相邻分镜之间的连续性，判断是否应该使用视频延长模式。

    通过比较场景、角色重叠等维度，给出延长(extend)或新生成(new)的推荐。
    LLM 可以根据分镜描述内容覆盖此推荐。

    Args:
        creation_uuid: 创作项目 UUID
        current_shot_number: 当前分镜编号
        previous_shot_number: 前一个分镜编号

    Returns:
        {
            "success": True,
            "same_scene": bool,
            "scene_current": "场景标题",
            "scene_previous": "场景标题",
            "shared_characters": ["角色名"],
            "characters_only_current": ["角色名"],
            "characters_only_previous": ["角色名"],
            "character_overlap_ratio": float,
            "previous_shot_description": "前一分镜描述",
            "current_shot_description": "当前分镜描述",
            "recommended_mode": "extend" | "new",
            "reasoning": "推荐理由"
        }
    """
    logger.info(f"[VideoPromptBuilder] 分析连续性: shot {previous_shot_number} -> {current_shot_number}")

    from app.agent.tools.async_db import get_async_session
    from app.models.shot import Shot
    from app.models.scene import Scene
    from app.models.character import Character
    from app.models.creation import Creation
    from sqlalchemy import select
    from sqlalchemy.orm import selectinload

    try:
        async with get_async_session() as db:
            # 获取 creation
            creation_stmt = select(Creation).where(Creation.uuid == creation_uuid)
            creation_result = await db.execute(creation_stmt)
            creation = creation_result.scalar_one_or_none()
            if not creation:
                return {"success": False, "error": f"创作不存在: {creation_uuid}"}

            # 获取两个分镜（含角色和场景关联）
            shots_stmt = (
                select(Shot)
                .join(Scene)
                .where(Scene.creation_id == creation.creation_id)
                .where(Shot.shot_number.in_([current_shot_number, previous_shot_number]))
                .options(selectinload(Shot.characters), selectinload(Shot.scene))
            )
            shots_result = await db.execute(shots_stmt)
            shots = {s.shot_number: s for s in shots_result.scalars().all()}

            current_shot = shots.get(current_shot_number)
            previous_shot = shots.get(previous_shot_number)

            if not current_shot:
                return {"success": False, "error": f"分镜 {current_shot_number} 不存在"}
            if not previous_shot:
                return {"success": False, "error": f"分镜 {previous_shot_number} 不存在"}

            # 场景比较
            same_scene = current_shot.scene_id == previous_shot.scene_id
            scene_current = current_shot.scene.title if current_shot.scene else "未知"
            scene_previous = previous_shot.scene.title if previous_shot.scene else "未知"

            # 角色比较
            chars_current = {c.character_id: c.name for c in current_shot.characters}
            chars_previous = {c.character_id: c.name for c in previous_shot.characters}

            current_ids = set(chars_current.keys())
            previous_ids = set(chars_previous.keys())
            shared_ids = current_ids & previous_ids
            union_ids = current_ids | previous_ids

            shared_characters = [chars_current[cid] for cid in shared_ids]
            characters_only_current = [chars_current[cid] for cid in current_ids - shared_ids]
            characters_only_previous = [chars_previous[cid] for cid in previous_ids - shared_ids]

            overlap_ratio = len(shared_ids) / len(union_ids) if union_ids else 0.0

            # 启发式推荐
            if same_scene and overlap_ratio >= 0.5:
                recommended_mode = "extend"
                reasoning = f"同一场景（{scene_current}），角色重叠率 {overlap_ratio:.0%}，建议视频延长"
            elif same_scene and overlap_ratio > 0:
                recommended_mode = "extend"
                reasoning = f"同一场景（{scene_current}），有部分角色重叠（{', '.join(shared_characters)}），可以考虑延长"
            else:
                recommended_mode = "new"
                if not same_scene:
                    reasoning = f"场景变化（{scene_previous} → {scene_current}），建议新视频"
                else:
                    reasoning = f"虽同场景但无角色重叠，建议新视频"

            return {
                "success": True,
                "same_scene": same_scene,
                "scene_current": scene_current,
                "scene_previous": scene_previous,
                "shared_characters": shared_characters,
                "characters_only_current": characters_only_current,
                "characters_only_previous": characters_only_previous,
                "character_overlap_ratio": round(overlap_ratio, 2),
                "previous_shot_description": previous_shot.description or "",
                "current_shot_description": current_shot.description or "",
                "previous_shot_id": previous_shot.shot_id,
                "current_shot_id": current_shot.shot_id,
                "recommended_mode": recommended_mode,
                "reasoning": reasoning,
            }

    except Exception as e:
        logger.error(f"[VideoPromptBuilder] 连续性分析失败: {e}")
        return {"success": False, "error": str(e)}


# ==================== 保存视频提示词工具 ====================

@tool
async def save_video_prompt_result(
    shot_id: int,
    prompt: str,
    prompt_params: Dict[str, Any],
    references: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """
    保存视频提示词和参数到分镜的 extra_data。

    Args:
        shot_id: 分镜 ID
        prompt: 带@引用的视频提示词
        prompt_params: 提示词参数，例如 {"generation_mode": "extend", "extend_from_shot_id": 23, "duration": 10}
        references: 资产引用列表，例如：
            [
                {"type": "character", "target_id": 24, "name": "张磊"},
                {"type": "scene", "target_id": 5, "name": "星夜街道"},
                {"type": "shot", "target_id": 23, "name": "分镜3"}
            ]
            - type: "character"（角色图）| "scene"（场景图）| "shot"（分镜视频）
            - target_id: 对应资源的数据库 ID
            - name: 资源名称

    Returns:
        {"success": True, "shot_id": int, "message": "保存成功"}
    """
    logger.info(f"[VideoPromptBuilder] 保存视频提示词: shot_id={shot_id}, refs={len(references)}")

    if not prompt or not prompt.strip():
        return {"success": False, "error": "prompt 不能为空"}

    from app.agent.tools.async_db import get_async_session
    from app.models.shot import Shot
    from sqlalchemy import select

    try:
        async with get_async_session() as db:
            shot_stmt = select(Shot).where(Shot.shot_id == shot_id)
            shot_result = await db.execute(shot_stmt)
            shot = shot_result.scalar_one_or_none()
            if not shot:
                return {"success": False, "error": f"分镜不存在: shot_id={shot_id}"}

            if not shot.extra_data:
                shot.extra_data = {}

            shot.extra_data["video_prompt"] = prompt
            shot.extra_data["prompt_params"] = prompt_params
            shot.extra_data["references"] = references

            flag_modified(shot, "extra_data")
            await db.flush()

            logger.info(f"[VideoPromptBuilder] 保存成功: shot_id={shot_id}, refs={len(references)}")

            return {
                "success": True,
                "shot_id": shot_id,
                "references_count": len(references),
                "message": f"视频提示词保存成功（{len(references)}个资产引用）",
            }

    except Exception as e:
        logger.error(f"[VideoPromptBuilder] 保存失败: {e}")
        return {"success": False, "error": str(e)}
