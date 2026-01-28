import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import sessionmaker
from app.main import app
from app.db.base import Base
from app.api.deps import get_async_db

SQLALCHEMY_DATABASE_URL = "sqlite+aiosqlite:///:memory:"

engine = create_async_engine(
    SQLALCHEMY_DATABASE_URL, echo=False
)
TestingAsyncSessionLocal = async_sessionmaker(
    engine, 
    class_=AsyncSession, 
    expire_on_commit=False,
    autocommit=False,
    autoflush=False
)

async def override_get_async_db():
    async with TestingAsyncSessionLocal() as db:
        try:
            yield db
        finally:
            await db.close()

@pytest.fixture(scope="function")
async def client():
    from app.models import user, novel, chapter, creation, character, scene, shot, asset
    
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    
    app.dependency_overrides[get_async_db] = override_get_async_db
    
    from httpx import AsyncClient, ASGITransport
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
    
    app.dependency_overrides.clear()
    
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
