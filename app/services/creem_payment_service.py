"""
Creem支付服务
处理Creem支付的业务逻辑
"""
from typing import Dict, Any, Optional
from datetime import datetime, timezone
from sqlalchemy.orm import Session
from app.models.order import Order
from app.models.creem_payment import CreemPayment
from app.services.creem_client import creem_client
from app.core.logger import logger
from app.core.config import settings


class CreemPaymentService:
    """Creem支付服务"""
    
    def create_payment(
        self,
        db: Session,
        order: Order,
        success_url: Optional[str] = None,
        cancel_url: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        创建Creem支付
        
        Args:
            db: 数据库会话
            order: 订单对象
            success_url: 支付成功回调URL
            cancel_url: 支付取消回调URL
        
        Returns:
            支付信息字典，包含checkout_url等
        """
        # 如果success_url存在，自动添加order_uuid参数
        final_success_url = success_url or order.success_url
        if final_success_url and "order_uuid" not in final_success_url:
            separator = "&" if "?" in final_success_url else "?"
            final_success_url = f"{final_success_url}{separator}order_uuid={order.uuid}"
        
        # 调用Creem API创建checkout session
        if not order.product.origin_product_id:
            raise ValueError("产品未配置远程产品ID（origin_product_id）")
        
        checkout = creem_client.create_checkout_session(
            creem_product_id=order.product.origin_product_id,
            success_url=final_success_url,
        )
        
        checkout_id = checkout.get("id") or checkout.get("checkout_id")
        checkout_url = checkout.get("checkout_url") or checkout.get("url")
        
        # 准备 payment_metadata，保存完整的 API 响应
        payment_metadata = {
            "checkout_created_at": datetime.now(timezone.utc).isoformat(),
            "checkout_response": checkout,  # 保存完整的 checkout API 响应
        }
        
        # 创建或更新Creem支付详情
        creem_payment = db.query(CreemPayment).filter(CreemPayment.order_id == order.order_id).first()
        if not creem_payment:
            creem_payment = CreemPayment(
                order_id=order.order_id,
                creem_checkout_id=checkout_id,
                checkout_url=checkout_url,
                payment_metadata=payment_metadata,
            )
            db.add(creem_payment)
        else:
            creem_payment.creem_checkout_id = checkout_id
            creem_payment.checkout_url = checkout_url
            # 合并 metadata（保留历史数据）
            if creem_payment.payment_metadata:
                creem_payment.payment_metadata.update(payment_metadata)
            else:
                creem_payment.payment_metadata = payment_metadata
        
        db.commit()
        db.refresh(creem_payment)
        
        logger.info(f"创建Creem支付成功: order_uuid={order.uuid}, checkout_id={checkout_id}")
        
        return {
            "checkout_url": checkout_url,
            "checkout_id": checkout_id,
        }
    
    def query_payment_status(self, db: Session, order: Order) -> Dict[str, Any]:
        """
        查询Creem支付状态
        
        Args:
            db: 数据库会话
            order: 订单对象
        
        Returns:
            支付状态信息
        """
        from app.core.config import settings
        
        creem_payment = order.creem_payment
        if not creem_payment or not creem_payment.creem_checkout_id:
            if settings.DEBUG:
                logger.debug(f"[DEBUG] 订单 {order.uuid} 没有 checkout_id，跳过查询")
            return {"status": "pending", "updated": False}
        
        try:
            # Debug 模式下记录查询详情
            if settings.DEBUG:
                logger.debug(f"[DEBUG] 开始查询Creem支付状态:")
                logger.debug(f"  订单UUID: {order.uuid}")
                logger.debug(f"  Checkout ID: {creem_payment.creem_checkout_id}")
                logger.debug(f"  查询API: GET /v1/checkouts?checkout_id={creem_payment.creem_checkout_id}")
            
            # 查询Checkout Session
            checkout = creem_client.get_checkout(creem_payment.creem_checkout_id)
            
            # Debug 模式下记录完整响应
            if settings.DEBUG:
                logger.debug(f"[DEBUG] Creem支付查询响应:")
                logger.debug(f"  订单UUID: {order.uuid}")
                logger.debug(f"  完整响应: {checkout}")
            
            checkout_status = checkout.get("status")  # pending, processing, completed, expired
            checkout_order = checkout.get("order")
            
            # 判断支付状态（根据 Creem API 文档）：
            # 1. checkout.status == "completed" 表示支付完成（主要判断）
            # 2. order.transaction 存在（有交易ID）表示已支付
            # 3. order.amount_paid > 0 且 amount_paid >= amount_due 表示已支付
            # 注意：order.status 可能是 "pending" 即使支付已完成，所以不能仅依赖它
            is_paid = False
            if checkout_status == "completed":
                is_paid = True
            elif isinstance(checkout_order, dict):
                transaction_id = checkout_order.get("transaction")
                amount_paid = checkout_order.get("amount_paid")
                amount_due = checkout_order.get("amount_due")
                
                # 有交易ID表示已支付
                if transaction_id:
                    is_paid = True
                # 或者已支付金额 >= 应付金额
                elif (amount_paid is not None and 
                      amount_due is not None and 
                      amount_paid > 0 and 
                      amount_paid >= amount_due):
                    is_paid = True
            
            if is_paid:
                # 更新支付详情
                if isinstance(checkout_order, dict):
                    creem_payment.creem_transaction_id = checkout_order.get("transaction") or checkout_order.get("id")
                
                # 保存查询时的完整响应到 metadata
                if not creem_payment.payment_metadata:
                    creem_payment.payment_metadata = {}
                
                # 保存查询历史
                query_history = creem_payment.payment_metadata.get("query_history", [])
                query_history.append({
                    "query_at": datetime.now(timezone.utc).isoformat(),
                    "checkout_status": checkout_status,
                    "checkout_response": checkout,  # 保存完整的响应
                })
                # 只保留最近 10 次查询记录
                creem_payment.payment_metadata["query_history"] = query_history[-10:]
                creem_payment.payment_metadata["last_query_at"] = datetime.now(timezone.utc).isoformat()
                creem_payment.payment_metadata["last_checkout_status"] = checkout_status
                
                db.commit()
                
                if settings.DEBUG:
                    logger.debug(f"[DEBUG] 订单 {order.uuid} 支付状态: paid (updated=True)")
                
                return {"status": "paid", "updated": True, "checkout_status": checkout_status}
            else:
                if settings.DEBUG:
                    logger.debug(f"[DEBUG] 订单 {order.uuid} 支付状态: {checkout_status} (updated=False)")
                
                return {"status": checkout_status, "updated": False}
                
        except Exception as e:
            logger.error(f"查询Creem支付状态失败: order_uuid={order.uuid}, error={e}")
            if settings.DEBUG:
                logger.debug(f"[DEBUG] 查询失败详情: {str(e)}")
            return {"status": "unknown", "updated": False, "error": str(e)}
    
    def handle_callback(self, db: Session, order: Order, callback_data: Dict[str, Any]) -> bool:
        """
        处理Creem支付回调
        
        Args:
            db: 数据库会话
            order: 订单对象
            callback_data: 回调数据
        
        Returns:
            是否处理成功
        """
        try:
            event_type = callback_data.get("type") or callback_data.get("event_type")
            
            if event_type in ("checkout.session.completed", "checkout.completed"):
                # 支付成功
                data = callback_data.get("data") or callback_data
                
                # 更新支付详情
                creem_payment = order.creem_payment
                if creem_payment:
                    checkout_order = data.get("order")
                    if isinstance(checkout_order, dict):
                        creem_payment.creem_transaction_id = checkout_order.get("transaction") or checkout_order.get("id")
                    
                    # 保存回调数据到 metadata
                    if not creem_payment.payment_metadata:
                        creem_payment.payment_metadata = {}
                    
                    callback_history = creem_payment.payment_metadata.get("callback_history", [])
                    callback_history.append({
                        "callback_at": datetime.now(timezone.utc).isoformat(),
                        "event_type": event_type,
                        "callback_data": callback_data,  # 保存完整的回调数据
                    })
                    # 只保留最近 10 次回调记录
                    creem_payment.payment_metadata["callback_history"] = callback_history[-10:]
                    creem_payment.payment_metadata["last_callback_at"] = datetime.now(timezone.utc).isoformat()
                    
                    db.commit()
                
                return True
            else:
                logger.warning(f"未处理的Creem事件类型: {event_type}")
                return False
                
        except Exception as e:
            logger.error(f"处理Creem支付回调失败: order_uuid={order.uuid}, error={e}")
            return False

