"""
订阅相关定时任务
"""
from datetime import datetime, timedelta, timezone
from sqlalchemy.orm import Session
from app.models.subscription import Subscription
from app.models.order import Order
from app.services.subscription_query_service import SubscriptionQueryService
from app.services.subscription_service import SubscriptionService
from app.services.creem_client import creem_client
from app.core.logger import logger


def poll_subscription_billing(db: Session, max_hours: int = 24) -> dict:
    """
    轮询订阅续费状态（Creem订阅）
    
    在每月1号查询Creem订阅的续费状态，补发积分
    注意：首期积分在购买时发放，后续积分在每月1号发放
    """
    now = datetime.now(timezone.utc)
    today = now.date()
    
    # 只在每月1号执行
    if today.day != 1:
        logger.debug(f"[轮询订阅] 今天不是1号，跳过执行: today={today}")
        return {
            "checked": 0,
            "issued": 0,
            "skipped": 0,
            "errors": 0,
            "total": 0,
            "message": f"今天不是1号，跳过执行: today={today}"
        }
    
    # 只处理Creem订阅，微信订阅手动续费不参与轮询
    subs = (
        db.query(Subscription)
        .filter(Subscription.status.in_(["active", "past_due"]))
        .filter(Subscription.billing_period.in_(["every-month", "every-quarter", "every-year"]))
        .filter(Subscription.payment_method == "creem")  # 只处理Creem订阅
        .all()
    )
    
    checked = 0
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
            # 如果没有任何历史记录，说明是新订阅，首期积分会在购买时发放，这里跳过
            from app.models.subscription_points_history import SubscriptionPointsHistory
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
                    f"[轮询订阅] 当月积分已发放: subscription_uuid={sub.uuid}, period_start={period_start.date()}"
                )
                continue
            
            checked += 1
            
            # 查询Creem交易历史（检查是否有已支付的交易）
            creem_sub = sub.creem_subscription
            if creem_sub:
                tx = creem_client.search_transactions(
                    subscription_id=creem_sub.creem_subscription_id,
                    page_size=1
                )
                items = tx.get("items") or []
                if items:
                    tx_status = items[0].get("status")
                    invoice_id = items[0].get("id")
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
                        db.commit()
                        issued += 1
                        logger.info(
                            f"[轮询订阅] Creem订阅积分发放成功: subscription_uuid={sub.uuid}, "
                            f"period_start={period_start.date()}, period_end={period_end.date()}, points={sub.points_per_period}"
                        )
                        continue
                    else:
                        logger.debug(
                            f"[轮询订阅] Creem订阅交易未支付: subscription_uuid={sub.uuid}, tx_status={tx_status}"
                        )
                else:
                    logger.debug(
                        f"[轮询订阅] Creem订阅无交易记录: subscription_uuid={sub.uuid}"
                    )
            
            # 若超 24h 未扣款，可视业务需求标记 past_due
            # 注意：这里不再使用period_start，因为现在是每月1号发放
            # 如果订阅状态异常，可以标记为past_due，但不会影响积分发放（积分在1号发放）
                
        except Exception as e:
            errors += 1
            logger.exception(f"轮询订阅续费失败 subscription_id={getattr(sub, 'subscription_id', None)}: {e}")
            db.rollback()
    
    logger.info(
        f"[轮询订阅] 轮询完成: total={len(subs)}, checked={checked}, issued={issued}, "
        f"skipped={skipped}, errors={errors}, period={period_start.date()}~{period_end.date()}"
    )
    
    return {"checked": checked, "issued": issued, "skipped": skipped, "errors": errors, "total": len(subs)}


# 注意：微信订阅不支持自动续费，不需要续费任务
# 微信订阅的积分发放由 run_monthly_payout 方法处理（按月按时发放，不查询支付状态）


def check_expired_subscriptions(db: Session) -> dict:
    """
    检查并标记过期的订阅
    
    对于已过期的订阅（current_period_end < now），将状态标记为expired
    """
    from app.services.subscription_service import SubscriptionService
    
    return SubscriptionService.check_and_mark_expired_subscriptions(db)

