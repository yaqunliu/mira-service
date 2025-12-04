from sqlalchemy import Boolean, Column, DateTime, Integer, String
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship
from app.db.base import Base


class User(Base):
    """用户模型"""
    __tablename__ = "users"
    
    user_id = Column(Integer, primary_key=True, index=True)
    username = Column(String(50), unique=True, index=True, nullable=False)
    email = Column(String(100), unique=True, nullable=False)
    hashed_password = Column(String(255), nullable=True)  # OAuth 用户可以为空
    
    # Supabase 用户 ID（用于关联）
    supabase_user_id = Column(String(255), unique=True, nullable=True, index=True)
    
    # 用户头像 URL
    avatar = Column(String(500), nullable=True)
    
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
    
    # 关系
    novels = relationship("Novel", back_populates="owner")
    creations = relationship("Creation", back_populates="owner")
    points_account = relationship("PointsAccount", back_populates="user", uselist=False)
