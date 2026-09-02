"""
积分服务 - 异步版本
处理积分账户、积分获取、积分消耗等业务逻辑
"""
from datetime import datetime, timedelta, time as dt_time
from typing import Optional, Dict, List, Tuple, Any
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import and_, func, desc, select, text
from app.models.points_account import PointsAccount
from app.models.points_record import PointsRecord
from app.models.temporary_points import TemporaryPoints
from app.core.config import settings
from app.core.logger import logger
from app.core.exceptions import InsufficientPointsError, AlreadyCheckedInError, DatabaseError
from app.core.timezone_utils import now, today_start, today_end, month_start, to_aware


class PointsAsyncService:
    """积分服务类 - 异步版本"""
    
    @staticmethod
    async def get_or_create_account(db: AsyncSession, user_id: int) -> PointsAccount:
        """
        获取或创建积分账户
        
        Args:
            db: AsyncSession
            user_id: 用户ID
            
        Returns:
            积分账户对象
        """
        result = await db.execute(
            select(PointsAccount).where(PointsAccount.user_id == user_id)
        )
        account = result.scalar_one_or_none()
        
        if not account:
            account = PointsAccount(
                user_id=user_id,
                total_points=0,
                available_points=0,
                frozen_points=0
            )
            db.add(account)
            await db.commit()
            await db.refresh(account)
            logger.info(f"为用户 {user_id} 创建积分账户: account_id={account.account_id}")
        
        return account
    
    @staticmethod
    async def _calculate_total_points(db: AsyncSession, account: PointsAccount) -> int:
        """
        计算总积分 = 长期积分 + 未过期的临时积分
        """
        now_dt = now()
        result = await db.execute(
            select(func.sum(TemporaryPoints.points)).where(
                and_(
                    TemporaryPoints.user_id == account.user_id,
                    TemporaryPoints.expires_at > now_dt,
                    TemporaryPoints.expire_record_id.is_(None)
                )
            )
        )
        temp_points_sum = result.scalar() or 0
        temp_points_sum = int(temp_points_sum)
        
        total = account.permanent_points + temp_points_sum
        return total
    
    @staticmethod
    async def _sync_total_points(db: AsyncSession, account: PointsAccount):
        """
        同步总积分
        """
        total = await PointsAsyncService._calculate_total_points(db, account)
        account.total_points = total
        await db.commit()
    
    @staticmethod
    async def get_account(db: AsyncSession, user_id: int) -> Optional[PointsAccount]:
        """
        获取用户积分账户
        """
        result = await db.execute(
            select(PointsAccount).where(PointsAccount.user_id == user_id)
        )
        return result.scalar_one_or_none()
    
    @staticmethod
    async def get_balance(db: AsyncSession, user_id: int) -> Dict[str, Any]:
        """
        获取用户积分余额
        """
        from app.models.temporary_points import TemporaryPoints
        from sqlalchemy import and_
        
        account = await PointsAsyncService.get_or_create_account(db, user_id)
        
        await PointsAsyncService._sync_total_points(db, account)
        
        today_start_dt = today_start()
        month_start_dt = month_start()
        now_dt = now()
        
        today_consumed_query = select(func.sum(PointsRecord.points)).where(
            and_(
                PointsRecord.user_id == user_id,
                PointsRecord.record_type == "consume",
                PointsRecord.created_at >= today_start_dt,
                PointsRecord.points < 0
            )
        )
        result = await db.execute(today_consumed_query)
        today_consumed = abs(int(result.scalar() or 0))
        
        month_consumed_query = select(func.sum(PointsRecord.points)).where(
            and_(
                PointsRecord.user_id == user_id,
                PointsRecord.record_type == "consume",
                PointsRecord.created_at >= month_start_dt,
                PointsRecord.points < 0
            )
        )
        result = await db.execute(month_consumed_query)
        month_consumed = abs(int(result.scalar() or 0))
        
        points_by_type = []
        
        permanent_points = account.permanent_points
        if permanent_points > 0:
            points_by_type.append({
                "points_type": "permanent",
                "points": permanent_points,
                "expires_at": None
            })
        
        temp_points_query = select(TemporaryPoints).where(
            and_(
                TemporaryPoints.user_id == user_id,
                TemporaryPoints.expires_at > now_dt,
                TemporaryPoints.expire_record_id.is_(None)
            )
        ).order_by(TemporaryPoints.expires_at.asc())
        result = await db.execute(temp_points_query)
        temp_points_list = result.scalars().all()
        
        temp_by_source = {}
        for temp in temp_points_list:
            source = temp.source_type
            if source not in temp_by_source:
                temp_by_source[source] = {
                    "points": 0,
                    "earliest_expire": temp.expires_at
                }
            temp_by_source[source]["points"] += temp.points
            if temp.expires_at < temp_by_source[source]["earliest_expire"]:
                temp_by_source[source]["earliest_expire"] = temp.expires_at
        
        for source_type, data in temp_by_source.items():
            points_by_type.append({
                "points_type": source_type,
                "points": data["points"],
                "expires_at": data["earliest_expire"].isoformat() if data["earliest_expire"] else None
            })
        
        return {
            "total_points": account.total_points,
            "available_points": account.available_points,
            "frozen_points": account.frozen_points,
            "permanent_points": account.permanent_points,
            "today_consumed": today_consumed,
            "month_consumed": month_consumed,
            "points_by_type": points_by_type
        }
    
    @staticmethod
    async def add_permanent_points(
        db: AsyncSession,
        user_id: int,
        points: int,
        reason: str,
        related_id: Optional[str] = None,
        record_type: str = "EARN"
    ) -> PointsRecord:
        """
        增加长期积分
        """
        account = await PointsAsyncService.get_or_create_account(db, user_id)
        
        account.permanent_points += points
        account.total_points += points
        account.available_points += points
        
        record = PointsRecord(
            user_id=user_id,
            account_id=account.account_id,
            points=abs(points),
            balance_after=account.available_points,
            record_type=record_type,
            reason=reason,
            related_id=related_id
        )
        db.add(record)
        await db.commit()
        await db.refresh(record)
        
        logger.info(f"用户 {user_id} 增加长期积分 {points}: {reason}")
        return record
    
    @staticmethod
    async def add_temporary_points(
        db: AsyncSession,
        user_id: int,
        points: int,
        source_type: str,
        expires_at: datetime,
        related_id: Optional[str] = None,
        description: Optional[str] = None
    ) -> TemporaryPoints:
        """
        增加临时积分
        """
        account = await PointsAsyncService.get_or_create_account(db, user_id)
        
        temp_points = TemporaryPoints(
            user_id=user_id,
            account_id=account.account_id,
            points=points,
            source_type=source_type,
            expires_at=expires_at,
            related_id=related_id
        )
        db.add(temp_points)
        await db.commit()
        await db.refresh(temp_points)
        
        await PointsAsyncService._sync_total_points(db, account)
        
        logger.info(f"用户 {user_id} 增加临时积分 {points} (有效期至 {expires_at}): {description or source_type}")
        return temp_points
    
    @staticmethod
    async def deduct_points(
        db: AsyncSession,
        user_id: int,
        points: int,
        reason: str,
        related_id: Optional[str] = None
    ) -> Tuple[PointsRecord, int]:
        """
        扣除积分（优先扣除长期积分，不足时使用临时积分）
        """
        if points <= 0:
            raise ValueError("扣除积分必须为正数")
        
        account = await PointsAsyncService.get_or_create_account(db, user_id)
        total = await PointsAsyncService._calculate_total_points(db, account)

        # 演示模式：跳过余额校验，允许扣成负数（见 settings.POINTS_CHECK_DISABLED）
        if settings.POINTS_CHECK_DISABLED:
            if total < points:
                logger.warning(
                    f"[演示模式] 跳过积分扣除校验(async): user_id={user_id}, "
                    f"需要 {points}, 可用 {total}, reason={reason}"
                )
        elif total < points:
            raise InsufficientPointsError(
                f"积分不足: 需要 {points}, 可用 {total}"
            )
        
        permanent_need = min(points, account.permanent_points)
        remaining = points - permanent_need
        
        account.permanent_points -= permanent_need
        account.available_points -= permanent_need
        
        if remaining > 0:
            result = await db.execute(
                select(TemporaryPoints).where(
                    and_(
                        TemporaryPoints.user_id == user_id,
                        TemporaryPoints.expires_at > now(),
                        TemporaryPoints.expire_record_id.is_(None)
                    )
                ).order_by(TemporaryPoints.expires_at)
            )
            temp_points_list = result.scalars().all()
            
            for temp in temp_points_list:
                if remaining <= 0:
                    break
                
                deduct = min(remaining, temp.points)
                temp.points -= deduct
                remaining -= deduct
                account.available_points -= deduct
        
        account.total_points = await PointsAsyncService._calculate_total_points(db, account)
        
        record = PointsRecord(
            user_id=user_id,
            account_id=account.account_id,
            points=-points,
            balance_after=account.available_points,
            record_type="SPEND",
            reason=reason,
            related_id=related_id
        )
        db.add(record)
        await db.commit()
        await db.refresh(record)
        
        logger.info(f"用户 {user_id} 扣除积分 {points}: {reason}")
        return record, points
    
    @staticmethod
    async def register_reward(db: AsyncSession, user_id: int):
        """
        新用户注册赠送积分
        """
        reward_points = settings.NEW_USER_REGISTRATION_POINTS
        if reward_points > 0:
            await PointsAsyncService.add_permanent_points(
                db=db,
                user_id=user_id,
                points=reward_points,
                reason="新用户注册奖励",
                record_type="REGISTER_REWARD"
            )
    
    @staticmethod
    async def checkin_reward(db: AsyncSession, user_id: int) -> PointsRecord:
        """
        每日签到奖励
        """
        today_start_dt = today_start()
        today_end_dt = today_end()
        
        result = await db.execute(
            select(TemporaryPoints).where(
                and_(
                    TemporaryPoints.user_id == user_id,
                    TemporaryPoints.source_type == "daily_checkin",
                    TemporaryPoints.created_at >= today_start_dt,
                    TemporaryPoints.created_at < today_end_dt
                )
            )
        )
        existing_checkin = result.scalar_one_or_none()
        
        if existing_checkin:
            raise AlreadyCheckedInError()
        
        if settings.POINTS_CHECKIN_EXPIRE_HOURS == 0:
            expires_at = today_end_dt
        else:
            expires_at = now() + timedelta(hours=settings.POINTS_CHECKIN_EXPIRE_HOURS)
        
        points = settings.POINTS_CHECKIN_REWARD
        
        return await PointsAsyncService.add_temporary_points(
            db=db,
            user_id=user_id,
            points=points,
            source_type="daily_checkin",
            expires_at=expires_at,
            description=f"每日签到获得 {points} 积分"
        )
    
    @staticmethod
    async def get_points_history(
        db: AsyncSession,
        user_id: int,
        limit: int = 50,
        offset: int = 0,
        record_type: Optional[str] = None,
        operation_type: Optional[str] = None,
        creation_id: Optional[int] = None,
        novel_id: Optional[int] = None,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None
    ) -> Tuple[List[PointsRecord], int]:
        """
        获取积分记录
        """
        query = select(PointsRecord).where(PointsRecord.user_id == user_id)
        
        if record_type:
            query = query.where(PointsRecord.record_type == record_type)
        if operation_type:
            query = query.where(PointsRecord.operation_type == operation_type)
        if creation_id is not None:
            query = query.where(PointsRecord.creation_id == creation_id)
        if novel_id is not None:
            query = query.where(PointsRecord.novel_id == novel_id)
        if start_date:
            query = query.where(PointsRecord.created_at >= start_date)
        if end_date:
            query = query.where(PointsRecord.created_at <= end_date)
        
        count_query = select(func.count()).select_from(query.subquery())
        count_result = await db.execute(count_query)
        total = count_result.scalar() or 0
        
        query = query.order_by(PointsRecord.created_at.desc()).limit(limit).offset(offset)
        
        result = await db.execute(query)
        records = result.scalars().all()
        
        return list(records), total
    
    @staticmethod
    async def get_statistics(
        db: AsyncSession,
        user_id: int,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None
    ) -> Dict:
        """
        获取积分统计信息
        """
        query = select(PointsRecord).where(PointsRecord.user_id == user_id)
        
        if start_date:
            query = query.where(PointsRecord.created_at >= start_date)
        if end_date:
            query = query.where(PointsRecord.created_at <= end_date)
        
        total_earned_query = select(func.sum(PointsRecord.points)).where(
            and_(
                PointsRecord.user_id == user_id,
                PointsRecord.points > 0
            )
        )
        if start_date:
            total_earned_query = total_earned_query.where(PointsRecord.created_at >= start_date)
        if end_date:
            total_earned_query = total_earned_query.where(PointsRecord.created_at <= end_date)
        result = await db.execute(total_earned_query)
        total_earned = result.scalar() or 0
        total_earned = int(total_earned)
        
        total_consumed_query = select(func.sum(PointsRecord.points)).where(
            and_(
                PointsRecord.user_id == user_id,
                PointsRecord.record_type == "consume",
                PointsRecord.points < 0
            )
        )
        if start_date:
            total_consumed_query = total_consumed_query.where(PointsRecord.created_at >= start_date)
        if end_date:
            total_consumed_query = total_consumed_query.where(PointsRecord.created_at <= end_date)
        result = await db.execute(total_consumed_query)
        total_consumed = result.scalar() or 0
        total_consumed = int(abs(total_consumed))
        
        checkin_count_query = select(func.count()).select_from(
            select(PointsRecord).where(
                and_(
                    PointsRecord.user_id == user_id,
                    PointsRecord.operation_type == "daily_checkin"
                )
            ).subquery()
        )
        result = await db.execute(checkin_count_query)
        checkin_count = result.scalar() or 0
        
        account = await PointsAsyncService.get_or_create_account(db, user_id)
        available_points = account.available_points if account else 0
        frozen_points = account.frozen_points if account else 0
        
        return {
            "total_earned": total_earned,
            "total_consumed": total_consumed,
            "available_points": available_points,
            "frozen_points": frozen_points,
            "checkin_count": checkin_count
        }
    
    @staticmethod
    async def add_points(
        db: AsyncSession,
        user_id: int,
        points: int,
        record_type: str = "reward",
        operation_type: str = "manual_add",
        description: Optional[str] = None,
        extra_data: Optional[Dict[str, Any]] = None
    ) -> PointsRecord:
        """
        手动添加积分（长期积分）
        """
        account = await PointsAsyncService.get_or_create_account(db, user_id)
        
        balance_before = account.available_points
        
        # 更新 permanent_points 和 total_points（修复：之前只更新 available_points 导致同步时积分丢失）
        account.permanent_points += points
        account.total_points += points
        account.available_points = account.total_points - account.frozen_points
        
        balance_after = account.available_points
        
        record = PointsRecord(
            account_id=account.account_id,
            user_id=user_id,
            record_type=record_type,
            operation_type=operation_type,
            points=points,
            balance_before=balance_before,
            balance_after=balance_after,
            description=description or f"添加 {points} 积分",
            extra_data=extra_data
        )
        db.add(record)
        await db.commit()
        await db.refresh(record)
        
        logger.info(f"用户 {user_id} 添加积分: {points}")
        return record
    
    @staticmethod
    async def check_expired_points(db: AsyncSession):
        """
        检查并处理过期积分
        """
        now_dt = now()
        result = await db.execute(
            select(TemporaryPoints).where(
                and_(
                    TemporaryPoints.expires_at <= now_dt,
                    TemporaryPoints.expire_record_id.is_(None)
                )
            )
        )
        expired_points = result.scalars().all()
        
        for temp in expired_points:
            if temp.points > 0:
                account = await PointsAsyncService.get_or_create_account(
                    db, temp.user_id
                )
                
                await PointsAsyncService.add_permanent_points(
                    db=db,
                    user_id=temp.user_id,
                    points=-temp.points,
                    reason=f"临时积分过期扣除",
                    related_id=str(temp.id),
                    record_type="EXPIRE"
                )
                
                temp.expire_record_id = "expired"
                await db.commit()
        
        return len(expired_points)
    
    @staticmethod
    async def freeze_points(
        db: AsyncSession,
        user_id: int,
        points: int,
        operation_type: str,
        creation_id: Optional[int] = None,
        novel_id: Optional[int] = None,
        description: Optional[str] = None,
        extra_data: Optional[Dict[str, Any]] = None
    ) -> PointsRecord:
        """
        冻结积分（用于任务提交时预扣）
        """
        from app.core.exceptions import InsufficientPointsError
        
        result = await db.execute(
            select(PointsAccount).where(
                PointsAccount.user_id == user_id
            )
        )
        account = result.scalar_one_or_none()
        
        if not account:
            account = PointsAccount(
                user_id=user_id,
                total_points=0,
                available_points=0,
                frozen_points=0,
                permanent_points=0
            )
            db.add(account)
            await db.flush()
        
        await PointsAsyncService._sync_total_points(db, account)
        balance_before = account.available_points

        # 演示模式：跳过余额校验，允许扣成负数（见 settings.POINTS_CHECK_DISABLED）
        if settings.POINTS_CHECK_DISABLED:
            logger.warning(
                f"[演示模式] 跳过积分冻结校验(async): user_id={user_id}, 需要 {points}, "
                f"可用 {balance_before}, operation_type={operation_type}"
            )
        else:
            if account.available_points < points:
                raise InsufficientPointsError(required=points, available=balance_before)

            if account.available_points <= 0:
                raise InsufficientPointsError(required=points, available=balance_before)
        
        account.frozen_points += points
        await PointsAsyncService._sync_total_points(db, account)
        balance_after = account.available_points
        
        record = PointsRecord(
            account_id=account.account_id,
            user_id=user_id,
            record_type="freeze",
            operation_type=operation_type,
            points=-points,
            balance_before=balance_before,
            balance_after=balance_after,
            creation_id=creation_id,
            novel_id=novel_id,
            description=description or f"冻结积分：{points}",
            extra_data=extra_data
        )
        db.add(record)
        await db.commit()
        await db.refresh(record)
        
        logger.info(f"用户 {user_id} 冻结积分: {points}, 可用余额: {balance_before} -> {balance_after}")
        return record
    
    @staticmethod
    async def confirm_frozen_points(
        db: AsyncSession,
        freeze_record_id: int
    ) -> PointsRecord:
        """
        确认冻结的积分（任务成功时调用）
        """
        from app.core.exceptions import NotFoundError
        
        result = await db.execute(
            select(PointsRecord).where(PointsRecord.record_id == freeze_record_id)
        )
        freeze_record = result.scalar_one_or_none()
        
        if not freeze_record:
            raise NotFoundError(detail="冻结记录不存在")
        
        if freeze_record.record_type != "freeze":
            raise ValueError("该记录不是冻结记录")
        
        check_result = await db.execute(
            select(PointsRecord).where(
                and_(
                    PointsRecord.record_type == "consume",
                    PointsRecord.extra_data.isnot(None),
                    text("points_records.extra_data->>'freeze_record_id'") == str(freeze_record_id)
                )
            )
        )
        existing_confirm = check_result.scalar_one_or_none()
        
        if existing_confirm:
            logger.warning(f"冻结记录 {freeze_record_id} 已确认，跳过重复确认")
            return existing_confirm
        
        result = await db.execute(
            select(PointsAccount).where(
                PointsAccount.user_id == freeze_record.user_id
            )
        )
        account = result.scalar_one_or_none()
        
        if not account:
            raise NotFoundError(detail="积分账户不存在")
        
        points = abs(freeze_record.points)
        await PointsAsyncService._sync_total_points(db, account)
        balance_before = account.available_points
        
        remaining_points = points
        deducted_temporary = 0
        deducted_permanent = 0
        
        temp_result = await db.execute(
            select(TemporaryPoints).where(
                and_(
                    TemporaryPoints.user_id == freeze_record.user_id,
                    TemporaryPoints.expires_at > now(),
                    TemporaryPoints.expire_record_id.is_(None)
                )
            ).order_by(TemporaryPoints.expires_at)
        )
        temp_points_list = temp_result.scalars().all()
        
        for temp in temp_points_list:
            if remaining_points <= 0:
                break
            
            if temp.points > 0:
                deduct_from_this = min(remaining_points, temp.points)
                temp.points -= deduct_from_this
                deducted_temporary += deduct_from_this
                remaining_points -= deduct_from_this
                
                if temp.points == 0:
                    await db.delete(temp)
        
        if remaining_points > 0:
            account.permanent_points -= remaining_points
            deducted_permanent = remaining_points
        
        account.frozen_points -= points
        await PointsAsyncService._sync_total_points(db, account)
        balance_after = account.available_points
        
        extra_data = freeze_record.extra_data or {}
        extra_data["freeze_record_id"] = freeze_record_id
        extra_data["deduction_details"] = {
            "temporary_points": deducted_temporary,
            "permanent_points": deducted_permanent
        }
        
        confirm_record = PointsRecord(
            account_id=account.account_id,
            user_id=freeze_record.user_id,
            record_type="consume",
            operation_type=freeze_record.operation_type,
            points=-points,
            balance_before=balance_before,
            balance_after=balance_after,
            creation_id=freeze_record.creation_id,
            novel_id=freeze_record.novel_id,
            description=f"确认扣除：{freeze_record.description}",
            extra_data=extra_data
        )
        db.add(confirm_record)
        await db.commit()
        await db.refresh(confirm_record)
        
        logger.info(f"用户 {freeze_record.user_id} 确认扣除冻结积分: {points}")
        return confirm_record
    
    @staticmethod
    async def release_frozen_points(
        db: AsyncSession,
        freeze_record_id: int,
        reason: Optional[str] = None
    ) -> PointsRecord:
        """
        释放冻结的积分（任务失败时调用）
        """
        from app.core.exceptions import NotFoundError
        
        result = await db.execute(
            select(PointsRecord).where(PointsRecord.record_id == freeze_record_id)
        )
        freeze_record = result.scalar_one_or_none()
        
        if not freeze_record:
            raise NotFoundError(detail="冻结记录不存在")
        
        if freeze_record.record_type != "freeze":
            raise ValueError("该记录不是冻结记录")
        
        check_result = await db.execute(
            select(PointsRecord).where(
                and_(
                    PointsRecord.record_type == "release",
                    PointsRecord.extra_data.isnot(None),
                    text("points_records.extra_data->>'freeze_record_id'") == str(freeze_record_id)
                )
            )
        )
        existing_release = check_result.scalar_one_or_none()
        
        if existing_release:
            logger.warning(f"冻结记录 {freeze_record_id} 已释放，跳过重复释放")
            return existing_release
        
        result = await db.execute(
            select(PointsAccount).where(
                PointsAccount.user_id == freeze_record.user_id
            )
        )
        account = result.scalar_one_or_none()
        
        if not account:
            raise NotFoundError(detail="积分账户不存在")
        
        points = abs(freeze_record.points)
        await PointsAsyncService._sync_total_points(db, account)
        balance_before = account.available_points
        
        account.frozen_points -= points
        await PointsAsyncService._sync_total_points(db, account)
        balance_after = account.available_points
        
        release_record = PointsRecord(
            account_id=account.account_id,
            user_id=freeze_record.user_id,
            record_type="release",
            operation_type=freeze_record.operation_type,
            points=points,
            balance_before=balance_before,
            balance_after=balance_after,
            creation_id=freeze_record.creation_id,
            novel_id=freeze_record.novel_id,
            description=f"释放冻结积分：{freeze_record.description}（原因：{reason or '任务失败'}）",
            extra_data={
                "freeze_record_id": freeze_record_id,
                "release_reason": reason
            }
        )
        db.add(release_record)
        await db.commit()
        await db.refresh(release_record)
        
        logger.info(f"用户 {freeze_record.user_id} 释放冻结积分: {points}")
        return release_record
