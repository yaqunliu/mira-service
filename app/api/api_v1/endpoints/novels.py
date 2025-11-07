from fastapi import APIRouter, Depends, HTTPException, status, UploadFile, File
from sqlalchemy.orm import Session
from typing import List

router = APIRouter()


@router.post("/upload")
async def upload_novel(file: UploadFile = File(...)):
    """上传小说文件"""
    # TODO: 实现小说上传逻辑
    pass


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
