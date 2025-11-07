#!/usr/bin/env python3
"""
数据库初始化脚本
"""

import asyncio
from sqlalchemy import create_engine
from app.core.config import settings
from app.db.base import Base
from app.models import *  # 导入所有模型


def init_db():
    """初始化数据库"""
    print("正在创建数据库表...")
    
    engine = create_engine(str(settings.DATABASE_URL))
    Base.metadata.create_all(bind=engine)
    
    print("数据库表创建完成!")


if __name__ == "__main__":
    init_db()
