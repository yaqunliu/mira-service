#!/bin/bash
# Celery Worker 启动脚本

# 切换到项目根目录
cd "$(dirname "$0")"

# 使用 uv run 启动 Celery Worker
# -A 指定 Celery 应用模块路径
#    app.core.celery_app.app 表示：
#    - app.core.celery_app = 模块路径（文件 app/core/celery_app.py）
#    - .app = 模块中的 Celery 应用实例变量名
# worker 启动 worker 进程
# -l INFO 设置日志级别为 INFO
uv run celery -A app.core.celery_app.app worker -l INFO

