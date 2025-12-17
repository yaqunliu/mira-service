from fastapi import APIRouter
from app.api.api_v1.endpoints import (
    auth,
    users,
    novels,
    creations,
    characters,
    scenes,
    shots,
    tasks,
    voices,
    points,
    model_configs,
    products,
    orders,
    subscriptions,
    webhooks,
)

api_router = APIRouter()

# 认证相关路由
api_router.include_router(auth.router, prefix="/auth", tags=["认证"])

# 用户管理路由
api_router.include_router(users.router, prefix="/users", tags=["用户管理"])

# 小说管理路由
api_router.include_router(novels.router, prefix="/novels", tags=["小说管理"])

# 创作管理路由
api_router.include_router(creations.router, prefix="/creations", tags=["创作管理"])

# 角色管理路由
api_router.include_router(characters.router, prefix="/characters", tags=["角色管理"])

# 场景管理路由
api_router.include_router(scenes.router, prefix="/scenes", tags=["场景管理"])

# 分镜管理路由
api_router.include_router(shots.router, prefix="/shots", tags=["分镜管理"])

# 任务状态查询路由
api_router.include_router(tasks.router, prefix="/tasks", tags=["任务管理"])

# 语音管理路由
api_router.include_router(voices.router, prefix="/voices", tags=["语音管理"])

# 积分管理路由
api_router.include_router(points.router, prefix="/points", tags=["积分管理"])

# 模型配置路由
api_router.include_router(model_configs.router, prefix="/model-configs", tags=["模型配置"])

# 产品 / 订单 / 订阅 / Webhook
api_router.include_router(products.router, prefix="/products", tags=["产品"])
api_router.include_router(orders.router, prefix="/orders", tags=["订单"])
api_router.include_router(subscriptions.router, prefix="/subscriptions", tags=["订阅"])
api_router.include_router(webhooks.router, prefix="/webhooks", tags=["Webhooks"])

