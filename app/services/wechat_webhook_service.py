"""
微信支付Webhook服务
处理微信支付回调通知
"""
import json
from typing import Dict, Any
from sqlalchemy.orm import Session
from app.models.order import Order
from app.services.order_service import OrderService
from app.services.subscription_service import SubscriptionService
from app.services.wechat_pay_client import wechat_pay_client
from app.core.logger import logger
from datetime import datetime, timezone


class WechatWebhookService:
    """微信支付Webhook服务"""
    
    @staticmethod
    def process_callback(db: Session, payload: Dict[str, Any], body_str: str) -> Dict[str, Any]:
        """
        处理微信支付回调
        
        Args:
            db: 数据库会话
            payload: 回调JSON数据
            body_str: 原始请求体（用于验签）
        
        Returns:
            处理结果
        """
        try:
            event_type = payload.get("event_type")
            
            # ========== WEBHOOK 处理日志 ==========
            logger.info("=" * 80)
            logger.info(f"🔄 [WECHAT WEBHOOK SERVICE] 开始处理回调")
            logger.info(f"   - 事件类型: {event_type}")
            logger.info(f"   - 完整 Payload:")
            logger.info(f"   {json.dumps(payload, indent=2, ensure_ascii=False)}")
            logger.info("=" * 80)
            
            if event_type == "TRANSACTION.SUCCESS":
                # 支付成功
                logger.info(f"✅ [WECHAT WEBHOOK SERVICE] 处理支付成功事件")
                result = WechatWebhookService._handle_transaction_success(db, payload)
                logger.info(f"✅ [WECHAT WEBHOOK SERVICE] 处理完成: {result}")
                return result
            else:
                logger.warning(f"⚠️ [WECHAT WEBHOOK SERVICE] 未处理的事件类型: {event_type}")
                return {"status": "ignored", "event_type": event_type}
                
        except Exception as e:
            logger.exception(f"❌ [WECHAT WEBHOOK SERVICE] 处理微信支付回调失败: {e}")
            raise
    
    @staticmethod
    def _handle_transaction_success(db: Session, payload: Dict[str, Any]) -> Dict[str, Any]:
        """处理支付成功回调"""
        logger.info(f"🔍 [WECHAT WEBHOOK SERVICE] 开始处理支付成功回调")
        
        # 解密resource数据
        resource = payload.get("resource", {})
        ciphertext = resource.get("ciphertext")
        associated_data = resource.get("associated_data", "")
        nonce = resource.get("nonce")
        
        logger.info(f"📦 [WECHAT WEBHOOK SERVICE] Resource 数据:")
        logger.info(f"   - ciphertext (前100字符): {ciphertext[:100] if ciphertext else 'N/A'}...")
        logger.info(f"   - associated_data: {associated_data}")
        logger.info(f"   - nonce: {nonce}")
        logger.info(f"   - 完整 resource: {json.dumps(resource, indent=2, ensure_ascii=False)}")
        
        if not ciphertext:
            raise ValueError("回调数据缺少ciphertext")
        
        # 解密
        logger.info(f"🔓 [WECHAT WEBHOOK SERVICE] 开始解密回调数据...")
        decrypted_data = wechat_pay_client.decrypt_callback_resource(
            ciphertext=ciphertext,
            associated_data=associated_data,
            nonce=nonce,
        )
        logger.info(f"✅ [WECHAT WEBHOOK SERVICE] 解密成功，解密后的数据:")
        logger.info(f"   {json.dumps(decrypted_data, indent=2, ensure_ascii=False)}")
        
        # 解析订单信息
        out_trade_no = decrypted_data.get("out_trade_no")  # 商户订单号
        transaction_id = decrypted_data.get("transaction_id")  # 微信支付订单号
        trade_state = decrypted_data.get("trade_state")  # 交易状态
        success_time = decrypted_data.get("success_time")  # 支付完成时间
        
        logger.info(f"📋 [WECHAT WEBHOOK SERVICE] 解析的订单信息:")
        logger.info(f"   - 商户订单号 (out_trade_no): {out_trade_no}")
        logger.info(f"   - 微信支付订单号 (transaction_id): {transaction_id}")
        logger.info(f"   - 交易状态 (trade_state): {trade_state}")
        logger.info(f"   - 支付完成时间 (success_time): {success_time}")
        
        if trade_state != "SUCCESS":
            logger.warning(f"订单 {out_trade_no} 交易状态不是SUCCESS: {trade_state}")
            return {"status": "ignored", "trade_state": trade_state}
        
        # 查询订单
        order = db.query(Order).filter(Order.order_number == out_trade_no).first()
        if not order:
            logger.error(f"订单不存在: out_trade_no={out_trade_no}")
            return {"status": "error", "message": "订单不存在"}
        
        # 解析支付时间
        paid_at = None
        if success_time:
            try:
                from dateutil import parser
                paid_at = parser.isoparse(success_time)
            except Exception as e:
                logger.warning(f"解析支付时间失败: {e}")
                paid_at = datetime.now(timezone.utc)
        else:
            paid_at = datetime.now(timezone.utc)
        
        # 处理订阅订单
        subscription_id = None
        if order.order_type == "subscription":
            # 微信订阅通过contract_id获取
            # 这里需要从回调数据中获取contract_id
            # 注意：Native支付可能不包含订阅信息，需要通过查询订单接口获取
            pass
        
        # 标记订单为已支付
        logger.info(f"💰 [WECHAT WEBHOOK SERVICE] 标记订单为已支付...")
        logger.info(f"   - 订单UUID: {order.uuid}")
        logger.info(f"   - 订单号: {order.order_number}")
        logger.info(f"   - 交易ID: {transaction_id}")
        logger.info(f"   - 支付时间: {paid_at}")
        logger.info(f"   - 订阅ID: {subscription_id}")
        
        OrderService.mark_paid(
            db=db,
            order=order,
            transaction_id=transaction_id,
            paid_at=paid_at,
            subscription_id=subscription_id,
        )
        
        logger.info(f"✅ [WECHAT WEBHOOK SERVICE] 微信支付回调处理成功")
        logger.info(f"   - 订单UUID: {order.uuid}")
        logger.info(f"   - 交易ID: {transaction_id}")
        logger.info("=" * 80)
        
        return {"status": "ok", "order_uuid": str(order.uuid)}

