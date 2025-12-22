"""
订单查询服务 - 容错机制
当Webhook失败时，通过查询接口获取支付状态
"""
from typing import Dict, Any
from sqlalchemy.orm import Session
from app.models.order import Order
from app.services.payment_service_factory import PaymentServiceFactory
from app.core.logger import logger


class OrderQueryService:
    """订单查询服务"""
    
    @staticmethod
    def query_order_status(db: Session, order: Order) -> Dict[str, Any]:
        """
        查询订单支付状态
        
        Args:
            db: 数据库会话
            order: 订单对象
        
        Returns:
            查询结果，包含status和updated字段
        """
        from app.core.config import settings
        
        try:
            # Debug 模式下记录查询开始
            if settings.DEBUG:
                logger.debug(f"[DEBUG] ========== 开始查询订单支付状态 ==========")
                logger.debug(f"  订单UUID: {order.uuid}")
                logger.debug(f"  支付方式: {order.payment_method}")
                logger.debug(f"  订单状态: {order.status}")
                logger.debug(f"  订单号: {order.order_number}")
            
            # 根据支付方式获取对应的支付服务
            payment_service = PaymentServiceFactory.get_service(order.payment_method)
            
            if settings.DEBUG:
                logger.debug(f"  支付服务: {type(payment_service).__name__}")
            
            # 查询支付状态
            result = payment_service.query_payment_status(db, order)
            
            # Debug 模式下记录查询结果
            if settings.DEBUG:
                logger.debug(f"[DEBUG] 订单查询结果:")
                logger.debug(f"  订单UUID: {order.uuid}")
                logger.debug(f"  查询结果: {result}")
                logger.debug(f"[DEBUG] ========== 查询订单支付状态完成 ==========")
            
            logger.info(f"查询订单状态: order_uuid={order.uuid}, status={result.get('status')}, updated={result.get('updated')}")
            
            return result
            
        except Exception as e:
            logger.error(f"查询订单状态失败: order_uuid={order.uuid}, error={e}")
            if settings.DEBUG:
                logger.debug(f"[DEBUG] 查询异常详情: {str(e)}")
                import traceback
                logger.debug(f"[DEBUG] 异常堆栈: {traceback.format_exc()}")
            return {"status": "unknown", "updated": False, "error": str(e)}

