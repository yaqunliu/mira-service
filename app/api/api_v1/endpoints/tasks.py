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
from app.models.creation import Creation
from app.core.celery_app import celery_app
from app.core.logger import logger
from app.utils.task_types import TaskType, get_task_type_from_name
from app.utils.response import success_response

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
                    "novel": {
                        "novel_id": novel.novel_id,
                        "title": novel.title,
                        "author": novel.author,
                        "status": novel.status,
                        "chapter_count": novel.chapter_count,
                    }
                }
    
    elif task_type == TaskType.CREATION_INIT:
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
                
                # 向后兼容：如果是小说上传任务，保留 novel_id 字段
                if task_type == TaskType.NOVEL_UPLOAD and resource_info:
                    response["novel_id"] = resource_info.get("novel_id")
                    
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

