"""
订单支付轮询兜底任务
按照设计文档：每5分钟执行一次，查询创建时间 >= 3分钟且 <= 24小时的 pending 订单
"""
from app.core.celery_app import celery_app
from app.db.base import _get_sync_session_factory
from app.services.order_service import OrderService
from app.core.logger import logger


@celery_app.task(name="poll_pending_orders", bind=True)
def poll_pending_orders(self):
    """
    订单支付轮询任务
    触发条件：订单 status=pending 且创建时间 >= 3分钟，未超过 24小时
    轮询节奏：每5分钟执行一次（由 Celery Beat 调度）
    """
    SessionFactory = _get_sync_session_factory()
    db = SessionFactory()
    try:
        result = OrderService.poll_pending_orders(db)
        logger.info(f"订单轮询完成: checked={result.get('checked', 0)}, paid={result.get('paid', 0)}, expired={result.get('expired', 0)}, errors={result.get('errors', 0)}")
        return result
    except Exception as e:
        logger.info(f"订单轮询任务执行失败: {e}")
        raise
    finally:
        db.close()

