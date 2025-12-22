from typing import Generator, Optional
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.orm import Session
from app.db.session import get_db
from app.models.user import User
from app.core.logger import logger
from app.services.supabase_service import supabase_service
from app.services.user_sync_service import UserSyncService

# 使用 HTTPBearer 替代 OAuth2PasswordBearer，因为不再有传统的登录端点
security = HTTPBearer(auto_error=False)


def get_default_user(db: Session) -> User:
    """
    获取默认用户（admin）
    如果不存在则创建
    
    Returns:
        User对象
    """
    user = db.query(User).filter(User.username == "admin").first()
    if not user:
        # 如果admin用户不存在，创建一个默认用户
        # 注意：这里使用一个默认密码哈希，实际使用时应该通过迁移创建
        from app.core.security import get_password_hash
        user = User(
            username="admin",
            email="admin@example.com",
            hashed_password=get_password_hash("admin123")
        )
        db.add(user)
        db.commit()
        db.refresh(user)
        logger.info("创建默认admin用户")
    return user


def get_current_user(
    db: Session = Depends(get_db),
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security)
) -> User:
    """
    获取当前用户
    只支持 Supabase JWT token 认证
    
    如果无法获取当前用户（token无效或未提供），则抛出401未授权异常
    """
    # 如果没有提供token，抛出未授权异常
    if not credentials:
        # 停掉 sync 相关日志
        # logger.warning("未提供token，拒绝访问")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="未提供认证令牌，请使用 Supabase 登录",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    token = credentials.credentials
    
    # 验证 Supabase token
    supabase_user_data = supabase_service.get_user_from_token(token)
    if not supabase_user_data:
        # 停掉 sync 相关日志
        # logger.warning("Supabase token 验证失败")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="无效的认证令牌，请使用 Supabase 登录",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    # 使用 Supabase token，同步用户到数据库
    user = UserSyncService.get_user_from_supabase_token(db, token)
    if not user:
        # 停掉 sync 相关日志
        # logger.warning("Supabase token 验证成功但无法同步用户")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="无法获取用户信息",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    return user


