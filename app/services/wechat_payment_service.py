"""
微信支付服务
处理微信支付的业务逻辑
"""
from typing import Dict, Any, Optional
from datetime import datetime, timezone
from sqlalchemy.orm import Session
from app.models.order import Order
from app.models.wechat_payment import WechatPayment
from app.services.wechat_pay_client import wechat_pay_client
from app.core.config import settings
from app.core.logger import logger


class WechatPaymentService:
    """微信支付服务"""
    
    def create_payment(
        self,
        db: Session,
        order: Order,
        success_url: Optional[str] = None,
        cancel_url: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        创建微信Native支付
        
        Args:
            db: 数据库会话
            order: 订单对象
            success_url: 支付成功回调URL（可选，微信支付使用notify_url）
            cancel_url: 支付取消回调URL（可选）
        
        Returns:
            支付信息字典，包含code_url等
        """
        # 构建商品描述
        description = f"{order.product.name} - {order.points_amount}积分"
        
        # 计算支付结束时间：20分钟后（RFC3339格式）
        # 格式：yyyy-MM-DDTHH:mm:ss+TIMEZONE
        from datetime import timedelta
        expire_time = datetime.now(timezone.utc) + timedelta(minutes=20)
        # 转换为北京时间（UTC+8）
        expire_time_beijing = expire_time + timedelta(hours=8)
        time_expire = expire_time_beijing.strftime("%Y-%m-%dT%H:%M:%S+08:00")
        
        # 调用微信支付API创建Native订单
        result = wechat_pay_client.create_native_order(
            description=description,
            out_trade_no=order.order_number,
            amount=order.amount,
            notify_url=settings.WECHAT_NOTIFY_URL,
            currency=order.currency,
            attach=str(order.uuid),  # 附加数据，传递订单UUID
            time_expire=time_expire,  # 支付结束时间：20分钟
        )
        
        code_url = result.get("code_url")
        prepay_id = result.get("prepay_id")
        
        # 准备 payment_metadata，保存完整的 API 响应
        payment_metadata = {
            "order_created_at": datetime.now(timezone.utc).isoformat(),
            "create_order_response": result,  # 保存完整的创建订单 API 响应
        }
        
        # 创建或更新微信支付详情
        wechat_payment = db.query(WechatPayment).filter(WechatPayment.order_id == order.order_id).first()
        if not wechat_payment:
            wechat_payment = WechatPayment(
                order_id=order.order_id,
                out_trade_no=order.order_number,
                code_url=code_url,
                prepay_id=prepay_id,
                payment_metadata=payment_metadata,
            )
            db.add(wechat_payment)
        else:
            wechat_payment.code_url = code_url
            wechat_payment.prepay_id = prepay_id
            # 合并 metadata（保留历史数据）
            if wechat_payment.payment_metadata:
                wechat_payment.payment_metadata.update(payment_metadata)
            else:
                wechat_payment.payment_metadata = payment_metadata
        
        db.commit()
        db.refresh(wechat_payment)
        
        logger.info(f"创建微信支付成功: order_uuid={order.uuid}, out_trade_no={order.order_number}")
        
        return {
            "code_url": code_url,
            "prepay_id": prepay_id,
        }
    
    def query_payment_status(self, db: Session, order: Order) -> Dict[str, Any]:
        """
        查询微信支付状态
        
        根据微信支付文档：
        - 订单支付成功后，商户可使用微信订单号查询订单或商户订单号查询订单
        - 若订单未支付，则只能使用商户订单号查询订单
        
        在轮询查询时，通常订单还未支付成功，所以只有商户订单号（out_trade_no），
        因此始终使用商户订单号查询接口。
        
        参考: https://pay.weixin.qq.com/doc/v3/merchant/4012791880
        
        Args:
            db: 数据库会话
            order: 订单对象
        
        Returns:
            支付状态信息
        """
        wechat_payment = order.wechat_payment
        if not wechat_payment:
            if settings.DEBUG:
                logger.debug(f"[DEBUG] 订单 {order.uuid} 没有微信支付记录，跳过查询")
            return {"status": "pending", "updated": False}
        
        try:
            # 轮询查询时，订单可能还未支付成功，只有商户订单号（out_trade_no）
            # 因此始终使用商户订单号查询接口
            if settings.DEBUG:
                logger.debug(f"[DEBUG] 开始查询微信支付状态（使用商户订单号）:")
                logger.debug(f"  订单UUID: {order.uuid}")
                logger.debug(f"  商户订单号: {order.order_number}")
                logger.debug(f"  查询API: GET /v3/pay/transactions/out-trade-no/{order.order_number}")
            
            # 使用商户订单号查询
            result = wechat_pay_client.query_order_by_out_trade_no(order.order_number)
            
            # Debug 模式下记录完整响应
            if settings.DEBUG:
                logger.debug(f"[DEBUG] 微信支付查询响应:")
                logger.debug(f"  订单UUID: {order.uuid}")
                logger.debug(f"  查询方法: 商户订单号")
                logger.debug(f"  完整响应: {result}")
            
            # 解析响应字段（根据文档：https://pay.weixin.qq.com/doc/v3/merchant/4012791879）
            trade_state = result.get("trade_state")  # SUCCESS, NOTPAY, CLOSED, REFUND, REVOKED, PAYERROR等
            transaction_id = result.get("transaction_id")  # 微信支付订单号
            out_trade_no = result.get("out_trade_no")  # 商户订单号
            success_time = result.get("success_time")  # 支付完成时间
            trade_state_desc = result.get("trade_state_desc")  # 交易状态描述
            
            # 更新支付详情（如果响应中有transaction_id，更新本地记录）
            if transaction_id and not wechat_payment.wechat_transaction_id:
                wechat_payment.wechat_transaction_id = transaction_id
                logger.info(f"订单 {order.uuid} 更新微信支付订单号: {transaction_id}")
            
            # 保存查询时的完整响应到 metadata
            if not wechat_payment.payment_metadata:
                wechat_payment.payment_metadata = {}
            
            # 保存查询历史
            query_history = wechat_payment.payment_metadata.get("query_history", [])
            query_history.append({
                "query_at": datetime.now(timezone.utc).isoformat(),
                "query_method": "商户订单号",  # 记录使用的查询方法
                "query_value": order.order_number,  # 记录查询值（商户订单号）
                "trade_state": trade_state,
                "trade_state_desc": trade_state_desc,  # 交易状态描述
                "transaction_id": transaction_id,  # 微信支付订单号（从响应中获取）
                "success_time": success_time,  # 支付完成时间
                "query_response": result,  # 保存完整的响应
            })
            # 只保留最近 10 次查询记录
            wechat_payment.payment_metadata["query_history"] = query_history[-10:]
            wechat_payment.payment_metadata["last_query_at"] = datetime.now(timezone.utc).isoformat()
            wechat_payment.payment_metadata["last_trade_state"] = trade_state
            wechat_payment.payment_metadata["last_trade_state_desc"] = trade_state_desc
            
            db.commit()
            
            # 转换状态（根据微信支付文档的trade_state值）
            # SUCCESS: 支付成功
            # NOTPAY: 未支付
            # CLOSED: 已关闭
            # REVOKED: 已撤销
            # USERPAYING: 用户支付中
            # PAYERROR: 支付失败
            # REFUND: 转入退款
            if trade_state == "SUCCESS":
                if settings.DEBUG:
                    logger.debug(f"[DEBUG] 订单 {order.uuid} 支付状态: paid (updated=True)")
                return {
                    "status": "paid", 
                    "updated": True, 
                    "trade_state": trade_state,
                    "trade_state_desc": trade_state_desc,
                    "success_time": success_time,
                    "transaction_id": transaction_id
                }
            elif trade_state == "NOTPAY":
                if settings.DEBUG:
                    logger.debug(f"[DEBUG] 订单 {order.uuid} 支付状态: pending (updated=False)")
                return {
                    "status": "pending", 
                    "updated": False, 
                    "trade_state": trade_state,
                    "trade_state_desc": trade_state_desc
                }
            elif trade_state == "CLOSED":
                if settings.DEBUG:
                    logger.debug(f"[DEBUG] 订单 {order.uuid} 支付状态: cancelled (updated=True)")
                return {
                    "status": "cancelled", 
                    "updated": True, 
                    "trade_state": trade_state,
                    "trade_state_desc": trade_state_desc
                }
            elif trade_state == "REVOKED":
                # 已撤销（用户主动撤销或系统撤销）
                if settings.DEBUG:
                    logger.debug(f"[DEBUG] 订单 {order.uuid} 支付状态: revoked (updated=True)")
                return {
                    "status": "cancelled", 
                    "updated": True, 
                    "trade_state": trade_state,
                    "trade_state_desc": trade_state_desc
                }
            elif trade_state == "USERPAYING":
                # 用户支付中（需要继续轮询）
                if settings.DEBUG:
                    logger.debug(f"[DEBUG] 订单 {order.uuid} 支付状态: userpaying (updated=False)")
                return {
                    "status": "pending", 
                    "updated": False, 
                    "trade_state": trade_state,
                    "trade_state_desc": trade_state_desc
                }
            elif trade_state == "PAYERROR":
                # 支付失败
                if settings.DEBUG:
                    logger.debug(f"[DEBUG] 订单 {order.uuid} 支付状态: payerror (updated=True)")
                return {
                    "status": "failed", 
                    "updated": True, 
                    "trade_state": trade_state,
                    "trade_state_desc": trade_state_desc
                }
            elif trade_state == "REFUND":
                # 转入退款（已支付但已退款）
                if settings.DEBUG:
                    logger.debug(f"[DEBUG] 订单 {order.uuid} 支付状态: refund (updated=False)")
                return {
                    "status": "refunded", 
                    "updated": False, 
                    "trade_state": trade_state,
                    "trade_state_desc": trade_state_desc
                }
            else:
                # 未知状态
                if settings.DEBUG:
                    logger.debug(f"[DEBUG] 订单 {order.uuid} 支付状态: {trade_state.lower()} (updated=False)")
                return {
                    "status": trade_state.lower(), 
                    "updated": False, 
                    "trade_state": trade_state,
                    "trade_state_desc": trade_state_desc
                }
                
        except Exception as e:
            logger.error(f"查询微信支付状态失败: order_uuid={order.uuid}, error={e}")
            if settings.DEBUG:
                logger.debug(f"[DEBUG] 查询失败详情: {str(e)}")
            return {"status": "unknown", "updated": False, "error": str(e)}
    
    def handle_callback(self, db: Session, order: Order, callback_data: Dict[str, Any]) -> bool:
        """
        处理微信支付回调
        
        Args:
            db: 数据库会话
            order: 订单对象
            callback_data: 回调数据（已解密）
        
        Returns:
            是否处理成功
        """
        try:
            event_type = callback_data.get("event_type")
            
            if event_type == "TRANSACTION.SUCCESS":
                # 支付成功
                resource = callback_data.get("resource", {})
                
                # 更新支付详情
                wechat_payment = order.wechat_payment
                if wechat_payment:
                    transaction_id = resource.get("transaction_id")
                    if transaction_id:
                        wechat_payment.wechat_transaction_id = transaction_id
                    
                    # 保存回调数据到 metadata
                    if not wechat_payment.payment_metadata:
                        wechat_payment.payment_metadata = {}
                    
                    callback_history = wechat_payment.payment_metadata.get("callback_history", [])
                    callback_history.append({
                        "callback_at": datetime.now(timezone.utc).isoformat(),
                        "event_type": event_type,
                        "callback_data": callback_data,  # 保存完整的回调数据
                    })
                    # 只保留最近 10 次回调记录
                    wechat_payment.payment_metadata["callback_history"] = callback_history[-10:]
                    wechat_payment.payment_metadata["last_callback_at"] = datetime.now(timezone.utc).isoformat()
                    
                    db.commit()
                
                return True
            else:
                logger.warning(f"未处理的微信支付事件类型: {event_type}")
                return False
                
        except Exception as e:
            logger.error(f"处理微信支付回调失败: order_uuid={order.uuid}, error={e}")
            return False

