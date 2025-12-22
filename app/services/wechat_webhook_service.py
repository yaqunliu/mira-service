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
            elif event_type in ("REFUND.SUCCESS", "REFUND.ABNORMAL", "REFUND.CLOSED"):
                # 退款回调
                logger.info(f"💸 [WECHAT WEBHOOK SERVICE] 处理退款事件: {event_type}")
                result = WechatWebhookService._handle_refund(db, payload, event_type)
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
        logger.info(f"   - 微信交易ID: {transaction_id}")
        logger.info(f"   - 支付时间: {paid_at}")
        logger.info(f"   - 订阅ID: {subscription_id}")
        
        OrderService.mark_paid(
            db=db,
            order=order,
            wechat_transaction_id=transaction_id,  # 使用正确的参数名
            paid_at=paid_at,
            # 注意：微信支付目前不支持订阅，subscription_id 参数不适用于微信支付
            # 如果将来支持微信订阅，可能需要添加 wechat_subscription_id 参数
        )
        
        logger.info(f"✅ [WECHAT WEBHOOK SERVICE] 微信支付回调处理成功")
        logger.info(f"   - 订单UUID: {order.uuid}")
        logger.info(f"   - 交易ID: {transaction_id}")
        logger.info("=" * 80)
        
        return {"status": "ok", "order_uuid": str(order.uuid)}
    
    @staticmethod
    def _handle_refund(db: Session, payload: Dict[str, Any], event_type: str) -> Dict[str, Any]:
        """
        处理退款回调
        参考文档: https://pay.weixin.qq.com/doc/v3/merchant/4012791886
        
        Args:
            db: 数据库会话
            payload: 回调JSON数据
            event_type: 事件类型 (REFUND.SUCCESS, REFUND.ABNORMAL, REFUND.CLOSED)
        
        Returns:
            处理结果
        """
        logger.info(f"🔍 [WECHAT WEBHOOK SERVICE] 开始处理退款回调: {event_type}")
        
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
        logger.info(f"🔓 [WECHAT WEBHOOK SERVICE] 开始解密退款回调数据...")
        decrypted_data = wechat_pay_client.decrypt_callback_resource(
            ciphertext=ciphertext,
            associated_data=associated_data,
            nonce=nonce,
        )
        logger.info(f"✅ [WECHAT WEBHOOK SERVICE] 解密成功，解密后的数据:")
        logger.info(f"   {json.dumps(decrypted_data, indent=2, ensure_ascii=False)}")
        
        # 解析退款信息
        out_trade_no = decrypted_data.get("out_trade_no")  # 商户订单号
        transaction_id = decrypted_data.get("transaction_id")  # 微信支付订单号
        out_refund_no = decrypted_data.get("out_refund_no")  # 商户退款单号
        refund_id = decrypted_data.get("refund_id")  # 微信支付退款单号
        refund_status = decrypted_data.get("refund_status")  # 退款状态
        success_time = decrypted_data.get("success_time")  # 退款成功时间
        amount_info = decrypted_data.get("amount", {})  # 金额信息
        refund_amount = amount_info.get("refund", 0)  # 退款金额（分）
        total_amount = amount_info.get("total", 0)  # 原订单金额（分）
        
        logger.info(f"📋 [WECHAT WEBHOOK SERVICE] 解析的退款信息:")
        logger.info(f"   - 商户订单号 (out_trade_no): {out_trade_no}")
        logger.info(f"   - 微信支付订单号 (transaction_id): {transaction_id}")
        logger.info(f"   - 商户退款单号 (out_refund_no): {out_refund_no}")
        logger.info(f"   - 微信支付退款单号 (refund_id): {refund_id}")
        logger.info(f"   - 退款状态 (refund_status): {refund_status}")
        logger.info(f"   - 退款成功时间 (success_time): {success_time}")
        logger.info(f"   - 退款金额 (refund): {refund_amount} 分")
        logger.info(f"   - 原订单金额 (total): {total_amount} 分")
        
        # 查询订单
        order = db.query(Order).filter(Order.order_number == out_trade_no).first()
        if not order:
            logger.error(f"❌ [WECHAT WEBHOOK SERVICE] 订单不存在: out_trade_no={out_trade_no}")
            return {"status": "error", "message": "订单不存在"}
        
        logger.info(f"📦 [WECHAT WEBHOOK SERVICE] 找到订单:")
        logger.info(f"   - 订单UUID: {order.uuid}")
        logger.info(f"   - 订单状态: {order.status}")
        logger.info(f"   - 订单类型: {order.order_type}")
        logger.info(f"   - 订单金额: {order.amount} 分")
        logger.info(f"   - 积分数量: {order.points_amount}")
        
        # 只处理退款成功的回调
        if event_type == "REFUND.SUCCESS" and refund_status == "SUCCESS":
            logger.info(f"💰 [WECHAT WEBHOOK SERVICE] 处理退款成功，开始扣除积分...")
            
            # 检查订单状态
            if order.status == "refunded":
                logger.warning(f"⚠️ [WECHAT WEBHOOK SERVICE] 订单已退款，跳过处理: order_uuid={order.uuid}")
                return {"status": "skipped", "message": "订单已退款"}
            
            if order.status != "paid":
                logger.warning(f"⚠️ [WECHAT WEBHOOK SERVICE] 订单状态不是已支付，跳过退款处理: order_uuid={order.uuid}, status={order.status}")
                return {"status": "ignored", "message": f"订单状态不是已支付: {order.status}"}
            
            # 计算退款比例和需要扣除的积分
            if total_amount <= 0:
                refund_ratio = 1.0
            else:
                refund_ratio = refund_amount / total_amount
            
            # 根据退款比例计算需要扣除的积分
            issued_points = order.points_amount
            if issued_points <= 0:
                can_deduct = 0
            else:
                can_deduct = int(issued_points * refund_ratio)
            
            logger.info(f"📊 [WECHAT WEBHOOK SERVICE] 退款计算:")
            logger.info(f"   - 退款比例: {refund_ratio:.2%}")
            logger.info(f"   - 已发放积分: {issued_points}")
            logger.info(f"   - 需要扣除积分: {can_deduct}")
            
            # 扣除积分（如果退款金额大于0）
            if can_deduct > 0:
                from app.services.points_service import PointsService
                account = PointsService.get_or_create_account(db, order.user_id)
                available_points = account.available_points
                
                # 实际可扣除的积分（不能超过可用积分）
                actual_deduct = min(can_deduct, available_points)
                
                if actual_deduct > 0:
                    logger.info(f"💸 [WECHAT WEBHOOK SERVICE] 扣除积分: {actual_deduct} (可用积分: {available_points})")
                    # 注意：deduct_points 方法不接受 record_type 参数，内部固定使用 "consume"
                    # 但退款应该使用 record_type="refund"，所以直接调用方法，record_type 会在 extra_data 中记录
                    PointsService.deduct_points(
                        db=db,
                        user_id=order.user_id,
                        points=actual_deduct,
                        operation_type="refund",
                        description=f"微信支付退款扣回积分 {order.uuid}",
                        extra_data={
                            "order_uuid": str(order.uuid),
                            "refund_ratio": refund_ratio,
                            "refund_id": refund_id,
                            "out_refund_no": out_refund_no,
                            "wechat_refund": True,
                            "actual_record_type": "refund",  # 在 extra_data 中记录实际类型
                        },
                    )
                    logger.info(f"✅ [WECHAT WEBHOOK SERVICE] 积分扣除成功: {actual_deduct}")
                else:
                    logger.warning(f"⚠️ [WECHAT WEBHOOK SERVICE] 用户可用积分不足，无法扣除: 需要={can_deduct}, 可用={available_points}")
            
            # 如果是订阅订单，取消订阅
            if order.order_type == "subscription" and order.subscription:
                logger.info(f"🚫 [WECHAT WEBHOOK SERVICE] 取消订阅: subscription_uuid={order.subscription.uuid}")
                
                # 微信订阅直接更新状态，不需要调用外部API
                if order.payment_method == "wechat":
                    subscription = order.subscription
                    subscription.status = "cancelled"
                    subscription.cancelled_at = datetime.now(timezone.utc)
                    subscription.cancel_at_period_end = False
                    db.commit()
                    logger.info(f"✅ [WECHAT WEBHOOK SERVICE] 微信订阅取消成功（直接更新状态）")
                else:
                    # Creem 订阅需要调用 API
                    SubscriptionService.cancel_subscription(
                        db=db,
                        user_id=order.user_id,
                        subscription_uuid=str(order.subscription.uuid),
                        cancel_at_period_end=False,
                    )
                    logger.info(f"✅ [WECHAT WEBHOOK SERVICE] Creem订阅取消成功")
            
            # 更新订单状态
            order.status = "refunded"
            order.order_metadata = order.order_metadata or {}
            order.order_metadata.update({
                "refund_amount": refund_amount,
                "refunded_points": can_deduct,
                "refund_ratio": refund_ratio,
                "refund_id": refund_id,
                "out_refund_no": out_refund_no,
                "refund_status": refund_status,
                "refund_time": success_time,
                "wechat_refund": True,
            })
            
            db.commit()
            db.refresh(order)
            
            logger.info(f"✅ [WECHAT WEBHOOK SERVICE] 退款处理成功")
            logger.info(f"   - 订单UUID: {order.uuid}")
            logger.info(f"   - 退款单号: {refund_id}")
            logger.info(f"   - 退款金额: {refund_amount} 分")
            logger.info(f"   - 扣除积分: {can_deduct}")
            logger.info("=" * 80)
            
            return {"status": "ok", "order_uuid": str(order.uuid), "refund_id": refund_id}
        
        elif event_type == "REFUND.ABNORMAL":
            # 退款异常：记录日志，但不处理业务逻辑
            logger.warning(f"⚠️ [WECHAT WEBHOOK SERVICE] 退款异常: refund_id={refund_id or 'N/A'}, out_trade_no={out_trade_no or 'N/A'}")
            logger.warning(f"   需要前往商户平台手动处理此笔退款")
            return {
                "status": "abnormal",
                "refund_id": refund_id,
                "out_trade_no": out_trade_no,
                "message": "退款异常，需要手动处理"
            }
        
        elif event_type == "REFUND.CLOSED":
            # 退款关闭：记录日志
            logger.info(f"ℹ️ [WECHAT WEBHOOK SERVICE] 退款关闭: refund_id={refund_id or 'N/A'}, out_trade_no={out_trade_no or 'N/A'}")
            return {
                "status": "closed",
                "refund_id": refund_id,
                "out_trade_no": out_trade_no,
                "message": "退款已关闭"
            }
        
        else:
            logger.warning(f"⚠️ [WECHAT WEBHOOK SERVICE] 未处理的退款状态: refund_status={refund_status}, event_type={event_type}")
            return {"status": "ignored", "refund_status": refund_status, "event_type": event_type}

