#!/bin/bash
# Celery Worker 启动脚本

# 切换到项目根目录
cd "$(dirname "$0")"

# 检查是否已有 worker 在运行
check_existing_workers() {
    local worker_count=$(ps aux | grep -E "celery.*worker.*app.core.celery_app.app" | grep -v grep | wc -l | tr -d ' ')
    if [ "$worker_count" -gt 0 ]; then
        echo "⚠️  警告: 检测到已有 $worker_count 个 Celery worker 进程在运行"
        echo "   这可能导致任务分发问题。"
        echo ""
        read -p "是否要停止所有现有 worker 并启动新的? (y/N): " -n 1 -r
        echo
        if [[ $REPLY =~ ^[Yy]$ ]]; then
            echo "正在停止所有现有的 Celery worker..."
            pkill -f "celery.*worker.*app.core.celery_app.app"
            sleep 2
            echo "已停止所有现有 worker"
        else
            echo "取消启动。如需停止现有 worker，请运行: pkill -f 'celery.*worker'"
            exit 1
        fi
    fi
}

# 信号处理函数：确保退出时正确关闭 worker
cleanup() {
    echo ""
    echo "正在停止 Celery worker..."
    # 发送 TERM 信号给当前进程组中的所有 celery worker
    pkill -TERM -P $$ -f "celery.*worker.*app.core.celery_app.app" 2>/dev/null
    wait
    echo "Celery worker 已停止"
    exit 0
}

# 注册信号处理
trap cleanup SIGINT SIGTERM

# 检查现有 worker
check_existing_workers

echo "=========================================="
echo "启动 Celery Worker"
echo "=========================================="
echo "按 Ctrl+C 停止 worker"
echo ""

# 使用 uv run 启动 Celery Worker
# -A 指定 Celery 应用模块路径
#    app.core.celery_app.app 表示：
#    - app.core.celery_app = 模块路径（文件 app/core/celery_app.py）
#    - .app = 模块中的 Celery 应用实例变量名
# worker 启动 worker 进程
# -l INFO 设置日志级别为 INFO
# --pool=solo 使用单进程模式（可选，如果需要多进程可以改为 prefork）
uv run celery -A app.core.celery_app.app worker -l INFO --pool=prefork --concurrency=4

# 如果 worker 正常退出，执行清理
cleanup

