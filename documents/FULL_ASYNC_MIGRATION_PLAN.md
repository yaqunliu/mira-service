# 完整异步架构迁移计划

## 📋 项目分析结果

### 同步代码分布统计

| 类别 | 文件数量 | 优先级 | 风险 |
|------|----------|--------|------|
| API 端点 | 15+ | 高 | 高并发时阻塞 |
| Service 层 | 20+ | 高 | 业务逻辑阻塞 |
| Task 任务 | 10+ | 中 | Celery worker 可保持同步 |
| 工具类 | 5+ | 中 | 辅助功能 |

### 需要迁移的文件清单

#### 1. 数据库层 (已部分完成 ✅)
- [x] `app/db/base.py` - 添加异步引擎
- [x] `app/db/session.py` - 添加异步会话
- [ ] `app/db/base.py` - 移除同步引擎

#### 2. API 依赖层
- [ ] `app/api/deps.py` - 迁移 `get_db()` → `get_async_db()`

#### 3. API 端点 (15+ 文件)
- [ ] `app/api/api_v1/end- [ ] `app/api/api_v1/endpoints/points/auth.py`
creations.py`
- [ ] `app/api/api_v1/endpoints/characters.py`
- [ ] `app/api/api_v1/endpoints/scenes.py`
- [ ] `app/api/api_v1/endpoints/scripts.py`
- [ ] `app/api/api_v1/endpoints/shots.py`
- [ ] `app/api/api_v1/endpoints/assets.py`
- [ ] `app/api/api_v1/endpoints/users.py`
- [ ] `app/api/api_v1/endpoints/tasks.py`
- [ ] `app/api/api_v1/endpoints/points.py`
- [ ] `app/api/api_v1/endpoints/subscriptions.py`
- [ ] `app/api/api_v1/endpoints/products.py`
- [ ] `app/api/api_v1/endpoints/orders.py`
- [ ] `app/api/api_v1/endpoints/video_generation.py`
- [ ] `app/api/api_v1/endpoints/novels.py`
- [ ] `app/api/api_v1/endpoints/webhooks.py`

#### 4. Service 层
- [ ] `app/services/subscription_service.py`
- [ ] `app/services/creem_payment_service.py`
- [ ] `app/services/user_sync_service.py`
- [ ] `app/services/supabase_service.py`
- [ ] 其他 services...

#### 5. Task 任务 (可保持同步)
> **注意**: Celery Worker 可以继续使用同步代码，因为它们运行在独立的进程池中
- [ ] `app/tasks/character_task.py` (保持同步)
- [ ] `app/tasks/creation_task.py` (保持同步)
- [ ] 其他 tasks... (保持同步)

#### 6. 外部 API 调用
- [ ] 将 `requests` 替换为 `httpx`
- [ ] 更新所有 HTTP 调用

---

## 🚀 迁移步骤

### 阶段 1: 基础设施 (已完成 ✅)
1. [x] 添加 asyncpg 驱动
2. [x] 创建异步引擎配置
3. [x] 创建 AsyncSessionLocal
4. [x] 创建异步文件工具
5. [x] 创建异步安全检测工具

### 阶段 2: 核心 API 层
1. [ ] 迁移 `app/api/deps.py`
2. [ ] 迁移认证端点 `auth.py`
3. [ ] 迁移创作管理 `creations.py`
4. [ ] 迁移资源管理 (characters, scenes, shots, assets)
5. [ ] 迁移用户管理 (users, points, subscriptions)

### 阶段 3: Service 层
1. [ ] 迁移订阅服务
2. [ ] 迁移支付服务
3. [ ] 迁移用户服务

### 阶段 4: 外部集成
1. [ ] 将 requests 替换为 httpx
2. [ ] 迁移 Supabase 客户端
3. [ ] 迁移其他外部服务

---

## 📝 迁移规范

### 同步 → 异步 转换规则

#### 1. 导入语句
```python
# ❌ 之前
from sqlalchemy.orm import Session

# ✅ 之后
from sqlalchemy.ext.asyncio import AsyncSession
```

#### 2. 依赖注入
```python
# ❌ 之前
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

# ✅ 之后
async def get_async_db():
    async with AsyncSessionLocal() as session:
        yield session
```

#### 3. 查询语句
```python
# ❌ 之前
user = db.query(User).filter(User.id == user_id).first()

# ✅ 之后
from sqlalchemy import select
user = await db.execute(select(User).where(User.id == user_id))
user = user.scalar_one_or_none()
```

#### 4. 外部 HTTP 调用
```python
# ❌ 之前
import requests
response = requests.get(url)

# ✅ 之后
import httpx
async with httpx.AsyncClient() as client:
    response = await client.get(url)
```

#### 5. 文件 I/O
```python
# ❌ 之前
with open(path, 'r') as f:
    content = f.read()

# ✅ 之后
import aiofiles
async with aiofiles.open(path, 'r') as f:
    content = await f.read()
```

---

## ⚠️ 注意事项

### 1. Celery Tasks
Celery Worker 运行在独立进程中，可以使用同步代码：
```python
# tasks.py - 可以保持同步
@celery_app.task
def sync_task():
    db = SessionLocal()
    # 同步操作
```

### 2. 向后兼容
迁移期间可以同时保留同步和异步版本：
```python
# deps.py
def get_db():  # 同步（向后兼容）
    ...

async def get_async_db():  # 异步（新代码使用）
    ...
```

### 3. 第三方库
检查第三方库是否支持异步：
- ✅ `httpx` - 支持异步
- ✅ `aiofiles` - 异步文件操作
- ✅ `asyncpg` - 异步 PostgreSQL
- ⚠️ `boto3` - 需要使用 `aiobotocore`

---

## ✅ 验证清单

迁移完成后，验证以下项目：

- [ ] 所有 API 端点使用 `AsyncSession`
- [ ] 所有查询使用 `await db.execute()`
- [ ] 所有外部调用使用 `httpx` + `await`
- [ ] 所有文件操作使用 `aiofiles` + `await`
- [ ] 单元测试通过
- [ ] 集成测试通过
- [ ] 压力测试通过

---

## 📊 预期效果

| 指标 | 迁移前 | 迁移后 | 提升 |
|------|--------|--------|------|
| 最大并发连接 | ~100 | ~1000+ | 10x |
| 请求延迟 (I/O 等待) | 阻塞 | 非阻塞 | 显著降低 |
| 内存占用 | 高 (线程栈) | 低 (Event Loop) | ~50% |
| 吞吐量 | 受限于线程池 | 受限于 CPU | 2-5x |

---

## 🏃 开始迁移

```bash
# 1. 安装依赖
pip install asyncpg aiofiles httpx

# 2. 语法检查
python -m py_compile app/**/*.py

# 3. 运行测试
pytest tests/ -v

# 4. 压力测试
locust -f tests/locustfile.py
```
