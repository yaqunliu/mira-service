from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session
from contextlib import contextmanager
from app.db.base import AsyncSessionLocal, SyncSessionLocal, get_async_db

SessionLocal = SyncSessionLocal


@contextmanager
def get_sync_session():
    """获取同步数据库会话的 context manager"""
    db = SyncSessionLocal()()
    try:
        yield db
    finally:
        db.close()


def get_sync_db() -> Session:
    db = SyncSessionLocal()()
    try:
        yield db
    finally:
        db.close()
