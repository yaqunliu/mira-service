from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from app.models.user import User
from app.api import deps
from app.core.logger import logger
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
async def create_video_generation_task(
    request: CreateVideoRequest,
    db: AsyncSession = Depends(deps.get_async_db),
    current_user: User = Depends(deps.get_current_user)
):
    """
    启动V2视频生成任务
    """
    if not request.input_text and not request.chapter_id:
        raise HTTPException(status_code=400, detail="必须提供 input_text 或 chapter_id")
        
    task_id = str(uuid.uuid4())
    input_text = request.input_text
    
    if request.chapter_id and not input_text:
        from app.services.novel_service import NovelService
        try:
            chapter = await NovelService.get_chapter_by_id_service(db, request.novel_id, request.chapter_id, current_user.user_id)
            if chapter.content_url:
                if chapter.content_url.startswith("http"):
                    import tempfile
                    import os
                    from app.utils.us3 import download_file_smart
                    
                    with tempfile.NamedTemporaryFile(delete=False) as tmp:
                        temp_save_path = tmp.name
                    
                    try:
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
                    with open(chapter.content_url, "r", encoding="utf-8") as f:
                        input_text = f.read()
            
            if not input_text:
                raise HTTPException(status_code=400, detail="无法获取章节内容")
                
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"获取章节失败: {str(e)}")

    if not input_text:
        raise HTTPException(status_code=400, detail="文案内容不能为空")

    from app.services.novel_service import NovelService
    creation_title = f"Creation for {task_id}"

    try:
        novel = await NovelService.get_novel_by_id_service(db, request.novel_id, current_user.user_id)
        if novel:
            novel_title = novel.title or "Untitled Novel"

            if request.chapter_id:
                try:
                    chapter = await NovelService.get_chapter_by_id_service(db, request.novel_id, request.chapter_id, current_user.user_id)
                    chapter_title = chapter.title or f"Chapter {request.chapter_id}"
                    creation_title = f"{novel_title} - {chapter_title}"
                except:
                    creation_title = novel_title
            else:
                creation_title = novel_title
    except:
        pass

    temp_dir = Path(settings.UPLOAD_DIR) / "temp_tasks"
    temp_dir.mkdir(parents=True, exist_ok=True)
    input_file_path = temp_dir / f"{task_id}_input.txt"
    status_file_path = temp_dir / f"{task_id}_status.json"

    with open(input_file_path, "w", encoding="utf-8") as f:
        f.write(input_text)

    with open(status_file_path, "w", encoding="utf-8") as f:
        json.dump({"status": "draft", "message": "Task created", "progress": 0}, f)

    new_creation = Creation(
        uuid=task_id,
        title=creation_title,
        owner_id=current_user.user_id,
        novel_id=request.novel_id,
        chapter_id=request.chapter_id or 0,
        status="draft",
        current_task_id=task_id,
        creation_type="chapter" if request.chapter_id else "script"
    )
    db.add(new_creation)
    await db.commit()
    
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
        return {"status": "processing"}
