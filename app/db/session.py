from sqlalchemy.orm import Session
from app.db.base import SessionLocal


def get_db() -> Session:
    """获取数据库会话"""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
