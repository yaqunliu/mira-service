FROM python:3.11-slim

# 设置工作目录
WORKDIR /app

# 安装系统依赖
RUN apt-get update && apt-get install -y \
    gcc \
    g++ \
    && rm -rf /var/lib/apt/lists/*

# 安装uv
RUN pip install uv

# 复制项目文件
COPY pyproject.toml ./
COPY app/ ./app/
COPY alembic/ ./alembic/
COPY alembic.ini ./
COPY README.md ./

# 安装Python依赖
RUN uv pip install --system -e .

# 创建必要的目录
RUN mkdir -p /app/uploads /app/logs

# 暴露端口
EXPOSE 8000

# 启动命令
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
