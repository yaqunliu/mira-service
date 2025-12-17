"""
订阅续费轮询兜底任务（计费日内 24h）
"""
from app.core.celery_app import celery_app
from app.db.session import SessionLocal
from app.services.subscription_service import SubscriptionService
from app.core.logger import logger


@celery_app.task(name="poll_subscriptions_billing")
def poll_subscriptions_billing():
    db = SessionLocal()
    try:
        result = SubscriptionService.poll_subscriptions_billing(db)
        logger.info(f"订阅续费轮询完成: {result}")
        return result
    except Exception as e:
        logger.exception(f"订阅续费轮询失败: {e}")
        raise
    finally:
        db.close()

