"""
简化版 Agent Chat API

重构后的 Chat API，将意图分发逻辑移至 Graph 内部
"""

from typing import Optional, Dict, Any
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
import asyncio

from app.core.logger import logger
from app.core.auth import get_current_user


router = APIRouter(prefix="/agent", tags=["Agent Chat"])


class ChatRequest(BaseModel):
    """聊天请求"""
    creation_uuid: str = Field(..., description="创作项目 UUID")
    message: str = Field(..., description="用户消息")
    thread_id: Optional[str] = Field(None, description="对话线程 ID")
    action: Optional[str] = Field(None, description="用户操作: approve/reject/modify")
    action_data: Optional[Dict[str, Any]] = Field(None, description="操作附加数据")


class ChatResponse(BaseModel):
    """聊天响应（非流式）"""
    success: bool
    thread_id: str
    message: Optional[str] = None
    error: Optional[str] = None


@router.post("/chat")
async def chat(
    request: ChatRequest,
    current_user = Depends(get_current_user),
):
    """
    Agent 聊天接口（SSE 流式响应）
    
    重构后的简化版本：
    - 移除 API 层意图分发逻辑
    - 所有意图由 Graph 内部处理
    - 统一 SSE 输出格式
    """
    from uuid import uuid4
    from app.agent.graph.runner import GraphRunner
    
    # 生成或使用已有的 thread_id
    thread_id = request.thread_id or str(uuid4())
    
    logger.info(f"[Chat API] 收到消息: creation={request.creation_uuid}, thread={thread_id}")
    
    # 创建 Graph Runner
    runner = GraphRunner(
        creation_uuid=request.creation_uuid,
        thread_id=thread_id,
        user_id=current_user.id,
    )
    
    # 返回 SSE 流
    async def event_generator():
        # 首先发送 thread_id
        yield f"event: thread\ndata: {{\"thread_id\": \"{thread_id}\"}}\n\n"
        
        # 执行 Graph 并流式输出
        async for sse_event in runner.handle_chat_message(
            user_message=request.message,
            user_action=request.action,
            user_action_data=request.action_data,
        ):
            yield sse_event
    
    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",  # Nginx 禁用缓冲
        },
    )


@router.get("/chat/status/{creation_uuid}")
async def get_chat_status(
    creation_uuid: str,
    thread_id: Optional[str] = None,
    current_user = Depends(get_current_user),
):
    """
    获取聊天状态
    
    返回当前对话的状态摘要
    """
    from app.agent.graph.runner import GraphRunner
    
    if not thread_id:
        # 如果没有指定 thread_id，返回创作项目的基本信息
        return {
            "creation_uuid": creation_uuid,
            "status": "ready",
            "message": "请发送消息开始对话",
        }
    
    runner = GraphRunner(
        creation_uuid=creation_uuid,
        thread_id=thread_id,
        user_id=current_user.id,
    )
    
    status = await runner.get_status()
    return status


@router.get("/chat/history/{creation_uuid}")
async def get_chat_history(
    creation_uuid: str,
    thread_id: str,
    limit: int = 20,
    current_user = Depends(get_current_user),
):
    """
    获取聊天历史
    
    返回指定对话的消息历史
    """
    from app.agent.state.messages import MessageHistory
    
    history = MessageHistory(creation_uuid, thread_id)
    messages = await history.load()
    
    # 限制返回数量
    if len(messages) > limit:
        messages = messages[-limit:]
    
    return {
        "creation_uuid": creation_uuid,
        "thread_id": thread_id,
        "messages": messages,
        "total": len(messages),
    }


@router.delete("/chat/history/{creation_uuid}")
async def clear_chat_history(
    creation_uuid: str,
    thread_id: str,
    current_user = Depends(get_current_user),
):
    """
    清空聊天历史
    
    清除指定对话的所有消息和检查点
    """
    from app.agent.state.messages import MessageHistory
    from app.agent.state.persistence import StatePersistence
    
    # 清空消息
    history = MessageHistory(creation_uuid, thread_id)
    await history.clear()
    
    # 清空检查点
    persistence = StatePersistence(creation_uuid, thread_id)
    await persistence.clear_checkpoints()
    
    return {
        "success": True,
        "message": "聊天历史已清空",
    }


# 兼容旧版 API 的适配器
@router.post("/chat/legacy")
async def legacy_chat(
    request: ChatRequest,
    current_user = Depends(get_current_user),
):
    """
    旧版 Chat API 兼容接口
    
    将请求转发到新版 API，但返回非流式响应
    """
    from app.agent.graph.runner import GraphRunner
    from uuid import uuid4
    
    thread_id = request.thread_id or str(uuid4())
    
    runner = GraphRunner(
        creation_uuid=request.creation_uuid,
        thread_id=thread_id,
        user_id=current_user.id,
    )
    
    # 收集所有响应
    full_response = []
    async for sse_event in runner.handle_chat_message(
        user_message=request.message,
        user_action=request.action,
        user_action_data=request.action_data,
    ):
        # 解析 SSE 事件中的内容
        if "message.delta" in sse_event:
            import json
            try:
                # 提取 data 部分
                lines = sse_event.strip().split("\n")
                for line in lines:
                    if line.startswith("data:"):
                        data = json.loads(line[5:].strip())
                        if "content" in data:
                            full_response.append(data["content"])
            except:
                pass
    
    return ChatResponse(
        success=True,
        thread_id=thread_id,
        message="".join(full_response),
    )
