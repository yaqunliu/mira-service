from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware

from app.api.api_v1.api import api_router
from app.core.config import settings
from app.core.logger import setup_logging
from app.middleware.error_handler import http_exception_handler, general_exception_handler

# 设置日志
setup_logging()

app = FastAPI(
    title=settings.APP_NAME,
    version=settings.APP_VERSION,
    description="AI视频生成后端服务API",
    openapi_url=f"{settings.API_V1_STR}/openapi.json",
)

# 添加异常处理器
app.add_exception_handler(HTTPException, http_exception_handler)
app.add_exception_handler(Exception, general_exception_handler)

# 设置CORS
if settings.BACKEND_CORS_ORIGINS:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[str(origin) for origin in settings.BACKEND_CORS_ORIGINS],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
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
