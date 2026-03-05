# Video Generator API

AI视频生成后端服务，基于FastAPI构建，支持小说到视频的自动化生成。

## 功能特性

- 🔐 用户认证与授权
- 📚 小说上传与管理
- 🎬 视频创作项目管理
- 👤 角色设计与图片生成
- 🎭 场景与分镜管理
- 🎵 音频生成与合成
- 📁 资源文件管理
- ☁️ 云存储集成

## 技术栈

- **Web框架**: FastAPI
- **数据库**: PostgreSQL + SQLAlchemy
- **认证**: JWT + bcrypt
- **任务队列**: Celery + Redis
- **文件存储**: 本地存储 + 云存储
- **日志**: Loguru

## 项目结构

```
video-generator/
├── app/
│   ├── api/                    # API路由
│   │   └── api_v1/
│   │       ├── api.py         # 路由汇总
│   │       └── endpoints/      # 各模块端点
│   ├── core/                   # 核心配置
│   │   ├── config.py          # 应用配置
│   │   ├── security.py        # 安全相关
│   │   └── logger.py          # 日志配置
│   ├── db/                     # 数据库
│   │   └── base.py            # 数据库连接
│   ├── models/                 # 数据模型
│   ├── schemas/                # Pydantic模式
│   └── main.py                # 应用入口
├── alembic/                    # 数据库迁移
├── logs/                       # 日志文件
├── uploads/                    # 上传文件
└── pyproject.toml             # 项目配置
```

## 快速开始

### 1. 环境要求

- Python 3.10+
- PostgreSQL 12+
- Redis 6+

### 2. 安装依赖

使用uv管理依赖：

```bash
# 安装uv (如果还没安装)
pip install uv

# uv会自动管理虚拟环境和依赖，无需手动安装
# 直接使用 uv run 命令即可自动处理依赖
```

### 3. 环境配置

复制环境配置文件：

```bash
cp env.example .env
```

编辑`.env`文件，配置数据库连接等信息。

### 4. 数据库初始化

```bash
# 执行数据库迁移 (Alembic已配置好)
uv run alembic upgrade head

# 创建超级用户
uv run python scripts/create_superuser.py
```

### 5. 启动服务

```bash
# 开发模式 (推荐)
uv run uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

# 或使用项目启动脚本
uv run python run.py

# 生产模式
uv run uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 4
```

## API文档

启动服务后，访问以下地址查看API文档：

- Swagger UI: http://localhost:8100/docs
- ReDoc: http://localhost:8100/redoc

## 数据库设计

### 核心实体关系

```
User (用户)
├── Novel (小说)
│   └── Chapter (章节)
├── Creation (创作)
│   ├── Character (角色)
│   └── Scene (场景)
│       └── Shot (分镜)
└── Resource (资源)
```

### 主要数据表

- `users`: 用户信息
- `novels`: 小说信息
- `chapters`: 章节内容
- `creations`: 创作项目
- `characters`: 角色设计
- `scenes`: 场景设置
- `shots`: 分镜详情
- `resources`: 资源文件

## 开发指南

### 代码规范

项目使用以下工具保证代码质量：

- **Black**: 代码格式化
- **isort**: 导入排序
- **flake8**: 代码检查
- **mypy**: 类型检查

运行代码检查：

```bash
# 格式化代码
uv run black app/
uv run isort app/

# 代码检查
uv run flake8 app/
uv run mypy app/
```

### 测试

```bash
# 运行测试
uv run pytest

# 运行测试并生成覆盖率报告
uv run pytest --cov=app --cov-report=html
```

## 部署

### Docker部署

```bash
# 构建镜像
docker build -t video-generator .

# 运行容器
docker run -p 8000:8000 video-generator
```

### Docker Compose

```bash
# 启动所有服务
docker-compose up -d

# 查看日志
docker-compose logs -f
```

## 许可证

MIT License
