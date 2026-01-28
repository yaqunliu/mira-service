"""
错误处理与恢复 - Error Handling and Recovery

提供工作流错误处理和自动恢复功能
"""

from typing import Dict, Any, List, Optional, Callable
from app.agent.state.schemas import ComicDramaState
from app.core.logger import logger
from app.core.config import settings
from enum import Enum
import asyncio
import json


class ErrorCategory(Enum):
    """错误类别"""
    NETWORK = "network"
    API_LIMIT = "api_limit"
    VALIDATION = "validation"
    GENERATION = "generation"
    DATABASE = "database"
    TIMEOUT = "timeout"
    UNKNOWN = "unknown"


class ErrorSeverity(Enum):
    """错误严重程度"""
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class ErrorHandler:
    """错误处理器"""
    
    # 错误类别映射
    ERROR_CATEGORY_MAP = {
        "connection": ErrorCategory.NETWORK,
        "timeout": ErrorCategory.TIMEOUT,
        "rate limit": ErrorCategory.API_LIMIT,
        "quota": ErrorCategory.API_LIMIT,
        "validation": ErrorCategory.VALIDATION,
        "parse": ErrorCategory.VALIDATION,
        "generate": ErrorCategory.GENERATION,
        "database": ErrorCategory.DATABASE,
        "sql": ErrorCategory.DATABASE
    }
    
    def __init__(self):
        """初始化错误处理器"""
        self.error_counts = {}
        self.recovery_strategies = {}
        self._init_recovery_strategies()
        logger.info("错误处理器初始化完成")
    
    def _init_recovery_strategies(self):
        """初始化恢复策略"""
        self.recovery_strategies = {
            ErrorCategory.NETWORK: [
                "等待5秒后重试",
                "切换 API endpoint",
                "降低请求频率",
                "使用备用服务"
            ],
            ErrorCategory.API_LIMIT: [
                "等待速率限制重置",
                "减少并发请求",
                "使用缓存结果",
                "降级到简单模型"
            ],
            ErrorCategory.TIMEOUT: [
                "增加超时时间",
                "分批处理数据",
                "简化请求内容",
                "使用流式处理"
            ],
            ErrorCategory.GENERATION: [
                "重试生成",
                "调整生成参数",
                "使用缓存结果",
                "人工介入"
            ],
            ErrorCategory.VALIDATION: [
                "修正输入数据",
                "使用默认值",
                "跳过无效步骤",
                "记录并继续"
            ],
            ErrorCategory.DATABASE: [
                "重试数据库操作",
                "使用缓存数据",
                "回滚到上次检查点",
                "创建新会话"
            ]
        }
    
    def categorize_error(self, error: Exception) -> ErrorCategory:
        """
        分类错误
        
        Args:
            error: 异常对象
            
        Returns:
            错误类别
        """
        error_msg = str(error).lower()
        
        for pattern, category in self.ERROR_CATEGORY_MAP.items():
            if pattern in error_msg:
                return category
        
        return ErrorCategory.UNKNOWN
    
    def get_severity(self, error: Exception, category: ErrorCategory) -> ErrorSeverity:
        """
        获取错误严重程度
        
        Args:
            error: 异常对象
            category: 错误类别
            
        Returns:
            严重程度
        """
        if category in [ErrorCategory.DATABASE]:
            return ErrorSeverity.CRITICAL
        elif category in [ErrorCategory.API_LIMIT, ErrorCategory.GENERATION]:
            return ErrorSeverity.HIGH
        elif category in [ErrorCategory.TIMEOUT, ErrorCategory.NETWORK]:
            return ErrorSeverity.MEDIUM
        else:
            return ErrorSeverity.LOW
    
    def get_recovery_suggestions(
        self,
        error: Exception,
        category: ErrorCategory
    ) -> List[str]:
        """
        获取恢复建议
        
        Args:
            error: 异常对象
            category: 错误类别
            
        Returns:
            恢复建议列表
        """
        return self.recovery_strategies.get(category, [
            "检查错误日志",
            "重试操作",
            "联系技术支持"
        ])
    
    def should_retry(
        self,
        error: Exception,
        retry_count: int,
        max_retries: int = 3
    ) -> bool:
        """
        判断是否应该重试
        
        Args:
            error: 异常对象
            retry_count: 当前重试次数
            max_retries: 最大重试次数
            
        Returns:
            是否应该重试
        """
        category = self.categorize_error(error)
        
        if category == ErrorCategory.CRITICAL:
            return False
        
        if category == ErrorCategory.VALIDATION:
            return False
        
        if retry_count >= max_retries:
            return False
        
        return True
    
    def record_error(self, error: Exception, context: str):
        """
        记录错误
        
        Args:
            error: 异常对象
            context: 错误上下文
        """
        category = self.categorize_error(error)
        severity = self.get_severity(error, category)
        
        error_key = f"{context}:{category.value}"
        self.error_counts[error_key] = self.error_counts.get(error_key, 0) + 1
        
        log_method = logger.error if severity == ErrorSeverity.CRITICAL else logger.warning
        log_method(
            f"错误发生 - 上下文: {context}, "
            f"类别: {category.value}, "
            f"严重程度: {severity.value}, "
            f"错误: {str(error)}"
        )
    
    async def handle_error(
        self,
        state: ComicDramaState,
        error: Exception,
        node_name: str,
        retry_count: int = 0
    ) -> ComicDramaState:
        """
        处理错误
        
        Args:
            state: 当前状态
            error: 异常对象
            node_name: 节点名称
            retry_count: 重试次数
            
        Returns:
            更新后的状态
        """
        category = self.categorize_error(error)
        severity = self.get_severity(error, category)
        suggestions = self.get_recovery_suggestions(error, category)
        
        self.record_error(error, node_name)
        
        error_info = {
            "node": node_name,
            "category": category.value,
            "severity": severity.value,
            "message": str(error),
            "suggestions": suggestions,
            "retry_count": retry_count,
            "timestamp": ""
        }
        
        state["errors"].append(error_info)
        
        if severity == ErrorSeverity.CRITICAL:
            state["current_stage"] = "error"
            state["messages"].append({
                "role": "system",
                "content": f"❌ 严重错误: {str(error)}，工作流已停止"
            })
        
        elif self.should_retry(error, retry_count):
            state["messages"].append({
                "role": "system",
                "content": f"⚠️ {node_name} 错误，正在重试 ({retry_count + 1}/3): {str(error)}"
            })
        
        else:
            state["messages"].append({
                "role": "system",
                "content": f"⚠️ {node_name} 错误，建议: {suggestions[0]}"
            })
        
        return state


class RecoveryManager:
    """恢复管理器"""
    
    def __init__(self):
        """初始化恢复管理器"""
        self.checkpoint_service = None
        logger.info("恢复管理器初始化完成")
    
    def set_checkpoint_service(self, service):
        """设置检查点服务"""
        self.checkpoint_service = service
    
    async def create_recovery_point(
        self,
        state: ComicDramaState,
        reason: str = "manual"
    ) -> Dict[str, Any]:
        """
        创建恢复点
        
        Args:
            state: 当前状态
            reason: 创建原因
            
        Returns:
            恢复点信息
        """
        if not self.checkpoint_service:
            logger.warning("检查点服务未设置，无法创建恢复点")
            return {"success": False, "error": "服务未初始化"}
        
        try:
            checkpoint_id = f"recovery_{state.get('session_id')}_{state.get('current_stage')}"
            
            checkpoint_data = {
                "state": state,
                "reason": reason,
                "stage": state.get("current_stage"),
                "timestamp": ""
            }
            
            result = await self.checkpoint_service.put(
                thread_id=state.get("thread_id"),
                checkpoint_id=checkpoint_id,
                data=checkpoint_data
            )
            
            logger.info(f"创建恢复点: {checkpoint_id}")
            
            return {
                "success": True,
                "checkpoint_id": checkpoint_id,
                "stage": state.get("current_stage")
            }
            
        except Exception as e:
            logger.error(f"创建恢复点失败: {e}")
            return {"success": False, "error": str(e)}
    
    async def restore_from_point(
        self,
        state: ComicDramaState,
        checkpoint_id: str
    ) -> ComicDramaState:
        """
        从恢复点恢复
        
        Args:
            state: 当前状态
            checkpoint_id: 恢复点 ID
            
        Returns:
            恢复后的状态
        """
        if not self.checkpoint_service:
            logger.warning("检查点服务未设置，无法恢复")
            return state
        
        try:
            result = await self.checkpoint_service.get(
                thread_id=state.get("thread_id"),
                checkpoint_id=checkpoint_id
            )
            
            if result and "state" in result:
                restored_state = result["state"]
                state.update(restored_state)
                state["messages"].append({
                    "role": "system",
                    "content": f"🔄 已从检查点恢复: {checkpoint_id}"
                })
                logger.info(f"从检查点恢复: {checkpoint_id}")
                return state
            
            return state
            
        except Exception as e:
            logger.error(f"从检查点恢复失败: {e}")
            return state
    
    async def rollback_to_stage(
        self,
        state: ComicDramaState,
        target_stage: str
    ) -> ComicDramaState:
        """
        回滚到指定阶段
        
        Args:
            state: 当前状态
            target_stage: 目标阶段
            
        Returns:
            回滚后的状态
        """
        stage_order = [
            "init", "script_analysis", "asset_generation",
            "storyboard_creation", "audio_processing",
            "video_generation", "editing", "completed"
        ]
        
        try:
            current_idx = stage_order.index(state.get("current_stage", "init"))
            target_idx = stage_order.index(target_stage)
            
            if target_idx >= current_idx:
                return state
            
            state["current_stage"] = target_stage
            state["messages"].append({
                "role": "system",
                "content": f"🔙 已回滚到 {target_stage} 阶段"
            })
            
            logger.info(f"回滚到阶段: {target_stage}")
            
            return state
            
        except ValueError:
            logger.error(f"无效的目标阶段: {target_stage}")
            return state


class CircuitBreaker:
    """熔断器"""
    
    def __init__(
        self,
        failure_threshold: int = 5,
        recovery_time: int = 60
    ):
        """
        初始化熔断器
        
        Args:
            failure_threshold: 失败阈值
            recovery_time: 恢复时间（秒）
        """
        self.failure_threshold = failure_threshold
        self.recovery_time = recovery_time
        self.failure_count = {}
        self.last_failure_time = {}
        self.state = {}
        logger.info("熔断器初始化完成")
    
    def is_open(self, key: str) -> bool:
        """检查熔断器是否开启"""
        if key not in self.state:
            return False
        
        if self.state[key] == "open":
            elapsed = asyncio.get_event_loop().time() - self.last_failure_time.get(key, 0)
            if elapsed > self.recovery_time:
                self.state[key] = "half_open"
                return False
            return True
        
        return False
    
    def record_failure(self, key: str):
        """记录失败"""
        self.failure_count[key] = self.failure_count.get(key, 0) + 1
        self.last_failure_time[key] = asyncio.get_event_loop().time()
        
        if self.failure_count[key] >= self.failure_threshold:
            self.state[key] = "open"
            logger.warning(f"熔断器开启: {key}")
    
    def record_success(self, key: str):
        """记录成功"""
        self.failure_count[key] = 0
        self.state[key] = "closed"
        logger.info(f"熔断器关闭: {key}")


# 全局实例
error_handler = ErrorHandler()
recovery_manager = RecoveryManager()
circuit_breaker = CircuitBreaker()


async def with_error_handling(
    func: Callable,
    state: ComicDramaState,
    node_name: str
) -> ComicDramaState:
    """
    带错误处理的函数执行
    
    Args:
        func: 要执行的函数
        state: 当前状态
        node_name: 节点名称
        
    Returns:
        执行后的状态
    """
    retry_count = 0
    max_retries = 3
    
    while retry_count < max_retries:
        try:
            result = await func(state)
            circuit_breaker.record_success(node_name)
            return result
            
        except Exception as e:
            circuit_breaker.record_failure(node_name)
            
            if circuit_breaker.is_open(node_name):
                state["errors"].append({
                    "node": node_name,
                    "category": "circuit_breaker",
                    "message": f"服务暂时不可用: {node_name}",
                    "severity": "high"
                })
                return state
            
            state = await error_handler.handle_error(
                state, e, node_name, retry_count
            )
            
            if error_handler.should_retry(e, retry_count):
                retry_count += 1
                await asyncio.sleep(2 ** retry_count)
            else:
                break
    
    return state
