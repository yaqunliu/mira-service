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
    
    路由规则（简化版）：
    | 意图分类 | 目标节点 | 说明 |
    |----------|----------|------|
    | query | status_query | 状态查询 + 知识问答（ReAct Agent） |
    | production | task_execution | 制作任务（子图） |
    | confirm | task_execution | 确认/取消（子图） |
    | out_of_scope | clarify | 超出范围，引导用户 |
    
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
    
    # 查询类 -> status_query（ReAct Agent，支持状态查询+知识问答）
    if intent_category == "query":
        logger.info("[Router] -> status_query (查询/知识问答)")
        return "status_query"
    
    # 制作类 -> task_execution（子图）
    if intent_category == "production":
        logger.info("[Router] -> task_execution (制作任务)")
        return "task_execution"
    
    # 确认类 -> task_execution（子图）
    if intent_category == "confirm":
        logger.info("[Router] -> task_execution (确认/取消)")
        return "task_execution"
    
    # 兼容旧的意图分类
    if intent_category == "status_query":
        logger.info("[Router] -> status_query (兼容旧分类)")
        return "status_query"
    
    if intent_category in ["task_intent", "asset_action"]:
        logger.info("[Router] -> task_execution (兼容旧分类)")
        return "task_execution"
    
    # 超出范围/其他 -> clarify
    logger.info("[Router] -> clarify (超出范围或未知)")
    return "clarify"
