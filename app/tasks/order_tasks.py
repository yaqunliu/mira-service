"""
订单相关定时任务
"""
from datetime import datetime, timedelta, timezone
from sqlalchemy.orm import Session
from app.models.order import Order
from app.services.order_query_service import OrderQueryService
from app.services.order_service import OrderService
from app.core.logger import logger


def poll_pending_orders(db: Session, max_age_hours: int = 24) -> dict:
    """
    轮询待支付订单
    
    查询创建时间在3分钟前到24小时内的pending订单，调用支付平台查询接口
    """
    now = datetime.now(timezone.utc)
    min_age = now - timedelta(minutes=3)  # 至少3分钟后才查询
    max_age = now - timedelta(hours=max_age_hours)
    
    orders = (
        db.query(Order)
        .filter(Order.status == "pending")
        .filter(Order.created_at <= min_age)
        .filter(Order.created_at >= max_age)
        .all()
    )
    
    checked = 0
    paid = 0
    expired = 0
    errors = 0
    
    logger.info(f"开始轮询订单支付状态，找到 {len(orders)} 个待检查订单")
    
    for order in orders:
        try:
            checked += 1
            logger.info(f"检查订单: order_uuid={order.uuid}, payment_method={order.payment_method}")
            
            # 查询订单状态
            result = OrderQueryService.query_order_status(db, order)
            
            if result.get("status") == "paid" and result.get("updated"):
                # 订单已支付，状态已更新
                paid += 1
                logger.info(f"订单 {order.uuid} 支付成功，积分已发放")
            elif result.get("status") == "cancelled" and result.get("updated"):
                # 订单已取消
                expired += 1
            else:
                # 订单仍为pending或其他状态
                pass
            
            # 超过24小时未支付的订单标记为failed
            if order.created_at and (now - order.created_at) > timedelta(hours=max_age_hours):
                logger.warning(f"订单 {order.uuid} 超过 {max_age_hours} 小时未支付，标记为 failed")
                order.status = "failed"
                db.commit()
                expired += 1
                
        except Exception as e:
            errors += 1
            logger.exception(f"轮询订单支付失败 order_uuid={order.uuid}: {e}")
            db.rollback()
    
    return {"checked": checked, "paid": paid, "expired": expired, "errors": errors}

