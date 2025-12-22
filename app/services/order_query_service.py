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
            # 根据支付方式获取对应的支付服务
            payment_service = PaymentServiceFactory.get_service(order.payment_method)
            
            # 查询支付状态
            result = payment_service.query_payment_status(db, order)
            
            # 简化日志：只记录一条，包含状态和是否更新
            status = result.get('status', 'unknown')
            updated = result.get('updated', False)
            logger.info(f"订单轮询: order_uuid={order.uuid}, status={status}, updated={updated}")
            
            return result
            
        except Exception as e:
            # 简化日志：只记录一条错误日志
            logger.info(f"订单轮询: order_uuid={order.uuid}, status=error, error={str(e)}")
            return {"status": "unknown", "updated": False, "error": str(e)}

