#!/usr/bin/env python3
"""
创建超级用户脚本
"""

from sqlalchemy.orm import sessionmaker
from sqlalchemy import create_engine
from app.core.config import settings
from app.core.security import get_password_hash
from app.models.user import User


def create_superuser():
    """创建超级用户"""
    engine = create_engine(str(settings.DATABASE_URL))
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    
    db = SessionLocal()
    
    try:
        # 检查是否已存在超级用户
        existing_superuser = db.query(User).filter(User.is_superuser == True).first()
        if existing_superuser:
            print(f"超级用户已存在: {existing_superuser.username}")
            return
        
        # 创建超级用户
        username = input("请输入超级用户名: ")
        email = input("请输入邮箱: ")
        password = input("请输入密码: ")
        
        if not username or not email or not password:
            print("用户名、邮箱和密码不能为空!")
            return
        
        # 检查用户名是否已存在
        existing_user = db.query(User).filter(User.username == username).first()
        if existing_user:
            print(f"用户名 {username} 已存在!")
            return
        
        # 检查邮箱是否已存在
        existing_email = db.query(User).filter(User.email == email).first()
        if existing_email:
            print(f"邮箱 {email} 已存在!")
            return
        
        hashed_password = get_password_hash(password)
        superuser = User(
            username=username,
            email=email,
            hashed_password=hashed_password,
            is_active=True,
            is_superuser=True,
            quota_limit=1000,
        )
        
        db.add(superuser)
        db.commit()
        db.refresh(superuser)
        
        print(f"超级用户创建成功: {superuser.username}")
        
    except Exception as e:
        print(f"创建超级用户失败: {e}")
        db.rollback()
    finally:
        db.close()


if __name__ == "__main__":
    create_superuser()
