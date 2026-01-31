"""
响应格式化节点

将内部状态格式化为用户可见的响应，并转换为 SSE 事件
"""

from typing import Dict, Any, Optional

from app.core.logger import logger


# 节点可见性配置
NODE_VISIBILITY = {
    # 对话调度层 - 用户可见
    "entry": "user",
    "intent_detection": "internal",  # 意图识别过程不展示
    "router": "internal",            # 路由逻辑不展示
    "status_query": "user",
    "task_execution": "user",
    "clarify": "user",
    "response_formatter": "user",
    "human_review": "user",          # 人机交互结果需要流式展示给用户
    
    # 业务执行层 - 分析过程不展示，仅内部记录
    "script_analysis": "internal",   # 剧本分析/提示词生成不流式展示
    "asset_generation": "internal",  # 图片生成不流式展示
    "storyboard_generation": "internal",
    "audio_processing": "internal",
    "video_generation": "internal",
    "editing": "internal",
}


async def response_formatter_node(state: Dict[str, Any]) -> Dict[str, Any]:
    """
    响应格式化节点
    
    将内部处理结果格式化为用户友好的响应，
    并准备 SSE 事件数据
    
    Args:
        state: 当前 Graph 状态
        
    Returns:
        更新后的状态，包含格式化后的响应和 SSE 事件
    """
    logger.info("[Node] response_formatter: 开始格式化响应")
    
    from datetime import datetime
    
    response_text = state.get("response_text", "")
    messages = state.get("messages", [])
    last_node = _get_last_node(messages)
    
    try:
        # 获取节点可见性
        visibility = NODE_VISIBILITY.get(last_node, "user")
        
        # 构建 SSE 事件
        sse_events = []
        
        if visibility == "user":
            # 用户可见消息
            sse_events.extend(_build_message_events(response_text, last_node))
        elif visibility == "thinking":
            # 思考过程（可选展示）
            sse_events.extend(_build_thinking_events(response_text, last_node))
        # internal 类型不生成 SSE 事件
        
        # 添加看板操作事件（如果有）
        board_actions = state.get("board_actions", [])
        for action in board_actions:
            sse_events.append(_build_board_action_event(action))
        
        # 添加进度事件（如果有）
        if state.get("progress_update"):
            sse_events.append(_build_progress_event(state["progress_update"]))
        
        logger.info(f"[Node] response_formatter: 生成 {len(sse_events)} 个 SSE 事件")
        
        return {
            "sse_events": sse_events,
            "formatted_response": response_text,
            "response_visibility": visibility,
            "updated_at": datetime.now().isoformat(),
        }
        
    except Exception as e:
        logger.error(f"[Node] response_formatter 错误: {e}")
        
        return {
            "sse_events": [
                {
                    "event": "error",
                    "data": {
                        "error": str(e),
                        "code": "FORMAT_ERROR",
                        "recoverable": True,
                    }
                }
            ],
            "errors": state.get("errors", []) + [{"node": "response_formatter", "error": str(e)}],
        }


def _get_last_node(messages: list) -> str:
    """获取最后一条消息的来源节点"""
    if not messages:
        return "unknown"
    
    last_message = messages[-1]
    return last_message.get("node", "unknown")


def _build_message_events(content: str, node: str) -> list:
    """构建消息类 SSE 事件"""
    import uuid
    
    message_id = str(uuid.uuid4())
    
    events = [
        {
            "event": "message.start",
            "data": {"id": message_id},
        },
    ]
    
    # 将内容分块发送（模拟流式输出）
    chunk_size = 50
    for i in range(0, len(content), chunk_size):
        chunk = content[i:i+chunk_size]
        events.append({
            "event": "message.delta",
            "data": {
                "id": message_id,
                "content": chunk,
                "node": node,
            },
        })
    
    events.append({
        "event": "message.end",
        "data": {
            "id": message_id,
            "finish_reason": "stop",
        },
    })
    
    return events


def _build_thinking_events(content: str, node: str) -> list:
    """构建思考类 SSE 事件"""
    import uuid
    
    thinking_id = str(uuid.uuid4())
    
    events = [
        {
            "event": "thinking.start",
            "data": {"id": thinking_id},
        },
        {
            "event": "thinking.delta",
            "data": {
                "id": thinking_id,
                "content": content,
                "node": node,
            },
        },
        {
            "event": "thinking.end",
            "data": {"id": thinking_id},
        },
    ]
    
    return events


def _build_board_action_event(action: Dict[str, Any]) -> Dict[str, Any]:
    """构建看板操作 SSE 事件"""
    return {
        "event": "board.action",
        "data": {
            "action": action.get("action"),  # update/highlight/scroll/refresh
            "target": action.get("target"),  # character/scene/shot + id
            "data": action.get("data", {}),
        },
    }


def _build_progress_event(progress: Dict[str, Any]) -> Dict[str, Any]:
    """构建进度更新 SSE 事件"""
    return {
        "event": "progress",
        "data": {
            "stage": progress.get("stage"),
            "current": progress.get("current", 0),
            "total": progress.get("total", 0),
            "message": progress.get("message", ""),
        },
    }


def build_tool_events(
    tool_name: str,
    tool_id: str,
    status: str,
    progress: Optional[int] = None,
    result_summary: Optional[str] = None,
) -> list:
    """
    构建 Tool 调用相关的 SSE 事件
    
    Args:
        tool_name: 工具名称
        tool_id: 工具调用 ID
        status: 状态（start/progress/end）
        progress: 进度百分比
        result_summary: 结果摘要
        
    Returns:
        SSE 事件列表
    """
    if status == "start":
        return [{
            "event": "tool.start",
            "data": {
                "id": tool_id,
                "tool_name": tool_name,
            },
        }]
    elif status == "progress":
        return [{
            "event": "tool.progress",
            "data": {
                "id": tool_id,
                "status": "processing",
                "progress": progress or 0,
            },
        }]
    elif status == "end":
        return [{
            "event": "tool.end",
            "data": {
                "id": tool_id,
                "status": "completed",
                "result_summary": result_summary or "",
            },
        }]
    
    return []


def build_done_event() -> Dict[str, Any]:
    """构建流结束事件"""
    return {
        "event": "done",
        "data": {},
    }
