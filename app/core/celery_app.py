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
        "app.tasks.step4_scene_image_gen_task",
        "app.tasks.step7_video_prompt_gen_task",
        "app.tasks.step8_video_gen_task",
        "app.tasks.full_generation_task",
        "app.tasks.points_task",
        "app.tasks.subscription_task",
        "app.tasks.order_poll_task",
        "app.tasks.subscription_poll_task",
        "app.tasks.subscription_sync_task",
        "app.tasks.subscription_expire_task",
        "app.tasks.video_export",
        # Agent 专用 Tasks
        "app.agent.tasks.image_tasks",
        "app.agent.tasks.video_tasks",
        "app.agent.tasks.audio_tasks",
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
    # Beat 调度器配置
    # 默认使用 PersistentScheduler，调度状态存储在 celerybeat-schedule 文件中
    # 如果需要使用 Redis 存储，可以安装 redbeat 并使用: beat_scheduler="redbeat.RedBeatScheduler"
)

# 定时任务配置
app.conf.beat_schedule = {
    'expire-daily-points': {
        'task': 'expire_daily_points_task',
        'schedule': crontab(hour=0, minute=0),  # 每天 00:00 执行
    },
    'issue-subscription-points-monthly': {
        'task': 'issue_subscription_points_monthly',
        'schedule': crontab(day_of_month=1, hour=0, minute=10),  # 每月1号 00:10 发放月度积分
    },
    'poll-pending-orders': {
        'task': 'poll_pending_orders',
        'schedule': crontab(minute='*/3'),  # 每3分钟兜底查询一次未支付订单
    },
    'poll-subscriptions-billing': {
        'task': 'poll_subscriptions_billing',
        'schedule': crontab(day_of_month=1, hour=0, minute=5),  # 每月1号 00:05 查询Creem订阅续费状态并发放积分
    },
    'sync-subscriptions-daily': {
        'task': 'sync_subscriptions',
        'schedule': crontab(hour=2, minute=0),  # 每天 02:00 执行
    },
    'check-expired-subscriptions': {
        'task': 'check_expired_subscriptions',
        'schedule': crontab(hour=1, minute=0),  # 每天 01:00 执行，检查并标记过期的订阅
    },
}

# 为了向后兼容，也导出 celery_app 别名
celery_app = app

