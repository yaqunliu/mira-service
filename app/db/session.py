from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session
from app.db.base import AsyncSessionLocal, SyncSessionLocal, get_async_db

SessionLocal = SyncSessionLocal


def get_sync_db() -> Session:
    db = SyncSessionLocal()()
    try:
        yield db
    finally:
        db.close()
