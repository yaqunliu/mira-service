"""
积分系统定时任务
"""
from app.core.celery_app import celery_app
from app.db.base import _get_sync_session_factory
from app.services.points_service import PointsService
from app.core.logger import logger


@celery_app.task(name="expire_daily_points_task")
def expire_daily_points_task():
    """
    每日 00:00 执行，过期每日签到积分
    
    定时任务配置在 celery_app.py 中
    """
    db = _get_sync_session_factory()()
    try:
        expired_points = PointsService.expire_daily_points(db)
        logger.info(f"积分过期任务完成，共过期 {expired_points} 积分")
        return {"expired_points": expired_points}
    except Exception as e:
        logger.opt(exception=True).error("积分过期任务失败: {}", str(e))
        raise
    finally:
        db.close()
