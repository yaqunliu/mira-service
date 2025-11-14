from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware

from app.api.api_v1.api import api_router
from app.core.config import settings
from app.core.logger import setup_logging
from app.middleware.error_handler import (
    http_exception_handler,
    service_exception_handler,
    general_exception_handler
)
from app.core.exceptions import BaseServiceException

# 设置日志
setup_logging()

app = FastAPI(
    title=settings.APP_NAME,
    version=settings.APP_VERSION,
    description="AI视频生成后端服务API",
    openapi_url=f"{settings.API_V1_STR}/openapi.json",
)

# 添加异常处理器
# 注意：异常处理器的顺序很重要，更具体的异常应该先注册
app.add_exception_handler(HTTPException, http_exception_handler)
app.add_exception_handler(BaseServiceException, service_exception_handler)
app.add_exception_handler(Exception, general_exception_handler)

# 设置CORS
if settings.BACKEND_CORS_ORIGINS:
    # 如果配置了允许的源，使用配置的源
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[str(origin) for origin in settings.BACKEND_CORS_ORIGINS],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
elif settings.DEBUG:
    # 开发环境（DEBUG=True）且未配置CORS源时，允许所有源
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],  # 允许所有源
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
else:
    # 生产环境（DEBUG=False）且未配置CORS源时，不允许任何源（安全默认值）
    # 或者可以抛出警告，提示需要配置CORS
    import warnings
    warnings.warn(
        "生产环境未配置 BACKEND_CORS_ORIGINS，CORS 中间件未启用。"
        "如需允许跨域请求，请在配置中设置 BACKEND_CORS_ORIGINS。",
        UserWarning
    )

# 添加受信任主机中间件
app.add_middleware(TrustedHostMiddleware, allowed_hosts=settings.ALLOWED_HOSTS)

# 包含API路由
app.include_router(api_router, prefix=settings.API_V1_STR)


@app.get("/")
async def root():
    return {"message": "Video Generator API", "version": settings.APP_VERSION}


@app.get("/health")
async def health_check():
    return {"status": "healthy"}
