import uuid
from datetime import datetime, timedelta, timezone
from typing import List, Optional, Tuple
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import desc
from fastapi import HTTPException, status
from app.models.order import Order
from app.models.product import Product
from app.models.subscription import Subscription
from app.models.creem_subscription import CreemSubscription
from app.models.wechat_subscription import WechatSubscription
from app.services.creem_client import creem_client
from app.services.product_service import ProductService
from app.services.points_service import PointsService
from app.services.payment_service_factory import PaymentServiceFactory
from app.models.user import User
from app.core.logger import logger
from fastapi import HTTPException
from app.schemas.refund import RefundResponse
from app.services.subscription_service import SubscriptionService
from app.models.webhook_event import WebhookEvent
from app.schemas.order import Order as OrderSchema
from app.core.config import settings


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
        
        # 检查订阅产品是否已存在活跃订阅（防止重复购买）
        # 注意：微信订阅允许重复购买（续费就是新订单），Creem订阅不允许重复购买
        if order_type == "subscription" and product.payment_method != "wechat":
            existing_subscription = (
                db.query(Subscription)
                .join(Order, Subscription.order_id == Order.order_id)
                .filter(
                    Subscription.user_id == user.user_id,
                    Order.product_id == product.product_id,
                    Subscription.status.in_(["active", "past_due"]),  # 活跃或逾期状态都算作已有订阅
                )
                .first()
            )
            if existing_subscription:
                # Creem订阅不允许重复购买
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"您已拥有该产品的活跃订阅，无法重复购买。订阅状态：{existing_subscription.status}"
                )

        # 从产品获取支付方式
        payment_method = product.payment_method
        if not payment_method:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="产品未配置支付方式"
            )
        
        # 验证产品是否配置了远程产品ID（Creem需要传递产品ID）
        if payment_method == "creem" and not product.origin_product_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="产品未配置远程产品ID（origin_product_id），Creem支付需要此字段"
            )
        # 微信支付不需要产品ID，可以继续

        order_number = OrderService._generate_order_number()
        order = Order(
            order_number=order_number,
            user_id=user.user_id,
            product_id=product.product_id,
            payment_method=payment_method,  # 从产品获取
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

        # 根据支付方式调用对应的支付服务
        payment_service = PaymentServiceFactory.get_service(payment_method)
        payment_info = payment_service.create_payment(
            db=db,
            order=order,
            success_url=success_url,
            cancel_url=cancel_url,
        )
        
        # 将 payment_info 保存到 order_metadata 中，方便后期排查
        if metadata is None:
            metadata = {}
        else:
            # 确保 metadata 是字典的副本，避免修改原始对象
            metadata = dict(metadata)
        
        # 保存支付信息到 metadata
        metadata["payment_info"] = payment_info
        metadata["payment_info_created_at"] = datetime.now(timezone.utc).isoformat()
        
        # 更新订单的 metadata
        order.order_metadata = metadata
        
        db.commit()
        
        # 重新加载订单以获取关联的支付信息和产品信息
        order = (
            db.query(Order)
            .options(
                joinedload(Order.creem_payment),
                joinedload(Order.wechat_payment),
                joinedload(Order.product),
            )
            .filter(Order.order_id == order.order_id)
            .first()
        )
        
        logger.info(
            f"创建订单成功: order_uuid={order.uuid}, "
            f"payment_method={payment_method}, "
            f"payment_info={payment_info}"
        )
        
        # 构建返回的订单对象，包含 payment_info
        return OrderService._build_order_with_payment_info(order)

    @staticmethod
    def get_order_by_uuid(db: Session, user: User, order_uuid: str) -> Order:
        order = (
            db.query(Order)
            .options(
                joinedload(Order.creem_payment),
                joinedload(Order.wechat_payment),
                joinedload(Order.product),
            )
            .filter(Order.uuid == order_uuid, Order.user_id == user.user_id)
            .first()
        )
        if not order:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="订单不存在")
        return OrderService._build_order_with_payment_info(order)

    @staticmethod
    def _build_order_with_payment_info(order: Order) -> Order:
        """
        构建包含 payment_info 的订单对象
        
        由于 Pydantic schema 的 payment_info 字段需要从关联表中获取，
        我们需要在返回订单时手动设置这个属性。
        """
        # 构建 payment_info 字典
        payment_info = None
        
        if order.payment_method == "creem" and order.creem_payment:
            payment_info = {
                "checkout_url": order.creem_payment.checkout_url,
                "checkout_id": order.creem_payment.creem_checkout_id,
            }
            if order.creem_payment.creem_transaction_id:
                payment_info["transaction_id"] = order.creem_payment.creem_transaction_id
        elif order.payment_method == "wechat" and order.wechat_payment:
            payment_info = {
                "code_url": order.wechat_payment.code_url,
                "out_trade_no": order.wechat_payment.out_trade_no,
            }
            if order.wechat_payment.wechat_transaction_id:
                payment_info["transaction_id"] = order.wechat_payment.wechat_transaction_id
            if order.wechat_payment.prepay_id:
                payment_info["prepay_id"] = order.wechat_payment.prepay_id
        
        # 将 payment_info 附加到订单对象上
        # 这样 Pydantic schema 在序列化时就能获取到这个字段
        order.payment_info = payment_info
        
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
        query = (
            db.query(Order)
            .options(
                joinedload(Order.creem_payment),
                joinedload(Order.wechat_payment),
                joinedload(Order.product),
            )
            .filter(Order.user_id == user.user_id)
        )
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
        # 为每个订单构建 payment_info
        items = [OrderService._build_order_with_payment_info(order) for order in items]
        return items, total

    @staticmethod
    def mark_paid(
        db: Session,
        order: Order,
        creem_transaction_id: Optional[str] = None,
        paid_at: Optional[datetime] = None,
        creem_subscription_id: Optional[str] = None,
        wechat_transaction_id: Optional[str] = None,
    ):
        """
        标记订单为已支付并发放积分
        
        Args:
            db: 数据库会话
            order: 订单对象
            creem_transaction_id: Creem 交易 ID（Creem 支付时使用）
            paid_at: 支付时间
            creem_subscription_id: Creem 订阅 ID（订阅订单需要）
            wechat_transaction_id: 微信交易 ID（微信支付时使用）
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
        
        # 根据支付方式更新对应的支付详情表
        if order.payment_method == "creem" and order.creem_payment:
            if creem_transaction_id:
                order.creem_payment.creem_transaction_id = creem_transaction_id
        elif order.payment_method == "wechat" and order.wechat_payment:
            if wechat_transaction_id:
                order.wechat_payment.wechat_transaction_id = wechat_transaction_id
        
        db.flush()

        # 发放积分（一次性支付）
        if order.order_type == "onetime" and not order.points_issued:
            logger.info(f"开始为订单 {order.uuid} 发放积分: points={order.points_amount}, user_id={order.user_id}")
            try:
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
                db.flush()  # 确保 points_issued 更新被保存
                logger.info(
                    f"订单发放积分成功 order_uuid={order.uuid}, "
                    f"points_record_id={points_record.record_id}, "
                    f"points={order.points_amount}, "
                    f"points_issued={order.points_issued}, "
                    f"user_id={order.user_id}"
                )
                # 验证积分是否真的发放成功
                from app.models.points_record import PointsRecord
                verify_record = db.query(PointsRecord).filter(PointsRecord.record_id == points_record.record_id).first()
                if verify_record:
                    logger.info(f"验证积分记录存在: record_id={verify_record.record_id}, points={verify_record.points}")
                else:
                    logger.error(f"警告：积分记录不存在！record_id={points_record.record_id}")
            except Exception as e:
                logger.error(f"订单发放积分失败 order_uuid={order.uuid}, error={e}")
                import traceback
                logger.error(f"积分发放异常堆栈: {traceback.format_exc()}")
                raise
        
        # 处理订阅订单的首期积分发放
        elif order.order_type == "subscription":
            # 获取或创建订阅记录
            subscription = None
            is_renewal = False  # 初始化 is_renewal 变量
            # 根据支付方式确定订阅ID
            subscription_id = None
            if order.payment_method == "creem":
                subscription_id = creem_subscription_id
            elif order.payment_method == "wechat":
                # 微信订阅ID从其他地方传入，这里暂时为None
                subscription_id = None
            
            if subscription_id:
                # 根据支付方式查询订阅
                if order.payment_method == "creem":
                    creem_sub = (
                        db.query(CreemSubscription)
                        .filter(CreemSubscription.creem_subscription_id == subscription_id)
                        .first()
                    )
                    if creem_sub:
                        subscription = creem_sub.subscription
                elif order.payment_method == "wechat":
                    # 微信订阅通过contract_id查询
                    wechat_sub = (
                        db.query(WechatSubscription)
                        .filter(WechatSubscription.wechat_contract_id == subscription_id)
                        .first()
                    )
                    if wechat_sub:
                        subscription = wechat_sub.subscription
            
            if not subscription:
                # 创建订阅记录
                subscription = SubscriptionService.upsert_from_webhook(
                    db=db,
                    user_id=order.user_id,
                    order=order,
                    payment_method=order.payment_method,
                    subscription_id=subscription_id,  # 通用订阅ID
                    status="active",
                    billing_period=order.product.billing_period,
                    current_period_start=paid_at or datetime.now(timezone.utc),
                    current_period_end=None,
                    next_billing_date=None,
                    points_per_period=order.points_amount,
                    metadata=None,
                )
                logger.info(f"订单 {order.uuid} 创建订阅记录: subscription_id={subscription.subscription_id}")
                is_renewal = False  # 新创建的订阅不是续费
            else:
                # 更新已存在的订阅（微信订阅续费场景）
                if order.payment_method == "wechat":
                    is_renewal = True
                    # 更新订阅状态和周期
                    subscription.status = "active"
                    subscription.order_id = order.order_id  # 更新关联的订单
                    period_start = paid_at or datetime.now(timezone.utc)
                    period_end = SubscriptionService._calculate_period_end(
                        period_start,
                        subscription.billing_period or order.product.billing_period or "every-month"
                    )
                    subscription.current_period_start = period_start
                    subscription.current_period_end = period_end
                    subscription.next_billing_date = None  # 手动续费，不设置下次扣款时间
                    subscription.points_per_period = order.points_amount
                    # 确保metadata标记为手动续费
                    if not subscription.subscription_metadata:
                        subscription.subscription_metadata = {}
                    subscription.subscription_metadata["auto_renewal"] = False
                    subscription.subscription_metadata["renewal_type"] = "manual"
                    subscription.subscription_metadata["last_renewed_at"] = datetime.now(timezone.utc).isoformat()
                    subscription.subscription_metadata["renewal_order_uuid"] = str(order.uuid)
                    db.commit()
                    logger.info(
                        f"订单 {order.uuid} 更新微信订阅续费: subscription_id={subscription.subscription_id}, "
                        f"period_start={period_start}, period_end={period_end}"
                    )
                
                # 如果订阅ID存在，尝试从支付平台API获取完整订阅信息
                if subscription_id:
                    try:
                        if order.payment_method == "creem":
                            creem_sub = creem_client.get_subscription(subscription_id)
                            # 使用统一的同步方法同步所有字段
                            SubscriptionService.sync_from_creem_api(db, subscription, creem_sub)
                            db.commit()
                            logger.info(f"从 Creem API 同步订阅信息成功: {subscription_id}")
                        # 微信订阅信息同步待实现
                    except Exception as e:
                        logger.warning(f"从支付平台API获取订阅详情失败: {e}")
            
            # 对于微信订阅，如果周期结束时间未设置，需要计算（新创建的订阅）
            if order.payment_method == "wechat" and not subscription.current_period_end:
                period_start = subscription.current_period_start or paid_at or datetime.now(timezone.utc)
                period_end = SubscriptionService._calculate_period_end(
                    period_start, 
                    subscription.billing_period or order.product.billing_period or "every-month"
                )
                subscription.current_period_end = period_end
                # 确保metadata标记为手动续费
                if not subscription.subscription_metadata:
                    subscription.subscription_metadata = {}
                subscription.subscription_metadata["auto_renewal"] = False
                subscription.subscription_metadata["renewal_type"] = "manual"
                db.commit()
                logger.info(f"微信订阅计算周期结束时间: subscription_id={subscription.subscription_id}, period_end={period_end}")
            
            # 检查是否已发放首期积分（通过检查是否有历史记录）
            # 注意：如果是续费（is_renewal=True），已经在续费逻辑中处理了积分发放，这里跳过
            if not is_renewal:
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
                    logger.info(f"开始为订单 {order.uuid} 发放订阅首期积分: subscription_id={subscription.subscription_id}, points={subscription.points_per_period}")
                    try:
                        history = SubscriptionService.issue_cycle_points(
                            db=db,
                            subscription=subscription,
                            order=order,
                            period_start=period_start,
                            period_end=period_end,
                            invoice_id=creem_transaction_id or wechat_transaction_id,  # 使用通用 invoice_id 参数
                        )
                        logger.info(f"订单 {order.uuid} 订阅首期积分发放成功: history_id={history.history_id}, points={subscription.points_per_period}")
                    except Exception as e:
                        logger.error(f"订单 {order.uuid} 订阅首期积分发放失败: error={e}")
                        raise
                else:
                    logger.info(f"订单 {order.uuid} 订阅首期积分已发放，跳过: history_id={existing_history.history_id}")
            else:
                # 续费时也需要发放积分（新周期）
                period_start = subscription.current_period_start or paid_at or datetime.now(timezone.utc)
                period_end = subscription.current_period_end or (period_start + timedelta(days=30))
                
                # 检查是否已发放过这个周期的积分
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
                    # 发放续费周期的积分
                    logger.info(f"开始为订单 {order.uuid} 发放微信订阅续费积分: subscription_id={subscription.subscription_id}, points={subscription.points_per_period}")
                    try:
                        history = SubscriptionService.issue_cycle_points(
                            db=db,
                            subscription=subscription,
                            order=order,
                            period_start=period_start,
                            period_end=period_end,
                            invoice_id=wechat_transaction_id,  # 使用微信交易号作为invoice_id
                        )
                        logger.info(
                            f"订单 {order.uuid} 微信订阅续费积分发放成功: history_id={history.history_id}, "
                            f"points={subscription.points_per_period}, period_start={period_start}, period_end={period_end}"
                        )
                    except Exception as e:
                        logger.error(f"订单 {order.uuid} 微信订阅续费积分发放失败: error={e}")
                        raise
                else:
                    logger.info(
                        f"订单 {order.uuid} 微信订阅续费积分已发放，跳过: history_id={existing_history.history_id}"
                    )

        db.commit()
        db.refresh(order)

    @staticmethod
    def _generate_order_number() -> str:
        return datetime.now(timezone.utc).strftime("ORD%Y%m%d%H%M%S") + uuid.uuid4().hex[:6].upper()

    # ========== 轮询容错：查询交易并补发 ==========
    @staticmethod
    def poll_pending_orders(db: Session, now: datetime | None = None, max_age_hours: int = 24) -> dict:
        """
        查询处于 pending 的订单，调用支付平台查询接口确认支付。
        
        轮询策略：
        - 微信支付：只查询30分钟内的订单，超过20分钟未支付则标记为取消，超过30分钟不再轮询
        - Creem支付：查询24小时内的订单，如果支付未完成不修改状态，只是不再轮询
        
        触发条件：创建 >=3 分钟
        """
        from app.services.order_query_service import OrderQueryService
        
        # 确保 now 是 timezone-aware 的 datetime
        if now is None:
            now = datetime.now(timezone.utc)
        elif now.tzinfo is None:
            # 如果传入的是 naive datetime，转换为 UTC aware
            now = now.replace(tzinfo=timezone.utc)
        
        min_age = now - timedelta(minutes=3)
        from sqlalchemy.orm import joinedload
        
        # 分别查询微信支付和Creem支付的订单
        # 微信支付：只查询30分钟内的订单
        wechat_max_age = now - timedelta(minutes=30)
        wechat_orders = (
            db.query(Order)
            .options(joinedload(Order.wechat_payment))
            .filter(Order.status == "pending")
            .filter(Order.payment_method == "wechat")
            .filter(Order.created_at <= min_age)
            .filter(Order.created_at >= wechat_max_age)
            .all()
        )
        
        # Creem支付：查询24小时内的订单
        creem_max_age = now - timedelta(hours=max_age_hours)
        creem_orders = (
            db.query(Order)
            .options(joinedload(Order.creem_payment))
            .filter(Order.status == "pending")
            .filter(Order.payment_method == "creem")
            .filter(Order.created_at <= min_age)
            .filter(Order.created_at >= creem_max_age)
            .all()
        )
        
        orders = wechat_orders + creem_orders

        checked = 0
        paid = 0
        expired = 0
        errors = 0

        logger.info(f"开始轮询订单支付状态，找到 {len(orders)} 个待检查订单（微信: {len(wechat_orders)}, Creem: {len(creem_orders)}）")
        
        # Debug 模式下记录轮询开始信息
        if settings.DEBUG:
            logger.debug(f"[DEBUG] ========== 订单轮询任务开始 ==========")
            logger.debug(f"  当前时间: {now.isoformat()}")
            logger.debug(f"  最小创建时间: {min_age.isoformat()}")
            logger.debug(f"  微信订单最大创建时间: {wechat_max_age.isoformat()} (30分钟内)")
            logger.debug(f"  Creem订单最大创建时间: {creem_max_age.isoformat()} ({max_age_hours}小时内)")
            logger.debug(f"  待检查订单数: {len(orders)} (微信: {len(wechat_orders)}, Creem: {len(creem_orders)})")
        
        for order in orders:
            try:
                checked += 1
                order_age = (now - order.created_at).total_seconds() / 60  # 订单寿命（分钟）
                
                logger.info(f"检查订单: order_uuid={order.uuid}, payment_method={order.payment_method}, created_at={order.created_at}, age={order_age:.1f}分钟")
                
                # Debug 模式下记录订单详情
                if settings.DEBUG:
                    logger.debug(f"[DEBUG] 检查订单详情:")
                    logger.debug(f"  订单UUID: {order.uuid}")
                    logger.debug(f"  订单号: {order.order_number}")
                    logger.debug(f"  支付方式: {order.payment_method}")
                    logger.debug(f"  订单类型: {order.order_type}")
                    logger.debug(f"  创建时间: {order.created_at}")
                    logger.debug(f"  订单寿命: {order_age:.1f}分钟")
                
                # 根据支付方式处理
                if order.payment_method == "wechat":
                    # 微信支付：只查询30分钟内的订单
                    if order_age > 30:
                        logger.info(f"订单 {order.uuid} 超过30分钟，不再轮询")
                        continue
                    
                    # 查询微信支付状态
                    result = OrderQueryService.query_order_status(db, order)
                    
                    if result.get("status") == "paid":
                        # 订单已支付，需要更新订单状态并发放积分
                        if order.status != "paid":
                            # 解析支付时间
                            success_time = result.get("success_time")
                            paid_at = None
                            if success_time:
                                try:
                                    from dateutil import parser
                                    paid_at = parser.isoparse(success_time)
                                    # 转换为UTC时间
                                    if paid_at.tzinfo is None:
                                        paid_at = paid_at.replace(tzinfo=timezone.utc)
                                    else:
                                        paid_at = paid_at.astimezone(timezone.utc)
                                except Exception as e:
                                    logger.warning(f"解析支付时间失败: {e}")
                                    paid_at = now
                            else:
                                paid_at = now
                            
                            # 获取微信交易号
                            wechat_transaction_id = result.get("transaction_id")
                            
                            # 标记订单为已支付并发放积分
                            OrderService.mark_paid(
                                db=db,
                                order=order,
                                wechat_transaction_id=wechat_transaction_id,
                                paid_at=paid_at,
                            )
                            logger.info(f"订单 {order.uuid} 支付成功，已更新订单状态并发放积分")
                        else:
                            logger.info(f"订单 {order.uuid} 已支付，状态已更新")
                        paid += 1
                    elif result.get("status") == "cancelled":
                        # 订单已取消
                        if order.status != "cancelled":
                            order.status = "cancelled"
                            db.commit()
                            logger.info(f"订单 {order.uuid} 已取消")
                        expired += 1
                    elif order_age > 20:
                        # 超过20分钟未支付，标记为取消
                        logger.warning(f"订单 {order.uuid} 超过20分钟未支付，标记为取消")
                        order.status = "cancelled"
                        db.commit()
                        expired += 1
                    else:
                        # 订单仍为pending，继续等待
                        logger.info(f"订单 {order.uuid} 仍在等待支付，订单寿命: {order_age:.1f}分钟")
                
                elif order.payment_method == "creem":
                    # Creem支付：查询24小时内的订单
                    # 从关系对象中获取 checkout_id
                    creem_checkout_id = None
                    if order.creem_payment:
                        creem_checkout_id = order.creem_payment.creem_checkout_id
                    
                    if not creem_checkout_id:
                        logger.warning(f"订单 {order.uuid} 没有 checkout_id，跳过")
                        continue
                    
                    # 重试机制：最多重试3次
                    max_retries = 3
                    retry_delay = 2  # 秒
                    checkout_data = None
                    
                    for retry_count in range(max_retries):
                        try:
                            # 通过 checkout_id 查询 checkout 详情（更直接的方法）
                            logger.info(f"订单 {order.uuid} 查询 checkout (尝试 {retry_count + 1}/{max_retries}): checkout_id={creem_checkout_id}")
                            checkout_data = creem_client.get_checkout(creem_checkout_id)
                            
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
                    
                    # 保存轮询时的 checkout 详情到 order_metadata
                    if not order.order_metadata:
                        order.order_metadata = {}
                    
                    polling_history = order.order_metadata.get("polling_history", [])
                    polling_history.append({
                        "polled_at": now.isoformat(),
                        "checkout_id": checkout_id,
                        "checkout_status": checkout_status,
                        "checkout_data": checkout_data,  # 保存完整的 checkout 数据
                    })
                    # 只保留最近 20 次轮询记录
                    order.order_metadata["polling_history"] = polling_history[-20:]
                    order.order_metadata["last_polled_at"] = now.isoformat()
                    order.order_metadata["last_checkout_status"] = checkout_status
                    
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
                        creem_order_status = checkout_order.get("status")  # pending, paid 等
                        creem_order_amount = checkout_order.get("amount")
                        creem_order_amount_due = checkout_order.get("amount_due")
                        creem_order_amount_paid = checkout_order.get("amount_paid")
                        creem_order_currency = checkout_order.get("currency")
                        creem_order_type = checkout_order.get("type")  # recurring, onetime
                        creem_transaction_id = checkout_order.get("transaction")
                        
                        logger.info(
                            f"订单 {order.uuid} Creem Order 详情: "
                            f"order_id={creem_order_id}, "
                            f"order_status={creem_order_status}, "
                            f"amount={creem_order_amount}, "
                            f"amount_due={creem_order_amount_due}, "
                            f"amount_paid={creem_order_amount_paid}, "
                            f"currency={creem_order_currency}, "
                            f"type={creem_order_type}, "
                            f"transaction_id={creem_transaction_id}"
                        )
                        
                        # 判断支付状态（根据 Creem API 文档）：
                        # 1. checkout.status == "completed" 表示支付完成（主要判断）
                        # 2. order.transaction 存在（有交易ID）表示已支付
                        # 3. order.amount_paid > 0 且 amount_paid >= amount_due 表示已支付
                        # 注意：order.status 可能是 "pending" 即使支付已完成，所以不能仅依赖它
                        is_paid = (
                            checkout_status == "completed" or 
                            (creem_transaction_id is not None) or
                            (creem_order_amount_paid is not None and 
                             creem_order_amount_due is not None and 
                             creem_order_amount_paid > 0 and 
                             creem_order_amount_paid >= creem_order_amount_due)
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
                                f"order_status={creem_order_status}, "
                                f"transaction_id={creem_transaction_id}, "
                                f"amount_paid={creem_order_amount_paid}, "
                                f"amount_due={creem_order_amount_due}"
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
                            
                            # 保存支付成功信息到 order_metadata
                            if not order.order_metadata:
                                order.order_metadata = {}
                            order.order_metadata["paid_via_polling"] = True
                            order.order_metadata["paid_at_polling"] = now.isoformat()
                            order.order_metadata["polling_checkout_data"] = checkout_data  # 保存支付成功时的 checkout 数据
                            
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
                    
                    # Creem支付：如果支付未完成，不修改状态，只是不再轮询（超过24小时会自动停止轮询）
                    logger.info(f"订单 {order.uuid} Creem支付未完成，不修改状态，继续等待或停止轮询")
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

