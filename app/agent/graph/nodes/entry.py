"""
Entry 节点 - 对话调度层入口

接收用户消息，初始化对话状态
"""

from typing import Dict, Any
from datetime import datetime

from app.agent.state.schemas import ComicDramaState
from app.core.logger import logger


async def entry_node(state: ComicDramaState) -> Dict[str, Any]:
    """
    入口节点 - 接收用户消息，初始化对话状态
    
    职责：
    1. 记录用户消息到对话历史
    2. 检查是否有 user_action（Human Review 响应）
    3. 更新时间戳
    
    Args:
        state: 当前 Graph 状态
        
    Returns:
        状态更新字典
    """
    logger.info(f"[Entry Node] 收到用户消息: {state.get('user_message', '')[:50]}...")
    
    # 获取当前消息
    user_message = state.get("user_message", "")
    user_action = state.get("user_action")
    user_action_data = state.get("user_action_data", {})
    
    # 构建消息记录
    new_message = {
        "role": "user",
        "content": user_message,
        "timestamp": datetime.utcnow().isoformat(),
    }
    
    # 如果有 action，添加到消息元数据
    if user_action:
        new_message["action"] = user_action
        new_message["action_data"] = user_action_data
        logger.info(f"[Entry Node] 检测到用户 Action: {user_action}")
    
    # 获取现有消息历史
    messages = state.get("messages", [])
    
    # 返回状态更新
    return {
        "messages": messages + [new_message],
        "updated_at": datetime.utcnow().isoformat(),
        # 清除待处理的 action（已处理）
        "pending_action": user_action if user_action else None,
    }
