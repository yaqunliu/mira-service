# 异步架构迁移指南

## 概述

本文档描述了将 `mira-service` 从同步架构迁移到异步架构的变更。

## 迁移原因

1. **提高并发能力**：异步架构可以在单进程中处理更多并发请求
2. **避免线程阻塞**：长时间运行的 I/O 操作不会阻塞整个线程
3. **资源利用**：更好地利用 CPU 和网络资源

## 主要变更

### 1. 数据库层

#### 同步 → 异步

```python
# 之前（同步）
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(bind=engine)

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

# 之后（异步）
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker

ASYNC_DATABASE_URL = DATABASE_URL.replace(
    "postgresql://", "postgresql+asyncpg://"
)

async_engine = create_async_engine(ASYNC_DATABASE_URL)
AsyncSessionLocal = async_sessionmaker(
    bind=async_engine,
    class_=AsyncSession,
    autocommit=False,
    autoflush=False,
    expire_on_commit=False
)

async def get_async_db():
    async with AsyncSessionLocal() as session:
        try:
            yield session
        finally:
            await session.close()
```

### 2. 工具类

#### 同步 Session → 异步工厂

```python
# 之前
class BaseTool:
    def __init__(self, db: Session):
        self.db = db

class ReadCharacterTool(BaseTool):
    async def execute(self, state, character_id=None):
        result = await self.db.execute(select(Character)...)
        return result.scalar_one_or_none()

# 之后
class BaseTool:
    def __init__(self, db_factory=None):
        self.db_factory = db_factory

class ReadCharacterTool(BaseTool):
    async def execute(self, state, character_id=None):
        async with AsyncSessionLocal() as db:
            result = await db.execute(select(Character)...)
            return result.scalar_one_or_none()
```

### 3. 文件 I/O

#### 同步 → 异步

```python
# 之前
def read_file(path):
    with open(path, 'r') as f:
        return f.read()

# 之后
import aiofiles

async def read_file(path):
    async with aiofiles.open(path, 'r') as f:
        return await f.read()
```

### 4. 外部 API 调用

#### requests → httpx

```python
# 之前
import requests

def call_api(url, data):
    response = requests.post(url, json=data)
    return response.json()

# 之后
import httpx

async def call_api(url, data):
    async with httpx.AsyncClient() as client:
        response = await client.post(url, json=data)
        return response.json()
```

## 文件变更清单

| 文件 | 变更 |
|------|------|
| `app/db/base.py` | 添加异步引擎和 AsyncSessionLocal |
| `app/db/session.py` | 添加 get_async_db 和 get_sync_db |
| `app/agent/tools/base.py` | 改为使用 db_factory |
| `app/agent/tools/asset_tools.py` | 使用 AsyncSessionLocal |
| `app/agent/tools/async_db.py` | 新增异步数据库工具类 |
| `app/utils/async_file.py` | 新增异步文件操作工具 |
| `app/api/v1/endpoints/agent.py` | 修复 SSE 流中的数据库会话管理 |

## 性能对比

### 同步架构

```
请求处理流程：
┌──────────────────────────────────────────────────────────┐
│ Request → Thread Pool (占用1线程)                        │
│            ↓                                             │
│         DB Query (阻塞线程)                              │
│            ↓                                             │
│        API Call (阻塞线程)                               │
│            ↓                                             │
│         Response                                         │
└──────────────────────────────────────────────────────────┘

限制：线程池大小 = 100（每进程）
      最大并发 = 100 请求/进程
```

### 异步架构

```
请求处理流程：
┌──────────────────────────────────────────────────────────┐
│ Request → Event Loop (单线程)                            │
│            ↓                                             │
│      DB Query (await → 释放线程)                         │
│            ↓                                             │
│     API Call (await → 释放线程)                          │
│            ↓                                             │
│         Response                                         │
└──────────────────────────────────────────────────────────┘

优势：可处理 1000+ 并发请求
```

## 最佳实践

### 1. 保持向后兼容

```python
# 在迁移期间，同时提供同步和异步接口
def get_db():
    """同步接口（向后兼容）"""
    db = SyncSessionLocal()
    try:
        yield db
    finally:
        db.close()

async def get_async_db():
    """异步接口（新代码使用）"""
    async with AsyncSessionLocal() as session:
        yield session
```

### 2. CPU 密集型操作

```python
from concurrent.futures import ThreadPoolExecutor

# 对于 CPU 密集型操作，使用线程池
async def run_inference():
    loop = asyncio.get_event_loop()
    with ThreadPoolExecutor() as pool:
        result = await loop.run_in_executor(pool, heavy_computation)
    return result
```

### 3. 连接池配置

```python
# 异步引擎连接池配置
async_engine = create_async_engine(
    ASYNC_DATABASE_URL,
    pool_size=20,          # 池大小
    max_overflow=40,       # 最大溢出
    pool_timeout=30,       # 超时时间
    pool_pre_ping=True     # 预连接检查
)
```

## 验证方法

```bash
# 1. 运行语法检查
python -m py_compile app/**/*.py

# 2. 运行异步测试
pytest tests/ -v -k async

# 3. 压力测试
locust -f tests/locustfile.py --host=http://localhost:8000
```

## 常见问题

### Q1: 异步函数中调用同步函数会怎样？

A: 会阻塞 Event Loop。应使用 `asyncio.to_thread()` 或 `run_in_executor()`。

```python
import asyncio
from PIL import Image

# ❌ 错误
def process_image(path):
    img = Image.open(path)
    return img.size

# ✅ 正确
async def process_image(path):
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, Image.open, path)
```

### Q2: 如何调试异步代码？

A: 使用 `asyncio.run()` 并开启调试模式：

```python
asyncio.run(main(), debug=True)
```

或在代码中添加日志：

```python
logger.info("异步操作开始")
await some_async_operation()
logger.info("异步操作完成")
```

## 下一步

1. 将其他 API 端点迁移到异步
2. 将 Service 层迁移到异步
3. 替换所有 `requests` 调用为 `httpx`
4. 添加更多异步单元测试
5. 性能基准测试
