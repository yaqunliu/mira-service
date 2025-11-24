import sys
import logging
from loguru import logger
from app.core.config import settings


def setup_logging():
    """配置日志系统"""
    # 移除默认的logger
    logger.remove()
    
    # 关闭 SQLAlchemy 的日志输出（使用标准 logging 模块）
    # 设置 SQLAlchemy 相关日志级别为 WARNING，避免打印 SQL 查询
    logging.getLogger('sqlalchemy.engine').setLevel(logging.WARNING)
    logging.getLogger('sqlalchemy.pool').setLevel(logging.WARNING)
    logging.getLogger('sqlalchemy.dialects').setLevel(logging.WARNING)
    logging.getLogger('sqlalchemy.orm').setLevel(logging.WARNING)
    
    # 添加控制台输出
    logger.add(
        sys.stdout,
        level=settings.LOG_LEVEL,
        format="<green>{time:YYYY-MM-DD HH:mm:ss}</green> | <level>{level: <8}</level> | <cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - <level>{message}</level>",
        colorize=True,
    )
    
    # 添加文件输出
    logger.add(
        "logs/app.log",
        level=settings.LOG_LEVEL,
        format="{time:YYYY-MM-DD HH:mm:ss} | {level: <8} | {name}:{function}:{line} - {message}",
        rotation="1 day",
        retention="30 days",
        compression="zip",
    )
    
    return logger
