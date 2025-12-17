#!/bin/bash
# Celery Beat 启动脚本（定时任务调度器）

# 切换到项目根目录
cd "$(dirname "$0")"

# 检查是否已有 beat 在运行
check_existing_beat() {
    local beat_count=$(ps aux | grep -E "celery.*beat.*app.core.celery_app.app" | grep -v grep | wc -l | tr -d ' ')
    if [ "$beat_count" -gt 0 ]; then
        echo "⚠️  警告: 检测到已有 $beat_count 个 Celery beat 进程在运行"
        echo "   这可能导致任务重复调度。"
        echo ""
        read -p "是否要停止所有现有 beat 并启动新的? (y/N): " -n 1 -r
        echo
        if [[ $REPLY =~ ^[Yy]$ ]]; then
            echo "正在停止所有现有的 Celery beat..."
            pkill -f "celery.*beat.*app.core.celery_app.app"
            sleep 2
            echo "已停止所有现有 beat"
        else
            echo "取消启动。如需停止现有 beat，请运行: pkill -f 'celery.*beat'"
            exit 1
        fi
    fi
}

# 信号处理函数：确保退出时正确关闭 beat
cleanup() {
    echo ""
    echo "正在停止 Celery beat..."
    pkill -TERM -P $$ -f "celery.*beat.*app.core.celery_app.app" 2>/dev/null
    wait
    echo "Celery beat 已停止"
    exit 0
}

# 注册信号处理
trap cleanup SIGINT SIGTERM

# 检查现有 beat（非交互模式下跳过）
if [ -t 0 ]; then
    check_existing_beat
fi

echo "=========================================="
echo "启动 Celery Beat (定时任务调度器)"
echo "=========================================="
echo "按 Ctrl+C 停止 beat"
echo ""

# 使用 uv run 启动 Celery Beat
# -A 指定 Celery 应用模块路径
#    app.core.celery_app.app 表示：
#    - app.core.celery_app = 模块路径（文件 app/core/celery_app.py）
#    - .app = 模块中的 Celery 应用实例变量名
# beat 启动 beat 进程（定时任务调度器）
# -l INFO 设置日志级别为 INFO
# --pidfile 指定 PID 文件路径（可选，用于进程管理）
uv run celery -A app.core.celery_app.app beat -l INFO

# 如果 beat 正常退出，执行清理
cleanup

