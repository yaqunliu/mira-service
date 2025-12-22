from datetime import datetime, timedelta, timezone
import calendar
from typing import Optional, Tuple, List, Dict, Any
try:
    from dateutil.relativedelta import relativedelta
except ImportError:
    # 如果dateutil未安装，使用timedelta作为fallback
    class relativedelta:
        def __init__(self, months=0, years=0):
            self.months = months
            self.years = years
from dateutil.relativedelta import relativedelta
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError
from sqlalchemy import text as sa_text
from fastapi import HTTPException, status
from app.models.subscription import Subscription
from app.models.order import Order
from app.models.subscription_points_history import SubscriptionPointsHistory
from app.models.creem_subscription import CreemSubscription
from app.models.wechat_subscription import WechatSubscription
from app.services.points_service import PointsService
from app.services.creem_client import creem_client
from app.core.logger import logger
from app.models.webhook_event import WebhookEvent


class SubscriptionService:
    @staticmethod
    def get_by_uuid(db: Session, user_id: int, uuid_str: str) -> Subscription | None:
        from sqlalchemy.orm import joinedload
        subscription = (
            db.query(Subscription)
            .options(joinedload(Subscription.creem_subscription))
            .filter(Subscription.uuid == uuid_str, Subscription.user_id == user_id)
            .first()
        )
        return subscription

    @staticmethod
    def list_subscriptions(
        db: Session, user_id: int, page: int, page_size: int
    ) -> Tuple[List[Subscription], int]:
        from sqlalchemy.orm import joinedload
        query = (
            db.query(Subscription)
            .options(joinedload(Subscription.creem_subscription))
            .filter(Subscription.user_id == user_id)
            .order_by(Subscription.created_at.desc())
        )
        total = query.count()
        items = query.offset((page - 1) * page_size).limit(page_size).all()
        return items, total

    @staticmethod
    def get_active_subscriptions_by_product(
        db: Session, user_id: int
    ) -> List[Subscription]:
        from sqlalchemy.orm import joinedload
        from sqlalchemy import func
        # 获取每个产品的最新活跃订阅
        subquery = (
            db.query(
                Subscription.product_id,
                func.max(Subscription.subscription_id).label("max_id")
            )
            .filter(Subscription.user_id == user_id)
            .filter(Subscription.status == "active")
            .group_by(Subscription.product_id)
            .subquery()
        )
        subscriptions = (
            db.query(Subscription)
            .options(joinedload(Subscription.creem_subscription))
            .join(subquery, Subscription.subscription_id == subquery.c.max_id)
            .filter(Subscription.user_id == user_id)
            .filter(Subscription.status == "active")
            .all()
        )
        return subscriptions

    @staticmethod
    def get_customer_portal_url(
        db: Session, user_id: int, subscription_uuid: str
    ) -> str:
        subscription = SubscriptionService.get_by_uuid(db, user_id, subscription_uuid)
        if not subscription:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="订阅不存在"
            )
        
        creem_subscription_id = subscription.creem_subscription.creem_subscription_id
        
        # 尝试从 Creem API 获取订阅详情，看是否包含客户门户 URL
        try:
            creem_sub = creem_client.get_subscription(creem_subscription_id)
            # 检查 Creem 返回的数据中是否包含客户门户 URL
            portal_url = creem_sub.get("customer_portal_url") or creem_sub.get("portal_url") or creem_sub.get("manage_url")
            if portal_url:
                return portal_url
        except Exception as e:
            logger.warning(f"获取 Creem 订阅详情失败，使用默认 URL: {e}")
        
        # 如果没有客户门户 URL，构建默认的客户门户 URL
        # 基于 Creem API URL 构建：api.creem.io -> creem.io
        from app.core.config import settings
        creem_base_url = str(settings.CREEM_API_URL).replace("api.", "")
        # 如果还是 api.creem.io，则使用 creem.io
        if "api." in creem_base_url:
            creem_base_url = "https://creem.io"
        return f"{creem_base_url}/subscriptions/{creem_subscription_id}"

    @staticmethod
    def cancel_subscription(
        db: Session,
        user_id: int,
        subscription_uuid: str,
        cancel_at_period_end: bool = True,
    ) -> Subscription:
        subscription = SubscriptionService.get_by_uuid(db, user_id, subscription_uuid)
        if not subscription:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="订阅不存在"
            )
        
        creem_subscription_id = subscription.creem_subscription.creem_subscription_id

        # 根据 cancel_at_period_end 构建请求体
        # 如果 cancel_at_period_end=True，使用 scheduled 模式，在周期结束时取消
        # 如果 cancel_at_period_end=False，使用 immediate 模式，立即取消
        if cancel_at_period_end:
            request_body = {
                "mode": "scheduled",
                "onExecute": "cancel"
            }
        else:
            request_body = {
                "mode": "immediate"
            }
        
        logger.info(
            f"[取消订阅] subscription_uuid={subscription_uuid}, "
            f"creem_subscription_id={creem_subscription_id}, "
            f"cancel_at_period_end={cancel_at_period_end}, "
            f"request_body={request_body}"
        )
        
        # 调用 Creem 取消 API（使用路径参数，根据 API 文档）
        # API 路径：POST /v1/subscriptions/{id}/cancel
        creem_response = creem_client._request(
            "POST",
            f"/v1/subscriptions/{creem_subscription_id}/cancel",
            json=request_body,
        )
        
        logger.info(
            f"[取消订阅] Creem API 响应: subscription_uuid={subscription_uuid}, "
            f"status={creem_response.get('status')}, "
            f"canceled_at={creem_response.get('canceled_at')}"
        )
        
        # 同步返回的订阅数据到本地数据库
        SubscriptionService.sync_from_creem_api(db, subscription, creem_response)
        
        # 更新取消相关字段
        subscription.cancel_at_period_end = cancel_at_period_end
        # 如果立即取消，状态应该是 cancelled
        if not cancel_at_period_end:
            subscription.status = "cancelled"
            if not subscription.cancelled_at:
                subscription.cancelled_at = datetime.utcnow()
        # 如果是 scheduled 取消，根据 API 响应更新状态
        # 注意：scheduled_cancel 状态的订阅在周期结束前仍然需要同步数据，所以保持状态为 scheduled_cancel
        # 但根据 webhook 处理逻辑，scheduled_cancel 应该保持为 active 直到周期结束
        # 这里我们根据 API 响应来决定：如果 API 返回 scheduled_cancel，就设置为 scheduled_cancel
        # 如果 API 返回 active（但 cancel_at_period_end=True），保持 active 状态
        elif creem_response.get("status") == "scheduled_cancel":
            subscription.status = "scheduled_cancel"
        # 如果 API 返回 active 但 cancel_at_period_end=True，保持 active 状态（这样轮询仍然能查询到）
        elif creem_response.get("status") == "active" and cancel_at_period_end:
            subscription.status = "active"  # 保持 active，确保轮询能查询到
        
        db.commit()
        db.refresh(subscription)
        
        logger.info(
            f"[取消订阅] 订阅取消成功: subscription_uuid={subscription_uuid}, "
            f"status={subscription.status}, "
            f"cancel_at_period_end={subscription.cancel_at_period_end}, "
            f"cancelled_at={subscription.cancelled_at}"
        )
        
        return subscription

    @staticmethod
    def upsert_from_webhook(
        db: Session,
        user_id: int,
        order: Order,
        payment_method: str,  # 支付方式
        subscription_id: str,  # 通用订阅ID（Creem的subscription_id或微信的contract_id）
        status: str,
        billing_period: Optional[str],
        current_period_start: Optional[datetime],
        current_period_end: Optional[datetime],
        next_billing_date: Optional[datetime],
        points_per_period: int,
        metadata: Optional[dict] = None,
    ) -> Subscription:
        # 根据支付方式查询订阅
        subscription = None
        if payment_method == "creem":
            creem_sub = (
                db.query(CreemSubscription)
                .filter(CreemSubscription.creem_subscription_id == subscription_id)
                .first()
            )
            if creem_sub:
                subscription = creem_sub.subscription
        elif payment_method == "wechat":
            wechat_sub = (
                db.query(WechatSubscription)
                .filter(WechatSubscription.wechat_contract_id == subscription_id)
                .first()
            )
            if wechat_sub:
                subscription = wechat_sub.subscription
        else:
            # 通过订单查询订阅
            subscription = (
                db.query(Subscription)
                .filter(
                    Subscription.order_id == order.order_id,
                    Subscription.user_id == user_id,
                )
                .first()
            )

        if not subscription:
            # 对于微信订阅，next_billing_date永远为null（不会自动续费）
            if payment_method == "wechat":
                next_billing_date = None  # 微信订阅永远不自动续费
                # 标记为手动续费
                if metadata is None:
                    metadata = {}
                metadata["auto_renewal"] = False
                metadata["renewal_type"] = "manual"
                logger.info(f"微信订阅创建，next_billing_date=null（不会自动续费）")
            
            # 创建订阅记录
            subscription = Subscription(
                order_id=order.order_id,
                user_id=user_id,
                product_id=order.product_id,
                payment_method=payment_method,
                status=status,
                billing_period=billing_period or order.product.billing_period or "",
                current_period_start=current_period_start,
                current_period_end=current_period_end,
                next_billing_date=next_billing_date,  # 微信订阅为null
                points_per_period=points_per_period,
                subscription_metadata=metadata,
            )
            db.add(subscription)
            db.flush()
            
            # 创建对应的订阅详情记录
            if payment_method == "creem":
                creem_sub = CreemSubscription(
                    subscription_id=subscription.subscription_id,
                    creem_subscription_id=subscription_id,
                    subscription_metadata=metadata,
                )
                db.add(creem_sub)
            elif payment_method == "wechat":
                wechat_sub = WechatSubscription(
                    subscription_id=subscription.subscription_id,
                    wechat_contract_id=subscription_id,
                    subscription_metadata=metadata,
                )
                db.add(wechat_sub)
        else:
            # 更新订阅信息
            subscription.status = status or subscription.status
            subscription.billing_period = billing_period or subscription.billing_period
            subscription.current_period_start = current_period_start or subscription.current_period_start
            subscription.current_period_end = current_period_end or subscription.current_period_end
            subscription.next_billing_date = next_billing_date or subscription.next_billing_date
            # points_per_period 不能为 0 或 None，所以需要明确检查
            if points_per_period is not None and points_per_period > 0:
                subscription.points_per_period = points_per_period
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
        invoice_id: Optional[str] = None,  # 通用发票ID
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
            payment_method=locked_subscription.payment_method,
            invoice_id=invoice_id,  # 通用发票ID
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
                return exists
            raise

    @staticmethod
    def _anchor_day(subscription: Subscription, order: Order) -> int:
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
    def _calculate_period_end(period_start: datetime, billing_period: str) -> datetime:
        """
        根据计费周期计算周期结束时间
        
        Args:
            period_start: 周期开始时间
            billing_period: 计费周期（every-month, every-quarter, every-year）
        
        Returns:
            周期结束时间
        """
        try:
            from dateutil.relativedelta import relativedelta
            if billing_period == "every-month":
                return period_start + relativedelta(months=1)
            elif billing_period == "every-quarter":
                return period_start + relativedelta(months=3)
            elif billing_period == "every-year":
                return period_start + relativedelta(years=1)
            else:
                # 默认30天
                return period_start + timedelta(days=30)
        except ImportError:
            # 如果dateutil未安装，使用timedelta作为fallback
            if billing_period == "every-month":
                return period_start + timedelta(days=30)
            elif billing_period == "every-quarter":
                return period_start + timedelta(days=90)
            elif billing_period == "every-year":
                return period_start + timedelta(days=365)
            else:
                return period_start + timedelta(days=30)

    @staticmethod
    def _period_for_month(anchor_day: int, ref: datetime) -> tuple[datetime, datetime]:
        """
        根据锚定日和参考日期计算当月周期（用于月付或年付按月发放）
        """
        year = ref.year
        month = ref.month
        
        # 计算周期开始：当月锚定日
        try:
            period_start = datetime(year, month, anchor_day, tzinfo=timezone.utc)
        except ValueError:
            # 如果锚定日超出当月天数（如2月31日），使用当月最后一天
            last_day = calendar.monthrange(year, month)[1]
            period_start = datetime(year, month, min(anchor_day, last_day), tzinfo=timezone.utc)
        
        # 计算周期结束：下月锚定日的前一天
        next_month = month + 1 if month < 12 else 1
        next_year = year if month < 12 else year + 1
        try:
            period_end = datetime(next_year, next_month, anchor_day, tzinfo=timezone.utc) - timedelta(days=1)
        except ValueError:
            last_day = calendar.monthrange(next_year, next_month)[1]
            period_end = datetime(next_year, next_month, min(anchor_day, last_day), tzinfo=timezone.utc) - timedelta(days=1)
        
        return period_start, period_end

    @staticmethod
    def _period_for_quarter(anchor_day: int, ref: datetime) -> tuple[datetime, datetime]:
        """
        根据锚定日和参考日期计算当季度周期（用于季度付）
        
        季度划分：
        - Q1: 1-3月
        - Q2: 4-6月
        - Q3: 7-9月
        - Q4: 10-12月
        """
        year = ref.year
        month = ref.month
        
        # 确定当前季度
        if month <= 3:
            quarter_start_month = 1
            quarter_end_month = 3
        elif month <= 6:
            quarter_start_month = 4
            quarter_end_month = 6
        elif month <= 9:
            quarter_start_month = 7
            quarter_end_month = 9
        else:
            quarter_start_month = 10
            quarter_end_month = 12
        
        # 计算周期开始：当前季度第一个月的锚定日
        try:
            period_start = datetime(year, quarter_start_month, anchor_day, tzinfo=timezone.utc)
        except ValueError:
            last_day = calendar.monthrange(year, quarter_start_month)[1]
            period_start = datetime(year, quarter_start_month, min(anchor_day, last_day), tzinfo=timezone.utc)
        
        # 计算周期结束：下一季度第一个月的锚定日的前一天
        next_quarter_start_month = quarter_end_month + 1
        next_quarter_year = year
        if next_quarter_start_month > 12:
            next_quarter_start_month = 1
            next_quarter_year = year + 1
        
        try:
            period_end = datetime(next_quarter_year, next_quarter_start_month, anchor_day, tzinfo=timezone.utc) - timedelta(days=1)
        except ValueError:
            last_day = calendar.monthrange(next_quarter_year, next_quarter_start_month)[1]
            period_end = datetime(next_quarter_year, next_quarter_start_month, min(anchor_day, last_day), tzinfo=timezone.utc) - timedelta(days=1)
        
        return period_start, period_end

    @staticmethod
    def sync_from_creem_api(
        db: Session,
        subscription: Subscription,
        creem_sub_data: Dict[str, Any],
    ) -> Subscription:
        """
        从 Creem API 返回的数据同步订阅信息到数据库
        
        Args:
            db: 数据库会话
            subscription: 订阅对象
            creem_sub_data: Creem API 返回的订阅数据
        
        Returns:
            更新后的订阅对象
        """
        from app.services.webhook_service import WebhookService
        
        # 状态映射：将 Creem 的状态映射到本地状态
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
        
        # 更新状态
        creem_status = creem_sub_data.get("status")
        if creem_status:
            mapped_status = status_mapping.get(creem_status, creem_status)
            subscription.status = mapped_status
        
        # 更新周期信息
        current_period_start = WebhookService._parse_datetime(
            creem_sub_data.get("current_period_start_date")
        )
        if current_period_start:
            subscription.current_period_start = current_period_start
        
        current_period_end = WebhookService._parse_datetime(
            creem_sub_data.get("current_period_end_date")
        )
        if current_period_end:
            subscription.current_period_end = current_period_end
        
        next_billing_date = WebhookService._parse_datetime(
            creem_sub_data.get("next_transaction_date")
        )
        if next_billing_date:
            subscription.next_billing_date = next_billing_date
        
        # 更新取消时间
        canceled_at = WebhookService._parse_datetime(
            creem_sub_data.get("canceled_at")
        )
        if canceled_at:
            subscription.cancelled_at = canceled_at
        
        # 更新元数据：合并现有元数据和新的元数据
        creem_metadata = creem_sub_data.get("metadata")
        if creem_metadata:
            if subscription.subscription_metadata:
                # 合并元数据
                subscription.subscription_metadata.update(creem_metadata)
            else:
                subscription.subscription_metadata = creem_metadata
        
        # 将额外的有用信息存储到元数据中
        if not subscription.subscription_metadata:
            subscription.subscription_metadata = {}
        
        # 存储最后交易ID（如果有）
        last_transaction_id = creem_sub_data.get("last_transaction_id")
        if last_transaction_id:
            subscription.subscription_metadata["last_transaction_id"] = last_transaction_id
        
        # 存储最后交易日期（如果有）
        last_transaction_date = WebhookService._parse_datetime(
            creem_sub_data.get("last_transaction_date")
        )
        if last_transaction_date:
            subscription.subscription_metadata["last_transaction_date"] = last_transaction_date.isoformat()
        
        # 存储收款方式（如果有）
        collection_method = creem_sub_data.get("collection_method")
        if collection_method:
            subscription.subscription_metadata["collection_method"] = collection_method
        
        # 存储最后交易的部分信息（如果有，避免存储整个对象）
        last_transaction = creem_sub_data.get("last_transaction")
        if last_transaction and isinstance(last_transaction, dict):
            # 只存储关键信息，避免数据过大
            transaction_summary = {
                "id": last_transaction.get("id"),
                "status": last_transaction.get("status"),
                "amount": last_transaction.get("amount"),
                "currency": last_transaction.get("currency"),
                "type": last_transaction.get("type"),
                "period_start": last_transaction.get("period_start"),
                "period_end": last_transaction.get("period_end"),
            }
            subscription.subscription_metadata["last_transaction_summary"] = transaction_summary
        
        # 存储产品信息摘要（如果有）
        product = creem_sub_data.get("product")
        if product and isinstance(product, dict):
            product_summary = {
                "id": product.get("id"),
                "name": product.get("name"),
                "price": product.get("price"),
                "currency": product.get("currency"),
                "billing_type": product.get("billing_type"),
                "billing_period": product.get("billing_period"),
            }
            subscription.subscription_metadata["product_summary"] = product_summary
        
        # 存储客户信息摘要（如果有）
        customer = creem_sub_data.get("customer")
        if customer and isinstance(customer, dict):
            customer_summary = {
                "id": customer.get("id"),
                "email": customer.get("email"),
                "name": customer.get("name"),
                "country": customer.get("country"),
            }
            subscription.subscription_metadata["customer_summary"] = customer_summary
        
        # 存储订阅项信息（items）
        items = creem_sub_data.get("items")
        if items and isinstance(items, list):
            items_summary = []
            for item in items:
                if isinstance(item, dict):
                    items_summary.append({
                        "id": item.get("id"),
                        "product_id": item.get("product_id"),
                        "price_id": item.get("price_id"),
                        "units": item.get("units"),
                    })
            subscription.subscription_metadata["items_summary"] = items_summary
        
        # 存储折扣信息（如果有）
        discount = creem_sub_data.get("discount")
        if discount and isinstance(discount, dict) and discount:
            subscription.subscription_metadata["discount"] = discount
        
        # 存储订阅的创建和更新时间
        created_at = WebhookService._parse_datetime(creem_sub_data.get("created_at"))
        if created_at:
            subscription.subscription_metadata["creem_created_at"] = created_at.isoformat()
        
        updated_at = WebhookService._parse_datetime(creem_sub_data.get("updated_at"))
        if updated_at:
            subscription.subscription_metadata["creem_updated_at"] = updated_at.isoformat()
        
        # 存储 mode（test/production）
        mode = creem_sub_data.get("mode")
        if mode:
            subscription.subscription_metadata["creem_mode"] = mode
        
        # 存储最后一次同步的完整 API 响应（用于调试，但只保留最新的一次）
        subscription.subscription_metadata["last_sync_response"] = creem_sub_data
        subscription.subscription_metadata["last_synced_at"] = datetime.now(timezone.utc).isoformat()
        
        # 记录同步操作的详细信息
        logger.debug(
            f"[同步订阅数据] subscription_uuid={subscription.uuid}: "
            f"next_billing_date={subscription.next_billing_date}, "
            f"current_period_start={subscription.current_period_start}, "
            f"current_period_end={subscription.current_period_end}, "
            f"status={subscription.status}"
        )
        
        db.flush()
        logger.debug(f"[同步订阅数据] subscription_uuid={subscription.uuid} 数据已flush到数据库")
        
        # 再次刷新以确认数据已更新
        db.refresh(subscription)
        logger.debug(
            f"[同步订阅数据] subscription_uuid={subscription.uuid} flush后确认: "
            f"next_billing_date={subscription.next_billing_date}, "
            f"current_period_end={subscription.current_period_end}"
        )
        
        return subscription

    @staticmethod
    def poll_subscriptions_billing(db: Session, max_hours: int = 24) -> dict:
        """
        轮询订阅续费状态
        
        在计费日查询订阅的续费状态，补发积分
        
        Args:
            db: 数据库会话
            max_hours: 最大等待时间（小时），超过此时间未扣款则标记为 past_due
        
        Returns:
            轮询结果统计字典
        """
        from datetime import datetime, timedelta, timezone
        from app.models.subscription_points_history import SubscriptionPointsHistory
        from app.services.creem_client import creem_client
        
        now = datetime.now(timezone.utc)
        today = now.date()
        
        # 查询需要轮询的订阅：
        # - active: 活跃订阅
        # - past_due: 逾期订阅
        # - scheduled_cancel: 计划取消的订阅（在周期结束前仍然需要同步数据）
        # - cancelled: 已取消的订阅（需要同步最新状态，比如清空 next_billing_date）
        # 注意：
        # 1. 即使是已取消的订阅，也需要从 Creem API 同步最新状态
        # 2. 微信订阅不参与轮询（因为不能自动续费，不需要查询支付状态）
        subs = (
            db.query(Subscription)
            .filter(Subscription.status.in_(["active", "past_due", "scheduled_cancel", "cancelled"]))
            .filter(Subscription.billing_period.in_(["every-month", "every-quarter", "every-year"]))
            .filter(Subscription.payment_method == "creem")  # 只处理Creem订阅，微信订阅不轮询支付状态
            .all()
        )
        
        checked = 0
        issued = 0
        skipped = 0
        errors = 0
        
        for sub in subs:
            try:
                logger.debug(f"[轮询订阅] 检查订阅: subscription_uuid={sub.uuid}, status={sub.status}, billing_period={sub.billing_period}")
                
                order = sub.order
                if not order:
                    skipped += 1
                    logger.info(f"[轮询订阅] 跳过订阅 {sub.uuid}: 原因=没有关联订单")
                    continue
                
                logger.debug(f"[轮询订阅] 订阅 {sub.uuid} 关联订单: order_uuid={order.uuid}, order_id={order.order_id}")
                
                # 检查是否已发放过首期积分（通过查询历史记录）
                # 如果没有任何历史记录，说明是新订阅，首期积分会在购买时发放，这里跳过
                has_any_history = (
                    db.query(SubscriptionPointsHistory)
                    .filter(SubscriptionPointsHistory.subscription_id == sub.subscription_id)
                    .first()
                )
                
                if not has_any_history:
                    # 没有历史记录，说明是新订阅，首期积分会在购买时发放，这里跳过
                    skipped += 1
                    logger.debug(
                        f"[轮询订阅] 跳过新订阅（首期积分在购买时发放）: subscription_uuid={sub.uuid}"
                    )
                    continue
                
                # 计算当月周期（每月1号到月底）
                period_start, period_end = SubscriptionService._period_for_month_first(now)
                
                logger.debug(
                    f"[轮询订阅] 订阅 {sub.uuid} 周期计算: "
                    f"period_start={period_start.date()}, "
                    f"period_end={period_end.date() if period_end else None}, today={today}"
                )
                
                # 仅在每月1号执行（与月度发放任务保持一致）
                # 但是，如果订阅已取消，仍然需要同步数据（不检查日期）
                if sub.status != "cancelled" and today.day != 1:
                    skipped += 1
                    logger.debug(
                        f"[轮询订阅] 跳过订阅 {sub.uuid}: 原因=今天不是1号, "
                        f"today={today}"
                    )
                    continue
                
                # 如果订阅已取消，记录日志但继续处理（用于同步取消状态）
                if sub.status == "cancelled":
                    logger.info(
                        f"[轮询订阅] 订阅 {sub.uuid} 已取消，继续同步最新状态以更新信息（如清空 next_billing_date）"
                    )
                
                logger.debug(f"[轮询订阅] 订阅 {sub.uuid} 在计费日窗口内，检查是否已发放积分")
                
                # 幂等：已发放则跳过（但需要检查重要数据是否完整）
                exists = (
                    db.query(SubscriptionPointsHistory)
                    .filter(
                        SubscriptionPointsHistory.subscription_id == sub.subscription_id,
                        SubscriptionPointsHistory.period_start == period_start,
                    )
                    .first()
                )
                
                # 检查重要数据是否完整
                important_data_missing = False
                missing_fields = []
                
                # 检查 next_billing_date
                if not sub.next_billing_date:
                    important_data_missing = True
                    missing_fields.append("next_billing_date")
                
                # 检查 current_period_start 和 current_period_end
                if not sub.current_period_start:
                    important_data_missing = True
                    missing_fields.append("current_period_start")
                if not sub.current_period_end:
                    important_data_missing = True
                    missing_fields.append("current_period_end")
                
                # 检查 metadata 中的关键信息
                if not sub.subscription_metadata:
                    important_data_missing = True
                    missing_fields.append("subscription_metadata")
                else:
                    # 检查 metadata 中是否有 last_sync_response（表示从未同步过）
                    if "last_sync_response" not in sub.subscription_metadata:
                        important_data_missing = True
                        missing_fields.append("metadata.last_sync_response")
                    else:
                        # 如果已有 last_sync_response，检查是否有 next_transaction_date 相关信息
                        last_sync = sub.subscription_metadata.get("last_sync_response", {})
                        if not last_sync.get("next_transaction_date"):
                            important_data_missing = True
                            missing_fields.append("metadata.next_transaction_date")
                
                if exists and not important_data_missing:
                    # 积分已发放且数据完整，可以跳过
                    skipped += 1
                    logger.info(
                        f"[轮询订阅] 跳过订阅 {sub.uuid}: 原因=积分已发放且数据完整, "
                        f"period_start={period_start.date()}, history_id={exists.history_id}"
                    )
                    continue
                elif exists and important_data_missing:
                    # 积分已发放但数据不完整，需要同步数据
                    logger.info(
                        f"[轮询订阅] 订阅 {sub.uuid} 积分已发放但数据不完整，继续同步数据: "
                        f"missing_fields={missing_fields}, period_start={period_start.date()}, history_id={exists.history_id}"
                    )
                    # 继续执行后续的数据同步逻辑
                elif not exists:
                    # 积分未发放，需要处理
                    logger.debug(f"[轮询订阅] 订阅 {sub.uuid} 积分未发放，需要处理")
                
                # 如果积分已发放但数据不完整，checked 不增加（因为主要是为了补全数据）
                # 如果积分未发放，checked 增加（需要处理续费）
                if not exists:
                    checked += 1
                    logger.info(f"[轮询订阅] 开始处理订阅 {sub.uuid}: payment_method={sub.payment_method}, 需要发放积分")
                else:
                    logger.info(f"[轮询订阅] 开始补全订阅 {sub.uuid} 的数据: payment_method={sub.payment_method}, missing_fields={missing_fields}")
                
                # 根据支付方式查询续费状态
                if sub.payment_method == "creem":
                    creem_sub = sub.creem_subscription
                    if not creem_sub:
                        skipped += 1
                        logger.warning(f"[轮询订阅] 跳过订阅 {sub.uuid}: 原因=没有Creem订阅详情记录")
                        continue
                    
                    logger.debug(f"[轮询订阅] 订阅 {sub.uuid} Creem订阅ID: {creem_sub.creem_subscription_id}")
                    
                    # 1. 先获取完整的订阅信息，同步所有字段（包括 next_billing_date 等）
                    try:
                        logger.debug(f"[轮询订阅] 订阅 {sub.uuid} 开始获取Creem订阅详情")
                        creem_sub_data = creem_client.get_subscription(creem_sub.creem_subscription_id)
                        logger.info(
                            f"[轮询订阅] 订阅 {sub.uuid} 获取Creem订阅详情成功: "
                            f"status={creem_sub_data.get('status')}, "
                            f"next_transaction_date={creem_sub_data.get('next_transaction_date')}, "
                            f"current_period_start_date={creem_sub_data.get('current_period_start_date')}, "
                            f"current_period_end_date={creem_sub_data.get('current_period_end_date')}"
                        )
                        logger.debug(f"[轮询订阅] 订阅 {sub.uuid} 完整API响应: {creem_sub_data}")
                        
                        # 记录同步前的数据状态
                        logger.info(
                            f"[轮询订阅] 订阅 {sub.uuid} 同步前数据状态: "
                            f"next_billing_date={sub.next_billing_date}, "
                            f"current_period_start={sub.current_period_start}, "
                            f"current_period_end={sub.current_period_end}, "
                            f"has_metadata={sub.subscription_metadata is not None}"
                        )
                        
                        # 使用统一的同步方法同步所有字段（包括 next_transaction_date -> next_billing_date）
                        SubscriptionService.sync_from_creem_api(db, sub, creem_sub_data)
                        
                        # 如果订阅已取消，清空 next_billing_date（因为不会再付费）
                        creem_status = creem_sub_data.get("status")
                        if creem_status in ("cancelled", "canceled"):
                            if sub.next_billing_date:
                                logger.info(
                                    f"[轮询订阅] 订阅 {sub.uuid} 已取消，清空 next_billing_date: "
                                    f"原值={sub.next_billing_date}"
                                )
                                sub.next_billing_date = None
                            # 确保状态更新为 cancelled
                            if sub.status != "cancelled":
                                logger.info(
                                    f"[轮询订阅] 订阅 {sub.uuid} 状态更新为 cancelled: 原状态={sub.status}"
                                )
                                sub.status = "cancelled"
                            # 如果 cancelled_at 为空，设置为当前时间或从 API 获取
                            if not sub.cancelled_at:
                                from app.services.webhook_service import WebhookService
                                cancelled_at = WebhookService._parse_datetime(creem_sub_data.get("canceled_at"))
                                sub.cancelled_at = cancelled_at or datetime.utcnow()
                                logger.info(
                                    f"[轮询订阅] 订阅 {sub.uuid} 设置 cancelled_at: {sub.cancelled_at}"
                                )
                        
                        # 刷新对象以获取最新数据
                        db.refresh(sub)
                        
                        # 记录同步后的数据状态
                        logger.info(
                            f"[轮询订阅] 订阅 {sub.uuid} 同步后数据状态: "
                            f"status={sub.status}, "
                            f"next_billing_date={sub.next_billing_date}, "
                            f"current_period_start={sub.current_period_start}, "
                            f"current_period_end={sub.current_period_end}, "
                            f"cancelled_at={sub.cancelled_at}, "
                            f"has_metadata={sub.subscription_metadata is not None}, "
                            f"metadata_keys={list(sub.subscription_metadata.keys()) if sub.subscription_metadata else []}"
                        )
                        
                        # 提交数据库更改
                        db.commit()
                        logger.info(f"[轮询订阅] 订阅 {sub.uuid} 数据同步并提交到数据库成功")
                        
                        # 保存轮询历史到 metadata
                        if not sub.subscription_metadata:
                            sub.subscription_metadata = {}
                        
                        polling_history = sub.subscription_metadata.get("polling_history", [])
                        polling_history.append({
                            "polled_at": now.isoformat(),
                            "subscription_data": creem_sub_data,  # 保存完整的订阅 API 响应
                        })
                        # 只保留最近 20 次轮询记录
                        sub.subscription_metadata["polling_history"] = polling_history[-20:]
                        sub.subscription_metadata["last_polled_at"] = now.isoformat()
                        
                        logger.info(f"[轮询订阅] 订阅 {sub.uuid} 轮询时同步订阅信息成功")
                    except Exception as e:
                        logger.warning(f"[轮询订阅] 订阅 {sub.uuid} 获取订阅详情失败: {e}")
                        # 即使获取订阅详情失败，也继续尝试查询交易历史
                        
                        # 2. 查询Creem交易历史，检查是否有新的已支付交易
                        try:
                            logger.debug(f"[轮询订阅] 订阅 {sub.uuid} 开始查询交易历史")
                            tx = creem_client.search_transactions(
                                subscription_id=creem_sub.creem_subscription_id,
                                page_size=1
                            )
                            logger.debug(f"[轮询订阅] 订阅 {sub.uuid} 查询交易历史成功: items_count={len(tx.get('items', []))}")
                            
                            # 保存交易查询结果到 metadata
                            if not sub.subscription_metadata:
                                sub.subscription_metadata = {}
                            if "last_transaction_query" not in sub.subscription_metadata:
                                sub.subscription_metadata["last_transaction_query"] = {}
                            sub.subscription_metadata["last_transaction_query"] = {
                                "queried_at": now.isoformat(),
                                "transaction_response": tx,  # 保存完整的交易查询响应
                            }
                            
                            items = tx.get("items") or []
                            if items:
                                tx_status = items[0].get("status")
                                invoice_id = items[0].get("id")
                                transaction_data = items[0]  # 保存完整的交易数据
                                
                                # 保存交易详情到 metadata
                                if "last_transaction_details" not in sub.subscription_metadata:
                                    sub.subscription_metadata["last_transaction_details"] = {}
                                sub.subscription_metadata["last_transaction_details"] = {
                                    "transaction_id": transaction_data.get("id"),
                                    "status": transaction_data.get("status"),
                                    "amount": transaction_data.get("amount"),
                                    "currency": transaction_data.get("currency"),
                                    "created_at": transaction_data.get("created_at"),
                                    "period_start": transaction_data.get("period_start"),
                                    "period_end": transaction_data.get("period_end"),
                                    "full_transaction_data": transaction_data,  # 保存完整的交易数据
                                }
                                
                                if tx_status and tx_status.lower() == "paid":
                                    # 发放积分
                                    SubscriptionService.issue_cycle_points(
                                        db=db,
                                        subscription=sub,
                                        order=order,
                                        period_start=period_start,
                                        period_end=period_end,
                                        invoice_id=invoice_id,
                                    )
                                    sub.status = "active"
                                    
                                    # 保存积分发放信息到 metadata
                                    if "points_issued_history" not in sub.subscription_metadata:
                                        sub.subscription_metadata["points_issued_history"] = []
                                    sub.subscription_metadata["points_issued_history"].append({
                                        "issued_at": now.isoformat(),
                                        "period_start": period_start.isoformat(),
                                        "period_end": period_end.isoformat(),
                                        "invoice_id": invoice_id,
                                        "points_amount": sub.points_per_period,
                                    })
                                    # 只保留最近 20 次发放记录
                                    sub.subscription_metadata["points_issued_history"] = sub.subscription_metadata["points_issued_history"][-20:]
                                    
                                    db.commit()
                                    if not exists:
                                        issued += 1
                                    logger.info(
                                        f"[轮询订阅] 订阅 {sub.uuid} 续费积分发放成功: invoice_id={invoice_id}, "
                                        f"was_already_issued={exists is not None}"
                                    )
                                    continue
                            else:
                                logger.info(
                                    f"[轮询订阅] 订阅 {sub.uuid} 未找到已支付交易: "
                                    f"items_count={len(items)}, first_item_status={items[0].get('status') if items else None}"
                                )
                        except Exception as e:
                            logger.warning(f"[轮询订阅] 订阅 {sub.uuid} 查询交易历史失败: {e}")
                    else:
                        logger.warning(f"[轮询订阅] 跳过订阅 {sub.uuid}: 原因=支付方式不是Creem或没有Creem订阅详情")
                
                # 若超 24h 未扣款，可视业务需求标记 past_due
                hours_since_period_start = (now - period_start).total_seconds() / 3600
                if hours_since_period_start > max_hours:
                    logger.warning(
                        f"[轮询订阅] 订阅 {sub.uuid} 超过 {max_hours} 小时未扣款，标记为 past_due: "
                        f"hours_since_period_start={hours_since_period_start:.2f}"
                    )
                    sub.status = "past_due"
                    db.commit()
                    
            except Exception as e:
                errors += 1
                subscription_uuid = getattr(sub, 'uuid', None) or f"subscription_id={getattr(sub, 'subscription_id', None)}"
                logger.exception(f"[轮询订阅] 订阅续费处理失败 {subscription_uuid}: {e}")
                db.rollback()
        
        logger.info(
            f"[轮询订阅] 轮询完成: total={len(subs)}, checked={checked}, issued={issued}, "
            f"skipped={skipped}, errors={errors}"
        )
        return {"checked": checked, "issued": issued, "skipped": skipped, "errors": errors, "total": len(subs)}
    
    @staticmethod
    def _period_for_month_first(now: datetime) -> tuple[datetime, datetime]:
        """
        计算当月周期（每月1号到月底）
        
        Args:
            now: 当前时间
        
        Returns:
            (period_start, period_end) - 当月1号00:00:00 到下月1号00:00:00的前一秒
        """
        year = now.year
        month = now.month
        
        # 周期开始：当月1号 00:00:00
        period_start = datetime(year, month, 1, 0, 0, 0, tzinfo=timezone.utc)
        
        # 周期结束：下月1号 00:00:00 的前一秒（即当月最后一天 23:59:59）
        if month == 12:
            next_year = year + 1
            next_month = 1
        else:
            next_year = year
            next_month = month + 1
        
        period_end = datetime(next_year, next_month, 1, 0, 0, 0, tzinfo=timezone.utc) - timedelta(seconds=1)
        
        return period_start, period_end
    
    @staticmethod
    def run_monthly_payout(db: Session) -> dict:
        """
        月度积分发放任务（每月1号执行）
        
        处理所有订阅的月度积分发放：
        - 订阅当天已发放首期积分
        - 后续积分都在每月1号发放（当月1号到月底的周期）
        
        Args:
            db: 数据库会话
        
        Returns:
            发放结果统计字典
        """
        from datetime import datetime, timedelta, timezone
        from app.models.subscription_points_history import SubscriptionPointsHistory
        
        now = datetime.now(timezone.utc)
        today = now.date()
        
        # 只在每月1号执行
        if today.day != 1:
            logger.debug(f"[月度发放] 今天不是1号，跳过执行: today={today}")
            return {
                "total": 0,
                "issued": 0,
                "skipped": 0,
                "errors": 0,
                "message": f"今天不是1号，跳过执行: today={today}"
            }
        
        # 查询所有活跃的订阅（包括Creem和微信）
        subs = (
            db.query(Subscription)
            .filter(Subscription.status == "active")
            .filter(Subscription.billing_period.in_(["every-month", "every-quarter", "every-year"]))
            .all()
        )
        
        issued = 0
        skipped = 0
        errors = 0
        
        # 计算当月周期（1号到月底）
        period_start, period_end = SubscriptionService._period_for_month_first(now)
        
        for sub in subs:
            try:
                order = sub.order
                if not order:
                    skipped += 1
                    continue
                
                # 检查是否已发放过首期积分（通过查询历史记录）
                # 如果没有任何历史记录，说明是当月新订阅，首期积分会在购买时发放，这里跳过
                has_any_history = (
                    db.query(SubscriptionPointsHistory)
                    .filter(SubscriptionPointsHistory.subscription_id == sub.subscription_id)
                    .first()
                )
                
                if not has_any_history:
                    # 没有历史记录，说明是新订阅，首期积分会在购买时发放，这里跳过
                    skipped += 1
                    logger.debug(
                        f"[月度发放] 跳过新订阅（首期积分在购买时发放）: subscription_uuid={sub.uuid}"
                    )
                    continue
                
                # 幂等检查：检查当月是否已发放
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
                    logger.debug(
                        f"[月度发放] 当月积分已发放: subscription_uuid={sub.uuid}, period_start={period_start.date()}"
                    )
                    continue
                
                # 对于微信订阅，直接发放积分（不查询支付状态，因为不能自动续费，已经购买过）
                if sub.payment_method == "wechat":
                    SubscriptionService.issue_cycle_points(
                        db=db,
                        subscription=sub,
                        order=order,
                        period_start=period_start,
                        period_end=period_end,
                        invoice_id=None,  # 微信订阅没有invoice_id
                    )
                    db.commit()
                    issued += 1
                    logger.info(
                        f"[月度发放] 微信订阅积分发放成功: subscription_uuid={sub.uuid}, "
                        f"period_start={period_start.date()}, period_end={period_end.date()}, points={sub.points_per_period}"
                    )
                # 注意：Creem订阅由poll_subscriptions_billing轮询任务处理
                # 该任务会查询支付状态后发放积分，这里不处理Creem订阅，避免重复发放
                
            except Exception as e:
                errors += 1
                logger.exception(f"[月度发放] 订阅积分发放失败 subscription_uuid={sub.uuid}: {e}")
                db.rollback()
        
        logger.info(
            f"[月度发放] 月度发放完成: total={len(subs)}, issued={issued}, "
            f"skipped={skipped}, errors={errors}, period={period_start.date()}~{period_end.date()}"
        )
        
        return {
            "total": len(subs),
            "issued": issued,
            "skipped": skipped,
            "errors": errors,
            "period_start": period_start.isoformat(),
            "period_end": period_end.isoformat(),
        }
    
    @staticmethod
    def check_and_mark_expired_subscriptions(db: Session) -> dict:
        """
        检查并标记过期的订阅
        
        对于已过期的订阅（current_period_end < now），将状态标记为expired
        
        Args:
            db: 数据库会话
        
        Returns:
            检查结果统计字典
        """
        from datetime import datetime, timezone
        
        now = datetime.now(timezone.utc)
        
        # 查询所有活跃的订阅，检查是否已过期
        expired_subs = (
            db.query(Subscription)
            .filter(Subscription.status == "active")
            .filter(Subscription.current_period_end.isnot(None))
            .filter(Subscription.current_period_end < now)
            .all()
        )
        
        marked = 0
        errors = 0
        
        for sub in expired_subs:
            try:
                old_status = sub.status
                sub.status = "expired"
                
                # 如果还没有cancelled_at，设置为当前时间
                if not sub.cancelled_at:
                    sub.cancelled_at = now
                
                # 对于微信订阅，清空next_billing_date（如果存在）
                if sub.payment_method == "wechat" and sub.next_billing_date:
                    sub.next_billing_date = None
                
                # 对于Creem订阅，清空next_billing_date（如果已过期）
                if sub.payment_method == "creem" and sub.next_billing_date:
                    sub.next_billing_date = None
                
                # 更新metadata
                if not sub.subscription_metadata:
                    sub.subscription_metadata = {}
                sub.subscription_metadata["expired_at"] = now.isoformat()
                sub.subscription_metadata["expired_check_at"] = now.isoformat()
                
                db.commit()
                marked += 1
                logger.info(
                    f"[过期检查] 标记订阅为已过期: subscription_id={sub.subscription_id}, "
                    f"subscription_uuid={sub.uuid}, payment_method={sub.payment_method}, "
                    f"current_period_end={sub.current_period_end}, status={old_status}->expired"
                )
            except Exception as e:
                errors += 1
                logger.exception(f"[过期检查] 标记订阅过期失败 subscription_id={sub.subscription_id}: {e}")
                db.rollback()
        
        logger.info(
            f"[过期检查] 过期检查完成: total={len(expired_subs)}, marked={marked}, errors={errors}"
        )
        
        return {
            "total": len(expired_subs),
            "marked": marked,
            "errors": errors,
        }
