from fastapi import Request, HTTPException
from fastapi.responses import JSONResponse
from loguru import logger
import traceback
from app.core.exceptions import BaseServiceException


async def http_exception_handler(request: Request, exc: HTTPException):
    """HTTP异常处理器"""
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "error": True,
            "message": exc.detail,
            "status_code": exc.status_code,
        }
    )


async def service_exception_handler(request: Request, exc: BaseServiceException):
    """业务异常处理器（如果API层未捕获，由全局处理器处理）"""
    logger.warning(f"Service exception not caught in API layer: {exc.message}")
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "error": True,
            "message": exc.detail,
            "status_code": exc.status_code,
        }
    )


async def general_exception_handler(request: Request, exc: Exception):
    """通用异常处理器"""
    logger.error(f"Unhandled exception: {exc}")
    logger.error(traceback.format_exc())
    
    return JSONResponse(
        status_code=500,
        content={
            "error": True,
            "message": "Internal server error",
            "status_code": 500,
        }
    )
