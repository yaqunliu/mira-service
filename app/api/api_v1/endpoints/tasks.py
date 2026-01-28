"""
任务状态查询接口
用于前端通过 task_id 查询 Celery 任务状态和关联的资源信息

支持多种任务类型：
- 小说上传任务 (novel_upload)
- AI 生成任务 (character_image_generation, shot_image_generation, audio_generation, video_synthesis 等)
"""
import json
from typing import Optional, Dict, Any, List
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.api.deps import get_async_db
from app.models.novel import Novel
from app.models.character import Character
from app.models.shot import Shot
from app.models.scene import Scene
from app.models.creation import Creation
from app.core.celery_app import celery_app
from app.core.logger import logger
from app.utils.task_types import TaskType, get_task_type_from_name
from app.utils.response import success_response
from sqlalchemy.orm import selectinload

router = APIRouter()


def parse_narration(narration_str: Optional[str]) -> List[str]:
    if not narration_str:
        return []
    try:
        data = json.loads(narration_str)
        if isinstance(data, list):
            return data
        return [str(data)]
    except (json.JSONDecodeError, TypeError):
        return [narration_str]


async def _get_resource_by_task_result(
    task_type: TaskType,
    result: Dict[str, Any],
    db: AsyncSession
) -> Optional[Dict[str, Any]]:
    if task_type == TaskType.NOVEL_UPLOAD:
        novel_id = result.get("novel_id")
        if novel_id:
            result = await db.execute(
                select(Novel).where(Novel.novel_id == novel_id)
            )
            novel = result.scalar_one_or_none()
            if novel:
                return {
                    "type": "novel",
                    "novel_id": novel.novel_id,
                    "novel_uuid": novel.uuid,
                    "novel": {
                        "novel_id": novel.novel_id,
                        "uuid": novel.uuid,
                        "title": novel.title,
                        "author": novel.author,
                        "status": novel.status,
                        "chapter_count": novel.chapter_count,
                    }
                }
    
    elif task_type == TaskType.CREATION_INIT or task_type == TaskType.BATCH_SHOT_IMAGE_GENERATION:
        creation_id = result.get("creation_id")
        if creation_id:
            result = await db.execute(
                select(Creation).where(Creation.creation_id == creation_id)
            )
            creation = result.scalar_one_or_none()
            if creation:
                return {
                    "type": "creation",
                    "creation_id": creation.creation_id,
                    "creation": {
                        "creation_id": creation.creation_id,
                        "title": creation.title,
                        "status": creation.status,
                        "video_url": result.get("video_url"),
                        "audio_url": result.get("audio_url"),
                    }
                }
    
    elif task_type == TaskType.CHARACTER_IMAGE_GENERATION:
        character_id = result.get("character_id")
        if character_id:
            result = await db.execute(
                select(Character).where(Character.character_id == character_id)
            )
            character = result.scalar_one_or_none()
            if character:
                return {
                    "type": "character",
                    "character_id": character_id,
                    "character": {
                        "character_id": character.character_id,
                        "name": character.name,
                        "image_url": result.get("image_url"),
                    }
                }
    
    elif task_type == TaskType.SHOT_IMAGE_GENERATION:
        shot_id = result.get("shot_id")
        if shot_id:
            result = await db.execute(
                select(Shot).where(Shot.shot_id == shot_id)
            )
            shot = result.scalar_one_or_none()
            if shot:
                return {
                    "type": "shot",
                    "shot_id": shot_id,
                    "shot": {
                        "shot_id": shot.shot_id,
                        "title": shot.title,
                        "image_url": result.get("image_url"),
                    }
                }
    
    elif task_type in [TaskType.CHARACTER_ANALYSIS, TaskType.SCENE_DESCRIPTION_GENERATION, TaskType.SCENE_SHOT_DECOMPOSITION, TaskType.SCENE_IMAGE_GENERATION, TaskType.SHOT_SCRIPT_DESIGN, TaskType.SHOT_IMAGE_PROMPT_GENERATION, TaskType.VIDEO_PROMPT_GENERATION, TaskType.AI_VIDEO_GENERATION]:
        creation_id = result.get("creation_id")
        if not creation_id:
            result = await db.execute(
                select(Creation).where(Creation.uuid == result.get("task_id"))
            )
            creation = result.scalar_one_or_none()
        else:
            result = await db.execute(
                select(Creation).where(Creation.creation_id == creation_id)
            )
            creation = result.scalar_one_or_none()
            
        if creation:
            shots_data = []
            if creation.status == "completed":
                result = await db.execute(
                    select(Shot).join(Scene).where(
                        Scene.creation_id == creation.creation_id
                    ).order_by(Shot.shot_id)
                )
                shots = result.scalars().all()
                for s in shots:
                    shots_data.append({
                        "shot_id": s.shot_id,
                        "title": s.title,
                        "narration": parse_narration(s.narration),
                        "image_url": s.image_url,
                        "video_url": s.video_url,
                        "audio_url": s.audio_url,
                        "content": s.content
                    })

            return {
                "type": "creation_v2",
                "creation_id": creation.creation_id,
                "creation": {
                    "creation_id": creation.creation_id,
                    "title": creation.title,
                    "status": creation.status,
                    "timeline_config": creation.timeline_config,
                    "shots": shots_data,
                    "video_url": creation.video_url,
                    "audio_url": creation.audio_url,
                }
            }
    
    return None


@router.get("/{task_id}")
async def get_task_status(task_id: str, db: AsyncSession = Depends(get_async_db)):
    try:
        task = celery_app.AsyncResult(task_id)
        task_state = task.state
        
        task_type = None
        if task_state == "SUCCESS" and task.result:
            try:
                if isinstance(task.result, dict) and "task_type" in task.result:
                    task_type_str = task.result.get("task_type")
                    try:
                        task_type = TaskType(task_type_str)
                    except ValueError:
                        pass
            except Exception:
                pass
        
        if task_type is None and task_state == "PROGRESS" and task.info:
            try:
                if isinstance(task.info, dict) and "task_type" in task.info:
                    task_type_str = task.info.get("task_type")
                    try:
                        task_type = TaskType(task_type_str)
                    except ValueError:
                        pass
            except Exception:
                pass
        
        if task_type is None:
            task_type = TaskType.NOVEL_UPLOAD
        
        response = {
            "task_id": task_id,
            "task_type": task_type.value,
            "status": task_state,
        }
        
        if task_state == "PENDING" or task_state == "STARTED":
            result = await db.execute(
                select(Creation).where(Creation.uuid == task_id)
            )
            creation = result.scalar_one_or_none()
            if creation and creation.status == "processing":
                from datetime import datetime, timedelta, timezone
                now = datetime.now(timezone.utc)
                if creation.updated_at and now - creation.updated_at.replace(tzinfo=timezone.utc) > timedelta(minutes=10):
                    logger.warning(f"检测到僵尸任务: task_id={task_id}, creation_id={creation.creation_id}. 标记为完成失败。")
                    creation.status = "failed"
                    await db.commit()
                    task_state = "FAILURE"
                    response["status"] = "FAILURE"
                    response["message"] = "任务异常中断或超时"
                    return success_response(data=response)

            response.update({
                "message": "任务正在处理中",
                "resource": None,
                "progress": None,
            })
        elif task_state == "PROGRESS":
            try:
                progress_info = task.info if task.info else {}
                response.update({
                    "message": progress_info.get("status", "任务正在处理中"),
                    "resource": None,
                    "progress": {
                        "current": progress_info.get("current", 0),
                        "total": progress_info.get("total", 100),
                        "percent": progress_info.get("percent", 0),
                        "status": progress_info.get("status", "处理中"),
                        "stage": progress_info.get("stage", "unknown"),
                        "success_count": progress_info.get("success_count", 0),
                        "error_count": progress_info.get("error_count", 0),
                    }
                })
            except Exception as e:
                logger.error(f"获取进度信息失败: {str(e)}")
                response.update({
                    "message": "任务正在处理中",
                    "resource": None,
                    "progress": None,
                })
        elif task_state == "SUCCESS":
            try:
                result = task.result
                if not isinstance(result, dict):
                    result = {}
                
                resource_info = await _get_resource_by_task_result(task_type, result, db)
                
                response.update({
                    "message": "任务处理完成",
                    "resource": resource_info,
                    "progress": {
                        "current": 100,
                        "total": 100,
                        "percent": 100,
                        "status": "处理完成",
                        "stage": "completed",
                    },
                })
                
                if task_type == TaskType.NOVEL_UPLOAD and resource_info:
                    response["novel_id"] = resource_info.get("novel_id")
                    response["novel_uuid"] = resource_info.get("novel_uuid")
                    
            except Exception as e:
                logger.error(f"获取任务结果失败: {str(e)}")
                response.update({
                    "message": "任务完成，但获取结果时出错",
                    "resource": None,
                    "progress": None,
                })
        elif task_state == "FAILURE":
            try:
                error_info = str(task.info) if task.info else "未知错误"
                response.update({
                    "message": "任务处理失败",
                    "error": error_info,
                    "resource": None,
                    "progress": None,
                })
            except Exception:
                response.update({
                    "message": "任务处理失败",
                    "error": "无法获取错误详情",
                    "resource": None,
                    "progress": None,
                })
        elif task_state == "RETRY":
            response.update({
                "message": "任务正在重试",
                "resource": None,
                "progress": None,
            })
        elif task_state == "REVOKED":
            response.update({
                "message": "任务已被撤销",
                "resource": None,
                "progress": None,
            })
        else:
            response.update({
                "message": f"任务状态: {task_state}",
                "resource": None,
                "progress": None,
            })
        
        return success_response(
            data=response,
            message=response.get("message", "任务状态查询成功")
        )
        
    except Exception as e:
        logger.error(f"查询任务状态失败: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"查询任务状态失败: {str(e)}"
        )


@router.get("/{task_id}/novel")
async def get_task_novel(task_id: str, db: AsyncSession = Depends(get_async_db)):
    result = await db.execute(
        select(Novel).where(Novel.task_id == task_id)
    )
    novel = result.scalar_one_or_none()
    
    if novel:
        return success_response(
            data={
                "task_id": task_id,
                "novel_id": novel.novel_id,
                "novel": {
                    "novel_id": novel.novel_id,
                    "title": novel.title,
                    "author": novel.author,
                    "status": novel.status,
                    "chapter_count": novel.chapter_count,
                    "created_at": novel.created_at,
                }
            },
            message="小说信息获取成功"
        )
    
    try:
        task = celery_app.AsyncResult(task_id)
        if task.state == "SUCCESS":
            result = task.result
            if isinstance(result, dict) and "novel_id" in result:
                novel_id = result["novel_id"]
                result = await db.execute(
                    select(Novel).where(Novel.novel_id == novel_id)
                )
                novel = result.scalar_one_or_none()
                if novel:
                    return success_response(
                        data={
                            "task_id": task_id,
                            "novel_id": novel_id,
                            "novel": {
                                "novel_id": novel.novel_id,
                                "title": novel.title,
                                "author": novel.author,
                                "status": novel.status,
                                "chapter_count": novel.chapter_count,
                                "created_at": novel.created_at,
                            }
                        },
                        message="小说信息获取成功"
                    )
    except Exception as e:
        logger.error(f"从任务结果获取小说信息失败: {str(e)}")
    
    raise HTTPException(
        status_code=404,
        detail="未找到关联的小说记录"
    )


@router.get("/{task_id}/sub-tasks")
async def get_task_sub_tasks(task_id: str, db: AsyncSession = Depends(get_async_db)):
    try:
        task = celery_app.AsyncResult(task_id)
        task_state = task.state
        
        task_type = None
        progress_info = {}
        sub_task_ids = []
        
        if task_state == "PROGRESS" and task.info:
            progress_info = task.info if isinstance(task.info, dict) else {}
            task_type_str = progress_info.get("task_type")
            if task_type_str:
                try:
                    task_type = TaskType(task_type_str)
                except ValueError:
                    pass
            sub_task_ids = progress_info.get("sub_tasks", [])
        elif task_state == "SUCCESS" and task.result:
            result = task.result if isinstance(task.result, dict) else {}
            task_type_str = result.get("task_type")
            if task_type_str:
                try:
                    task_type = TaskType(task_type_str)
                except ValueError:
                    pass
            sub_task_ids = result.get("sub_tasks", [])
        
        return success_response(data={
            "task_id": task_id,
            "status": task_state,
            "task_type": task_type.value if task_type else None,
            "progress": {
                "total": progress_info.get("total", len(sub_task_ids)),
                "completed": progress_info.get("success_count", 0) + progress_info.get("failed_count", 0),
                "success_count": progress_info.get("success_count", 0),
                "failed_count": progress_info.get("error_count", 0),
            },
            "sub_tasks": sub_task_ids
        })
    except Exception as e:
        logger.error(f"查询子任务状态失败: {str(e)}")
        raise HTTPException(status_code=500, detail=f"查询子任务状态失败: {str(e)}")
