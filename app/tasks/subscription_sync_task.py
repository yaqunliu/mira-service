"""
订阅信息同步任务（定期同步所有字段）
定期从 Creem API 同步订阅信息，同步所有字段包括状态、取消信息、周期信息等
"""
from datetime import timedelta
from app.core.celery_app import celery_app
from app.db.session import SessionLocal
from app.models.subscription import Subscription
from app.services.creem_client import creem_client
from app.services.webhook_service import WebhookService
from app.core.logger import logger


@celery_app.task(name="sync_subscriptions")
def sync_subscriptions():
    """
    订阅信息同步任务
    定期从 Creem API 同步订阅信息，同步所有字段包括：
    - 状态（status）
    - 取消信息（canceled_at, cancel_at_period_end）
    - 周期信息（current_period_start, current_period_end, next_billing_date）
    - 元数据（metadata）
    - 计费周期（billing_period）
    每天执行一次（由 Celery Beat 调度）
    """
    db = SessionLocal()
    try:
        logger.info("=" * 60)
        logger.info("开始执行订阅信息同步任务")
        logger.info("=" * 60)
        
        # 只查询活跃订阅（订阅不能恢复，已取消/过期的无需同步）
        subscriptions = (
            db.query(Subscription)
            .filter(Subscription.status == "active")
            .all()
        )
        
        synced = 0
        updated = 0
        skipped = 0
        errors = 0
        
        for sub in subscriptions:
            try:
                # 从 Creem API 获取订阅详情
                try:
                    creem_sub = creem_client.get_subscription(sub.creem_subscription_id)
                except Exception as api_error:
                    logger.warning(f"获取订阅详情失败 {sub.creem_subscription_id}: {api_error}")
                    errors += 1
                    continue
                
                # 同步所有字段
                updated_fields = []
                
                # 1. 同步状态（重要：可能已取消或过期）
                creem_status = creem_sub.get("status")
                if creem_status and creem_status != sub.status:
                    old_status = sub.status
                    sub.status = creem_status
                    updated_fields.append(f"status({old_status}->{creem_status})")
                
                # 2. 同步取消信息
                canceled_at = WebhookService._parse_datetime(creem_sub.get("canceled_at"))
                if canceled_at:
                    if not sub.cancelled_at or sub.cancelled_at != canceled_at:
                        sub.cancelled_at = canceled_at
                        updated_fields.append("cancelled_at")
                # 如果 Creem 中没有 canceled_at 但本地有，可能是误标记，保留本地值
                
                # 3. 同步周期开始时间
                period_start = WebhookService._parse_datetime(
                    creem_sub.get("current_period_start_date")
                )
                if period_start:
                    if not sub.current_period_start or sub.current_period_start != period_start:
                        sub.current_period_start = period_start
                        updated_fields.append("current_period_start")
                
                # 4. 同步周期结束时间
                period_end = WebhookService._parse_datetime(
                    creem_sub.get("current_period_end_date")
                )
                if period_end:
                    if not sub.current_period_end or sub.current_period_end != period_end:
                        sub.current_period_end = period_end
                        updated_fields.append("current_period_end")
                
                # 5. 同步下次计费时间
                next_billing = WebhookService._parse_datetime(
                    creem_sub.get("next_transaction_date")
                )
                if next_billing:
                    if not sub.next_billing_date or sub.next_billing_date != next_billing:
                        sub.next_billing_date = next_billing
                        updated_fields.append("next_billing_date")
                # 如果已取消，next_billing_date 可能为 None，这是正常的
                
                # 6. 同步计费周期（虽然通常不会变，但为了完整性也同步）
                creem_billing_period = creem_sub.get("product", {}).get("billing_period")
                if creem_billing_period and creem_billing_period != sub.billing_period:
                    sub.billing_period = creem_billing_period
                    updated_fields.append("billing_period")
                
                # 7. 同步元数据
                creem_metadata = creem_sub.get("metadata")
                if creem_metadata is not None:
                    # 如果 Creem 有 metadata，更新本地（即使本地已有也更新，确保一致性）
                    if sub.subscription_metadata != creem_metadata:
                        sub.subscription_metadata = creem_metadata
                        updated_fields.append("metadata")
                
                # 8. 处理 cancel_at_period_end 逻辑
                # 如果状态是 cancelled 但 cancel_at_period_end 为 False，说明是立即取消
                # 如果状态是 active 但 canceled_at 不为空，说明是计划在周期结束时取消
                if creem_status == "cancelled" and canceled_at:
                    # 检查是否是计划取消（cancel_at_period_end）
                    # 如果 canceled_at 接近 current_period_end，可能是计划取消
                    if sub.current_period_end and canceled_at:
                        # 如果取消时间接近周期结束时间（相差小于7天），可能是计划取消
                        time_diff = abs((canceled_at - sub.current_period_end).total_seconds())
                        if time_diff < 7 * 24 * 3600:
                            if not sub.cancel_at_period_end:
                                sub.cancel_at_period_end = True
                                updated_fields.append("cancel_at_period_end")
                        else:
                            if sub.cancel_at_period_end:
                                sub.cancel_at_period_end = False
                                updated_fields.append("cancel_at_period_end")
                
                # 提交更新
                if updated_fields:
                    db.commit()
                    updated += 1
                    logger.info(
                        f"订阅 {sub.creem_subscription_id} 同步成功，更新字段: {', '.join(updated_fields)}"
                    )
                else:
                    skipped += 1
                
                synced += 1
                
            except Exception as e:
                errors += 1
                logger.exception(f"同步订阅失败 subscription_id={getattr(sub, 'subscription_id', None)}: {e}")
                db.rollback()
        
        logger.info("=" * 60)
        logger.info(
            f"订阅同步完成: total={len(subscriptions)}, synced={synced}, updated={updated}, "
            f"skipped={skipped}, errors={errors}"
        )
        logger.info("=" * 60)
        
        return {
            "total": len(subscriptions),
            "synced": synced,
            "updated": updated,
            "skipped": skipped,
            "errors": errors,
        }
    except Exception as e:
        logger.exception(f"订阅同步任务执行失败: {e}")
        raise
    finally:
        db.close()

