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
        # 支持多种事件类型字段名：eventType, type, event
        event_type = payload.get("eventType") or payload.get("type") or payload.get("event")
        # 支持多种事件ID字段名：id, event_id
        creem_event_id = payload.get("id") or payload.get("event_id")
        if not event_type:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="缺少事件类型")

        event = WebhookService.record_event(db, event_type, creem_event_id, payload, source="webhook")
        if event.processed:
            logger.info(f"Webhook 事件已处理，跳过: {creem_event_id or event.uuid}")
            return {"status": "skipped"}

        try:
            if event_type in ("checkout.session.completed", "checkout.completed"):
                WebhookService._handle_checkout_completed(db, payload)
            elif event_type == "checkout.session.failed":
                WebhookService._handle_checkout_failed(db, payload)
            elif event_type in ("invoice.paid", "subscription.paid"):
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
                WebhookService._handle_subscription_update(db, payload)
            elif event_type in ("subscription.cancelled", "subscription.canceled"):
                WebhookService._handle_subscription_cancelled(db, payload)
            elif event_type == "subscription.scheduled_cancel":
                WebhookService._handle_subscription_scheduled_cancel(db, payload)
            elif event_type in ("refund.created", "dispute.created"):
                logger.info(f"收到事件 {event_type}，目前仅记录事件，不做业务处理")
            else:
                logger.warning(f"未处理的事件类型: {event_type}")
        except Exception as e:
            logger.exception(f"处理 Webhook 事件失败: {e}")
            event.error_message = str(e)
            db.commit()
            raise
        else:
            WebhookService.mark_processed(db, event)
        return {"status": "ok"}

    @staticmethod
    def _handle_checkout_completed(db: Session, payload: Dict[str, Any]):
        data = payload.get("data") or payload.get("object") or {}
        checkout_id = WebhookService._get(data, ["id", "checkout_id", "checkout_session_id"])
        order_uuid = WebhookService._get(data, ["metadata", "order_uuid"])
        creem_transaction_id = WebhookService._get(data, ["transaction_id"])
        subscription_id = WebhookService._get(data, ["subscription_id", "subscription", "subscriptionId"])
        status = WebhookService._get(data, ["status"]) or "paid"
        paid_at = WebhookService._parse_datetime(WebhookService._get(data, ["paid_at", "created_at", "created"]))

        if not checkout_id and not order_uuid:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="缺少订单标识")

        order = None
        if order_uuid:
            order = db.query(Order).filter(Order.uuid == order_uuid).first()
        if not order and checkout_id:
            order = db.query(Order).filter(Order.creem_checkout_id == checkout_id).first()
        if not order:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="订单不存在")

        OrderService.mark_paid(db, order, creem_transaction_id=creem_transaction_id, paid_at=paid_at)

        # 若为订阅，创建订阅记录并发放首期积分
        if order.order_type == "subscription":
            subscription = SubscriptionService.upsert_from_webhook(
                db=db,
                user_id=order.user_id,
                order=order,
                creem_subscription_id=subscription_id or checkout_id or order.creem_checkout_id,
                status="active" if status == "paid" else status,
                billing_period=order.product.billing_period,
                current_period_start=paid_at or datetime.utcnow(),
                current_period_end=None,
                next_billing_date=None,
                points_per_period=order.points_amount,
                metadata=data.get("metadata"),
            )
            
            # 如果订阅ID存在，尝试从 Creem API 获取完整订阅信息
            if subscription.creem_subscription_id and not subscription.current_period_end:
                try:
                    from app.services.creem_client import creem_client
                    creem_sub = creem_client.get_subscription(subscription.creem_subscription_id)
                    subscription.current_period_end = WebhookService._parse_datetime(
                        creem_sub.get("current_period_end_date")
                    )
                    subscription.next_billing_date = WebhookService._parse_datetime(
                        creem_sub.get("next_transaction_date")
                    )
                    if not subscription.subscription_metadata:
                        subscription.subscription_metadata = creem_sub.get("metadata")
                    db.commit()
                    logger.info(f"从 Creem API 同步订阅信息成功: {subscription.creem_subscription_id}")
                except Exception as e:
                    logger.warning(f"从 Creem API 获取订阅详情失败: {e}")
            
            SubscriptionService.issue_cycle_points(
                db=db,
                subscription=subscription,
                order=order,
                period_start=subscription.current_period_start or paid_at or datetime.utcnow(),
                period_end=subscription.current_period_end or datetime.utcnow(),
                creem_invoice_id=None,
            )

    @staticmethod
    def _handle_checkout_failed(db: Session, payload: Dict[str, Any]):
        data = payload.get("data") or payload.get("object") or {}
        checkout_id = WebhookService._get(data, ["id", "checkout_id"])
        order_uuid = WebhookService._get(data, ["metadata", "order_uuid"])
        order = None
        if order_uuid:
            order = db.query(Order).filter(Order.uuid == order_uuid).first()
        if not order and checkout_id:
            order = db.query(Order).filter(Order.creem_checkout_id == checkout_id).first()
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
        if not order and subscription is None:
            # 无法找到关联订单，跳过
            return

        subscription = SubscriptionService.upsert_from_webhook(
            db=db,
            user_id=order.user_id,
            order=order,
            creem_subscription_id=subscription_id,
            status=status_value or "active",
            billing_period=order.product.billing_period if order else subscription.billing_period,
            current_period_start=period_start,
            current_period_end=period_end,
            next_billing_date=next_billing,
            points_per_period=order.points_amount if order else subscription.points_per_period,
            metadata=data.get("metadata"),
        )
        db.commit()

    @staticmethod
    def _handle_subscription_cancelled(db: Session, payload: Dict[str, Any]):
        # 支持 payload.object 格式（Creem 实际格式）
        data = payload.get("object") or payload.get("data") or {}
        subscription_id = data.get("id") or WebhookService._get(data, ["subscription_id"])
        subscription = db.query(Subscription).filter(Subscription.creem_subscription_id == subscription_id).first()
        if subscription:
            subscription.status = "cancelled"
            # 如果 webhook 中有 canceled_at，使用它；否则使用当前时间
            canceled_at = WebhookService._parse_datetime(data.get("canceled_at"))
            subscription.cancelled_at = canceled_at or datetime.utcnow()
            db.commit()

    @staticmethod
    def _handle_subscription_scheduled_cancel(db: Session, payload: Dict[str, Any]):
        data = payload.get("data") or payload.get("object") or {}
        subscription_id = WebhookService._get(data, ["id", "subscription_id"])
        subscription = db.query(Subscription).filter(Subscription.creem_subscription_id == subscription_id).first()
        if subscription:
            subscription.cancel_at_period_end = True
            subscription.status = subscription.status or "active"
            db.commit()

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

        subscription = db.query(Subscription).filter(Subscription.creem_subscription_id == subscription_id).first()
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
            creem_invoice_id=invoice_id,
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

