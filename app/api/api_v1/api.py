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

