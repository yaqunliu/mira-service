"""
统一API响应格式工具

所有API接口应使用此工具返回统一格式的响应：
{
    "data": ...,      # 业务数据（必需）
    "message": ...,   # 返回信息（可选）
    "code": ...       # 状态码（可选）
}
"""
from typing import Any, Optional, Dict


def success_response(
    data: Any,
    message: Optional[str] = None,
    code: Optional[int] = None
) -> Dict[str, Any]:
    """
    成功响应格式
    
    Args:
        data: 业务数据
        message: 返回信息（可选）
        code: 状态码（可选，默认200）
        
    Returns:
        统一格式的响应字典
    """
    response: Dict[str, Any] = {
        "data": data
    }
    
    if message is not None:
        response["message"] = message
    
    if code is not None:
        response["code"] = code
    
    return response


def error_response(
    message: str,
    code: Optional[int] = None,
    data: Optional[Any] = None
) -> Dict[str, Any]:
    """
    错误响应格式
    
    Args:
        message: 错误信息
        code: 错误码（可选）
        data: 错误相关数据（可选）
        
    Returns:
        统一格式的错误响应字典
    """
    response: Dict[str, Any] = {
        "data": data if data is not None else None,
        "message": message
    }
    
    if code is not None:
        response["code"] = code
    
    return response
