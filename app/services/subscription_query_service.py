"""
订阅查询服务 - 容错机制
查询订阅状态和签约关系
"""
from typing import Dict, Any
from sqlalchemy.orm import Session
from app.models.subscription import Subscription
from app.services.creem_client import creem_client
from app.services.wechat_pay_client import wechat_pay_client
from app.core.logger import logger
from datetime import datetime


class SubscriptionQueryService:
    """订阅查询服务"""
    
    @staticmethod
    def query_subscription_status(db: Session, subscription: Subscription) -> Dict[str, Any]:
        """
        查询订阅状态
        
        Args:
            db: 数据库会话
            subscription: 订阅对象
        
        Returns:
            查询结果，包含status和updated字段
        """
        try:
            if subscription.payment_method == "creem":
                return SubscriptionQueryService._query_creem_subscription(db, subscription)
            elif subscription.payment_method == "wechat":
                return SubscriptionQueryService._query_wechat_subscription(db, subscription)
            else:
                raise ValueError(f"不支持的支付方式: {subscription.payment_method}")
                
        except Exception as e:
            logger.error(f"查询订阅状态失败: subscription_uuid={subscription.uuid}, error={e}")
            return {"status": "unknown", "updated": False, "error": str(e)}
    
    @staticmethod
    def _query_creem_subscription(db: Session, subscription: Subscription) -> Dict[str, Any]:
        """查询Creem订阅状态"""
        creem_sub = subscription.creem_subscription
        if not creem_sub:
            return {"status": "unknown", "updated": False}
        
        try:
            # 查询订阅详情
            sub_data = creem_client.get_subscription(creem_sub.creem_subscription_id)
            
            # 使用统一的同步方法同步所有字段
            from app.services.subscription_service import SubscriptionService
            SubscriptionService.sync_from_creem_api(db, subscription, sub_data)
            
            db.commit()
            
            return {"status": subscription.status, "updated": True}
            
        except Exception as e:
            logger.error(f"查询Creem订阅状态失败: {e}")
            return {"status": subscription.status, "updated": False, "error": str(e)}
    
    @staticmethod
    def _query_wechat_subscription(db: Session, subscription: Subscription) -> Dict[str, Any]:
        """查询微信订阅状态（查询签约关系）"""
        wechat_sub = subscription.wechat_subscription
        if not wechat_sub or not wechat_sub.wechat_contract_id:
            return {"status": "unknown", "updated": False}
        
        try:
            # 查询签约关系
            # 注意：这里需要实现微信支付的查询签约关系接口
            # 由于微信支付查询签约关系使用的是V2 API（XML格式），需要单独实现
            # 这里先返回当前状态，后续实现
            
            # TODO: 实现微信支付查询签约关系接口
            # contract = wechat_pay_client.query_contract(wechat_sub.wechat_contract_id)
            # if contract.contract_state == 0:  # 0: 已签约
            #     subscription.status = "active"
            # elif contract.contract_state == 1:  # 1: 未签约（已解约）
            #     subscription.status = "cancelled"
            
            logger.warning("微信订阅查询签约关系接口待实现")
            return {"status": subscription.status, "updated": False}
            
        except Exception as e:
            logger.error(f"查询微信订阅状态失败: {e}")
            return {"status": subscription.status, "updated": False, "error": str(e)}

