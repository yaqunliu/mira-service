from typing import Optional, Dict, Any
from sqlalchemy.orm import Session
from app.models.user import User
from app.services.supabase_service import supabase_service
from app.services.points_service import PointsService
from app.core.logger import logger


class UserSyncService:
    """
    将 Supabase 用户同步到现有的 users 表
    """
    
    @staticmethod
    def sync_supabase_user(
        db: Session,
        supabase_user_data: Dict[str, Any]
    ) -> User:
        """
        同步 Supabase 用户到本地 users 表
        如果用户已存在（通过 email 或 supabase_user_id），则更新；否则创建新用户
        """
        email = supabase_user_data.get("email")
        supabase_user_id = supabase_user_data.get("supabase_user_id")
        
        if not email:
            raise ValueError("Email is required")
        
        # 首先通过 supabase_user_id 查找用户
        user = None
        if supabase_user_id:
            user = db.query(User).filter(User.supabase_user_id == supabase_user_id).first()
        
        # 如果没找到，通过 email 查找
        if not user:
            user = db.query(User).filter(User.email == email).first()
        
        if user:
            # 更新现有用户
            updated = False
            
            # 更新 supabase_user_id（如果还没有）
            if supabase_user_id and not user.supabase_user_id:
                user.supabase_user_id = supabase_user_id
                updated = True
            
            # 更新邮箱（如果不同）
            if user.email != email:
                user.email = email
                updated = True
            
            # 更新用户元数据中的头像（如果有）
            user_metadata = supabase_user_data.get("user_metadata", {})
            # 优先使用 avatar_url 字段，如果没有则使用 user_metadata 中的值
            avatar_url = supabase_user_data.get("avatar_url") or user_metadata.get("avatar_url") or user_metadata.get("picture")
            logger.info(f"同步用户头像: email={email}, avatar_url={avatar_url}, has_avatar_field={hasattr(user, 'avatar')}")
            if avatar_url:
                # 如果 User 模型有 avatar 字段，更新它（即使已有值也更新，确保使用最新的头像）
                if hasattr(user, 'avatar'):
                    if user.avatar != avatar_url:
                        user.avatar = avatar_url
                        updated = True
                        logger.info(f"更新用户头像: {avatar_url}")
                else:
                    # 如果没有 avatar 字段，记录日志但不报错
                    logger.warning(f"User 模型没有 avatar 字段，无法更新头像。avatar_url={avatar_url}")
            
            if updated:
                db.commit()
                db.refresh(user)
            
            return user
        else:
            # 创建新用户
            # 从 email 生成 username
            username = email.split("@")[0]
            
            # 确保 username 唯一
            base_username = username
            counter = 1
            while db.query(User).filter(User.username == username).first():
                username = f"{base_username}{counter}"
                counter += 1
            
            # 获取用户元数据
            user_metadata = supabase_user_data.get("user_metadata", {})
            # 优先使用 avatar_url 字段，如果没有则使用 user_metadata 中的值
            avatar_url = supabase_user_data.get("avatar_url") or user_metadata.get("avatar_url") or user_metadata.get("picture")
            logger.info(f"创建新用户头像: email={email}, avatar_url={avatar_url}")
            
            new_user = User(
                username=username,
                email=email,
                hashed_password=None,  # OAuth 用户不需要密码
                supabase_user_id=supabase_user_id,
                avatar=avatar_url,  # 直接设置 avatar 字段
            )
            
            db.add(new_user)
            db.commit()
            db.refresh(new_user)
            
            # 创建积分账户并赠送注册积分
            try:
                PointsService.register_reward(db, new_user.user_id)
                logger.info(f"Supabase 用户注册积分赠送成功: user_id={new_user.user_id}")
            except Exception as e:
                # 如果积分赠送失败，记录日志但不影响注册流程
                logger.error(f"Supabase 用户注册积分赠送失败: user_id={new_user.user_id}, error={str(e)}")
            
            return new_user
    
    @staticmethod
    def get_user_from_supabase_token(
        db: Session,
        token: str
    ) -> Optional[User]:
        """
        从 Supabase token 获取或创建用户
        """
        supabase_user_data = supabase_service.get_user_from_token(token)
        if not supabase_user_data:
            return None
        return UserSyncService.sync_supabase_user(db, supabase_user_data)

