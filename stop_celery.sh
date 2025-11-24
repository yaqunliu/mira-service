#!/bin/bash
# Celery Worker 停止脚本

echo "正在停止所有 Celery worker..."

# 查找所有运行中的 Celery worker 进程
WORKER_PIDS=$(ps aux | grep -E "celery.*worker.*app.core.celery_app.app" | grep -v grep | awk '{print $2}')

if [ -z "$WORKER_PIDS" ]; then
    echo "✓ 没有发现运行中的 Celery worker"
    exit 0
fi

# 统计数量
WORKER_COUNT=$(echo "$WORKER_PIDS" | wc -l | tr -d ' ')
echo "发现 $WORKER_COUNT 个 Celery worker 进程"

# 停止所有 worker
for pid in $WORKER_PIDS; do
    echo "  停止进程 PID: $pid"
    kill -TERM "$pid" 2>/dev/null
done

# 等待进程退出
sleep 2

# 检查是否还有进程在运行
REMAINING=$(ps aux | grep -E "celery.*worker.*app.core.celery_app.app" | grep -v grep | wc -l | tr -d ' ')

if [ "$REMAINING" -gt 0 ]; then
    echo "⚠️  仍有 $REMAINING 个进程未停止，强制终止..."
    pkill -9 -f "celery.*worker.*app.core.celery_app.app"
    sleep 1
fi

# 最终检查
FINAL_COUNT=$(ps aux | grep -E "celery.*worker.*app.core.celery_app.app" | grep -v grep | wc -l | tr -d ' ')

if [ "$FINAL_COUNT" -eq 0 ]; then
    echo "✓ 所有 Celery worker 已停止"
else
    echo "⚠️  仍有 $FINAL_COUNT 个进程在运行，请手动检查"
fi

