"""
异步数据库工具 - 提供异步数据库会话管理
"""

from typing import AsyncGenerator
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from app.db.base import AsyncSessionLocal
import contextlib


@contextlib.asynccontextmanager
async def get_async_db_session() -> AsyncGenerator[AsyncSession, None]:
    """
    获取异步数据库会话的上下文管理器

    Usage:
        async with get_async_db_session() as db:
            result = await db.execute(select(User)...)

    Returns:
        AsyncSession 实例
    """
    # AsyncSessionLocal 是工厂类，需要先实例化再调用
    # AsyncSessionLocal() 返回工厂实例，再调用 () 获取 session
    session = AsyncSessionLocal()()
    try:
        yield session
        await session.commit()
    except Exception:
        await session.rollback()
        raise
    finally:
        await session.close()


# 别名，方便 db_tools 调用
get_async_session = get_async_db_session


async def execute_async(db: AsyncSession, stmt):
    """
    异步执行 SQL 语句

    Args:
        db: AsyncSession 实例
        stmt: SQLAlchemy 语句

    Returns:
        Result 对象
    """
    return await db.execute(stmt)


async def scalar_async(db: AsyncSession, stmt):
    """
    异步执行并返回单个标量值

    Args:
        db: AsyncSession 实例
        stmt: SQLAlchemy 语句

    Returns:
        标量值或 None
    """
    result = await db.execute(stmt)
    return result.scalar_one_or_none()


async def scalars_async(db: AsyncSession, stmt):
    """
    异步执行并返回所有标量值

    Args:
        db: AsyncSession 实例
        stmt: SQLAlchemy 语句

    Returns:
        标量列表
    """
    result = await db.execute(stmt)
    return result.scalars().all()


class AsyncDBTool:
    """
    异步数据库工具类

    封装常用的异步数据库操作
    """

    def __init__(self, db_factory=None):
        """
        初始化

        Args:
            db_factory: 异步会话工厂函数
        """
        self.db_factory = db_factory or AsyncSessionLocal

    async def get_session(self) -> AsyncSession:
        """获取数据库会话"""
        return self.db_factory()

    @contextlib.asynccontextmanager
    async def session(self) -> AsyncGenerator[AsyncSession, None]:
        """
        使用上下文管理器获取会话

        Usage:
            async with tool.session() as db:
                await db.execute(...)
        """
        async with self.db_factory() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise
            finally:
                await session.close()

    async def fetch_one(self, stmt):
        """
        查询单个结果

        Args:
            stmt: SQLAlchemy select 语句

        Returns:
            结果对象或 None
        """
        async with self.session() as db:
            result = await db.execute(stmt)
            return result.scalar_one_or_none()

    async def fetch_all(self, stmt):
        """
        查询所有结果

        Args:
            stmt: SQLAlchemy select 语句

        Returns:
            结果列表
        """
        async with self.session() as db:
            result = await db.execute(stmt)
            return result.scalars().all()

    async def insert(self, model, **kwargs):
        """
        插入新记录

        Args:
            model: SQLAlchemy 模型类
            **kwargs: 字段值

        Returns:
            新创建的实例
        """
        async with self.session() as db:
            obj = model(**kwargs)
            db.add(obj)
            await db.flush()
            await db.refresh(obj)
            return obj

    async def update(self, stmt):
        """
        执行更新语句

        Args:
            stmt: SQLAlchemy update 语句

        Returns:
            更新的记录数
        """
        async with self.session() as db:
            result = await db.execute(stmt)
            await db.flush()
            return result.rowcount

    async def delete(self, stmt):
        """
        执行删除语句

        Args:
            stmt: SQLAlchemy delete 语句

        Returns:
            删除的记录数
        """
        async with self.session() as db:
            result = await db.execute(stmt)
            await db.flush()
            return result.rowcount
