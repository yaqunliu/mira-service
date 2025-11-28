"""
字体工具模块
用于管理字幕渲染所需的字体文件
"""
import os
import requests
from typing import Optional
from pathlib import Path
from app.core.config import settings
from app.core.logger import logger


def get_font_path() -> str:
    """
    获取字幕字体文件路径
    如果本地不存在则从网络下载
    
    Returns:
        str: 字体文件的绝对路径
    """
    # 构建本地字体路径
    font_dir = Path(settings.FONT_DIR)
    font_path = font_dir / settings.SUBTITLE_FONT_NAME
    
    # 转为绝对路径
    font_path = font_path.resolve()
    
    # 如果字体文件已存在，直接返回
    if font_path.exists():
        logger.debug(f"字体文件已存在: {font_path}")
        return str(font_path)
    
    # 创建字体目录
    font_dir.mkdir(parents=True, exist_ok=True)
    
    # 从网络下载字体
    logger.info(f"正在下载字体文件: {settings.SUBTITLE_FONT_URL}")
    try:
        response = requests.get(settings.SUBTITLE_FONT_URL, timeout=60)
        response.raise_for_status()
        
        # 保存到本地
        with open(font_path, 'wb') as f:
            f.write(response.content)
        
        logger.info(f"字体文件下载成功: {font_path}")
        return str(font_path)
        
    except requests.RequestException as e:
        logger.error(f"字体文件下载失败: {e}")
        raise RuntimeError(f"无法下载字体文件: {e}")


def ensure_font_exists() -> Optional[str]:
    """
    确保字体文件存在，如果不存在则下载
    
    Returns:
        Optional[str]: 字体文件路径，失败返回 None
    """
    try:
        font_path = get_font_path()
        if os.path.exists(font_path):
            return font_path
        return None
    except Exception as e:
        logger.error(f"确保字体存在失败: {e}")
        return None

