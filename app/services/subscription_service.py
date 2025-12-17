from datetime import datetime, timedelta, timezone
import calendar
from typing import Optional, Tuple, List
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError
from fastapi import HTTPException, status
from app.models.subscription import Subscription
from app.models.order import Order
from app.models.subscription_points_history import SubscriptionPointsHistory
from app.services.points_service import PointsService
from app.services.creem_client import creem_client
from app.core.logger import logger
from app.models.webhook_event import WebhookEvent


class SubscriptionService:
    @staticmethod
    def get_by_uuid(db: Session, user_id: int, uuid_str: str) -> Subscription | None:
        return (
            db.query(Subscription)
            .filter(Subscription.uuid == uuid_str, Subscription.user_id == user_id)
            .first()
        )

    @staticmethod
    def list_subscriptions(
        db: Session,
        user_id: int,
        page: int = 1,
        page_size: int = 20,
    ) -> Tuple[List[Subscription], int]:
        query = db.query(Subscription).filter(Subscription.user_id == user_id)
        total = query.count()
        items = (
            query.order_by(Subscription.created_at.desc().nullslast())
            .offset((page - 1) * page_size)
            .limit(page_size)
            .all()
        )
        return items, total

    @staticmethod
    def cancel_subscription(
        db: Session,
        user_id: int,
        subscription_uuid: str,
        cancel_at_period_end: bool = True,
    ) -> Subscription:
        subscription = SubscriptionService.get_by_uuid(db, user_id, subscription_uuid)
        if not subscription:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="订阅不存在")

        # 调用 Creem 取消
        creem_client._request(
            "POST",
            f"/v1/subscriptions/{subscription.creem_subscription_id}/cancel",
            json={"cancel_at_period_end": cancel_at_period_end},
        )

        subscription.cancel_at_period_end = cancel_at_period_end
        subscription.status = "cancelled" if not cancel_at_period_end else subscription.status
        subscription.cancelled_at = datetime.utcnow() if not cancel_at_period_end else subscription.cancelled_at
        db.commit()
        db.refresh(subscription)
        return subscription

    @staticmethod
    def upsert_from_webhook(
        db: Session,
        user_id: int,
        order: Order,
        creem_subscription_id: str,
        status: str,
        billing_period: Optional[str],
        current_period_start: Optional[datetime],
        current_period_end: Optional[datetime],
        next_billing_date: Optional[datetime],
        points_per_period: int,
        metadata: Optional[dict] = None,
    ) -> Subscription:
        subscription = (
            db.query(Subscription)
            .filter(
                Subscription.creem_subscription_id == creem_subscription_id,
                Subscription.user_id == user_id,
            )
            .first()
        )

        if not subscription:
            subscription = Subscription(
                order_id=order.order_id,
                user_id=user_id,
                creem_subscription_id=creem_subscription_id,
                status=status,
                billing_period=billing_period or order.product.billing_period or "",
                current_period_start=current_period_start,
                current_period_end=current_period_end,
                next_billing_date=next_billing_date,
                points_per_period=points_per_period,
                subscription_metadata=metadata,
            )
            db.add(subscription)
        else:
            subscription.status = status or subscription.status
            subscription.billing_period = billing_period or subscription.billing_period
            subscription.current_period_start = current_period_start or subscription.current_period_start
            subscription.current_period_end = current_period_end or subscription.current_period_end
            subscription.next_billing_date = next_billing_date or subscription.next_billing_date
            subscription.points_per_period = points_per_period or subscription.points_per_period
            subscription.subscription_metadata = metadata or subscription.subscription_metadata

        db.flush()
        db.refresh(subscription)
        return subscription

    @staticmethod
    def _normalize_period_date(dt: datetime) -> datetime:
        """
        规范化周期日期：只保留日期部分，时间设为 00:00:00
        确保同一周期的 period_start 格式一致，避免幂等性检查失败
        """
        if not dt:
            return dt
        # 转换为 UTC 时区（如果有时区信息）
        if dt.tzinfo:
            dt = dt.astimezone(timezone.utc)
        # 只保留日期部分，时间设为 00:00:00
        return datetime.combine(dt.date(), datetime.min.time()).replace(tzinfo=timezone.utc)

    @staticmethod
    def issue_cycle_points(
        db: Session,
        subscription: Subscription,
        order: Order,
        period_start: datetime,
        period_end: datetime,
        creem_invoice_id: Optional[str] = None,
    ) -> SubscriptionPointsHistory:
        # 规范化周期日期：统一格式为日期精度（时间设为 00:00:00）
        # 这确保同一周期的 period_start 格式一致，避免幂等性检查失败
        normalized_period_start = SubscriptionService._normalize_period_date(period_start)
        normalized_period_end = SubscriptionService._normalize_period_date(period_end)
        
        # 幂等检查：先查询是否已存在（使用规范化后的日期）
        exists = (
            db.query(SubscriptionPointsHistory)
            .filter(
                SubscriptionPointsHistory.subscription_id == subscription.subscription_id,
                SubscriptionPointsHistory.period_start == normalized_period_start,
            )
            .first()
        )
        if exists:
            logger.info(
                f"订阅积分已发放，跳过: subscription_id={subscription.subscription_id}, "
                f"period_start={normalized_period_start}, history_id={exists.history_id}"
            )
            return exists

        # 使用 SELECT FOR UPDATE 锁定订阅记录，防止并发问题
        # 注意：这里锁定 subscription 表，确保同一订阅的并发操作串行化
        locked_subscription = (
            db.query(Subscription)
            .filter(Subscription.subscription_id == subscription.subscription_id)
            .with_for_update()
            .first()
        )
        if not locked_subscription:
            raise ValueError(f"订阅不存在: subscription_id={subscription.subscription_id}")

        # 再次检查（双重检查锁定模式，Double-Checked Locking）
        exists = (
            db.query(SubscriptionPointsHistory)
            .filter(
                SubscriptionPointsHistory.subscription_id == locked_subscription.subscription_id,
                SubscriptionPointsHistory.period_start == normalized_period_start,
            )
            .first()
        )
        if exists:
            logger.info(
                f"订阅积分已发放（锁定后检查），跳过: subscription_id={locked_subscription.subscription_id}, "
                f"period_start={normalized_period_start}, history_id={exists.history_id}"
            )
            return exists

        # 发放积分
        points_record = PointsService.add_points(
            db=db,
            user_id=locked_subscription.user_id,
            points=locked_subscription.points_per_period,
            record_type="recharge",
            operation_type="subscription",
            points_type="normal",
            description="订阅积分发放",
            extra_data={"subscription_uuid": str(locked_subscription.uuid), "order_uuid": str(order.uuid)},
        )

        # 创建历史记录（使用规范化后的日期）
        history = SubscriptionPointsHistory(
            subscription_id=locked_subscription.subscription_id,
            order_id=order.order_id,
            user_id=locked_subscription.user_id,
            points_record_id=points_record.record_id,
            period_start=normalized_period_start,
            period_end=normalized_period_end,
            points_amount=locked_subscription.points_per_period,
            creem_invoice_id=creem_invoice_id,
        )
        locked_subscription.last_points_issued_at = datetime.utcnow()
        db.add(history)
        
        try:
            db.commit()
            db.refresh(history)
            logger.info(
                f"订阅积分发放成功: subscription_id={locked_subscription.subscription_id}, "
                f"period_start={normalized_period_start}, history_id={history.history_id}, points={locked_subscription.points_per_period}"
            )
            return history
        except IntegrityError as e:
            # 如果违反唯一约束（数据库层面的最后保护）
            db.rollback()
            logger.warning(
                f"订阅积分发放唯一约束冲突: subscription_id={locked_subscription.subscription_id}, "
                f"period_start={normalized_period_start}, error={e}"
            )
            # 再次查询，可能另一个线程已经插入
            exists = (
                db.query(SubscriptionPointsHistory)
                .filter(
                    SubscriptionPointsHistory.subscription_id == locked_subscription.subscription_id,
                    SubscriptionPointsHistory.period_start == normalized_period_start,
                )
                .first()
            )
            if exists:
                logger.info(
                    f"订阅积分已由其他线程发放，返回已存在记录: subscription_id={locked_subscription.subscription_id}, "
                    f"period_start={normalized_period_start}, history_id={exists.history_id}"
                )
                return exists
            # 如果查询不到，说明是其他唯一约束冲突，重新抛出
            logger.error(f"订阅积分发放唯一约束冲突但查询不到记录: subscription_id={locked_subscription.subscription_id}, period_start={normalized_period_start}")
            raise
        except Exception as e:
            # 其他错误
            db.rollback()
            logger.exception(f"订阅积分发放失败: subscription_id={locked_subscription.subscription_id}, period_start={normalized_period_start}")
            raise

    # ========== 月度兜底发放（含年付的月度发放） ==========
    @staticmethod
    def run_monthly_payout(db: Session, now: datetime | None = None) -> dict:
        """
        兜底：每日检查需要在本月购买日发放的订阅积分（按月发放，含年付）。
        幂等：通过 subscription_id + period_start。
        """
        now = now or datetime.utcnow()
        today_date = now.date()
        issued = 0
        skipped = 0
        errors = 0

        subs = (
            db.query(Subscription)
            .filter(Subscription.status == "active")
            .filter(Subscription.billing_period.in_(["every-month", "every-year"]))
            .all()
        )

        for sub in subs:
            try:
                order = sub.order
                if not order:
                    skipped += 1
                    continue

                anchor_day = SubscriptionService._anchor_day(sub, order)
                period_start, period_end = SubscriptionService._period_for_month(anchor_day, now)

                # 只在“购买日”执行（即今日日期等于当月锚日；若当月天数不足则为当月最后一天）
                if today_date != period_start.date():
                    skipped += 1
                    continue

                # 幂等检查
                exists = (
                    db.query(SubscriptionPointsHistory)
                    .filter(
                        SubscriptionPointsHistory.subscription_id == sub.subscription_id,
                        SubscriptionPointsHistory.period_start == period_start,
                    )
                    .first()
                )
                if exists:
                    skipped += 1
                    continue

                SubscriptionService.issue_cycle_points(
                    db=db,
                    subscription=sub,
                    order=order,
                    period_start=period_start,
                    period_end=period_end,
                    creem_invoice_id=None,
                )
                issued += 1
            except Exception as e:
                errors += 1
                logger.exception(f"订阅月度发放失败 subscription_id={getattr(sub, 'subscription_id', None)}: {e}")
                db.rollback()

        return {"issued": issued, "skipped": skipped, "errors": errors, "total": len(subs)}

    # ========== 轮询容错：计费日内查询续费交易并发放 ==========
    @staticmethod
    def poll_subscriptions_billing(db: Session, now: datetime | None = None, max_hours: int = 24) -> dict:
        """
        在计费日（锚定购买日）窗口内查询 subscription 的交易（支持年付月发放），无 Webhook 时兜底发放。
        """
        now = now or datetime.utcnow()
        today = now.date()

        subs = (
            db.query(Subscription)
            .filter(Subscription.status.in_(["active", "past_due"]))
            .filter(Subscription.billing_period.in_(["every-month", "every-year"]))
            .all()
        )

        checked = 0
        issued = 0
        skipped = 0
        errors = 0

        for sub in subs:
            try:
                order = sub.order
                if not order:
                    skipped += 1
                    continue

                anchor_day = SubscriptionService._anchor_day(sub, order)
                period_start, period_end = SubscriptionService._period_for_month(anchor_day, now)

                # 仅在计费日当天或次日内窗口（24h）尝试
                if not (period_start.date() <= today <= (period_start + timedelta(hours=max_hours)).date()):
                    skipped += 1
                    continue

                # 幂等：已发放则跳过
                exists = (
                    db.query(SubscriptionPointsHistory)
                    .filter(
                        SubscriptionPointsHistory.subscription_id == sub.subscription_id,
                        SubscriptionPointsHistory.period_start == period_start,
                    )
                    .first()
                )
                if exists:
                    skipped += 1
                    continue

                checked += 1

                tx = creem_client.search_transactions(subscription_id=sub.creem_subscription_id, page_size=1)
                items = tx.get("items") or []
                if items:
                    tx_status = items[0].get("status")
                    invoice_id = items[0].get("id")
                    if tx_status and tx_status.lower() == "paid":
                        # 记录轮询事件到 webhook_events 表
                        event_payload = {
                            "type": "invoice.paid",
                            "subscription_id": sub.creem_subscription_id,
                            "invoice_id": invoice_id,
                            "period_start": period_start.isoformat() if period_start else None,
                            "period_end": period_end.isoformat() if period_end else None,
                            "source": "polling",
                        }
                        event = WebhookEvent(
                            event_type="invoice.paid",
                            creem_event_id=f"polling_{sub.creem_subscription_id}_{int(now.timestamp())}",
                            payload=event_payload,
                            source="polling",
                            processed=True,
                            processed_at=now,
                        )
                        db.add(event)
                        
                        SubscriptionService.issue_cycle_points(
                            db=db,
                            subscription=sub,
                            order=order,
                            period_start=period_start,
                            period_end=period_end,
                            creem_invoice_id=invoice_id,
                        )
                        sub.status = "active"
                        db.commit()
                        issued += 1
                        continue

                # 若超 24h 未扣款，可视业务需求标记 past_due
                if now - period_start > timedelta(hours=max_hours):
                    sub.status = "past_due"
                    db.commit()
            except Exception as e:
                errors += 1
                logger.exception(f"轮询订阅续费失败 subscription_id={getattr(sub, 'subscription_id', None)}: {e}")
                db.rollback()

        return {"checked": checked, "issued": issued, "skipped": skipped, "errors": errors, "total": len(subs)}

    @staticmethod
    def _anchor_day(subscription: Subscription, order: Order | None = None) -> int:
        """
        计算锚定日：优先当前周期开始日，否则订阅创建日，否则订单支付日/创建日，默认 1。
        """
        for dt in [
            subscription.current_period_start,
            subscription.created_at,
            order.paid_at if order else None,
            order.created_at if order else None,
        ]:
            if dt:
                return max(1, min(dt.day, 28 if dt.month == 2 else 31))
        return 1

    @staticmethod
    def _period_for_month(anchor_day: int, ref: datetime) -> tuple[datetime, datetime]:
        """
        根据锚定日计算当月周期 [period_start, period_end)，period_end 为下月锚定日。
        返回的日期已规范化：时间设为 00:00:00，时区为 UTC。
        """
        # 确保 ref 是 UTC 时区
        if ref.tzinfo:
            ref = ref.astimezone(timezone.utc)
        else:
            ref = ref.replace(tzinfo=timezone.utc)
        
        year, month = ref.year, ref.month
        last_day = calendar.monthrange(year, month)[1]
        start_day = min(anchor_day, last_day)
        period_start = datetime(year, month, start_day, tzinfo=timezone.utc)

        next_month = month + 1
        next_year = year
        if next_month == 13:
            next_month = 1
            next_year += 1
        next_last_day = calendar.monthrange(next_year, next_month)[1]
        next_start_day = min(anchor_day, next_last_day)
        period_end = datetime(next_year, next_month, next_start_day, tzinfo=timezone.utc)
        return period_start, period_end

