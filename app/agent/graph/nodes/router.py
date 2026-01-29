"""
Router 节点 - 路由分发

根据意图识别结果路由到不同的处理节点
"""

from typing import Literal

from app.agent.state.schemas import ComicDramaState
from app.core.logger import logger


# 路由目标类型
RouterTarget = Literal["status_query", "task_execution", "clarify"]


def router_node(state: ComicDramaState) -> RouterTarget:
    """
    路由节点 - 根据意图分发到不同节点
    
    路由规则：
    | 条件 | 目标节点 | 说明 |
    |------|----------|------|
    | intent_category == "status_query" | status_query | 状态查询分支 |
    | intent_category == "task_intent" && confidence > 0.8 | task_execution | 高置信度任务执行 |
    | intent_category == "task_intent" && confidence <= 0.8 | clarify | 低置信度需确认 |
    | intent_category == "asset_action" | task_execution | 资产操作 |
    | intent_category in ["confirm", "cancel"] | task_execution | 用户确认/取消 |
    | intent_category == "other" or "unknown" | clarify | 未知意图引导 |
    
    Args:
        state: 当前 Graph 状态
        
    Returns:
        目标节点名称
    """
    intent_category = state.get("intent_category", "other")
    confidence = state.get("intent_confidence", 0.0)
    detected_intent = state.get("detected_intent", "unknown")
    
    logger.info(
        f"[Router] 路由决策: "
        f"category={intent_category}, "
        f"intent={detected_intent}, "
        f"confidence={confidence}"
    )
    
    # 状态查询 -> status_query
    if intent_category == "status_query":
        logger.info("[Router] -> status_query")
        return "status_query"
    
    # 任务意图
    if intent_category == "task_intent":
        if confidence > 0.8:
            logger.info("[Router] -> task_execution (高置信度)")
            return "task_execution"
        else:
            logger.info("[Router] -> clarify (低置信度)")
            return "clarify"
    
    # 资产操作 -> task_execution
    if intent_category == "asset_action":
        logger.info("[Router] -> task_execution (资产操作)")
        return "task_execution"
    
    # 确认/取消 -> task_execution
    if intent_category == "confirm":
        logger.info("[Router] -> task_execution (确认/取消)")
        return "task_execution"
    
    # 其他/未知 -> clarify
    logger.info("[Router] -> clarify (未知意图)")
    return "clarify"
