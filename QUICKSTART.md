# 快速启动指南

## 1. 环境准备

### 安装依赖
```bash
# 安装uv (如果还没安装)
pip install uv

# uv会自动管理虚拟环境和依赖
# 无需手动创建虚拟环境或激活，直接使用 uv run 即可
# uv run 会自动：
# - 创建虚拟环境（如果不存在）
# - 安装项目依赖
# - 在正确的环境中运行命令
```

### 数据库设置
```bash
# 1. 安装PostgreSQL (如果还没安装)
# macOS: brew install postgresql
# Ubuntu: sudo apt-get install postgresql postgresql-contrib

# 2. 创建数据库
createdb video_generator

# 3. 配置环境变量
cp env.example .env
# 编辑 .env 文件，设置数据库连接信息
```

## 2. 数据库初始化

```bash
# 执行数据库迁移
uv run alembic upgrade head

# 创建超级用户
uv run python scripts/create_superuser.py
```

## 3. 启动服务

### 启动 FastAPI 服务

#### 开发模式
```bash
# 方式1: 使用启动脚本 (推荐)
uv run python run.py

# 方式2: 直接使用uvicorn
uv run uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

#### 生产模式
```bash
uv run uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 4
```

### 启动 Celery Worker

**重要**: Celery Worker 需要在项目根目录下启动，用于处理异步任务（如小说上传处理）。

```bash
# 方式1: 使用启动脚本 (推荐)
./start_celery.sh

# 方式2: 手动启动（必须在项目根目录）
cd /path/to/video-generator
uv run celery -A app.core.celery_app.app worker -l INFO

# 方式3: 后台运行
uv run celery -A app.core.celery_app.app worker -l INFO --detach
```

**注意**:
- 必须在项目根目录运行，不能在其他目录
- 确保 Redis 服务已启动
- 确保 `.env` 文件配置正确

### Docker方式
```bash
# 构建并启动所有服务
docker-compose up -d

# 查看日志
docker-compose logs -f api
```

## 4. 验证安装

访问以下地址验证服务是否正常运行：

- 应用首页: http://localhost:8100/
- API文档: http://localhost:8100/docs
- 健康检查: http://localhost:8100/health

## 5. API使用示例

### 用户注册
```bash
curl -X POST "http://localhost:8100/api/v1/auth/register" \
  -H "Content-Type: application/json" \
  -d '{
    "username": "testuser",
    "email": "test@example.com",
    "password": "password123"
  }'
```

### 用户登录
```bash
curl -X POST "http://localhost:8100/api/v1/auth/login" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "username=testuser&password=password123"
```

### 上传小说
```bash
curl -X POST "http://localhost:8100/api/v1/novels/upload" \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -F "file=@your_novel.txt"
```

## 6. 开发工具

### 运行测试
```bash
uv run pytest
```

### 代码格式化
```bash
uv run black app/
uv run isort app/
```

### 类型检查
```bash
uv run mypy app/
```

## 7. 常见问题

### 数据库连接错误
- 检查PostgreSQL服务是否启动
- 确认.env文件中的数据库配置正确
- 确保数据库已创建

### 端口占用
- 修改.env文件中的端口配置
- 或者使用 `--port` 参数指定其他端口

### 依赖安装失败
- 确保Python版本 >= 3.10
- 使用 `uv run` 命令自动管理虚拟环境
- 检查网络连接

### 命令找不到错误
- 使用 `uv run` 前缀运行所有项目命令
- 例如：`uv run uvicorn app.main:app --reload` 而不是 `uvicorn app.main:app --reload`
- uv 会自动在正确的虚拟环境中运行命令

## 8. 下一步

- 查看完整的API文档: http://localhost:8100/docs
- 阅读项目README了解更多功能
- 根据业务需求实现具体的API逻辑
