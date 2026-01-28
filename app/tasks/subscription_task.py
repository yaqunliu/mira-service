"""
订阅月度积分发放兜底任务（含年付按月发放）
"""
from app.core.celery_app import celery_app
from app.db.base import _get_sync_session_factory
from app.services.subscription_service import SubscriptionService
from app.core.logger import logger


@celery_app.task(name="issue_subscription_points_monthly")
def issue_subscription_points_monthly():
    db = _get_sync_session_factory()()
    try:
        result = SubscriptionService.run_monthly_payout(db)
        logger.info(f"订阅月度发放完成: {result}")
        return result
    except Exception as e:
        logger.exception(f"订阅月度发放失败: {e}")
        raise
    finally:
        db.close()

