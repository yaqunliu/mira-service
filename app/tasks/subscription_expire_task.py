"""
订阅过期检查任务
"""
from app.core.celery_app import celery_app
from app.db.session import SessionLocal
from app.tasks.subscription_tasks import check_expired_subscriptions
from app.core.logger import logger


@celery_app.task(name="check_expired_subscriptions")
def check_expired_subscriptions_task():
    """检查并标记过期的订阅"""
    db = SessionLocal()
    try:
        result = check_expired_subscriptions(db)
        logger.info(f"订阅过期检查完成: {result}")
        return result
    except Exception as e:
        logger.exception(f"订阅过期检查失败: {e}")
        raise
    finally:
        db.close()

