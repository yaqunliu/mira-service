"""
超时与重试机制

为 LLM 调用和 Tool 执行提供自动重试功能
"""

import asyncio
from typing import Callable, Any, Optional, Dict, TypeVar
from functools import wraps

from app.core.logger import logger


# 默认超时配置（秒）
TIMEOUT_CONFIG = {
    "llm": 60,           # LLM 调用超时
    "db_tool": 10,       # 数据库 Tool 超时
    "generation_tool": 300,  # 生成类 Tool 超时（视频生成较长）
    "analysis_tool": 120,    # 分析类 Tool 超时
    "knowledge_tool": 30,    # 知识库 Tool 超时
}

# 默认重试配置
RETRY_CONFIG = {
    "max_attempts": 3,
    "base_delay": 1.0,    # 基础延迟（秒）
    "max_delay": 30.0,    # 最大延迟（秒）
    "exponential_base": 2,  # 指数退避基数
}


T = TypeVar("T")


class RetryError(Exception):
    """重试失败异常"""
    def __init__(self, message: str, attempts: int, last_error: Exception):
        self.message = message
        self.attempts = attempts
        self.last_error = last_error
        super().__init__(message)


async def call_llm_with_retry(
    llm_func: Callable,
    *args,
    max_attempts: int = RETRY_CONFIG["max_attempts"],
    timeout: float = TIMEOUT_CONFIG["llm"],
    **kwargs,
) -> Any:
    """
    带重试的 LLM 调用
    
    Args:
        llm_func: LLM 调用函数（async）
        *args: 位置参数
        max_attempts: 最大重试次数
        timeout: 超时时间（秒）
        **kwargs: 关键字参数
        
    Returns:
        LLM 调用结果
        
    Raises:
        RetryError: 所有重试均失败
    """
    last_error = None
    
    for attempt in range(1, max_attempts + 1):
        try:
            logger.debug(f"[Retry] LLM 调用尝试 {attempt}/{max_attempts}")
            
            # 带超时的调用
            result = await asyncio.wait_for(
                llm_func(*args, **kwargs),
                timeout=timeout,
            )
            
            return result
            
        except asyncio.TimeoutError as e:
            last_error = e
            logger.warning(f"[Retry] LLM 调用超时 (attempt {attempt})")
            
        except Exception as e:
            last_error = e
            logger.warning(f"[Retry] LLM 调用失败 (attempt {attempt}): {e}")
        
        # 计算延迟
        if attempt < max_attempts:
            delay = _calculate_delay(attempt)
            logger.debug(f"[Retry] 等待 {delay:.1f}s 后重试...")
            await asyncio.sleep(delay)
    
    raise RetryError(
        f"LLM 调用失败，已重试 {max_attempts} 次",
        attempts=max_attempts,
        last_error=last_error,
    )


async def execute_tool_with_retry(
    tool_func: Callable,
    tool_type: str = "db_tool",
    *args,
    max_attempts: int = RETRY_CONFIG["max_attempts"],
    timeout: Optional[float] = None,
    **kwargs,
) -> Any:
    """
    带重试的 Tool 执行
    
    Args:
        tool_func: Tool 函数（async）
        tool_type: Tool 类型（用于确定超时时间）
        *args: 位置参数
        max_attempts: 最大重试次数
        timeout: 超时时间（秒），None 则使用默认配置
        **kwargs: 关键字参数
        
    Returns:
        Tool 执行结果
        
    Raises:
        RetryError: 所有重试均失败
    """
    if timeout is None:
        timeout = TIMEOUT_CONFIG.get(tool_type, TIMEOUT_CONFIG["db_tool"])
    
    last_error = None
    
    for attempt in range(1, max_attempts + 1):
        try:
            logger.debug(f"[Retry] Tool 执行尝试 {attempt}/{max_attempts}, type={tool_type}")
            
            result = await asyncio.wait_for(
                tool_func(*args, **kwargs),
                timeout=timeout,
            )
            
            # 检查结果是否为失败状态
            if isinstance(result, dict) and result.get("status") == "failed":
                if result.get("recoverable", True):
                    raise Exception(result.get("error", "Tool 执行失败"))
            
            return result
            
        except asyncio.TimeoutError as e:
            last_error = e
            logger.warning(f"[Retry] Tool 执行超时 (attempt {attempt})")
            
        except Exception as e:
            last_error = e
            logger.warning(f"[Retry] Tool 执行失败 (attempt {attempt}): {e}")
        
        if attempt < max_attempts:
            delay = _calculate_delay(attempt)
            await asyncio.sleep(delay)
    
    raise RetryError(
        f"Tool 执行失败，已重试 {max_attempts} 次",
        attempts=max_attempts,
        last_error=last_error,
    )


def _calculate_delay(attempt: int) -> float:
    """计算指数退避延迟"""
    delay = RETRY_CONFIG["base_delay"] * (RETRY_CONFIG["exponential_base"] ** (attempt - 1))
    return min(delay, RETRY_CONFIG["max_delay"])


def with_retry(
    max_attempts: int = RETRY_CONFIG["max_attempts"],
    timeout: Optional[float] = None,
    tool_type: str = "db_tool",
):
    """
    重试装饰器
    
    Usage:
        @with_retry(max_attempts=3, timeout=30)
        async def my_tool_func():
            ...
    """
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        async def wrapper(*args, **kwargs):
            return await execute_tool_with_retry(
                func,
                tool_type=tool_type,
                *args,
                max_attempts=max_attempts,
                timeout=timeout,
                **kwargs,
            )
        return wrapper
    return decorator


class TimeoutManager:
    """超时管理器"""
    
    def __init__(self, custom_config: Optional[Dict[str, float]] = None):
        self.config = {**TIMEOUT_CONFIG, **(custom_config or {})}
    
    def get_timeout(self, operation_type: str) -> float:
        """获取指定操作类型的超时时间"""
        return self.config.get(operation_type, self.config.get("db_tool", 10))
    
    def update_timeout(self, operation_type: str, timeout: float):
        """更新超时配置"""
        self.config[operation_type] = timeout


# 全局超时管理器实例
timeout_manager = TimeoutManager()
