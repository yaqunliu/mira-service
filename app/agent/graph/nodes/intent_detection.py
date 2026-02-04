"""
Intent Detection 节点 - 意图识别

使用 LLM 识别用户消息的意图类型
"""

import json
from typing import Dict, Any, Optional

from langchain_openai import ChatOpenAI

from app.agent.prompts import load_prompt, format_prompt, get_prompt_config
from app.agent.state.schemas import ComicDramaState
from app.core.config import settings
from app.core.logger import logger


async def intent_detection_node(state: ComicDramaState) -> Dict[str, Any]:
    """
    意图识别节点 - 使用 LLM 识别用户意图
    
    职责：
    1. 加载意图识别提示词
    2. 构建上下文（用户消息、对话历史、当前阶段）
    3. 调用 LLM 进行意图识别
    4. 解析返回的 JSON 结果
    
    Args:
        state: 当前 Graph 状态
        
    Returns:
        状态更新字典，包含识别结果
    """
    logger.info("[Intent Detection] 开始识别用户意图")
    
    # 检查是否有 pending_action（来自 Human Review）
    pending_action = state.get("pending_action")
    if pending_action:
        logger.info(f"[Intent Detection] 检测到 pending_action: {pending_action}")
        # 直接映射 action 到意图
        return _handle_action_intent(pending_action, state)
    
    # 加载提示词
    prompt_data = load_prompt("intent_detection")
    
    # 构建上下文
    context = {
        "user_message": state.get("user_message", ""),
        "chat_history": state.get("messages", [])[-10:],  # 最近 10 条
        "current_stage": state.get("current_stage", "init"),
    }
    
    # 渲染提示词
    prompt = format_prompt(prompt_data, context)
    
    # 获取模型配置
    model = get_prompt_config(prompt_data, "model", "gpt-4o-mini")
    temperature = get_prompt_config(prompt_data, "temperature", 0.3)
    
    # 调用 LLM
    try:
        llm = ChatOpenAI(
            model=model,
            temperature=temperature,
            api_key=settings.OPENAI_API_KEY,
        )
        
        response = await llm.ainvoke(prompt)
        result = _parse_intent_response(response.content)
        
        logger.info(
            f"[Intent Detection] 识别结果: "
            f"intent={result.get('intent')}, "
            f"category={result.get('intent_category')}, "
            f"confidence={result.get('confidence')}"
        )
        
        return {
            "detected_intent": result.get("intent", "unknown"),
            "intent_category": result.get("intent_category", "other"),
            "intent_confidence": result.get("confidence", 0.0),
            "intent_details": result.get("details", {}),
        }
        
    except Exception as e:
        logger.error(f"[Intent Detection] LLM 调用失败: {e}")
        # 降级处理：返回 unknown
        return {
            "detected_intent": "unknown",
            "intent_category": "other",
            "intent_confidence": 0.0,
            "intent_details": {"error": str(e)},
        }


def _handle_action_intent(action: str, state: ComicDramaState) -> Dict[str, Any]:
    """
    处理来自 Human Review 的 action
    
    将 action 映射为意图
    """
    action_to_intent = {
        "approve": ("confirm", "confirm"),
        "reject": ("cancel", "confirm"),
        "modify": ("regenerate_prompt", "asset_action"),
        "retry": ("regenerate", "asset_action"),
        "skip": ("confirm", "confirm"),
        "abort": ("cancel", "confirm"),
    }
    
    intent, category = action_to_intent.get(action, ("unknown", "other"))
    
    return {
        "detected_intent": intent,
        "intent_category": category,
        "intent_confidence": 1.0,  # action 是明确的
        "intent_details": {
            "source": "user_action",
            "action": action,
            "action_data": state.get("user_action_data", {}),
        },
    }


def _parse_intent_response(content: str) -> Dict[str, Any]:
    """
    解析 LLM 返回的 JSON 响应
    
    处理可能的格式问题（如 markdown 代码块包裹）
    """
    # 移除可能的 markdown 代码块标记
    content = content.strip()
    if content.startswith("```json"):
        content = content[7:]
    if content.startswith("```"):
        content = content[3:]
    if content.endswith("```"):
        content = content[:-3]
    content = content.strip()
    
    try:
        return json.loads(content)
    except json.JSONDecodeError as e:
        logger.warning(f"[Intent Detection] JSON 解析失败: {e}, content: {content[:100]}")
        return {
            "intent": "unknown",
            "intent_category": "other",
            "confidence": 0.0,
            "details": {"parse_error": str(e)},
        }
