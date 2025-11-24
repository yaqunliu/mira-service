from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base
from sqlalchemy.orm import sessionmaker
from app.core.config import settings
import logging

# 关闭 SQLAlchemy 引擎的日志输出
# 设置 SQLAlchemy 引擎日志级别为 WARNING，避免打印 SQL 查询
logging.getLogger('sqlalchemy.engine').setLevel(logging.WARNING)
logging.getLogger('sqlalchemy.pool').setLevel(logging.WARNING)
logging.getLogger('sqlalchemy.dialects').setLevel(logging.WARNING)

engine = create_engine(
    str(settings.DATABASE_URL),
    echo=False  # 始终关闭 echo，避免打印 SQL 查询
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()
