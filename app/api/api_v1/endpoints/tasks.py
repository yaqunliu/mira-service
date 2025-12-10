"""
任务状态查询接口
用于前端通过 task_id 查询 Celery 任务状态和关联的资源信息

支持多种任务类型：
- 小说上传任务 (novel_upload)
- AI 生成任务 (character_image_generation, shot_image_generation, audio_generation, video_synthesis 等)
"""
from typing import Optional, Dict, Any
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from app.api.deps import get_db
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


def _get_resource_by_task_result(
    task_type: TaskType,
    result: Dict[str, Any],
    db: Session
) -> Optional[Dict[str, Any]]:
    """
    根据任务类型和结果获取关联的资源信息
    
    Args:
        task_type: 任务类型
        result: 任务结果字典
        db: 数据库会话
        
    Returns:
        资源信息字典，如果未找到则返回 None
    """
    if task_type == TaskType.NOVEL_UPLOAD:
        novel_id = result.get("novel_id")
        if novel_id:
            novel = db.query(Novel).filter(Novel.novel_id == novel_id).first()
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
    
    elif task_type == TaskType.CREATION_INIT or task_type == TaskType.CHARACTER_ANALYSIS or task_type == TaskType.SCENE_DESCRIPTION_GENERATION or task_type == TaskType.BATCH_SHOT_IMAGE_GENERATION:
        creation_id = result.get("creation_id")
        if creation_id:
            creation = db.query(Creation).filter(Creation.creation_id == creation_id).first()
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
            character = db.query(Character).filter(Character.character_id == character_id).first()
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
            shot = db.query(Shot).filter(Shot.shot_id == shot_id).first()
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
    
    elif task_type == TaskType.VIDEO_SYNTHESIS:
        creation_id = result.get("creation_id")
        if creation_id:
            creation = db.query(Creation).filter(Creation.creation_id == creation_id).first()
            if creation:
                return {
                    "type": "creation",
                    "creation_id": creation_id,
                    "creation": {
                        "creation_id": creation.creation_id,
                        "title": creation.title,
                        "status": creation.status,
                        "video_url": result.get("video_url"),
                        "audio_url": result.get("audio_url"),
                    }
                }
    
    return None


@router.get("/{task_id}")
async def get_task_status(task_id: str, db: Session = Depends(get_db)):
    """
    通过 task_id 查询任务状态和进度（通用接口，支持所有任务类型）
    
    返回信息包括：
    - Celery 任务状态（PENDING, STARTED, PROGRESS, SUCCESS, FAILURE, RETRY, REVOKED）
    - 任务类型（task_type）
    - 进度信息（当状态为PROGRESS时）：
      - current: 当前进度
      - total: 总进度
      - percent: 百分比
      - status: 状态描述
      - stage: 处理阶段
      - success_count: 成功处理的数量（如适用）
      - error_count: 失败的数量（如适用）
    - 如果任务完成，返回关联的资源信息（根据任务类型返回 novel_id, character_id, shot_id 等）
    - 如果任务失败，返回错误信息
    
    Args:
        task_id: Celery 任务ID
        
    Returns:
        任务状态、进度和相关信息的字典
        
    示例响应（小说上传处理中）:
    {
        "task_id": "xxx",
        "task_type": "novel_upload",
        "status": "PROGRESS",
        "message": "正在处理第 5/20 章",
        "progress": {
            "current": 5,
            "total": 20,
            "percent": 25,
            "status": "正在处理第 5/20 章",
            "stage": "uploading_chapters",
            "success_count": 5,
            "error_count": 0
        },
        "resource": null
    }
    
    示例响应（角色图片生成完成）:
    {
        "task_id": "yyy",
        "task_type": "character_image_generation",
        "status": "SUCCESS",
        "message": "任务处理完成",
        "progress": {
            "current": 100,
            "total": 100,
            "percent": 100,
            "status": "处理完成",
            "stage": "completed"
        },
        "resource": {
            "type": "character",
            "character_id": 123,
            "character": {
                "character_id": 123,
                "name": "帝王",
                "image_url": "https://..."
            }
        }
    }
    """
    try:
        # 查询 Celery 任务状态
        task = celery_app.AsyncResult(task_id)
        
        # 获取任务状态
        task_state = task.state
        
        # 推断任务类型
        # 方法1: 从任务结果中获取任务类型（如果任务已完成）
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
        
        # 方法2: 从进度信息中获取任务类型（如果任务正在执行）
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
        
        # 方法3: 从任务名称推断（如果方法1和2都失败）
        if task_type is None:
            # 尝试从 Celery 的 inspect 功能获取任务信息
            # 如果无法获取，默认使用小说上传类型（向后兼容）
            task_type = TaskType.NOVEL_UPLOAD
        
        # 基础响应
        response = {
            "task_id": task_id,
            "task_type": task_type.value,
            "status": task_state,
        }
        
        # 根据任务状态返回不同信息
        if task_state == "PENDING":
            # 任务等待执行
            response.update({
                "message": "任务等待执行",
                "resource": None,
                "progress": None,
            })
        elif task_state == "STARTED":
            # 任务正在执行
            response.update({
                "message": "任务正在处理中",
                "resource": None,
                "progress": None,
            })
        elif task_state == "PROGRESS":
            # 任务执行中，有进度信息
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
            # 任务成功完成
            try:
                result = task.result
                if not isinstance(result, dict):
                    result = {}
                
                # 根据任务类型获取关联的资源信息
                resource_info = _get_resource_by_task_result(task_type, result, db)
                
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
                
                # 向后兼容：如果是小说上传任务，保留 novel_id 和 novel_uuid 字段
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
            # 任务失败
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
            # 任务重试中
            response.update({
                "message": "任务正在重试",
                "resource": None,
                "progress": None,
            })
        elif task_state == "REVOKED":
            # 任务被撤销
            response.update({
                "message": "任务已被撤销",
                "resource": None,
                "progress": None,
            })
        else:
            # 未知状态
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
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"查询任务状态失败: {str(e)}"
        )


@router.get("/{task_id}/novel")
async def get_task_novel(task_id: str, db: Session = Depends(get_db)):
    """
    通过 task_id 查询关联的小说信息（向后兼容接口）
    
    注意：此接口仅适用于小说上传任务。对于其他任务类型，请使用 GET /{task_id} 接口。
    
    Args:
        task_id: Celery 任务ID
        
    Returns:
        小说信息（如果存在）
    """
    # 先通过 task_id 在数据库中查找关联的小说
    novel = db.query(Novel).filter(Novel.task_id == task_id).first()
    
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
    
    # 如果数据库中没有找到，尝试从任务结果中获取
    try:
        task = celery_app.AsyncResult(task_id)
        if task.state == "SUCCESS":
            result = task.result
            if isinstance(result, dict) and "novel_id" in result:
                novel_id = result["novel_id"]
                novel = db.query(Novel).filter(Novel.novel_id == novel_id).first()
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
        status_code=status.HTTP_404_NOT_FOUND,
        detail="未找到关联的小说记录"
    )


@router.get("/{task_id}/sub-tasks")
async def get_task_sub_tasks(task_id: str, db: Session = Depends(get_db)):
    """
    查询批量任务的子任务状态
    
    适用于批量分镜图片生成等任务，返回主任务状态和所有子任务的状态。
    
    Args:
        task_id: 主任务ID
        
    Returns:
        {
            "task_id": "xxx",
            "status": "PROGRESS",
            "task_type": "batch_shot_image_generation",
            "progress": {
                "total": 10,
                "completed": 5,
                "success_count": 4,
                "failed_count": 1
            },
            "sub_tasks": [
                {
                    "task_id": "sub-task-1",
                    "status": "SUCCESS",
                    "shot_id": 1,
                    "image_url": "https://..."
                },
                ...
            ]
        }
    """
    try:
        # 查询主任务状态
        task = celery_app.AsyncResult(task_id)
        task_state = task.state
        
        # 获取任务类型和进度信息
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
            progress_info = {
                "total": result.get("total", 0),
                "completed": result.get("total", 0),
                "success_count": result.get("success_count", 0),
                "failed_count": result.get("failed_count", 0),
            }
        
        # 查询所有子任务状态
        sub_tasks_status = []
        for sub_task_id in sub_task_ids:
            sub_task = celery_app.AsyncResult(sub_task_id)
            sub_task_info = {
                "task_id": sub_task_id,
                "status": sub_task.state,
            }
            
            # 获取子任务的详细信息
            if sub_task.state == "SUCCESS" and sub_task.result:
                sub_result = sub_task.result if isinstance(sub_task.result, dict) else {}
                sub_task_info.update({
                    "shot_id": sub_result.get("shot_id"),
                    "shot_title": sub_result.get("shot_title"),
                    "success": sub_result.get("success", False),
                    "image_url": sub_result.get("image_url"),
                    "error": sub_result.get("error"),
                    "skipped": sub_result.get("skipped", False),
                })
            elif sub_task.state == "PROGRESS" and sub_task.info:
                sub_info = sub_task.info if isinstance(sub_task.info, dict) else {}
                sub_task_info.update({
                    "shot_id": sub_info.get("shot_id"),
                    "status_message": sub_info.get("status"),
                })
            elif sub_task.state == "FAILURE":
                sub_task_info["error"] = str(sub_task.info) if sub_task.info else "未知错误"
            
            sub_tasks_status.append(sub_task_info)
        
        response = {
            "task_id": task_id,
            "status": task_state,
            "task_type": task_type.value if task_type else None,
            "progress": {
                "total": progress_info.get("total", 0),
                "completed": progress_info.get("completed", 0),
                "success_count": progress_info.get("success_count", 0),
                "failed_count": progress_info.get("failed_count", 0),
                "status": progress_info.get("status", ""),
                "stage": progress_info.get("stage", ""),
            },
            "sub_tasks": sub_tasks_status,
        }
        
        return success_response(data=response, message="子任务状态查询成功")
        
    except Exception as e:
        logger.error(f"查询子任务状态失败: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"查询子任务状态失败: {str(e)}"
        )


@router.get("/{task_id}/shots")
async def get_task_shots_progress(task_id: str, db: Session = Depends(get_db)):
    """
    查询分镜图片生成任务的进度和分镜详情
    
    该接口不仅返回任务状态，还会从数据库获取最新的分镜信息（包含 image_url）。
    前端可以通过此接口获取实时的分镜图片生成进度。
    
    Args:
        task_id: 任务ID
        
    Returns:
        {
            "task_id": "xxx",
            "status": "PROGRESS",
            "progress": {...},
            "creation_id": 123,
            "scenes": [
                {
                    "scene_id": 1,
                    "title": "场景1",
                    "shots": [
                        {
                            "shot_id": 1,
                            "title": "分镜1",
                            "image_url": "https://...",
                            "image_prompt": "...",
                            "status": "completed"  # pending/generating/completed/failed
                        },
                        ...
                    ]
                },
                ...
            ]
        }
    """
    try:
        # 查询主任务状态
        task = celery_app.AsyncResult(task_id)
        
        # 安全获取任务状态（task.state 访问可能抛出异常，比如 Redis 数据损坏时）
        try:
            task_state = task.state
        except Exception as state_error:
            logger.warning(f"获取任务 {task_id} 状态失败: {str(state_error)}")
            return success_response(
                data={
                    "task_id": task_id,
                    "status": "UNKNOWN",
                    "progress": None,
                    "creation_id": None,
                    "scenes": [],
                    "message": "任务状态获取失败，可能任务数据已损坏或任务不存在",
                    "error": str(state_error)
                },
                message="任务状态获取失败"
            )
        
        # 处理 PENDING 状态（任务还未开始）
        if task_state == "PENDING":
            return success_response(
                data={
                    "task_id": task_id,
                    "status": task_state,
                    "progress": None,
                    "creation_id": None,
                    "scenes": [],
                    "message": "任务等待执行中"
                },
                message="任务等待执行中"
            )
        
        # 处理 FAILURE 状态
        if task_state == "FAILURE":
            error_msg = "未知错误"
            try:
                if task.info:
                    error_msg = str(task.info)
            except Exception:
                pass
            return success_response(
                data={
                    "task_id": task_id,
                    "status": task_state,
                    "progress": None,
                    "creation_id": None,
                    "scenes": [],
                    "message": "任务执行失败",
                    "error": error_msg
                },
                message="任务执行失败"
            )
        
        # 获取 creation_id
        creation_id = None
        progress_info = {}
        sub_task_results = {}  # shot_id -> result
        
        if task_state == "PROGRESS" and task.info:
            info = task.info if isinstance(task.info, dict) else {}
            creation_id = info.get("creation_id")
            progress_info = {
                "total": info.get("total", 0),
                "completed": info.get("completed", 0),
                "success_count": info.get("success_count", 0),
                "failed_count": info.get("failed_count", 0),
                "status": info.get("status", "处理中"),
                "stage": info.get("stage", ""),
            }
            # 获取已完成的结果
            results = info.get("results", [])
            for res in results:
                if isinstance(res, dict) and res.get("shot_id"):
                    sub_task_results[res["shot_id"]] = res
        elif task_state == "SUCCESS" and task.result:
            result = task.result if isinstance(task.result, dict) else {}
            creation_id = result.get("creation_id")
            progress_info = {
                "total": result.get("total", 0),
                "completed": result.get("total", 0),
                "success_count": result.get("success_count", 0),
                "failed_count": result.get("failed_count", 0),
                "status": "完成",
                "stage": "completed",
            }
            results = result.get("results", [])
            for res in results:
                if isinstance(res, dict) and res.get("shot_id"):
                    sub_task_results[res["shot_id"]] = res
        
        if not creation_id:
            return success_response(
                data={
                    "task_id": task_id,
                    "status": task_state,
                    "message": "无法获取创作ID，任务可能还未开始或不是分镜图片生成任务"
                },
                message="任务信息获取中"
            )
        
        # 从数据库获取场景和分镜信息
        scenes = (
            db.query(Scene)
            .options(selectinload(Scene.shots))
            .filter(Scene.creation_id == creation_id)
            .order_by(Scene.scene_id)
            .all()
        )
        
        scenes_data = []
        for scene in scenes:
            shots_data = []
            for shot in sorted(scene.shots, key=lambda s: s.shot_id):
                # 确定分镜状态
                shot_status = "pending"
                if shot.image_url:
                    shot_status = "completed"
                elif shot.shot_id in sub_task_results:
                    res = sub_task_results[shot.shot_id]
                    if res.get("success"):
                        shot_status = "completed"
                    elif res.get("error"):
                        shot_status = "failed"
                    else:
                        shot_status = "generating"
                
                shots_data.append({
                    "shot_id": shot.shot_id,
                    "title": shot.title,
                    "shot_number": shot.shot_number,
                    "image_url": shot.image_url,
                    "image_prompt": shot.image_prompt,
                    "narration": shot.narration,
                    "status": shot_status,
                })
            
            scenes_data.append({
                "scene_id": scene.scene_id,
                "title": scene.title,
                "duration": scene.duration,
                "shots": shots_data,
            })
        
        response = {
            "task_id": task_id,
            "status": task_state,
            "progress": progress_info,
            "creation_id": creation_id,
            "scenes": scenes_data,
        }
        
        return success_response(data=response, message="任务进度查询成功")
        
    except Exception as e:
        logger.error(f"查询任务分镜进度失败: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"查询任务分镜进度失败: {str(e)}"
        )

