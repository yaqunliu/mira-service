from sqlalchemy import create_engine, event
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import declarative_base, sessionmaker
from app.core.config import settings
from app.core.logger import logger
import logging
import warnings

logging.getLogger('sqlalchemy.engine').setLevel(logging.WARNING)
logging.getLogger('sqlalchemy.pool').setLevel(logging.WARNING)
logging.getLogger('sqlalchemy.dialects').setLevel(logging.WARNING)

warnings.filterwarnings("ignore", category=DeprecationWarning)

Base = declarative_base()

_sync_engine = None
_sync_session_factory = None
_async_engine = None
_async_session_factory = None


def _get_sync_engine():
    global _sync_engine
    if _sync_engine is None:
        _sync_engine = create_engine(
            str(settings.DATABASE_URL),
            echo=False,
            pool_pre_ping=True,
            pool_size=10,
            max_overflow=20,
            pool_recycle=3600,
            connect_args={
                "connect_timeout": 30
            }
        )
    return _sync_engine


def _get_sync_session_factory():
    global _sync_session_factory
    if _sync_session_factory is None:
        _sync_session_factory = sessionmaker(
            autocommit=False,
            autoflush=False,
            bind=_get_sync_engine()
        )
    return _sync_session_factory


def _get_async_engine():
    global _async_engine
    if _async_engine is None:
        ASYNC_DATABASE_URL = str(settings.DATABASE_URL).replace(
            "postgresql://", "postgresql+asyncpg://"
        )
        _async_engine = create_async_engine(
            ASYNC_DATABASE_URL,
            echo=False,
            pool_pre_ping=True,
            pool_size=5,
            max_overflow=10,
            pool_timeout=30,
            pool_recycle=1800,
            connect_args={
                "timeout": 30,
                "command_timeout": 60
            }
        )
    return _async_engine


def _get_async_session_factory():
    global _async_session_factory
    if _async_session_factory is None:
        _async_session_factory = async_sessionmaker(
            bind=_get_async_engine(),
            class_=AsyncSession,
            autocommit=False,
            autoflush=False,
            expire_on_commit=False,
            info={"deferred": True}
        )
    return _async_session_factory


async def _close_session(session: AsyncSession):
    """安全关闭异步会话"""
    if session is None:
        return
    
    try:
        await session.close()
    except Exception:
        pass


class SyncSessionLocal:
    """同步数据库会话工厂（延迟初始化）"""
    _instance = None
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance
    
    def __call__(self):
        return _get_sync_session_factory()()


class AsyncSessionLocal:
    """异步数据库会话工厂（延迟初始化）"""
    _instance = None
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance
    
    def __call__(self) -> AsyncSession:
        return _get_async_session_factory()()


async def get_async_db() -> AsyncSession:
    async_session = _get_async_session_factory()()
    try:
        yield async_session
    except Exception as e:
        await async_session.rollback()
        raise
    finally:
        await async_session.close()


def get_sync_db():
    db = SyncSessionLocal()()
    try:
        yield db
    finally:
        db.close()
