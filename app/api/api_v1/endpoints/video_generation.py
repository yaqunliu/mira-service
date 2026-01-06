from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from sqlalchemy.orm import Session
from app.db.session import SessionLocal
from app.models.user import User
from app.api import deps
from app.core.celery_app import celery_app
from app.core.logger import logger
# 已废弃：video_generation_flow 目录已删除
# from app.video_generation_flow.video_generation_pipeline import VideoGenerationPipeline
import uuid
from pathlib import Path
from app.core.config import settings
import json

router = APIRouter()

from pydantic import BaseModel
from typing import Optional
from app.models.creation import Creation

class CreateVideoRequest(BaseModel):
    novel_id: int
    chapter_id: Optional[int] = None
    input_text: Optional[str] = None

@router.post("/v2/create")
def create_video_generation_task(
    request: CreateVideoRequest,
    db: Session = Depends(deps.get_db),
    current_user: User = Depends(deps.get_current_user)
):
    """
    启动V2视频生成任务
    """
    if not request.input_text and not request.chapter_id:
        raise HTTPException(status_code=400, detail="必须提供 input_text 或 chapter_id")
        
    task_id = str(uuid.uuid4())
    
    # 获取输入文本
    input_text = request.input_text
    
    # 如果指定了章节，且没有提供文本，尝试从章节获取 (暂时先简单处理，实际需要从章节content_url读取)
    # 对于MVP，假设前端会传入 input_text 或者我们只是创建记录
    if request.chapter_id and not input_text:
         from app.services.novel_service import NovelService
         try:
             chapter = NovelService.get_chapter_by_id_service(db, request.novel_id, request.chapter_id, current_user.user_id)
             # Try to read content from content_url
             if chapter.content_url:
                 if chapter.content_url.startswith("http"):
                     # Handle remote URL (US3)
                     import tempfile
                     import os
                     from app.utils.us3 import download_file_smart
                     
                     with tempfile.NamedTemporaryFile(delete=False) as tmp:
                         temp_save_path = tmp.name
                     
                     try:
                         # Download file using smart downloader (handles US3/HTTP)
                         download_result = download_file_smart(
                            url_or_key=chapter.content_url,
                            save_file=temp_save_path
                         )
                         
                         if download_result.get('success'):
                             with open(temp_save_path, "r", encoding="utf-8") as f:
                                 input_text = f.read()
                         else:
                             raise Exception(f"Download failed: {download_result.get('message')}")
                             
                     finally:
                         if os.path.exists(temp_save_path):
                             os.remove(temp_save_path)
                             
                 elif Path(chapter.content_url).exists():
                     # Handle local file path
                     with open(chapter.content_url, "r", encoding="utf-8") as f:
                         input_text = f.read()
             
             if not input_text: 
                  # Fallback or error
                  raise HTTPException(status_code=400, detail="无法获取章节内容")
                  
         except Exception as e:
             raise HTTPException(status_code=400, detail=f"获取章节失败: {str(e)}")

    if not input_text:
         raise HTTPException(status_code=400, detail="文案内容不能为空")

    # 获取小说和章节信息以生成标题
    from app.services.novel_service import NovelService
    creation_title = f"Creation for {task_id}"  # 默认标题

    try:
        novel = NovelService.get_novel_by_id_service(db, request.novel_id, current_user.user_id)
        if novel:
            novel_title = novel.title or "Untitled Novel"

            if request.chapter_id:
                try:
                    chapter = NovelService.get_chapter_by_id_service(db, request.novel_id, request.chapter_id, current_user.user_id)
                    chapter_title = chapter.title or f"Chapter {request.chapter_id}"
                    creation_title = f"{novel_title} - {chapter_title}"
                except:
                    # 如果获取章节失败，只使用小说标题
                    creation_title = novel_title
            else:
                creation_title = novel_title
    except:
        # 如果获取小说信息失败，使用默认标题
        pass

    # Save input to a temporary file
    temp_dir = Path(settings.UPLOAD_DIR) / "temp_tasks"
    temp_dir.mkdir(parents=True, exist_ok=True)
    input_file_path = temp_dir / f"{task_id}_input.txt"
    output_file_path = temp_dir / f"{task_id}_output.json"
    status_file_path = temp_dir / f"{task_id}_status.json"

    with open(input_file_path, "w", encoding="utf-8") as f:
        f.write(input_text)

    # Initial status
    with open(status_file_path, "w", encoding="utf-8") as f:
        json.dump({"status": "draft", "message": "Task created", "progress": 0}, f)

    # Create Creation record in DB
    new_creation = Creation(
        uuid=task_id, # Use task_id as UUID for simple tracking
        title=creation_title, # 使用小说和章节标题
        owner_id=current_user.user_id,
        novel_id=request.novel_id,
        chapter_id=request.chapter_id or 0,
        status="draft",
        current_task_id=task_id,
        creation_type="chapter" if request.chapter_id else "script"
    )
    db.add(new_creation)
    db.commit()
    
    # We do NOT start the celery task chain automatically anymore.
    # The user will guide the creation process step-by-step in the V2 UI.
    
    return {"task_id": task_id, "status": "draft", "creation_id": new_creation.creation_id}

@router.get("/v2/{task_id}")
def get_video_generation_status(task_id: str):
    """
    获取V2视频生成任务状态
    """
    temp_dir = Path(settings.UPLOAD_DIR) / "temp_tasks"
    output_file_path = temp_dir / f"{task_id}_output.json"
    status_file_path = temp_dir / f"{task_id}_status.json"
    
    if output_file_path.exists():
        try:
            with open(output_file_path, "r", encoding="utf-8") as f:
                result = json.load(f)
            return {"status": "completed", "result": result}
        except Exception as e:
            return {"status": "error", "error": str(e)}
    elif status_file_path.exists():
        try:
            with open(status_file_path, "r", encoding="utf-8") as f:
                status_data = json.load(f)
            return status_data
        except Exception as e:
            return {"status": "processing", "message": "Reading status..."}
    else:
        # Check if task is failed or still processing? 
        # Without a DB record for status, we assume processing if output doesn't exist.
        return {"status": "processing"}

@celery_app.task
def generate_video_v2_task(input_path: str, output_path: str, task_id: str, status_path: str = None):
    # 已废弃：此 V2 API 端点已不再使用
    # VideoGenerationPipeline 已被删除
    # 请使用新的步骤化 API（step1-step8）
    logger.warning("generate_video_v2_task is deprecated and no longer supported")
    error_result = {"error": "此 API 端点已废弃，请使用新的步骤化 API", "status": "failed"}
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(error_result, f)
