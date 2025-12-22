"""
支付服务工厂 - 根据支付方式创建对应的支付服务
"""
from typing import Protocol
from app.models.order import Order
from app.core.logger import logger


class PaymentServiceProtocol(Protocol):
    """支付服务协议接口"""
    
    def create_payment(self, order: Order, **kwargs) -> dict:
        """创建支付，返回支付信息（如checkout_url或code_url）"""
        ...
    
    def query_payment_status(self, order: Order) -> dict:
        """查询支付状态"""
        ...
    
    def handle_callback(self, order: Order, callback_data: dict) -> bool:
        """处理支付回调，返回是否处理成功"""
        ...


class PaymentServiceFactory:
    """支付服务工厂"""
    
    @staticmethod
    def get_service(payment_method: str) -> PaymentServiceProtocol:
        """
        根据支付方式获取对应的支付服务
        
        Args:
            payment_method: 支付方式 (creem, wechat)
        
        Returns:
            支付服务实例
        """
        if payment_method == "creem":
            from app.services.creem_payment_service import CreemPaymentService
            return CreemPaymentService()
        elif payment_method == "wechat":
            from app.services.wechat_payment_service import WechatPaymentService
            return WechatPaymentService()
        else:
            raise ValueError(f"不支持的支付方式: {payment_method}")

