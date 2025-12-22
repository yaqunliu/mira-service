import json
from datetime import datetime
from typing import Any, Dict, Optional
from sqlalchemy.orm import Session
from fastapi import HTTPException, status
from app.models.webhook_event import WebhookEvent
from app.models.order import Order
from app.services.order_service import OrderService
from app.services.subscription_service import SubscriptionService
from app.models.subscription import Subscription
from app.core.logger import logger


class WebhookService:
    @staticmethod
    def record_event(db: Session, event_type: str, creem_event_id: Optional[str], payload: Dict[str, Any], source: str = "webhook") -> WebhookEvent:
        existing = None
        if creem_event_id:
            existing = db.query(WebhookEvent).filter(WebhookEvent.creem_event_id == creem_event_id).first()
            if existing:
                return existing

        event = WebhookEvent(
            event_type=event_type,
            creem_event_id=creem_event_id,
            payload=payload,
            source=source,
            processed=False,
        )
        db.add(event)
        db.commit()
        db.refresh(event)
        return event

    @staticmethod
    def mark_processed(db: Session, event: WebhookEvent):
        event.processed = True
        event.processed_at = datetime.utcnow()
        db.commit()

    @staticmethod
    def process_event(db: Session, payload: Dict[str, Any]):
        # ========== WEBHOOK 处理日志 ==========
        logger.info("=" * 80)
        logger.info(f"🔄 [CREEM WEBHOOK SERVICE] 开始处理事件")
        logger.info(f"   - 完整 Payload:")
        logger.info(f"   {json.dumps(payload, indent=2, ensure_ascii=False)}")
        logger.info("=" * 80)
        
        # 支持多种事件类型字段名：eventType, type, event
        event_type = payload.get("eventType") or payload.get("type") or payload.get("event")
        # 支持多种事件ID字段名：id, event_id
        creem_event_id = payload.get("id") or payload.get("event_id")
        
        logger.info(f"📋 [CREEM WEBHOOK SERVICE] 解析的事件信息:")
        logger.info(f"   - 事件类型: {event_type}")
        logger.info(f"   - 事件ID: {creem_event_id}")
        
        if not event_type:
            logger.error(f"❌ [CREEM WEBHOOK SERVICE] 缺少事件类型")
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="缺少事件类型")

        event = WebhookService.record_event(db, event_type, creem_event_id, payload, source="webhook")
        if event.processed:
            logger.info(f"⏭️ [CREEM WEBHOOK SERVICE] 事件已处理，跳过: {creem_event_id or event.uuid}")
            return {"status": "skipped"}

        try:
            logger.info(f"🎯 [CREEM WEBHOOK SERVICE] 路由到对应的事件处理器: {event_type}")
            if event_type in ("checkout.session.completed", "checkout.completed"):
                logger.info(f"💰 [CREEM WEBHOOK SERVICE] 处理支付完成事件")
                WebhookService._handle_checkout_completed(db, payload)
            elif event_type == "checkout.session.failed":
                logger.info(f"❌ [CREEM WEBHOOK SERVICE] 处理支付失败事件")
                WebhookService._handle_checkout_failed(db, payload)
            elif event_type in ("invoice.paid", "subscription.paid"):
                logger.info(f"💳 [CREEM WEBHOOK SERVICE] 处理发票/订阅支付事件")
                WebhookService._handle_invoice_paid(db, payload)
            elif event_type in (
                "subscription.created",
                "subscription.updated",
                "subscription.update",
                "subscription.active",
                "subscription.trialing",
                "subscription.past_due",
                "subscription.unpaid",
                "subscription.paused",
                "subscription.expired",
            ):
                logger.info(f"📝 [CREEM WEBHOOK SERVICE] 处理订阅更新事件")
                WebhookService._handle_subscription_update(db, payload)
            elif event_type in ("subscription.cancelled", "subscription.canceled"):
                logger.info(f"🚫 [CREEM WEBHOOK SERVICE] 处理订阅取消事件")
                WebhookService._handle_subscription_cancelled(db, payload)
            elif event_type == "subscription.scheduled_cancel":
                logger.info(f"⏰ [CREEM WEBHOOK SERVICE] 处理订阅计划取消事件")
                WebhookService._handle_subscription_scheduled_cancel(db, payload)
            elif event_type == "refund.created":
                logger.info(f"💸 [CREEM WEBHOOK SERVICE] 处理退款创建事件")
                WebhookService._handle_refund_created(db, payload)
            elif event_type == "dispute.created":
                logger.info(f"⚠️ [CREEM WEBHOOK SERVICE] 收到争议创建事件，目前仅记录事件，不做业务处理")
            else:
                logger.warning(f"⚠️ [CREEM WEBHOOK SERVICE] 未处理的事件类型: {event_type}")
        except Exception as e:
            logger.exception(f"❌ [CREEM WEBHOOK SERVICE] 处理 Webhook 事件失败: {e}")
            event.error_message = str(e)
            db.commit()
            raise
        else:
            WebhookService.mark_processed(db, event)
            logger.info(f"✅ [CREEM WEBHOOK SERVICE] 事件处理完成并标记为已处理")
            logger.info("=" * 80)
        return {"status": "ok"}

    @staticmethod
    def _handle_checkout_completed(db: Session, payload: Dict[str, Any]):
        # 支持 payload.object 格式（Creem 实际格式）
        data = payload.get("object") or payload.get("data") or {}
        
        # checkout_id: object.id
        checkout_id = data.get("id") or WebhookService._get(data, ["checkout_id", "checkout_session_id"])
        
        # order_uuid: 可能在 metadata 中，也可能需要通过 order.id 查找
        order_uuid = WebhookService._get(data, ["metadata", "order_uuid"])
        
        # order_id: object.order.id (Creem 订单ID)
        creem_order_id = WebhookService._get(data, ["order", "id"])
        
        # transaction_id: object.order.transaction
        creem_transaction_id = (
            WebhookService._get(data, ["order", "transaction"]) or
            data.get("transaction_id") or
            WebhookService._get(data, ["transaction"])
        )
        
        # subscription_id: object.subscription.id (可能是对象或字符串)
        subscription_obj = data.get("subscription")
        if isinstance(subscription_obj, dict):
            subscription_id = subscription_obj.get("id")
        else:
            subscription_id = subscription_obj or WebhookService._get(data, ["subscription_id", "subscriptionId"])
        
        status = data.get("status") or "completed"
        paid_at = WebhookService._parse_datetime(
            WebhookService._get(data, ["order", "updated_at"]) or
            WebhookService._get(data, ["paid_at", "created_at", "created"])
        )

        # 查找订单：优先通过 order_uuid，其次通过 checkout_id（从CreemPayment表查询）
        order = None
        if order_uuid:
            order = db.query(Order).filter(Order.uuid == order_uuid).first()
        if not order and checkout_id:
            # 通过CreemPayment表查询
            from app.models.creem_payment import CreemPayment
            creem_payment = db.query(CreemPayment).filter(CreemPayment.creem_checkout_id == checkout_id).first()
            if creem_payment:
                order = creem_payment.order
        if not order:
            logger.warning(f"checkout.completed 找不到订单: checkout_id={checkout_id}, creem_order_id={creem_order_id}, order_uuid={order_uuid}")
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="订单不存在")

        # 保存 webhook 数据到 order_metadata
        if not order.order_metadata:
            order.order_metadata = {}
        
        webhook_history = order.order_metadata.get("webhook_history", [])
        webhook_history.append({
            "webhook_at": datetime.utcnow().isoformat(),
            "event_type": "checkout.completed",
            "webhook_payload": payload,  # 保存完整的 webhook payload
        })
        # 只保留最近 10 次 webhook 记录
        order.order_metadata["webhook_history"] = webhook_history[-10:]
        order.order_metadata["last_webhook_at"] = datetime.utcnow().isoformat()
        order.order_metadata["paid_via_webhook"] = True
        
        # 标记订单为已支付（如果是订阅订单，mark_paid 内部会创建订阅记录并发放首期积分）
        OrderService.mark_paid(
            db=db,
            order=order,
            transaction_id=creem_transaction_id,
            paid_at=paid_at,
            subscription_id=subscription_id,
        )

        # 若为订阅，更新订阅信息（mark_paid 已创建订阅记录，这里只需要更新周期信息）
        if order.order_type == "subscription" and subscription_id:
            subscription = (
                db.query(Subscription)
                .filter(Subscription.order_id == order.order_id)
                .first()
            )
            
            if subscription:
                # 如果订阅ID存在，尝试从 webhook payload 或 Creem API 获取完整订阅信息
                subscription_obj = data.get("subscription")
                if isinstance(subscription_obj, dict):
                    # 从 webhook payload 中获取订阅信息
                    subscription.current_period_start = WebhookService._parse_datetime(
                        subscription_obj.get("current_period_start_date")
                    ) or subscription.current_period_start
                    subscription.current_period_end = WebhookService._parse_datetime(
                        subscription_obj.get("current_period_end_date")
                    ) or subscription.current_period_end
                    subscription.next_billing_date = WebhookService._parse_datetime(
                        subscription_obj.get("next_transaction_date")
                    ) or subscription.next_billing_date
                    db.commit()
                    logger.info(f"从 webhook payload 同步订阅信息成功: subscription_id={subscription_id}")
                elif subscription.payment_method == "creem":
                    # 如果 webhook 中没有订阅信息，尝试从 Creem API 获取
                    try:
                        from app.services.creem_client import creem_client
                        creem_sub = creem_client.get_subscription(subscription_id)
                        # 使用统一的同步方法同步所有字段
                        SubscriptionService.sync_from_creem_api(db, subscription, creem_sub)
                        db.commit()
                        logger.info(f"从 Creem API 同步订阅信息成功: subscription_id={subscription_id}")
                    except Exception as e:
                        logger.warning(f"从 Creem API 获取订阅详情失败: {e}")
                
                # 注意：首期积分已在 OrderService.mark_paid 中发放，这里不需要再次发放

    @staticmethod
    def _handle_checkout_failed(db: Session, payload: Dict[str, Any]):
        from app.models.creem_payment import CreemPayment
        data = payload.get("data") or payload.get("object") or {}
        checkout_id = WebhookService._get(data, ["id", "checkout_id"])
        order_uuid = WebhookService._get(data, ["metadata", "order_uuid"])
        order = None
        if order_uuid:
            order = db.query(Order).filter(Order.uuid == order_uuid).first()
        if not order and checkout_id:
            # 通过 creem_payments 表查找订单
            creem_payment = db.query(CreemPayment).filter(CreemPayment.creem_checkout_id == checkout_id).first()
            if creem_payment:
                order = creem_payment.order
        if not order:
            return
        order.status = "failed"
        db.commit()

    @staticmethod
    def _handle_subscription_update(db: Session, payload: Dict[str, Any]):
        # 支持 payload.object 格式（Creem 实际格式）
        data = payload.get("object") or payload.get("data") or {}
        subscription_id = data.get("id") or WebhookService._get(data, ["subscription_id"])
        order_uuid = WebhookService._get(data, ["metadata", "order_uuid"])
        status_value = data.get("status")
        period_start = WebhookService._parse_datetime(
            data.get("current_period_start_date") or WebhookService._get(data, ["current_period_start"])
        )
        period_end = WebhookService._parse_datetime(
            data.get("current_period_end_date") or WebhookService._get(data, ["current_period_end"])
        )
        next_billing = WebhookService._parse_datetime(
            data.get("next_transaction_date") or WebhookService._get(data, ["next_billing_date"])
        )

        subscription = (
            db.query(Subscription)
            .filter(Subscription.creem_subscription_id == subscription_id)
            .first()
        )
        order = subscription.order if subscription else None
        if not order and order_uuid:
            order = db.query(Order).filter(Order.uuid == order_uuid).first()
        
        # 如果找不到订阅和订单，尝试通过订阅ID查找订单（订阅可能已存在）
        if not order and subscription:
            order = subscription.order
        
        if not order and subscription is None:
            # 无法找到关联订单，跳过（可能是首次创建，等待 checkout.completed 事件）
            logger.warning(f"subscription.update 找不到订阅和订单: subscription_id={subscription_id}, order_uuid={order_uuid}")
            return

        # 如果订阅不存在，需要订单来创建；如果订阅存在，使用现有订阅的订单
        if not subscription and not order:
            logger.warning(f"subscription.update 无法创建订阅，缺少订单信息: subscription_id={subscription_id}")
            return

        # 处理状态映射：将 Creem 的状态映射到本地状态
        status_mapping = {
            "trialing": "active",  # 试用期视为活跃
            "active": "active",
            "past_due": "past_due",
            "unpaid": "unpaid",
            "paused": "paused",
            "expired": "expired",
            "canceled": "cancelled",  # 统一使用 cancelled
            "cancelled": "cancelled",
        }
        mapped_status = status_mapping.get(status_value, status_value or (subscription.status if subscription else "active"))
        
        subscription = SubscriptionService.upsert_from_webhook(
            db=db,
            user_id=order.user_id,
            order=order,
            payment_method="creem",  # Creem订阅
            subscription_id=subscription_id,
            status=mapped_status,
            billing_period=order.product.billing_period if order else (subscription.billing_period if subscription else None),
            current_period_start=period_start,
            current_period_end=period_end,
            next_billing_date=next_billing,
            points_per_period=order.points_amount if order else (subscription.points_per_period if subscription else 0),
            metadata=data.get("metadata"),
        )
        
        # 如果状态是 expired 或 cancelled，更新 cancelled_at
        if mapped_status in ("expired", "cancelled") and not subscription.cancelled_at:
            canceled_at = WebhookService._parse_datetime(data.get("canceled_at"))
            subscription.cancelled_at = canceled_at or datetime.utcnow()
        
        # 保存 webhook 数据到 subscription_metadata
        if not subscription.subscription_metadata:
            subscription.subscription_metadata = {}
        
        webhook_history = subscription.subscription_metadata.get("webhook_history", [])
        webhook_history.append({
            "webhook_at": datetime.utcnow().isoformat(),
            "event_type": "subscription.update",
            "webhook_payload": payload,  # 保存完整的 webhook payload
        })
        # 只保留最近 10 次 webhook 记录
        subscription.subscription_metadata["webhook_history"] = webhook_history[-10:]
        subscription.subscription_metadata["last_webhook_at"] = datetime.utcnow().isoformat()
        
        db.commit()
        logger.info(f"订阅更新: subscription_id={subscription_id}, status={mapped_status}")

    @staticmethod
    def _handle_subscription_cancelled(db: Session, payload: Dict[str, Any]):
        # 支持 payload.object 格式（Creem 实际格式）
        data = payload.get("object") or payload.get("data") or {}
        subscription_id = data.get("id") or WebhookService._get(data, ["subscription_id"])
        # 通过CreemSubscription表查询订阅
        from app.models.creem_subscription import CreemSubscription
        creem_sub = db.query(CreemSubscription).filter(CreemSubscription.creem_subscription_id == subscription_id).first()
        subscription = creem_sub.subscription if creem_sub else None
        if subscription:
            # 使用 webhook 中的状态（可能是 canceled 或 cancelled）
            status_value = data.get("status")
            if status_value in ("canceled", "cancelled"):
                subscription.status = "cancelled"
            else:
                subscription.status = "cancelled"  # 默认设为 cancelled
            
            # 如果 webhook 中有 canceled_at，使用它；否则使用当前时间
            canceled_at = WebhookService._parse_datetime(data.get("canceled_at"))
            subscription.cancelled_at = canceled_at or datetime.utcnow()
            subscription.cancel_at_period_end = False  # 已取消，不是计划取消
            db.commit()
            logger.info(f"订阅已取消: subscription_id={subscription_id}, canceled_at={subscription.cancelled_at}")

    @staticmethod
    def _handle_subscription_scheduled_cancel(db: Session, payload: Dict[str, Any]):
        # 支持 payload.object 格式（Creem 实际格式）
        data = payload.get("object") or payload.get("data") or {}
        subscription_id = data.get("id") or WebhookService._get(data, ["subscription_id"])
        # 通过CreemSubscription表查询订阅
        from app.models.creem_subscription import CreemSubscription
        creem_sub = db.query(CreemSubscription).filter(CreemSubscription.creem_subscription_id == subscription_id).first()
        subscription = creem_sub.subscription if creem_sub else None
        if subscription:
            subscription.cancel_at_period_end = True
            # 如果状态是 scheduled_cancel，保持 active 状态（在周期结束时取消）
            if data.get("status") == "scheduled_cancel":
                subscription.status = "active"
            else:
                subscription.status = subscription.status or "active"
            db.commit()
            logger.info(f"订阅计划取消: subscription_id={subscription_id}, cancel_at_period_end=True")

    @staticmethod
    def _handle_invoice_paid(db: Session, payload: Dict[str, Any]):
        # 支持 payload.object 格式（Creem 实际格式）
        data = payload.get("object") or payload.get("data") or {}
        
        # 订阅ID：可能在 object.id 或 object.subscription 或 last_transaction.subscription
        subscription_id = (
            data.get("id") or  # object.id (订阅ID)
            WebhookService._get(data, ["subscription_id", "subscription"]) or
            WebhookService._get(data, ["last_transaction", "subscription"])
        )
        
        # 发票/交易ID：可能在 object.last_transaction.id 或 object.last_transaction_id
        invoice_id = (
            WebhookService._get(data, ["last_transaction", "id"]) or
            data.get("last_transaction_id") or
            WebhookService._get(data, ["id", "invoice_id"])
        )
        
        # 周期信息：优先从 last_transaction 获取，其次从 object 直接获取
        period_start = (
            WebhookService._parse_datetime(WebhookService._get(data, ["last_transaction", "period_start"])) or
            WebhookService._parse_datetime(WebhookService._get(data, ["current_period_start_date"])) or
            WebhookService._parse_datetime(WebhookService._get(data, ["period_start", "current_period_start"]))
        )
        period_end = (
            WebhookService._parse_datetime(WebhookService._get(data, ["last_transaction", "period_end"])) or
            WebhookService._parse_datetime(WebhookService._get(data, ["current_period_end_date"])) or
            WebhookService._parse_datetime(WebhookService._get(data, ["period_end", "current_period_end"]))
        )

        # 通过CreemSubscription表查询订阅
        from app.models.creem_subscription import CreemSubscription
        creem_sub = db.query(CreemSubscription).filter(CreemSubscription.creem_subscription_id == subscription_id).first()
        subscription = creem_sub.subscription if creem_sub else None
        if not subscription:
            logger.warning(f"invoice.paid 找不到订阅 {subscription_id}")
            return
        order = subscription.order

        # 若事件未提供周期边界，按订阅锚日计算当月周期（支持年付按月发放）
        if not period_start or not period_end:
            anchor_day = SubscriptionService._anchor_day(subscription, order)
            period_start, period_end = SubscriptionService._period_for_month(anchor_day, datetime.utcnow())

        subscription.status = "active"
        subscription.current_period_start = period_start or subscription.current_period_start
        subscription.current_period_end = period_end or subscription.current_period_end
        subscription.next_billing_date = WebhookService._parse_datetime(
            data.get("next_transaction_date") or WebhookService._get(data, ["next_billing_date"])
        ) or subscription.next_billing_date
        # 更新 metadata（如果 webhook 中有）
        if data.get("metadata"):
            subscription.subscription_metadata = data.get("metadata")

        SubscriptionService.issue_cycle_points(
            db=db,
            subscription=subscription,
            order=order,
            period_start=period_start or datetime.utcnow(),
            period_end=period_end or datetime.utcnow(),
            invoice_id=invoice_id,  # 使用通用invoice_id参数
        )
        db.commit()

    @staticmethod
    def _get(data: Dict[str, Any], path: list):
        cur = data
        for key in path:
            if isinstance(cur, dict) and key in cur:
                cur = cur[key]
            else:
                return None
        return cur

    @staticmethod
    def _handle_refund_created(db: Session, payload: Dict[str, Any]):
        """
        处理退款事件
        根据退款金额和订单信息，扣除相应积分并更新订单状态
        """
        # 支持 payload.object 格式（Creem 实际格式）
        data = payload.get("object") or payload.get("data") or {}
        
        # 退款ID
        refund_id = data.get("id")
        
        # 订单ID：可能在 object.order.id 或 object.transaction.order
        order_id = (
            WebhookService._get(data, ["order", "id"]) or
            WebhookService._get(data, ["transaction", "order"])
        )
        
        # 退款金额
        refund_amount = data.get("refund_amount") or 0
        refund_currency = data.get("refund_currency") or "USD"
        refund_status = data.get("status") or "succeeded"
        
        if not order_id:
            logger.warning(f"refund.created 缺少订单ID: refund_id={refund_id}")
            return
        
        # 查找订单（通过 Creem 订单ID，需要添加 creem_order_id 字段或通过其他方式查找）
        # 注意：当前 Order 模型没有 creem_order_id 字段，可能需要通过其他方式关联
        # 暂时记录日志，等待后续实现
        logger.info(
            f"收到退款事件: refund_id={refund_id}, order_id={order_id}, "
            f"refund_amount={refund_amount}, status={refund_status}"
        )
        
        # TODO: 实现退款逻辑
        # 1. 通过 order_id 查找订单（需要添加 creem_order_id 字段或通过 metadata 关联）
        # 2. 计算可扣回积分
        # 3. 扣除积分
        # 4. 更新订单状态为 refunded
        # 5. 如果是订阅，取消订阅
        
        # 目前仅记录事件，等待订单模型支持 creem_order_id 或通过其他方式关联
        logger.warning(f"refund.created 事件暂未实现自动处理，需要手动处理: order_id={order_id}")

    @staticmethod
    def _parse_datetime(value: Any) -> Optional[datetime]:
        if not value:
            return None
        if isinstance(value, datetime):
            return value
        try:
            # 尝试解析 ISO 格式字符串
            if isinstance(value, str):
                # 处理 ISO 格式：2025-12-17T07:21:51.538Z
                iso_str = value.replace("Z", "+00:00")
                return datetime.fromisoformat(iso_str)
        except Exception:
            pass
        try:
            # 尝试解析时间戳（支持秒和毫秒）
            timestamp = float(value)
            # 如果时间戳大于 1e10，认为是毫秒时间戳，需要除以 1000
            if timestamp > 1e10:
                timestamp = timestamp / 1000.0
            return datetime.utcfromtimestamp(timestamp)
        except Exception:
            return None

