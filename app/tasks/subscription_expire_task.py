"""
订阅过期检查任务
"""
from app.core.celery_app import celery_app
from app.db.base import _get_sync_session_factory
from app.services.subscription_service import SubscriptionService
from app.core.logger import logger


@celery_app.task(name="check_expired_subscriptions")
def check_expired_subscriptions_task():
    """检查并标记过期的订阅"""
    db = _get_sync_session_factory()()
    try:
        result = SubscriptionService.check_and_mark_expired_subscriptions(db)
        logger.info(f"订阅过期检查完成: {result}")
        return result
    except Exception as e:
        logger.exception(f"订阅过期检查失败: {e}")
        raise
    finally:
        db.close()

