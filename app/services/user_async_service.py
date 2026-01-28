from typing import Optional, Dict, Any
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from sqlalchemy.orm import selectinload
from app.models.user import User
from app.services.supabase_service import supabase_service
from app.services.points_async_service import PointsAsyncService
from app.core.logger import logger


class UserAsyncService:
    """
    异步版本：将 Supabase 用户同步到现有的 users 表
    """
    
    @staticmethod
    async def sync_supabase_user(
        db: AsyncSession,
        supabase_user_data: Dict[str, Any]
    ) -> User:
        """
        同步 Supabase 用户到本地 users 表（异步）
        如果用户已存在（通过 email 或 supabase_user_id），则更新；否则创建新用户
        """
        email = supabase_user_data.get("email")
        supabase_user_id = supabase_user_data.get("supabase_user_id")
        
        if not email:
            raise ValueError("Email is required")
        
        user = None
        if supabase_user_id:
            result = await db.execute(
                select(User).where(User.supabase_user_id == supabase_user_id)
            )
            user = result.scalar_one_or_none()
        
        if not user:
            result = await db.execute(
                select(User).where(User.email == email)
            )
            user = result.scalar_one_or_none()
        
        if user:
            updated = False
            
            if supabase_user_id and not user.supabase_user_id:
                user.supabase_user_id = supabase_user_id
                updated = True
            
            if user.email != email:
                user.email = email
                updated = True
            
            user_metadata = supabase_user_data.get("user_metadata", {})
            avatar_url = supabase_user_data.get("avatar_url") or user_metadata.get("avatar_url") or user_metadata.get("picture")
            
            if avatar_url:
                if hasattr(user, 'avatar'):
                    if user.avatar != avatar_url:
                        user.avatar = avatar_url
                        updated = True
            
            if updated:
                await db.commit()
                await db.refresh(user)
            
            return user
        else:
            username = email.split("@")[0]
            
            base_username = username
            counter = 1
            while True:
                result = await db.execute(
                    select(User).where(User.username == username)
                )
                existing = result.scalar_one_or_none()
                if not existing:
                    break
                username = f"{base_username}{counter}"
                counter += 1
            
            user_metadata = supabase_user_data.get("user_metadata", {})
            avatar_url = supabase_user_data.get("avatar_url") or user_metadata.get("avatar_url") or user_metadata.get("picture")
            
            new_user = User(
                username=username,
                email=email,
                hashed_password=None,
                supabase_user_id=supabase_user_id,
                avatar=avatar_url,
            )
            
            db.add(new_user)
            await db.commit()
            await db.refresh(new_user)
            
            try:
                await PointsAsyncService.register_reward(db, new_user.user_id)
            except Exception as e:
                logger.error(f"Supabase 用户注册积分赠送失败: user_id={new_user.user_id}, error={str(e)}")
            
            return new_user
    
    @staticmethod
    async def get_user_from_supabase_token(
        db: AsyncSession,
        token: str
    ) -> Optional[User]:
        """
        从 Supabase token 获取或创建用户（异步）
        """
        supabase_user_data = supabase_service.get_user_from_token(token)
        if not supabase_user_data:
            return None
        return await UserAsyncService.sync_supabase_user(db, supabase_user_data)
    
    @staticmethod
    async def get_user_by_id(db: AsyncSession, user_id: int) -> Optional[User]:
        """
        根据用户 ID 获取用户（异步）
        """
        result = await db.execute(
            select(User).where(User.user_id == user_id)
        )
        return result.scalar_one_or_none()
    
    @staticmethod
    async def get_user_by_email(db: AsyncSession, email: str) -> Optional[User]:
        """
        根据邮箱获取用户（异步）
        """
        result = await db.execute(
            select(User).where(User.email == email)
        )
        return result.scalar_one_or_none()
    
    @staticmethod
    async def get_user_count(db: AsyncSession) -> int:
        """
        获取用户总数（异步）
        """
        result = await db.execute(select(func.count(User.user_id)))
        return result.scalar() or 0
