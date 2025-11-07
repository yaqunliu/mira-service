import os
import time
from fastapi import APIRouter, Depends, HTTPException, status, UploadFile, File
from sqlalchemy.orm import Session
from typing import List
from app.api.deps import get_db, get_current_user
from app.models.user import User
from app.tasks.novel_tasks import process_novel_upload
from app.core.config import settings
from app.core.logger import logger

router = APIRouter()

# 文件大小限制：50MB
MAX_NOVEL_FILE_SIZE = 50 * 1024 * 1024


@router.post("/upload", status_code=status.HTTP_202_ACCEPTED)
async def upload_novel(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user)
):
    """
    上传小说文件
    
    采用同步接收 + 异步处理的架构：
    1. 验证文件格式和大小
    2. 保存到临时目录
    3. 创建Celery异步任务
    4. 返回任务ID
    """
    # 1. 文件验证
    # 验证文件格式（仅接受.txt文件）
    if not file.filename or not file.filename.endswith('.txt'):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="仅支持.txt格式的小说文件"
        )
    
    # 验证文件大小
    file_content = await file.read()
    file_size = len(file_content)
    
    if file_size > MAX_NOVEL_FILE_SIZE:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"文件大小超过限制（最大{MAX_NOVEL_FILE_SIZE // (1024*1024)}MB）"
        )
    
    if file_size == 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="文件为空"
        )
    
    # 2. 获取用户
    user_id = user.user_id
    
    # 3. 临时存储
    # 创建临时目录：/tmp/novels/{user_id}/
    temp_dir = os.path.join("/tmp", "novels", str(user_id))
    os.makedirs(temp_dir, exist_ok=True)
    
    # 生成临时文件名：{timestamp}_{filename}
    timestamp = int(time.time())
    safe_filename = file.filename.replace(" ", "_").replace("/", "_")
    temp_filename = f"{timestamp}_{safe_filename}"
    temp_file_path = os.path.join(temp_dir, temp_filename)
    
    # 保存文件到临时目录
    try:
        with open(temp_file_path, "wb") as buffer:
            buffer.write(file_content)
        logger.info(f"文件已保存到临时目录: {temp_file_path}")
    except Exception as e:
        logger.error(f"保存临时文件失败: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="保存文件失败"
        )
    
    # 4. 任务投递
    try:
        task = process_novel_upload.delay(
            user_id=user_id,
            temp_file_path=temp_file_path,
            original_filename=file.filename
        )
        task_id = task.id
        logger.info(f"已创建Celery任务: task_id={task_id}, file={file.filename}")
        
        return {
            "task_id": task_id,
            "message": "文件已接收，正在处理中",
            "status": "processing"
        }
    except Exception as e:
        # 如果任务创建失败，清理临时文件
        if os.path.exists(temp_file_path):
            os.remove(temp_file_path)
        logger.error(f"创建Celery任务失败: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="创建处理任务失败"
        )


@router.get("/")
async def get_novels():
    """获取小说列表"""
    # TODO: 实现获取小说列表逻辑
    pass


@router.get("/{novel_id}")
async def get_novel(novel_id: int):
    """根据ID获取小说详情"""
    # TODO: 实现获取小说详情逻辑
    pass


@router.get("/{novel_id}/chapters")
async def get_novel_chapters(novel_id: int):
    """获取小说章节列表"""
    # TODO: 实现获取章节列表逻辑
    pass


@router.delete("/{novel_id}")
async def delete_novel(novel_id: int):
    """删除小说"""
    # TODO: 实现删除小说逻辑
    pass
