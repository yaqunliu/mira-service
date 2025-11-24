#!/bin/bash
# 查看 Celery Worker 状态脚本

echo "=========================================="
echo "Celery Worker 状态检查"
echo "=========================================="
echo ""

echo "【方法1】查看所有 Celery 进程数量："
WORKER_COUNT=$(ps aux | grep -E "celery.*worker" | grep -v grep | wc -l | tr -d ' ')
echo "  发现 $WORKER_COUNT 个 Celery worker 相关进程"
echo ""

echo "【方法2】查看 Celery 在线节点："
cd "$(dirname "$0")"
uv run celery -A app.core.celery_app.app inspect ping 2>&1 | grep -E "^->" | wc -l | xargs -I {} echo "  在线节点数: {}"
echo ""

echo "【方法3】查看详细的 worker 统计信息："
uv run celery -A app.core.celery_app.app inspect stats 2>&1 | grep -E '"hostname"|"pid"|"pool"' | head -10
echo ""

echo "【方法4】查看所有 Celery 进程详情："
ps aux | grep -E "celery.*worker" | grep -v grep | awk '{printf "  PID: %-8s 启动时间: %s %s\n", $2, $9, $10}' | head -10
echo ""

echo "=========================================="
echo "提示：如果发现多个 worker，建议停止所有后只启动一个"
echo "停止命令: pkill -f 'celery.*worker'"
echo "启动命令: ./start_celery.sh"
echo "=========================================="

