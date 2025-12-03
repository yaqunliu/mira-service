"""
Celery 应用配置
"""
from celery import Celery
from celery.schedules import crontab
from app.core.config import settings

# 创建 Celery 应用实例
# 使用 'app' 作为变量名，符合 Celery 约定，启动命令更简洁
app = Celery(
    "video_generator",
    broker=settings.REDIS_BROKER_URL,  # 使用数据库0存储任务队列
    backend=settings.REDIS_BACKEND_URL,  # 使用数据库1存储任务结果
    include=[
        "app.tasks.novel_tasks",
        "app.tasks.creation_task",
        "app.tasks.character_task",
        "app.tasks.shot_task",
        "app.tasks.full_generation_task",
        "app.tasks.points_task",
    ]
)

# Celery 配置
app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="Asia/Shanghai",
    enable_utc=True,
    task_track_started=True,
    task_time_limit=30 * 60,  # 30分钟超时
    task_soft_time_limit=25 * 60,  # 25分钟软超时
    worker_prefetch_multiplier=1,
    task_acks_late=True,
    # 解决 worker 启动后第一个任务失败的问题
    broker_connection_retry_on_startup=True,  # 启动时自动重试连接 broker
    broker_connection_retry=True,  # 启用连接重试
    broker_connection_max_retries=10,  # 最大重试次数
    broker_connection_retry_delay=1.0,  # 重试延迟（秒）
)

# 定时任务配置
app.conf.beat_schedule = {
    'expire-daily-points': {
        'task': 'expire_daily_points_task',
        'schedule': crontab(hour=0, minute=0),  # 每天 00:00 执行
    },
}

# 为了向后兼容，也导出 celery_app 别名
celery_app = app

