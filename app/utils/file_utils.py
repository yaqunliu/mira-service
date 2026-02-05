import os
import uuid
from pathlib import Path
from typing import Optional
from fastapi import UploadFile
from app.core.config import settings
from app.core.logger import logger


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


def read_prompt_file(filename: str) -> str:
    """
    读取 prompt 文件内容
    
    Args:
        filename: prompt 文件名（如 "playbook.md"），默认搜索 app/prompt/，找不到则回退 app/prompts/
        
    Returns:
        prompt 文件内容（字符串）
        
    Raises:
        FileNotFoundError: 当文件不存在时
        IOError: 当文件读取失败时
    """
    # 获取项目根目录（app 目录的父目录）
    app_dir = Path(__file__).parent.parent
    prompt_file = app_dir / "prompt" / filename
    
    if not prompt_file.exists():
        error_msg = f"Prompt 文件不存在: {filename} (searched in {prompt_file})"
        logger.error(error_msg)
        raise FileNotFoundError(error_msg)
    try:
        with open(prompt_file, 'r', encoding='utf-8') as f:
            content = f.read()
        logger.debug(f"成功读取 prompt 文件: {prompt_file.name}")
        return content
    except Exception as e:
        error_msg = f"读取 prompt 文件失败: {prompt_file.name}, 错误: {str(e)}"
        logger.error(error_msg)
        raise IOError(error_msg) from e


def read_knowledge_file(relative_path: str) -> str:
    """
    读取知识库文件内容
    
    Args:
        relative_path: 知识库文件相对路径（如 "director/camera_techniques.md"）
                      默认搜索 app/agent/knowledge/ 目录
        
    Returns:
        知识库文件内容（字符串），文件不存在返回空字符串
    """
    # 获取项目根目录（app 目录的父目录）
    app_dir = Path(__file__).parent.parent
    knowledge_file = app_dir / "agent" / "knowledge" / relative_path
    
    if not knowledge_file.exists():
        logger.warning(f"知识库文件不存在: {relative_path} (searched in {knowledge_file})")
        return ""
    
    try:
        with open(knowledge_file, 'r', encoding='utf-8') as f:
            content = f.read()
        logger.debug(f"成功读取知识库文件: {knowledge_file.name}")
        return content
    except Exception as e:
        logger.error(f"读取知识库文件失败: {knowledge_file.name}, 错误: {str(e)}")
        return ""
