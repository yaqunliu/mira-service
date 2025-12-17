import uuid
from datetime import datetime, timedelta, timezone
from typing import List, Optional, Tuple
from sqlalchemy.orm import Session
from sqlalchemy import desc
from fastapi import HTTPException, status
from app.models.order import Order
from app.models.product import Product
from app.models.subscription import Subscription
from app.services.creem_client import creem_client
from app.services.product_service import ProductService
from app.services.points_service import PointsService
from app.models.user import User
from app.core.logger import logger
from fastapi import HTTPException
from app.schemas.refund import RefundResponse
from app.services.subscription_service import SubscriptionService
from app.models.webhook_event import WebhookEvent


class OrderService:
    @staticmethod
    def create_order(
        db: Session,
        user: User,
        product_uuid: str,
        order_type: str,
        success_url: Optional[str],
        cancel_url: Optional[str],
        metadata: Optional[dict] = None,
    ) -> Order:
        product = ProductService.get_by_uuid(db, product_uuid)
        if not product:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="产品不存在")

        if product.status != "active":
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="产品未激活")

        # 校验订阅/一次性类型
        if order_type not in ("onetime", "subscription"):
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="订单类型不支持")
        if order_type == "subscription" and product.billing_type != "recurring":
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="请选择订阅类产品")
        if order_type == "onetime" and product.billing_type != "onetime":
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="请选择一次性产品")

        order_number = OrderService._generate_order_number()
        order = Order(
            order_number=order_number,
            user_id=user.user_id,
            product_id=product.product_id,
            order_type=order_type,
            status="pending",
            amount=product.price,
            currency=product.currency or "USD",
            points_amount=product.points_amount,
            points_issued=0,
            success_url=success_url,
            cancel_url=cancel_url,
            expires_at=datetime.now(timezone.utc) + timedelta(minutes=30),
            order_metadata=metadata,
        )
        db.add(order)
        db.flush()

        # 创建 checkout session
        # 如果success_url存在，自动添加order_uuid参数
        final_success_url = success_url
        if success_url and "order_uuid" not in success_url:
            separator = "&" if "?" in success_url else "?"
            final_success_url = f"{success_url}{separator}order_uuid={order.uuid}"
        
        checkout = creem_client.create_checkout_session(
            creem_product_id=product.creem_product_id,
            success_url=final_success_url,
        )
        order.creem_checkout_id = checkout.get("id") or checkout.get("checkout_id")
        order.checkout_url = checkout.get("checkout_url") or checkout.get("url")
        
        # 保存 order.id（如果存在），用于后续交易查询
        checkout_order = checkout.get("order")
        if isinstance(checkout_order, dict):
            creem_order_id = checkout_order.get("id")
        elif isinstance(checkout_order, str):
            creem_order_id = checkout_order
        else:
            creem_order_id = None
        
        # 如果有 order_id，保存到 creem_transaction_id 字段（临时使用，后续可能需要在模型中添加 creem_order_id）
        if creem_order_id:
            # 注意：这里暂时使用 creem_transaction_id 字段存储 order_id
            # 如果后续需要区分，可以在 Order 模型中添加 creem_order_id 字段
            pass  # 暂时不保存，因为查询时可以使用 checkout_id
        
        db.commit()
        db.refresh(order)
        logger.info(f"创建订单成功: order_uuid={order.uuid}, checkout_id={order.creem_checkout_id}, creem_order_id={creem_order_id}")
        return order

    @staticmethod
    def get_order_by_uuid(db: Session, user: User, order_uuid: str) -> Order:
        order = db.query(Order).filter(Order.uuid == order_uuid, Order.user_id == user.user_id).first()
        if not order:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="订单不存在")
        return order

    @staticmethod
    def list_orders(
        db: Session,
        user: User,
        status_filter: Optional[str],
        order_type: Optional[str],
        page: int,
        page_size: int,
    ) -> Tuple[List[Order], int]:
        query = db.query(Order).filter(Order.user_id == user.user_id)
        if status_filter:
            query = query.filter(Order.status == status_filter)
        if order_type:
            query = query.filter(Order.order_type == order_type)

        total = query.count()
        items = (
            query.order_by(desc(Order.created_at))
            .offset((page - 1) * page_size)
            .limit(page_size)
            .all()
        )
        return items, total

    @staticmethod
    def mark_paid(
        db: Session,
        order: Order,
        creem_transaction_id: Optional[str] = None,
        paid_at: Optional[datetime] = None,
        creem_subscription_id: Optional[str] = None,
    ):
        """
        标记订单为已支付并发放积分
        
        Args:
            db: 数据库会话
            order: 订单对象
            creem_transaction_id: Creem 交易 ID
            paid_at: 支付时间
            creem_subscription_id: Creem 订阅 ID（订阅订单需要）
        """
        # 如果已经是 paid 状态，检查是否需要补发积分
        if order.status == "paid":
            # 检查一次性订单是否已发放积分
            if order.order_type == "onetime" and not order.points_issued:
                logger.warning(f"订单 {order.uuid} 已标记为 paid 但未发放积分，开始补发")
                points_record = PointsService.add_points(
                    db=db,
                    user_id=order.user_id,
                    points=order.points_amount,
                    record_type="recharge",
                    operation_type="purchase",
                    points_type="normal",
                    description="积分购买（补发）",
                    extra_data={"order_uuid": str(order.uuid)},
                )
                order.points_issued = 1
                db.commit()
                logger.info(f"订单补发积分成功 order_uuid={order.uuid}, points_record_id={points_record.record_id}")
            return
        
        order.status = "paid"
        order.paid_at = paid_at or datetime.now(timezone.utc)
        order.creem_transaction_id = creem_transaction_id or order.creem_transaction_id
        db.flush()

        # 发放积分（一次性支付）
        if order.order_type == "onetime" and not order.points_issued:
            points_record = PointsService.add_points(
                db=db,
                user_id=order.user_id,
                points=order.points_amount,
                record_type="recharge",
                operation_type="purchase",
                points_type="normal",
                description="积分购买",
                extra_data={"order_uuid": str(order.uuid)},
            )
            order.points_issued = 1
            logger.info(f"订单发放积分成功 order_uuid={order.uuid}, points_record_id={points_record.record_id}")
        
        # 处理订阅订单的首期积分发放
        elif order.order_type == "subscription":
            # 获取或创建订阅记录
            subscription = None
            if creem_subscription_id:
                subscription = (
                    db.query(Subscription)
                    .filter(
                        Subscription.creem_subscription_id == creem_subscription_id,
                        Subscription.user_id == order.user_id,
                    )
                    .first()
                )
            
            if not subscription:
                # 创建订阅记录
                subscription = SubscriptionService.upsert_from_webhook(
                    db=db,
                    user_id=order.user_id,
                    order=order,
                    creem_subscription_id=creem_subscription_id or order.creem_checkout_id,
                    status="active",
                    billing_period=order.product.billing_period,
                    current_period_start=paid_at or datetime.now(timezone.utc),
                    current_period_end=None,
                    next_billing_date=None,
                    points_per_period=order.points_amount,
                    metadata=None,
                )
                logger.info(f"订单 {order.uuid} 创建订阅记录: subscription_id={subscription.subscription_id}")
                
                # 如果订阅ID存在，尝试从 Creem API 获取完整订阅信息
                if subscription.creem_subscription_id and not subscription.current_period_end:
                    try:
                        creem_sub = creem_client.get_subscription(subscription.creem_subscription_id)
                        from app.services.webhook_service import WebhookService
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
            
            # 检查是否已发放首期积分（通过检查是否有历史记录）
            period_start = subscription.current_period_start or paid_at or datetime.now(timezone.utc)
            period_end = subscription.current_period_end or (period_start + timedelta(days=30))  # 默认30天
            
            # 幂等检查：检查是否已发放过首期积分
            from app.models.subscription_points_history import SubscriptionPointsHistory
            existing_history = (
                db.query(SubscriptionPointsHistory)
                .filter(
                    SubscriptionPointsHistory.subscription_id == subscription.subscription_id,
                    SubscriptionPointsHistory.period_start == period_start,
                )
                .first()
            )
            
            if not existing_history:
                # 发放首期积分
                history = SubscriptionService.issue_cycle_points(
                    db=db,
                    subscription=subscription,
                    order=order,
                    period_start=period_start,
                    period_end=period_end,
                    creem_invoice_id=creem_transaction_id,
                )
                logger.info(f"订单 {order.uuid} 订阅首期积分发放成功: history_id={history.history_id}")
            else:
                logger.info(f"订单 {order.uuid} 订阅首期积分已发放，跳过: history_id={existing_history.history_id}")

        db.commit()
        db.refresh(order)

    @staticmethod
    def _generate_order_number() -> str:
        return datetime.now(timezone.utc).strftime("ORD%Y%m%d%H%M%S") + uuid.uuid4().hex[:6].upper()

    # ========== 轮询容错：查询交易并补发 ==========
    @staticmethod
    def poll_pending_orders(db: Session, now: datetime | None = None, max_age_hours: int = 24) -> dict:
        """
        查询处于 pending 且未超 max_age_hours 的订单，调用 Creem 交易查询确认支付。
        触发条件：创建 >=3 分钟；超 24 小时未支付则标记 failed 并停止。
        """
        # 确保 now 是 timezone-aware 的 datetime
        if now is None:
            now = datetime.now(timezone.utc)
        elif now.tzinfo is None:
            # 如果传入的是 naive datetime，转换为 UTC aware
            now = now.replace(tzinfo=timezone.utc)
        
        min_age = now - timedelta(minutes=3)
        max_age = now - timedelta(hours=max_age_hours)
        orders = (
            db.query(Order)
            .filter(Order.status == "pending")
            .filter(Order.created_at <= min_age)
            .filter(Order.created_at >= max_age)
            .all()
        )

        checked = 0
        paid = 0
        expired = 0
        errors = 0

        logger.info(f"开始轮询订单支付状态，找到 {len(orders)} 个待检查订单")
        
        for order in orders:
            try:
                checked += 1
                logger.info(f"检查订单: order_uuid={order.uuid}, checkout_id={order.creem_checkout_id}, created_at={order.created_at}")
                
                # 交易查询：根据 Creem API 文档，应该使用 order_id 查询
                # 如果 checkout 响应中有 order.id，应该使用它；否则尝试使用 checkout_id
                # 注意：根据 Creem API，checkout_id 可能也可以作为 order_id 使用
                if not order.creem_checkout_id:
                    logger.warning(f"订单 {order.uuid} 没有 checkout_id，跳过")
                    continue
                
                # 重试机制：最多重试3次
                max_retries = 3
                retry_delay = 2  # 秒
                checkout_data = None
                
                for retry_count in range(max_retries):
                    try:
                        # 通过 checkout_id 查询 checkout 详情（更直接的方法）
                        logger.info(f"订单 {order.uuid} 查询 checkout (尝试 {retry_count + 1}/{max_retries}): checkout_id={order.creem_checkout_id}")
                        checkout_data = creem_client.get_checkout(order.creem_checkout_id)
                        
                        # 记录完整的响应信息
                        logger.info(f"订单 {order.uuid} Creem API 响应 (checkout): {checkout_data}")
                        
                        # 如果查询成功，跳出重试循环
                        break
                    except Exception as retry_error:
                        if retry_count < max_retries - 1:
                            logger.warning(
                                f"订单 {order.uuid} 查询 checkout 失败 (尝试 {retry_count + 1}/{max_retries}): {retry_error}, "
                                f"{retry_delay}秒后重试"
                            )
                            import time
                            time.sleep(retry_delay)
                        else:
                            # 最后一次重试失败，抛出异常
                            logger.error(f"订单 {order.uuid} 查询 checkout 失败，已重试 {max_retries} 次: {retry_error}")
                            raise
                
                if not checkout_data:
                    logger.warning(f"订单 {order.uuid} 未获取到 checkout 数据")
                    continue
                
                # 解析 checkout 信息
                checkout_id = checkout_data.get("id")
                checkout_status = checkout_data.get("status")  # pending, processing, completed, expired
                checkout_order = checkout_data.get("order")  # 可能是字符串或对象
                checkout_subscription = checkout_data.get("subscription")
                checkout_product = checkout_data.get("product")
                
                logger.info(
                    f"订单 {order.uuid} checkout 详情: "
                    f"checkout_id={checkout_id}, "
                    f"checkout_status={checkout_status}, "
                    f"order={checkout_order}, "
                    f"subscription={checkout_subscription}, "
                    f"product={checkout_product}"
                )
                
                # 解析 order 信息（可能是字符串 ID 或完整对象）
                order_data = None
                if isinstance(checkout_order, dict):
                    order_data = checkout_order
                elif isinstance(checkout_order, str):
                    # 如果是字符串，说明只是 order ID，需要从 checkout 中获取更多信息
                    # 但根据文档，checkout 的 order 字段应该是完整对象
                    logger.info(f"订单 {order.uuid} checkout.order 是字符串 ID: {checkout_order}")
                
                # 如果 checkout_order 是对象，提取订单状态
                if isinstance(checkout_order, dict):
                    creem_order_id = checkout_order.get("id")
                    creem_order_status = checkout_order.get("status")  # pending, paid
                    creem_order_amount = checkout_order.get("amount")
                    creem_order_currency = checkout_order.get("currency")
                    creem_order_type = checkout_order.get("type")  # recurring, onetime
                    creem_transaction_id = checkout_order.get("transaction")
                    
                    logger.info(
                        f"订单 {order.uuid} Creem Order 详情: "
                        f"order_id={creem_order_id}, "
                        f"order_status={creem_order_status}, "
                        f"amount={creem_order_amount}, "
                        f"currency={creem_order_currency}, "
                        f"type={creem_order_type}, "
                        f"transaction_id={creem_transaction_id}"
                    )
                    
                    # 判断支付状态：checkout.status 为 completed 或 order.status 为 paid
                    is_paid = (
                        checkout_status == "completed" or 
                        (creem_order_status and creem_order_status.lower() == "paid")
                    )
                    
                    if is_paid:
                        logger.info(f"订单 {order.uuid} 支付成功 (checkout_status={checkout_status}, order_status={creem_order_status})，开始发放积分")
                        
                        # 记录轮询事件到 webhook_events 表
                        event_payload = {
                            "type": "checkout.session.completed",
                            "data": checkout_data,
                            "source": "polling",
                        }
                        event = WebhookEvent(
                            event_type="checkout.session.completed",
                            creem_event_id=f"polling_{order.uuid}_{int(now.timestamp())}",
                            payload=event_payload,
                            source="polling",
                            processed=True,
                            processed_at=now,
                        )
                        db.add(event)
                        
                        # 获取订阅 ID（如果是订阅订单）
                        creem_subscription_id = None
                        if checkout_subscription:
                            if isinstance(checkout_subscription, dict):
                                creem_subscription_id = checkout_subscription.get("id")
                            elif isinstance(checkout_subscription, str):
                                creem_subscription_id = checkout_subscription
                        
                        OrderService.mark_paid(
                            db, 
                            order, 
                            creem_transaction_id=creem_transaction_id, 
                            paid_at=now,
                            creem_subscription_id=creem_subscription_id
                        )
                        paid += 1
                        logger.info(f"订单 {order.uuid} 积分发放完成")
                        continue
                    else:
                        logger.info(
                            f"订单 {order.uuid} 尚未支付完成: "
                            f"checkout_status={checkout_status}, "
                            f"order_status={creem_order_status}"
                        )
                else:
                    # checkout_order 不是对象，可能是字符串或 None
                    # 根据 checkout_status 判断
                    if checkout_status == "completed":
                        logger.info(f"订单 {order.uuid} checkout 状态为 completed，开始发放积分")
                        
                        # 记录轮询事件到 webhook_events 表
                        event_payload = {
                            "type": "checkout.session.completed",
                            "data": checkout_data,
                            "source": "polling",
                        }
                        event = WebhookEvent(
                            event_type="checkout.session.completed",
                            creem_event_id=f"polling_{order.uuid}_{int(now.timestamp())}",
                            payload=event_payload,
                            source="polling",
                            processed=True,
                            processed_at=now,
                        )
                        db.add(event)
                        
                        # 获取订阅 ID（如果是订阅订单）
                        creem_subscription_id = None
                        if checkout_subscription:
                            if isinstance(checkout_subscription, dict):
                                creem_subscription_id = checkout_subscription.get("id")
                            elif isinstance(checkout_subscription, str):
                                creem_subscription_id = checkout_subscription
                        
                        OrderService.mark_paid(
                            db, 
                            order, 
                            creem_transaction_id=None, 
                            paid_at=now,
                            creem_subscription_id=creem_subscription_id
                        )
                        paid += 1
                        logger.info(f"订单 {order.uuid} 积分发放完成")
                        continue
                    elif checkout_status == "expired":
                        logger.warning(f"订单 {order.uuid} checkout 已过期")
                    else:
                        logger.info(f"订单 {order.uuid} checkout 状态为 {checkout_status}，等待支付完成")

                # 超过窗口仍未支付
                if order.created_at and (now - order.created_at) > timedelta(hours=max_age_hours):
                    logger.warning(f"订单 {order.uuid} 超过 {max_age_hours} 小时未支付，标记为 failed")
                    order.status = "failed"
                    db.commit()
                    expired += 1
            except Exception as e:
                errors += 1
                logger.exception(f"轮询订单支付失败 order_uuid={order.uuid}: {e}")
                db.rollback()

        return {"checked": checked, "paid": paid, "expired": expired, "errors": errors}

    @staticmethod
    def refund_order(
        db: Session,
        order: Order,
        force: bool = False,
        refund_reason: str | None = None,
    ) -> RefundResponse:
        """
        按“已到手积分可扣除比例”计算部分退款并扣分；仅管理员调用。
        """
        if order.status not in ("paid", "refunded"):
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="订单未支付或不可退款")

        issued_points = order.points_amount
        # 当前可用积分
        account = PointsService.get_or_create_account(db, order.user_id)
        can_deduct = min(account.available_points, issued_points)
        if issued_points <= 0:
            refund_ratio = 1.0
        else:
            refund_ratio = can_deduct / issued_points

        if not force and refund_ratio < 0.2:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="可退比例过低，拒绝退款")

        refund_amount = int(order.amount * refund_ratio)

        # 扣积分（负向记录）
        if can_deduct > 0:
            PointsService.deduct_points(
                db=db,
                user_id=order.user_id,
                points=can_deduct,
                record_type="refund",
                operation_type="refund",
                description=f"订单退款扣回积分 {order.uuid}",
                extra_data={"order_uuid": str(order.uuid), "refund_ratio": refund_ratio},
            )

        # 订阅需要取消（如果存在）
        if order.order_type == "subscription" and order.subscription:
            SubscriptionService.cancel_subscription(
                db=db,
                user_id=order.user_id,
                subscription_uuid=str(order.subscription.uuid),
                cancel_at_period_end=False,
            )

        order.status = "refunded"
        order.order_metadata = order.order_metadata or {}
        order.order_metadata.update(
            {
                "refund_amount": refund_amount,
                "refunded_points": can_deduct,
                "refund_ratio": refund_ratio,
                "refund_reason": refund_reason,
            }
        )
        db.commit()
        db.refresh(order)
        logger.info(
            f"订单退款成功 order_uuid={order.uuid}, amount={refund_amount}, points={can_deduct}, ratio={refund_ratio}"
        )
        return RefundResponse(
            refund_amount=refund_amount,
            refunded_points=can_deduct,
            refund_ratio=refund_ratio,
            status="refunded",
            message="退款完成",
        )

