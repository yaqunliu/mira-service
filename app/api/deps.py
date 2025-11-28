from typing import Generator, Optional
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jose import jwt, JWTError
from sqlalchemy.orm import Session
from app.core.config import settings
from app.db.session import get_db
from app.models.user import User
from app.core.logger import logger

oauth2_scheme = OAuth2PasswordBearer(tokenUrl=f"{settings.API_V1_STR}/auth/login", auto_error=False)


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
    token: Optional[str] = Depends(oauth2_scheme)
) -> User:
    """
    获取当前用户
    如果无法获取当前用户（token无效或未提供），则抛出401未授权异常
    """
    # 如果没有提供token，抛出未授权异常
    if not token:
        logger.warning("未提供token，拒绝访问")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="未提供认证令牌",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    try:
        payload = jwt.decode(
            token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM]
        )
        username: str = payload.get("sub")
        if username is None:
            logger.warning("token中未找到用户名")
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="无效的认证令牌",
                headers={"WWW-Authenticate": "Bearer"},
            )
    except JWTError as e:
        logger.warning(f"token验证失败: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="无效的认证令牌",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    user = db.query(User).filter(User.username == username).first()
    if user is None:
        logger.warning(f"用户 {username} 不存在")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="用户不存在",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    return user


