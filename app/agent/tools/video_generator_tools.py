"""
Video Generator Tools - 视频生成提交工具

提供视频生成任务的提交功能，供 VideoGeneratorNode 使用。
从 shot.extra_data 中读取 video_prompt 和 references，调用视频生成 API。
当前暂用 DEBUG_GENERATE_VIDEO_URL，后续替换为 Seedance 2.0 API。
"""

from typing import Dict, Any, List
from datetime import datetime

from langchain_core.tools import tool
from sqlalchemy.orm.attributes import flag_modified

from app.core.logger import logger


@tool
async def submit_video_generation(
    shot_id: int,
    creation_uuid: str,
) -> Dict[str, Any]:
    """
    为指定分镜提交视频生成任务。

    从 shot.extra_data 中读取 video_prompt、prompt_params、references，
    解析资源引用获取实际 URL，调用视频生成 API。

    Args:
        shot_id: 分镜 ID
        creation_uuid: 创作项目 UUID

    Returns:
        {
            "success": True,
            "shot_id": int,
            "video_url": str,
            "message": "视频生成成功"
        }
    """
    logger.info(f"[VideoGenerator] 提交视频生成: shot_id={shot_id}")

    from app.agent.tools.async_db import get_async_session
    from app.models.shot import Shot
    from app.models.scene import Scene
    from app.models.character import Character
    from app.models.creation import Creation
    from app.core.config import settings
    from sqlalchemy import select
    from sqlalchemy.orm import selectinload

    try:
        async with get_async_session() as db:
            # 获取分镜（含场景关联）
            shot_stmt = (
                select(Shot)
                .join(Scene)
                .join(Creation)
                .where(Shot.shot_id == shot_id, Creation.uuid == creation_uuid)
            )
            shot_result = await db.execute(shot_stmt)
            shot = shot_result.scalar_one_or_none()
            if not shot:
                return {"success": False, "error": f"分镜不存在: shot_id={shot_id}"}

            extra_data = shot.extra_data or {}
            video_prompt = extra_data.get("video_prompt")
            if not video_prompt:
                return {"success": False, "error": f"分镜 {shot_id} 没有视频提示词，请先构建提示词"}

            prompt_params = extra_data.get("prompt_params", {})
            references = extra_data.get("references", [])

            # 解析 references 获取实际资源 URL
            resolved_refs = []
            for ref in references:
                ref_type = ref.get("type")
                target_id = ref.get("target_id")
                ref_name = ref.get("name", "")

                if ref_type == "character":
                    char_stmt = select(Character).where(Character.character_id == target_id)
                    char_result = await db.execute(char_stmt)
                    char = char_result.scalar_one_or_none()
                    resolved_refs.append({
                        "type": "character",
                        "name": ref_name,
                        "target_id": target_id,
                        "url": char.image_url if char else "",
                    })

                elif ref_type == "scene":
                    scene_stmt = select(Scene).where(Scene.scene_id == target_id)
                    scene_result = await db.execute(scene_stmt)
                    scene = scene_result.scalar_one_or_none()
                    resolved_refs.append({
                        "type": "scene",
                        "name": ref_name,
                        "target_id": target_id,
                        "url": scene.image_url if scene else "",
                    })

                elif ref_type == "shot":
                    ref_shot_stmt = select(Shot).where(Shot.shot_id == target_id)
                    ref_shot_result = await db.execute(ref_shot_stmt)
                    ref_shot = ref_shot_result.scalar_one_or_none()
                    resolved_refs.append({
                        "type": "shot",
                        "name": ref_name,
                        "target_id": target_id,
                        "url": ref_shot.video_url if ref_shot else "",
                    })

            logger.info(f"[VideoGenerator] 解析引用完成: {len(resolved_refs)} 个资源")
            logger.info(f"[VideoGenerator] ====== VIDEO PROMPT ======")
            logger.info(f"[VideoGenerator] {video_prompt}")
            logger.info(f"[VideoGenerator] ====== PROMPT PARAMS ======")
            logger.info(f"[VideoGenerator] {prompt_params}")
            logger.info(f"[VideoGenerator] ====== REFERENCES ======")
            logger.info(f"[VideoGenerator] {resolved_refs}")

            # TODO: 替换为真实的 Seedance 2.0 API 调用
            # 当前使用 DEBUG_GENERATE_VIDEO_URL 作为占位
            video_url = settings.DEBUG_GENERATE_VIDEO_URL
            logger.info(f"[VideoGenerator] 使用 DEBUG URL: {video_url}")

            # 更新 shot 记录
            shot.video_url = video_url
            shot.video_status = "completed"

            if not shot.extra_data:
                shot.extra_data = {}
            shot.extra_data["resolved_references"] = resolved_refs
            shot.extra_data["video_generated_at"] = datetime.utcnow().isoformat()

            if not shot.status_detail:
                shot.status_detail = {}
            shot.status_detail["video_status"] = "completed"
            shot.status_detail["video_completed_at"] = datetime.utcnow().isoformat()

            flag_modified(shot, "extra_data")
            flag_modified(shot, "status_detail")
            await db.flush()

            logger.info(f"[VideoGenerator] 视频生成成功: shot_id={shot_id}")

            return {
                "success": True,
                "shot_id": shot_id,
                "video_url": video_url,
                "generation_mode": prompt_params.get("generation_mode", "new"),
                "references_count": len(resolved_refs),
                "message": f"视频生成成功（{prompt_params.get('generation_mode', 'new')}模式）",
            }

    except Exception as e:
        logger.error(f"[VideoGenerator] 视频生成失败: shot_id={shot_id}, error={e}")
        return {"success": False, "shot_id": shot_id, "error": str(e)}


@tool
async def batch_submit_video_generation(
    creation_uuid: str,
) -> Dict[str, Any]:
    """
    批量为所有有视频提示词但未生成视频的分镜提交视频生成任务。

    Args:
        creation_uuid: 创作项目 UUID

    Returns:
        {
            "success": True,
            "total": int,
            "results": [{"shot_id": int, "success": bool}, ...]
        }
    """
    logger.info(f"[VideoGenerator] 批量提交视频生成: creation_uuid={creation_uuid}")

    from app.agent.tools.async_db import get_async_session
    from app.models.shot import Shot
    from app.models.scene import Scene
    from app.models.creation import Creation
    from sqlalchemy import select

    try:
        async with get_async_session() as db:
            creation_stmt = select(Creation).where(Creation.uuid == creation_uuid)
            creation_result = await db.execute(creation_stmt)
            creation = creation_result.scalar_one_or_none()
            if not creation:
                return {"success": False, "error": f"创作不存在: {creation_uuid}"}

            # 查询所有需要生成视频的分镜
            shots_stmt = (
                select(Shot)
                .join(Scene)
                .where(Scene.creation_id == creation.creation_id)
                .order_by(Shot.shot_number)
            )
            shots_result = await db.execute(shots_stmt)
            shots = shots_result.scalars().all()

            shots_to_generate = []
            for shot in shots:
                extra_data = shot.extra_data or {}
                has_prompt = bool(extra_data.get("video_prompt"))
                has_video = bool(shot.video_url)
                if has_prompt and not has_video:
                    shots_to_generate.append(shot.shot_id)

            if not shots_to_generate:
                return {
                    "success": True,
                    "total": 0,
                    "results": [],
                    "message": "没有需要生成视频的分镜（所有有提示词的分镜都已生成视频）",
                }

        # 逐个提交生成（使用 submit_video_generation 工具的底层逻辑）
        results = []
        for sid in shots_to_generate:
            result = await submit_video_generation.ainvoke({
                "shot_id": sid,
                "creation_uuid": creation_uuid,
            })
            results.append({
                "shot_id": sid,
                "success": result.get("success", False),
                "video_url": result.get("video_url", ""),
                "error": result.get("error", ""),
            })

        success_count = sum(1 for r in results if r["success"])
        failed_count = len(results) - success_count

        logger.info(f"[VideoGenerator] 批量生成完成: {success_count} 成功, {failed_count} 失败")

        return {
            "success": failed_count == 0,
            "total": len(results),
            "success_count": success_count,
            "failed_count": failed_count,
            "results": results,
            "message": f"批量视频生成完成：{success_count} 成功，{failed_count} 失败",
        }

    except Exception as e:
        logger.error(f"[VideoGenerator] 批量生成失败: {e}")
        return {"success": False, "error": str(e)}
