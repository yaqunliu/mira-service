"""
积分服务
处理积分账户、积分获取、积分消耗等业务逻辑
"""
from datetime import datetime, timedelta, time as dt_time
from typing import Optional, Dict, List, Tuple
from sqlalchemy.orm import Session
from sqlalchemy import and_, func, desc, text
from app.models.points_account import PointsAccount
from app.models.points_record import PointsRecord
from app.models.temporary_points import TemporaryPoints
from app.core.config import settings
from app.core.logger import logger
from app.core.exceptions import InsufficientPointsError, AlreadyCheckedInError, DatabaseError
from app.core.timezone_utils import now, today_start, today_end, month_start, to_aware


class PointsService:
    """积分服务类"""
    
    @staticmethod
    def get_or_create_account(db: Session, user_id: int) -> PointsAccount:
        """
        获取或创建积分账户
        
        Args:
            db: 数据库会话
            user_id: 用户ID
            
        Returns:
            积分账户对象
        """
        account = db.query(PointsAccount).filter(PointsAccount.user_id == user_id).first()
        if not account:
            account = PointsAccount(
                user_id=user_id,
                total_points=0,
                available_points=0,
                frozen_points=0
            )
            db.add(account)
            db.commit()
            db.refresh(account)
            logger.info(f"为用户 {user_id} 创建积分账户: account_id={account.account_id}")
        return account
    
    @staticmethod
    def _calculate_total_points(db: Session, account: PointsAccount) -> int:
        """
        计算总积分 = 长期积分 + 未过期的临时积分
        
        Args:
            db: 数据库会话
            account: 积分账户
            
        Returns:
            总积分
        """
        now_dt = now()
        # 查询所有未过期的临时积分（且还未被标记为过期处理）
        temp_points_sum = db.query(func.sum(TemporaryPoints.points)).filter(
            and_(
                TemporaryPoints.user_id == account.user_id,
                TemporaryPoints.expires_at > now_dt,
                TemporaryPoints.expire_record_id.is_(None)  # 还未创建过期记录
            )
        ).scalar() or 0
        temp_points_sum = int(temp_points_sum)
        
        # 总积分 = 长期积分 + 未过期的临时积分
        total = account.permanent_points + temp_points_sum
        return total
    
    @staticmethod
    def _sync_total_points(db: Session, account: PointsAccount):
        """
        同步总积分（确保 total_points = permanent_points + 未过期的临时积分）
        
        Args:
            db: 数据库会话
            account: 积分账户
        """
        total = PointsService._calculate_total_points(db, account)
        account.total_points = total
        account.available_points = total - account.frozen_points
    
    @staticmethod
    def get_account_balance(db: Session, user_id: int) -> Dict:
        """
        获取账户余额信息
        
        Args:
            db: 数据库会话
            user_id: 用户ID
            
        Returns:
            余额信息字典
        """
        account = PointsService.get_or_create_account(db, user_id)
        
        # 检查并处理已过期但未创建过期记录的临时积分
        now_dt = now()
        expired_temp_points = db.query(TemporaryPoints).filter(
            and_(
                TemporaryPoints.user_id == user_id,
                TemporaryPoints.expires_at <= now_dt,
                TemporaryPoints.points > 0,  # 还有未使用的积分
                TemporaryPoints.expire_record_id.is_(None)  # 还未创建过期记录
            )
        ).all()
        
        if expired_temp_points:
            # 按用户分组计算过期积分
            total_expired = sum(temp.points for temp in expired_temp_points)
            balance_before = account.available_points
            
            # 同步总积分（会自动减去过期的临时积分，因为临时积分已过期，不会被计入总积分）
            PointsService._sync_total_points(db, account)
            balance_after = account.available_points
            
            # 创建过期记录
            expire_record = PointsRecord(
                account_id=account.account_id,
                user_id=user_id,
                record_type="expire",
                operation_type="temporary_points_expire",
                points=-total_expired,
                points_type="temporary",
                balance_before=balance_before,
                balance_after=balance_after,
                description=f"临时积分过期，扣除 {total_expired} 积分"
            )
            db.add(expire_record)
            db.flush()  # 获取 record_id
            
            # 更新临时积分记录的 expire_record_id，标记已创建过期记录
            # 注意：不删除记录，因为需要保留历史数据，但标记已处理
            for temp in expired_temp_points:
                temp.expire_record_id = expire_record.record_id
                # 如果积分已全部过期，可以将 points 设为 0，但不删除记录
                # 或者保留原值，用于记录历史
                temp.points = 0  # 标记为已过期处理
            
            logger.info(
                f"用户 {user_id} 临时积分过期: {total_expired} 积分, "
                f"余额: {balance_before} -> {balance_after}, "
                f"过期记录ID: {expire_record.record_id}"
            )
        
        # 同步总积分（确保数据一致）
        PointsService._sync_total_points(db, account)
        db.commit()
        
        # 计算今日消耗
        today_start_dt = today_start()
        today_consumed = db.query(func.sum(PointsRecord.points)).filter(
            and_(
                PointsRecord.user_id == user_id,
                PointsRecord.record_type == "consume",
                PointsRecord.created_at >= today_start_dt,
                PointsRecord.points < 0
            )
        ).scalar() or 0
        today_consumed = abs(int(today_consumed))
        
        # 计算本月消耗
        month_start_dt = month_start()
        month_consumed = db.query(func.sum(PointsRecord.points)).filter(
            and_(
                PointsRecord.user_id == user_id,
                PointsRecord.record_type == "consume",
                PointsRecord.created_at >= month_start_dt,
                PointsRecord.points < 0
            )
        ).scalar() or 0
        month_consumed = abs(int(month_consumed))
        
        # 按积分类型分组统计
        points_by_type = []
        now_dt = now()
        
        # 长期积分（不过期）
        permanent_points = account.permanent_points
        if permanent_points > 0:
            points_by_type.append({
                "points_type": "permanent",
                "points": permanent_points,
                "expires_at": None
            })
        
        # 临时积分（按来源类型分组，只查询未过期的）
        temp_points_list = db.query(TemporaryPoints).filter(
            and_(
                TemporaryPoints.user_id == user_id,
                TemporaryPoints.expires_at > now_dt,
                TemporaryPoints.expire_record_id.is_(None)  # 还未创建过期记录
            )
        ).order_by(TemporaryPoints.expires_at.asc()).all()
        
        # 按来源类型分组统计
        temp_by_source = {}
        earliest_expire = None
        for temp in temp_points_list:
            source = temp.source_type
            if source not in temp_by_source:
                temp_by_source[source] = {
                    "points": 0,
                    "earliest_expire": temp.expires_at
                }
            temp_by_source[source]["points"] += temp.points
            if earliest_expire is None or temp.expires_at < earliest_expire:
                earliest_expire = temp.expires_at
        
        for source_type, data in temp_by_source.items():
            points_by_type.append({
                "points_type": source_type,  # checkin, activity 等
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
    def add_points(
        db: Session,
        user_id: int,
        points: int,
        record_type: str,  # reward, recharge, checkin
        operation_type: str,
        points_type: str = "normal",  # normal, daily_checkin
        expires_at: Optional[datetime] = None,
        description: str = None,
        extra_data: Dict = None
    ) -> PointsRecord:
        """
        增加积分
        
        Args:
            db: 数据库会话
            user_id: 用户ID
            points: 积分数量（正数）
            record_type: 记录类型
            operation_type: 操作类型
            points_type: 积分类型（normal=长期积分，其他=临时积分）
            expires_at: 过期时间（临时积分必须提供）
            description: 描述
            extra_data: 扩展信息
            
        Returns:
            积分记录对象
        """
        account = PointsService.get_or_create_account(db, user_id)
        balance_before = account.available_points
        
        # 判断是临时积分还是长期积分
        is_temporary = expires_at is not None
        
        if is_temporary:
            # 临时积分：写入 temporary_points 表
            temp_points = TemporaryPoints(
                account_id=account.account_id,
                user_id=user_id,
                points=points,
                source_type=operation_type,  # 如 "daily_checkin", "activity" 等
                source_id=None,  # 可以关联到 PointsRecord 的 record_id
                expires_at=expires_at
            )
            db.add(temp_points)
            db.flush()  # 获取 temp_id
            
            # 更新账户（临时积分不直接加到 permanent_points）
            # 总积分会在 _sync_total_points 时计算
        else:
            # 长期积分：直接加到 permanent_points
            account.permanent_points += points
        
        # 同步总积分
        PointsService._sync_total_points(db, account)
        balance_after = account.available_points
        
        # 创建记录
        record = PointsRecord(
            account_id=account.account_id,
            user_id=user_id,
            record_type=record_type,
            operation_type=operation_type,
            points=points,
            points_type=points_type,
            expires_at=expires_at,
            balance_before=balance_before,
            balance_after=balance_after,
            description=description,
            extra_data=extra_data
        )
        db.add(record)
        db.commit()
        db.refresh(record)
        
        # 如果是临时积分，更新 source_id 为 record_id（可选）
        if is_temporary:
            temp_points.source_id = record.record_id
            db.commit()
        
        logger.info(f"用户 {user_id} 增加积分: {points} ({'临时' if is_temporary else '长期'}), 余额: {balance_before} -> {balance_after}")
        return record
    
    @staticmethod
    def register_reward(db: Session, user_id: int) -> PointsRecord:
        """
        注册奖励
        
        Args:
            db: 数据库会话
            user_id: 用户ID
            
        Returns:
            积分记录对象
        """
        points = settings.POINTS_REGISTER_REWARD
        return PointsService.add_points(
            db=db,
            user_id=user_id,
            points=points,
            record_type="reward",
            operation_type="register",
            description=f"注册赠送 {points} 积分"
        )
    
    @staticmethod
    def checkin_reward(db: Session, user_id: int) -> PointsRecord:
        """
        每日签到奖励（简化版，使用临时积分表）
        
        Args:
            db: 数据库会话
            user_id: 用户ID
            
        Returns:
            积分记录对象
            
        Raises:
            AlreadyCheckedInError: 今日已签到
        """
        # 简化签到检查：查询临时积分表，检查今天是否有签到记录
        today_start_dt = today_start()
        today_end_dt = today_end()
        
        existing_checkin = db.query(TemporaryPoints).filter(
            and_(
                TemporaryPoints.user_id == user_id,
                TemporaryPoints.source_type == "daily_checkin",
                TemporaryPoints.created_at >= today_start_dt,
                TemporaryPoints.created_at < today_end_dt
            )
        ).first()
        
        if existing_checkin:
            raise AlreadyCheckedInError()
        
        # 计算过期时间
        if settings.POINTS_CHECKIN_EXPIRE_HOURS == 0:
            # 当天24:00过期（即次日00:00:00，Asia/Shanghai时区）
            expires_at = today_end_dt
        else:
            # N小时后过期
            expires_at = now() + timedelta(hours=settings.POINTS_CHECKIN_EXPIRE_HOURS)
        
        points = settings.POINTS_CHECKIN_REWARD
        
        return PointsService.add_points(
            db=db,
            user_id=user_id,
            points=points,
            record_type="checkin",
            operation_type="daily_checkin",
            points_type="daily_checkin",
            expires_at=expires_at,
            description=f"每日签到获得 {points} 积分"
        )
    
    @staticmethod
    def check_deduction_exists(
        db: Session,
        user_id: int,
        operation_type: str,
        creation_id: int = None,
        shot_id: int = None,
        character_id: int = None,
        scene_id: int = None,
        time_window_hours: int = 1
    ) -> Optional[PointsRecord]:
        """
        检查是否已经为同一操作扣除过积分（幂等性检查）
        
        Args:
            db: 数据库会话
            user_id: 用户ID
            operation_type: 操作类型
            creation_id: 创作ID
            shot_id: 分镜ID（可选）
            character_id: 角色ID（可选）
            scene_id: 场景ID（可选）
            time_window_hours: 时间窗口（小时），默认1小时
            
        Returns:
            如果存在扣除记录，返回记录对象；否则返回 None
        """
        from datetime import datetime, timedelta
        
        query = db.query(PointsRecord).filter(
            and_(
                PointsRecord.user_id == user_id,
                PointsRecord.operation_type == operation_type,
                PointsRecord.record_type == "consume",
                PointsRecord.points < 0
            )
        )
        
        if creation_id:
            query = query.filter(PointsRecord.creation_id == creation_id)
        
        if shot_id:
            # 通过 extra_data 查询 shot_id
            # 使用 PostgreSQL 的 JSON 操作符 ->> 来获取文本值
            # 需要确保 extra_data 不为 None 且包含 shot_id 字段
            query = query.filter(
                and_(
                    PointsRecord.extra_data.isnot(None),
                    text("points_records.extra_data->>'shot_id'") == str(shot_id)
                )
            )
        
        if character_id:
            # 通过 extra_data 查询 character_id
            # 使用 PostgreSQL 的 JSON 操作符 ->> 来获取文本值
            # 需要确保 extra_data 不为 None 且包含 character_id 字段
            query = query.filter(
                and_(
                    PointsRecord.extra_data.isnot(None),
                    text("points_records.extra_data->>'character_id'") == str(character_id)
                )
            )

        if scene_id:
            # 通过 extra_data 查询 scene_id
            # 使用 PostgreSQL 的 JSON 操作符 ->> 来获取文本值
            # 需要确保 extra_data 不为 None 且包含 scene_id 字段
            query = query.filter(
                and_(
                    PointsRecord.extra_data.isnot(None),
                    text("points_records.extra_data->>'scene_id'") == str(scene_id)
                )
            )
        
        # 检查时间窗口内的记录
        time_threshold = now() - timedelta(hours=time_window_hours)
        query = query.filter(PointsRecord.created_at >= time_threshold)
        
        return query.order_by(desc(PointsRecord.created_at)).first()
    
    @staticmethod
    def deduct_points(
        db: Session,
        user_id: int,
        points: int,
        operation_type: str,
        creation_id: int = None,
        novel_id: int = None,
        description: str = None,
        extra_data: Dict = None,
        allow_negative: bool = False,
        check_duplicate: bool = True
    ) -> PointsRecord:
        """
        扣除积分（预扣机制，带并发安全和幂等性检查）
        
        Args:
            db: 数据库会话
            user_id: 用户ID
            points: 积分数量（正数，实际扣除时会转为负数）
            operation_type: 操作类型
            creation_id: 创作ID
            novel_id: 小说ID
            description: 描述
            extra_data: 扩展信息
            allow_negative: 是否允许负积分
            check_duplicate: 是否检查重复扣除（幂等性检查）
            
        Returns:
            积分记录对象
            
        Raises:
            InsufficientPointsError: 积分不足
        """
        # 使用 SELECT FOR UPDATE 锁定账户行，防止并发问题
        account = db.query(PointsAccount).filter(
            PointsAccount.user_id == user_id
        ).with_for_update().first()
        
        if not account:
            account = PointsAccount(
                user_id=user_id,
                total_points=0,
                available_points=0,
                frozen_points=0
            )
            db.add(account)
            db.flush()  # 获取 account_id
        
        # 幂等性检查：检查是否已经扣除过
        if check_duplicate:
            shot_id = extra_data.get('shot_id') if extra_data else None
            character_id = extra_data.get('character_id') if extra_data else None
            scene_id = extra_data.get('scene_id') if extra_data else None
            
            existing_deduction = PointsService.check_deduction_exists(
                db=db,
                user_id=user_id,
                operation_type=operation_type,
                creation_id=creation_id,
                shot_id=shot_id,
                character_id=character_id,
                scene_id=scene_id,
                time_window_hours=24  # 24小时内不重复扣除
            )
            
            if existing_deduction:
                logger.warning(
                    f"检测到重复扣除请求，跳过: user_id={user_id}, "
                    f"operation_type={operation_type}, creation_id={creation_id}, "
                    f"shot_id={shot_id}, character_id={character_id}, scene_id={scene_id}"
                )
                return existing_deduction  # 返回已存在的记录，不重复扣除
        
        balance_before = account.available_points
        
        # 检查余额（如果不允许负积分且余额不足，抛出异常）
        if not allow_negative and balance_before < points:
            raise InsufficientPointsError(required=points, available=balance_before)
        
        # 检查积分为负或0时，不允许扣除
        if balance_before <= 0:
            raise InsufficientPointsError(required=points, available=balance_before)
        
        # 同步总积分（确保数据一致）
        PointsService._sync_total_points(db, account)
        balance_before = account.available_points
        
        # 优先扣除临时积分（按过期时间升序，最早过期的先扣除）
        now_dt = now()
        remaining_points = points
        deducted_temporary = 0
        deducted_permanent = 0
        deduction_details = []  # 记录扣除详情
        
        # 查询所有未过期的临时积分，按过期时间升序排序
        temp_points_list = db.query(TemporaryPoints).filter(
            and_(
                TemporaryPoints.user_id == user_id,
                TemporaryPoints.expires_at > now_dt,
                TemporaryPoints.expire_record_id.is_(None)  # 还未创建过期记录
            )
        ).order_by(TemporaryPoints.expires_at.asc()).all()
        
        # 优先扣除临时积分（从最早过期的开始）
        for temp_points in temp_points_list:
            if remaining_points <= 0:
                break
            
            if temp_points.points > 0:
                deduct_from_this = min(remaining_points, temp_points.points)
                temp_points.points -= deduct_from_this
                deducted_temporary += deduct_from_this
                remaining_points -= deduct_from_this
                
                deduction_details.append({
                    "temp_id": temp_points.temp_id,
                    "source_type": temp_points.source_type,
                    "points": deduct_from_this,
                    "expires_at": temp_points.expires_at.isoformat() if temp_points.expires_at else None
                })
                
                # 如果该临时积分已全部扣除，可以删除（可选，或者保留为0）
                if temp_points.points == 0:
                    db.delete(temp_points)
                
                logger.debug(
                    f"从临时积分 {temp_points.temp_id} ({temp_points.source_type}) 扣除 {deduct_from_this} 积分 "
                    f"(过期时间: {temp_points.expires_at})"
                )
        
        # 剩余部分从长期积分中扣除
        if remaining_points > 0:
            if account.permanent_points < remaining_points:
                # 长期积分不足，抛出异常
                raise InsufficientPointsError(required=points, available=balance_before)
            account.permanent_points -= remaining_points
            deducted_permanent = remaining_points
        
        # 同步总积分（已经更新了 permanent_points 和临时积分，这里会重新计算 total_points）
        PointsService._sync_total_points(db, account)
        balance_after = account.available_points
        
        # 创建消耗记录（points 为负数）
        # 在 extra_data 中记录扣除详情
        if extra_data is None:
            extra_data = {}
        extra_data["deduction_details"] = {
            "temporary_points": deducted_temporary,
            "permanent_points": deducted_permanent,
            "details": deduction_details
        }
        
        record = PointsRecord(
            account_id=account.account_id,
            user_id=user_id,
            record_type="consume",
            operation_type=operation_type,
            points=-points,  # 负数表示消耗
            balance_before=balance_before,
            balance_after=balance_after,
            creation_id=creation_id,
            novel_id=novel_id,
            description=description,
            extra_data=extra_data
        )
        db.add(record)
        db.commit()
        db.refresh(record)
        
        logger.info(
            f"用户 {user_id} 扣除积分: {points} "
            f"(临时积分: {deducted_temporary}, 长期积分: {deducted_permanent}), "
            f"余额: {balance_before} -> {balance_after}"
        )
        return record
    
    @staticmethod
    def deduct_points_after(
        db: Session,
        user_id: int,
        points: int,
        operation_type: str,
        creation_id: int = None,
        novel_id: int = None,
        description: str = None,
        extra_data: Dict = None,
        check_duplicate: bool = False  # LLM调用不检查重复，因为可能多次调用
    ) -> PointsRecord:
        """
        扣除积分（后扣机制，允许负积分）
        
        Args:
            db: 数据库会话
            user_id: 用户ID
            points: 积分数量（正数）
            operation_type: 操作类型
            creation_id: 创作ID
            novel_id: 小说ID
            description: 描述
            extra_data: 扩展信息
            check_duplicate: 是否检查重复扣除（LLM调用通常不检查）
            
        Returns:
            积分记录对象
        """
        return PointsService.deduct_points(
            db=db,
            user_id=user_id,
            points=points,
            operation_type=operation_type,
            creation_id=creation_id,
            novel_id=novel_id,
            description=description,
            extra_data=extra_data,
            allow_negative=True,
            check_duplicate=check_duplicate
        )
    
    @staticmethod
    def freeze_points(
        db: Session,
        user_id: int,
        points: int,
        operation_type: str,
        creation_id: int = None,
        novel_id: int = None,
        description: str = None,
        extra_data: Dict = None
    ) -> PointsRecord:
        """
        冻结积分（用于任务提交时预扣，防止多设备并发超额使用）
        
        流程：
        1. 检查积分是否充足
        2. 冻结积分（available_points -= points, frozen_points += points）
        3. 创建冻结记录
        
        如果任务成功，调用 confirm_frozen_points 确认扣除
        如果任务失败，调用 release_frozen_points 退回积分
        
        Args:
            db: 数据库会话
            user_id: 用户ID
            points: 积分数量（正数）
            operation_type: 操作类型
            creation_id: 创作ID
            novel_id: 小说ID
            description: 描述
            extra_data: 扩展信息
            
        Returns:
            冻结记录对象
            
        Raises:
            InsufficientPointsError: 积分不足
        """
        # 使用 SELECT FOR UPDATE 锁定账户行，防止并发问题
        account = db.query(PointsAccount).filter(
            PointsAccount.user_id == user_id
        ).with_for_update().first()
        
        if not account:
            account = PointsAccount(
                user_id=user_id,
                total_points=0,
                available_points=0,
                frozen_points=0,
                permanent_points=0
            )
            db.add(account)
            db.flush()
        
        # 同步总积分（确保数据一致）
        PointsService._sync_total_points(db, account)
        balance_before = account.available_points
        
        # 检查余额
        if account.available_points < points:
            raise InsufficientPointsError(required=points, available=balance_before)
        
        if account.available_points <= 0:
            raise InsufficientPointsError(required=points, available=balance_before)
        
        # 冻结积分（只操作 frozen_points，available_points 会在同步时自动计算）
        account.frozen_points += points
        # 同步总积分（会重新计算 available_points = total_points - frozen_points）
        PointsService._sync_total_points(db, account)
        balance_after = account.available_points
        
        # 创建冻结记录（record_type="freeze"）
        record = PointsRecord(
            account_id=account.account_id,
            user_id=user_id,
            record_type="freeze",  # 冻结类型
            operation_type=operation_type,
            points=-points,  # 负数表示冻结
            balance_before=balance_before,
            balance_after=balance_after,
            creation_id=creation_id,
            novel_id=novel_id,
            description=description or f"冻结积分：{points}",
            extra_data=extra_data
        )
        db.add(record)
        db.commit()
        db.refresh(record)
        
        logger.info(f"用户 {user_id} 冻结积分: {points}, 可用余额: {balance_before} -> {balance_after}, 冻结余额: {account.frozen_points}")
        return record
    
    @staticmethod
    def confirm_frozen_points(
        db: Session,
        freeze_record_id: int
    ) -> PointsRecord:
        """
        确认冻结的积分（任务成功时调用）
        
        流程：
        1. 查询冻结记录
        2. 从 frozen_points 中扣除（frozen_points -= points）
        3. 创建确认扣除记录
        
        Args:
            db: 数据库会话
            freeze_record_id: 冻结记录的ID
            
        Returns:
            确认扣除记录对象
            
        Raises:
            NotFoundError: 冻结记录不存在
            AlreadyExistsError: 已确认
        """
        from app.core.exceptions import NotFoundError, AlreadyExistsError
        
        # 查询冻结记录
        freeze_record = db.query(PointsRecord).filter(
            PointsRecord.record_id == freeze_record_id
        ).first()
        
        if not freeze_record:
            raise NotFoundError(detail="冻结记录不存在")
        
        if freeze_record.record_type != "freeze":
            raise ValueError("该记录不是冻结记录")
        
        # 检查是否已确认
        existing_confirm = db.query(PointsRecord).filter(
            and_(
                PointsRecord.record_type == "consume",
                PointsRecord.extra_data.isnot(None),
                text("points_records.extra_data->>'freeze_record_id'") == str(freeze_record_id)
            )
        ).first()
        
        if existing_confirm:
            logger.warning(f"冻结记录 {freeze_record_id} 已确认，跳过重复确认")
            return existing_confirm  # 已确认，返回已存在的记录
        
        # 使用行锁
        account = db.query(PointsAccount).filter(
            PointsAccount.user_id == freeze_record.user_id
        ).with_for_update().first()
        
        if not account:
            raise NotFoundError(detail="积分账户不存在")
        
        # 确认扣除：实际扣除积分（优先扣除临时积分）
        points = abs(freeze_record.points)
        # 同步总积分（确保数据一致）
        PointsService._sync_total_points(db, account)
        balance_before = account.available_points
        
        # 优先扣除临时积分（按过期时间升序）
        now_dt = now()
        remaining_points = points
        deducted_temporary = 0
        deducted_permanent = 0
        
        temp_points_list = db.query(TemporaryPoints).filter(
            and_(
                TemporaryPoints.user_id == freeze_record.user_id,
                TemporaryPoints.expires_at > now_dt,
                TemporaryPoints.expire_record_id.is_(None)  # 还未创建过期记录
            )
        ).order_by(TemporaryPoints.expires_at.asc()).all()
        
        # 优先扣除临时积分
        for temp_points in temp_points_list:
            if remaining_points <= 0:
                break
            
            if temp_points.points > 0:
                deduct_from_this = min(remaining_points, temp_points.points)
                temp_points.points -= deduct_from_this
                deducted_temporary += deduct_from_this
                remaining_points -= deduct_from_this
                
                if temp_points.points == 0:
                    db.delete(temp_points)
        
        # 剩余部分从长期积分扣除
        if remaining_points > 0:
            account.permanent_points -= remaining_points
            deducted_permanent = remaining_points
        
        # 减少冻结积分
        account.frozen_points -= points
        
        # 同步总积分
        PointsService._sync_total_points(db, account)
        balance_after = account.available_points
        
        # 创建确认扣除记录
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
            points=-points,  # 负数表示消耗
            balance_before=balance_before,
            balance_after=balance_after,
            creation_id=freeze_record.creation_id,
            novel_id=freeze_record.novel_id,
            description=f"确认扣除：{freeze_record.description}",
            extra_data=extra_data
        )
        db.add(confirm_record)
        db.commit()
        db.refresh(confirm_record)
        
        logger.info(f"用户 {freeze_record.user_id} 确认扣除冻结积分: {points}, 冻结余额: {account.frozen_points}")
        return confirm_record
    
    @staticmethod
    def release_frozen_points(
        db: Session,
        freeze_record_id: int,
        reason: str = None
    ) -> PointsRecord:
        """
        释放冻结的积分（任务失败时调用）
        
        流程：
        1. 查询冻结记录
        2. 退回积分（frozen_points -= points, available_points += points）
        3. 创建释放记录
        
        Args:
            db: 数据库会话
            freeze_record_id: 冻结记录的ID
            reason: 释放原因
            
        Returns:
            释放记录对象
            
        Raises:
            NotFoundError: 冻结记录不存在
            AlreadyExistsError: 已释放
        """
        from app.core.exceptions import NotFoundError, AlreadyExistsError
        
        # 查询冻结记录
        freeze_record = db.query(PointsRecord).filter(
            PointsRecord.record_id == freeze_record_id
        ).first()
        
        if not freeze_record:
            raise NotFoundError(detail="冻结记录不存在")
        
        if freeze_record.record_type != "freeze":
            raise ValueError("该记录不是冻结记录")
        
        # 检查是否已释放
        existing_release = db.query(PointsRecord).filter(
            and_(
                PointsRecord.record_type == "release",
                PointsRecord.extra_data.isnot(None),
                text("points_records.extra_data->>'freeze_record_id'") == str(freeze_record_id)
            )
        ).first()
        
        if existing_release:
            logger.warning(f"冻结记录 {freeze_record_id} 已释放，跳过重复释放")
            return existing_release  # 已释放，返回已存在的记录
        
        # 使用行锁
        account = db.query(PointsAccount).filter(
            PointsAccount.user_id == freeze_record.user_id
        ).with_for_update().first()
        
        if not account:
            raise NotFoundError(detail="积分账户不存在")
        
        # 释放冻结的积分
        points = abs(freeze_record.points)
        # 同步总积分（确保数据一致）
        PointsService._sync_total_points(db, account)
        balance_before = account.available_points
        
        # 释放冻结的积分（只减少 frozen_points，available_points 会在同步时自动计算）
        account.frozen_points -= points
        
        # 同步总积分（会重新计算 available_points = total_points - frozen_points）
        PointsService._sync_total_points(db, account)
        balance_after = account.available_points
        
        # 创建释放记录
        release_record = PointsRecord(
            account_id=account.account_id,
            user_id=freeze_record.user_id,
            record_type="release",
            operation_type=freeze_record.operation_type,
            points=points,  # 正数表示退回
            balance_before=balance_before,
            balance_after=balance_after,
            creation_id=freeze_record.creation_id,
            novel_id=freeze_record.novel_id,
            description=f"释放冻结积分：{freeze_record.description}（原因：{reason or '任务失败'}）",
            extra_data={
                "freeze_record_id": freeze_record_id,
                "release_reason": reason,
                **(freeze_record.extra_data or {})
            }
        )
        db.add(release_record)
        db.commit()
        db.refresh(release_record)
        
        logger.info(f"用户 {freeze_record.user_id} 释放冻结积分: {points}, 余额: {balance_before} -> {balance_after}, 冻结余额: {account.frozen_points}")
        return release_record
    
    @staticmethod
    def refund_points(
        db: Session,
        user_id: int,
        original_record_id: int,
        reason: str = None
    ) -> PointsRecord:
        """
        退款积分（用于任务失败时退回预扣的积分）
        
        Args:
            db: 数据库会话
            user_id: 用户ID
            original_record_id: 原始扣除记录的ID
            reason: 退款原因
            
        Returns:
            退款记录
            
        Raises:
            NotFoundError: 原始记录不存在
            PermissionError: 无权退款
            AlreadyExistsError: 已退款
        """
        from app.core.exceptions import NotFoundError, PermissionError, AlreadyExistsError
        
        # 查询原始记录
        original_record = db.query(PointsRecord).filter(
            PointsRecord.record_id == original_record_id
        ).first()
        
        if not original_record:
            raise NotFoundError(detail="原始扣除记录不存在")
        
        if original_record.user_id != user_id:
            raise PermissionError(detail="无权退款该记录")
        
        if original_record.record_type != "consume":
            raise ValueError("只能退款消耗类型的记录")
        
        # 检查是否已经退款过
        existing_refund = db.query(PointsRecord).filter(
            and_(
                PointsRecord.record_type == "refund",
                PointsRecord.extra_data.isnot(None),
                text("points_records.extra_data->>'original_record_id'") == str(original_record_id)
            )
        ).first()
        
        if existing_refund:
            raise AlreadyExistsError(detail="该记录已退款")
        
        # 使用行锁获取账户
        account = db.query(PointsAccount).filter(
            PointsAccount.user_id == user_id
        ).with_for_update().first()
        
        if not account:
            raise NotFoundError(detail="积分账户不存在")
        
        # 退回积分
        refund_points = abs(original_record.points)  # 原始扣除的积分数量
        balance_before = account.available_points
        
        account.total_points += refund_points
        account.available_points += refund_points
        balance_after = account.available_points
        
        # 创建退款记录
        refund_record = PointsRecord(
            account_id=account.account_id,
            user_id=user_id,
            record_type="refund",
            operation_type=original_record.operation_type,
            points=refund_points,  # 正数表示增加
            balance_before=balance_before,
            balance_after=balance_after,
            creation_id=original_record.creation_id,
            novel_id=original_record.novel_id,
            description=f"退款：{original_record.description}（原因：{reason or '任务失败'}）",
            extra_data={
                "original_record_id": original_record_id,
                "refund_reason": reason
            }
        )
        db.add(refund_record)
        db.commit()
        db.refresh(refund_record)
        
        logger.info(f"用户 {user_id} 退款积分: {refund_points}, 余额: {balance_before} -> {balance_after}")
        return refund_record
    
    @staticmethod
    def get_records(
        db: Session,
        user_id: int,
        page: int = 1,
        page_size: int = 20,
        record_type: str = None,
        operation_type: str = None,
        creation_id: int = None,
        novel_id: int = None,
        start_date: datetime = None,
        end_date: datetime = None
    ) -> Tuple[List[PointsRecord], int]:
        """
        获取积分记录列表（支持多维度筛选和分页）
        
        Args:
            db: 数据库会话
            user_id: 用户ID
            page: 页码
            page_size: 每页数量
            record_type: 记录类型
            operation_type: 操作类型
            creation_id: 创作ID
            novel_id: 小说ID
            start_date: 开始日期
            end_date: 结束日期
            
        Returns:
            (记录列表, 总数) 元组
        """
        query = db.query(PointsRecord).filter(PointsRecord.user_id == user_id)
        
        # 筛选条件
        if record_type:
            # 如果明确指定了记录类型，则按指定类型查询
            query = query.filter(PointsRecord.record_type == record_type)
        else:
            # 如果没有指定记录类型，默认排除内部使用的 freeze 和 release 记录
            # 这些是中间状态记录，用户不需要看到，只需要看到最终的消耗记录
            query = query.filter(
                ~PointsRecord.record_type.in_(["freeze", "release"])
            )
        if operation_type:
            query = query.filter(PointsRecord.operation_type == operation_type)
        if creation_id:
            query = query.filter(PointsRecord.creation_id == creation_id)
        if novel_id:
            query = query.filter(PointsRecord.novel_id == novel_id)
        if start_date:
            query = query.filter(PointsRecord.created_at >= start_date)
        if end_date:
            query = query.filter(PointsRecord.created_at <= end_date)
        
        # 计算总数
        total = query.count()
        
        # 分页（按ID降序排序，最新的在前）
        skip = (page - 1) * page_size
        records = query.order_by(desc(PointsRecord.record_id)).offset(skip).limit(page_size).all()
        
        return records, total
    
    @staticmethod
    def get_statistics(
        db: Session,
        user_id: int,
        start_date: datetime = None,
        end_date: datetime = None
    ) -> Dict:
        """
        获取积分统计信息
        
        Args:
            db: 数据库会话
            user_id: 用户ID
            start_date: 开始日期
            end_date: 结束日期
            
        Returns:
            统计信息字典
        """
        query = db.query(PointsRecord).filter(PointsRecord.user_id == user_id)
        
        if start_date:
            query = query.filter(PointsRecord.created_at >= start_date)
        if end_date:
            query = query.filter(PointsRecord.created_at <= end_date)
        
        # 总获得
        total_earned = db.query(func.sum(PointsRecord.points)).filter(
            and_(
                PointsRecord.user_id == user_id,
                PointsRecord.points > 0
            )
        ).scalar() or 0
        total_earned = int(total_earned)
        
        # 总消耗
        total_consumed = db.query(func.sum(PointsRecord.points)).filter(
            and_(
                PointsRecord.user_id == user_id,
                PointsRecord.record_type == "consume",
                PointsRecord.points < 0
            )
        ).scalar() or 0
        total_consumed = abs(int(total_consumed))
        
        # 今日消耗
        today_start_dt = today_start()
        today_consumed = db.query(func.sum(PointsRecord.points)).filter(
            and_(
                PointsRecord.user_id == user_id,
                PointsRecord.record_type == "consume",
                PointsRecord.created_at >= today_start_dt,
                PointsRecord.points < 0
            )
        ).scalar() or 0
        today_consumed = abs(int(today_consumed))
        
        # 本月消耗
        month_start_dt = month_start()
        month_consumed = db.query(func.sum(PointsRecord.points)).filter(
            and_(
                PointsRecord.user_id == user_id,
                PointsRecord.record_type == "consume",
                PointsRecord.created_at >= month_start_dt,
                PointsRecord.points < 0
            )
        ).scalar() or 0
        month_consumed = abs(int(month_consumed))
        
        # 按操作类型统计消耗
        by_operation_type = {}
        operation_stats = db.query(
            PointsRecord.operation_type,
            func.sum(PointsRecord.points)
        ).filter(
            and_(
                PointsRecord.user_id == user_id,
                PointsRecord.record_type == "consume",
                PointsRecord.points < 0
            )
        ).group_by(PointsRecord.operation_type).all()
        
        for op_type, points_sum in operation_stats:
            if op_type:
                by_operation_type[op_type] = abs(int(points_sum))
        
        return {
            "total_earned": total_earned,
            "total_consumed": total_consumed,
            "today_consumed": today_consumed,
            "month_consumed": month_consumed,
            "by_operation_type": by_operation_type
        }
    
    @staticmethod
    def expire_daily_points(db: Session) -> int:
        """
        过期临时积分（定时任务调用，简化版）
        
        注意：此方法主要用于定时任务批量处理过期积分。
        日常查询时，get_account_balance 会自动处理已过期但未创建过期记录的临时积分。
        
        Args:
            db: 数据库会话
            
        Returns:
            过期积分总数
        """
        now_dt = now()
        
        # 查询所有过期的临时积分（且还未创建过期记录）
        expired_temp_points = db.query(TemporaryPoints).filter(
            and_(
                TemporaryPoints.expires_at <= now_dt,
                TemporaryPoints.points > 0,  # 还有未使用的积分
                TemporaryPoints.expire_record_id.is_(None)  # 还未创建过期记录
            )
        ).all()
        
        if not expired_temp_points:
            return 0
        
        # 按用户分组计算过期积分
        user_expired_points = {}
        user_temp_list = {}  # 记录每个用户的临时积分列表
        for temp in expired_temp_points:
            if temp.user_id not in user_expired_points:
                user_expired_points[temp.user_id] = 0
                user_temp_list[temp.user_id] = []
            user_expired_points[temp.user_id] += temp.points
            user_temp_list[temp.user_id].append(temp)
        
        total_expired = 0
        
        # 为每个用户创建过期记录并更新账户
        for user_id, expired_points in user_expired_points.items():
            account = PointsService.get_or_create_account(db, user_id)
            balance_before = account.available_points
            
            # 同步总积分（会自动减去过期的临时积分，因为临时积分已过期，不会被计入总积分）
            PointsService._sync_total_points(db, account)
            balance_after = account.available_points
            
            # 创建过期记录
            expire_record = PointsRecord(
                account_id=account.account_id,
                user_id=user_id,
                record_type="expire",
                operation_type="temporary_points_expire",
                points=-expired_points,
                points_type="temporary",
                balance_before=balance_before,
                balance_after=balance_after,
                description=f"临时积分过期，扣除 {expired_points} 积分"
            )
            db.add(expire_record)
            db.flush()  # 获取 record_id
            
            # 更新临时积分记录的 expire_record_id，标记已创建过期记录
            # 将 points 设为 0，标记为已过期处理（保留记录用于历史追踪）
            for temp in user_temp_list[user_id]:
                temp.expire_record_id = expire_record.record_id
                temp.points = 0  # 标记为已过期处理
            
            total_expired += expired_points
            logger.info(
                f"用户 {user_id} 临时积分过期: {expired_points}, "
                f"余额: {balance_before} -> {balance_after}, "
                f"过期记录ID: {expire_record.record_id}"
            )
        
        db.commit()
        logger.info(f"积分过期任务完成，共过期 {total_expired} 积分，涉及 {len(user_expired_points)} 个用户")
        return total_expired
