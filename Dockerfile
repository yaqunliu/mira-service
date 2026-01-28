FROM python:3.11-slim

# 设置工作目录
WORKDIR /app

ENV LANG=C.UTF-8
ENV LC_ALL=C.UTF-8
# 安装系统依赖 包括中文字体
RUN apt-get update && apt-get install -y \
    gcc \
    g++ \
    ffmpeg \
    fonts-wqy-zenhei \
    && rm -rf /var/lib/apt/lists/*

# 安装uv
RUN pip install uv

# 复制项目文件
COPY pyproject.toml ./
COPY app/ ./app/
COPY alembic/ ./alembic/
COPY alembic.ini ./
COPY README.md ./
COPY start_celery.sh ./
COPY stop_celery.sh ./

# 安装Python依赖
RUN uv pip install --system -e .
RUN uv pip install --system asyncpg>=0.29.0

# 创建必要的目录
RUN mkdir -p /app/uploads /app/logs /app/static/fonts

# 暴露端口
EXPOSE 8000

# 启动命令
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8100"]
