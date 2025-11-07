import os
import uuid
from typing import Optional
from fastapi import UploadFile
from app.core.config import settings


def generate_unique_filename(original_filename: str) -> str:
    """生成唯一的文件名"""
    file_extension = os.path.splitext(original_filename)[1]
    unique_id = str(uuid.uuid4())
    return f"{unique_id}{file_extension}"


def get_file_type(filename: str) -> str:
    """根据文件扩展名判断文件类型"""
    extension = os.path.splitext(filename)[1].lower()
    
    image_extensions = {'.jpg', '.jpeg', '.png', '.gif', '.bmp', '.webp'}
    audio_extensions = {'.mp3', '.wav', '.flac', '.aac', '.ogg'}
    video_extensions = {'.mp4', '.avi', '.mov', '.mkv', '.wmv', '.flv'}
    document_extensions = {'.txt', '.pdf', '.doc', '.docx', '.rtf'}
    
    if extension in image_extensions:
        return 'image'
    elif extension in audio_extensions:
        return 'audio'
    elif extension in video_extensions:
        return 'video'
    elif extension in document_extensions:
        return 'document'
    else:
        return 'other'


async def save_upload_file(upload_file: UploadFile, subfolder: str = "") -> tuple[str, str]:
    """
    保存上传的文件
    
    Returns:
        tuple: (file_path, filename)
    """
    # 创建上传目录
    upload_dir = os.path.join(settings.UPLOAD_DIR, subfolder)
    os.makedirs(upload_dir, exist_ok=True)
    
    # 生成唯一文件名
    filename = generate_unique_filename(upload_file.filename)
    file_path = os.path.join(upload_dir, filename)
    
    # 保存文件
    with open(file_path, "wb") as buffer:
        content = await upload_file.read()
        buffer.write(content)
    
    return file_path, filename


def delete_file(file_path: str) -> bool:
    """删除文件"""
    try:
        if os.path.exists(file_path):
            os.remove(file_path)
            return True
        return False
    except Exception:
        return False
