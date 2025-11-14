"""
业务异常定义
"""
from typing import Optional


class BaseServiceException(Exception):
    """服务层基础异常类"""
    
    def __init__(self, message: str, status_code: int = 500, detail: Optional[str] = None):
        self.message = message
        self.status_code = status_code
        self.detail = detail or message
        super().__init__(self.message)


class NotFoundError(BaseServiceException):
    """资源未找到异常"""
    
    def __init__(self, message: str = "资源未找到", detail: Optional[str] = None):
        super().__init__(message, status_code=404, detail=detail)


class ValidationError(BaseServiceException):
    """参数验证异常"""
    
    def __init__(self, message: str = "参数验证失败", detail: Optional[str] = None):
        super().__init__(message, status_code=400, detail=detail)


class PermissionError(BaseServiceException):
    """权限不足异常"""
    
    def __init__(self, message: str = "权限不足", detail: Optional[str] = None):
        super().__init__(message, status_code=403, detail=detail)


class FileSizeExceededError(BaseServiceException):
    """文件大小超限异常"""
    
    def __init__(self, message: str = "文件大小超过限制", detail: Optional[str] = None):
        super().__init__(message, status_code=413, detail=detail)


class FileEmptyError(BaseServiceException):
    """文件为空异常"""
    
    def __init__(self, message: str = "文件为空", detail: Optional[str] = None):
        super().__init__(message, status_code=400, detail=detail)


class DatabaseError(BaseServiceException):
    """数据库操作异常"""
    
    def __init__(self, message: str = "数据库操作失败", detail: Optional[str] = None):
        super().__init__(message, status_code=500, detail=detail)

