"""
Agent API 端点

重构版 - 使用 Graph Runner 统一处理所有意图
基于 agent_chat_refactor_design.md v1.3
"""

from typing import Optional, List, Dict, Any
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession
from pydantic import BaseModel, Field
from sqlalchemy import select, func, desc, delete
import json
import uuid

from app.db.session import get_async_db
from app.core.logger import logger
from app.api.deps import get_current_user
from app.models.user import User
from app.models.creation import Creation
from app.models.agent_session import AgentSession
from app.models.agent_message import AgentMessage, EventType


router = APIRouter()


# ==================== 请求/响应模型 ====================

class ChatRequest(BaseModel):
    """发送消息请求"""
    message: str = Field(..., description="用户输入的文本消息")
    attachments: Optional[List[dict]] = Field(None, description="附件列表")
    context: Optional[dict] = Field(None, description="上下文信息")
    action: Optional[str] = Field(None, description="用户操作: approve/reject/modify")
    action_data: Optional[Dict[str, Any]] = Field(None, description="操作附加数据")
    stream: bool = Field(True, description="是否使用流式响应")


class MessageHistoryResponse(BaseModel):
    """消息历史响应"""
    creation_uuid: str
    messages: List[dict]
    has_more: bool
    total_count: int


class InterruptRequest(BaseModel):
    """中断对话请求"""
    message_id: Optional[str] = Field(None, description="消息 ID")
    reason: str = Field("user_stopped", description="中断原因")


class InterruptResponse(BaseModel):
    """中断对话响应"""
    success: bool
    message: str
    session_id: str


class ResetRequest(BaseModel):
    """重置会话请求"""
    keep_assets: bool = Field(True, description="是否保留已生成的资产")


class ResetResponse(BaseModel):
    """重置会话响应"""
    success: bool
    message: str
    creation_uuid: str


# ==================== 辅助函数 ====================

async def get_or_create_session(
    db: AsyncSession,
    creation_uuid: str,
    user_id: int
) -> AgentSession:
    """获取或创建 Agent 会话"""
    stmt = select(AgentSession).where(
        AgentSession.creation_uuid == creation_uuid,
        AgentSession.deleted_at.is_(None)  # 只查活跃的 Session
    ).order_by(desc(AgentSession.created_at))
    
    result = await db.execute(stmt)
    session = result.scalar_one_or_none()
    
    if not session:
        creation_stmt = select(Creation).where(Creation.uuid == creation_uuid)
        creation_result = await db.execute(creation_stmt)
        creation = creation_result.scalar_one_or_none()
        
        if not creation:
            return None
        
        session = AgentSession(
            creation_id=creation.creation_id,
            thread_id=str(uuid.uuid4()),
            creation_uuid=creation_uuid,
            user_id=user_id,
            current_stage="init",
            status="active"
        )
        db.add(session)
        await db.commit()
        await db.refresh(session)
    
    return session


# ==================== API 端点 ====================

@router.post(
    "/{creation_uuid}/agent/chat",
    summary="发起 Agent 对话",
    description="向 Agent 发送用户消息，建立 SSE 连接接收流式响应"
)
async def agent_chat(
    creation_uuid: str,
    request: ChatRequest,
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(get_current_user)
):
    """
    向 Agent 发送消息并接收 SSE 流式响应
    
    重构版本：
    - 所有意图分发逻辑移至 Graph 内部
    - API 层仅负责会话管理和 SSE 流转发
    - 统一使用 GraphRunner 处理
    """
    from app.agent.graph.runner import GraphRunner
    
    async def event_generator():
        """生成 SSE 事件"""
        try:
            # 验证创作项目权限
            stmt = select(Creation).where(
                Creation.uuid == creation_uuid,
                Creation.owner_id == current_user.user_id
            )
            result = await db.execute(stmt)
            creation = result.scalar_one_or_none()
            
            if not creation:
                yield f"event: error\ndata: {json.dumps({'error': '创作项目不存在或无权限访问'})}\n\n"
                return
            
            # 获取或创建会话
            session = await get_or_create_session(db, creation_uuid, current_user.user_id)
            
            if not session:
                yield f"event: error\ndata: {json.dumps({'error': '创作项目不存在'})}\n\n"
                return
            
            # 发送 thread_id
            yield f"event: thread\ndata: {json.dumps({'thread_id': session.thread_id})}\n\n"
            
            # 创建 Graph Runner
            runner = GraphRunner(
                creation_uuid=creation_uuid,
                thread_id=session.thread_id,
                user_id=current_user.user_id,
            )
            
            logger.info(f"[Agent Chat] 开始处理消息: creation={creation_uuid}, thread={session.thread_id}")
            
            # 执行 Graph 并流式输出
            async for sse_event in runner.handle_chat_message(
                user_message=request.message,
                user_action=request.action,
                user_action_data=request.action_data,
            ):
                yield sse_event
                
        except Exception as e:
            logger.error(f"[Agent Chat] SSE 流生成失败: {e}")
            yield f"event: error\ndata: {json.dumps({'error': str(e)})}\n\n"
    
    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no"
        }
    )


@router.get(
    "/{creation_uuid}/agent/messages",
    response_model=MessageHistoryResponse,
    summary="获取会话历史",
    description="获取当前创作会话的历史对话记录"
)
async def get_messages(
    creation_uuid: str,
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(get_current_user),
    limit: int = 50,
    before: Optional[str] = None,
    after: Optional[str] = None
):
    """
    获取会话消息历史
    
    重构版本：从 Creation.extra_data['agent_threads'] 读取
    """
    try:
        stmt = select(Creation).where(
            Creation.uuid == creation_uuid,
            Creation.owner_id == current_user.user_id
        )
        result = await db.execute(stmt)
        creation = result.scalar_one_or_none()
        
        if not creation:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="创作项目不存在或无权限访问"
            )
        
        # 从 extra_data['agent_threads'] 读取所有会话的消息
        extra_data = creation.extra_data or {}
        agent_threads = extra_data.get("agent_threads", {})
        
        # 合并所有会话的消息（按时间排序）
        all_messages = []
        for thread_id, thread_data in agent_threads.items():
            thread_messages = thread_data.get("messages", [])
            for msg in thread_messages:
                msg["thread_id"] = thread_id
                all_messages.append(msg)
        
        # 按时间排序（最新的在前）
        all_messages.sort(key=lambda x: x.get("timestamp", ""), reverse=True)
        
        # 应用分页
        if before:
            all_messages = [m for m in all_messages if m.get("timestamp", "") < before]
        if after:
            all_messages = [m for m in all_messages if m.get("timestamp", "") > after]
        
        total = len(all_messages)
        messages = all_messages[:limit]
        
        return {
            "creation_uuid": creation_uuid,
            "messages": [
                {
                    "id": msg.get("id", ""),
                    "role": msg.get("role", ""),
                    "content": msg.get("content", ""),
                    "event_type": msg.get("event_type", "message"),
                    "metadata": msg.get("metadata", {}),
                    "timestamp": msg.get("timestamp")
                }
                for msg in reversed(messages)  # 改回正序（旧的在前）
            ],
            "has_more": len(all_messages) > limit,
            "total_count": total
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"获取消息历史失败: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"获取消息历史失败: {str(e)}"
        )


@router.post(
    "/{creation_uuid}/agent/interrupt",
    response_model=InterruptResponse,
    summary="中断对话",
    description="中断当前正在进行的 Agent 工作流"
)
async def interrupt_session(
    creation_uuid: str,
    request: InterruptRequest,
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(get_current_user)
):
    """
    中断当前正在进行的 Agent 响应
    """
    try:
        stmt = select(AgentSession).where(
            AgentSession.creation_uuid == creation_uuid,
            AgentSession.deleted_at.is_(None)
        ).order_by(desc(AgentSession.created_at))
        
        result = await db.execute(stmt)
        session = result.scalar_one_or_none()
        
        if not session:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="会话不存在或尚未初始化"
            )
        
        if session.status == "completed":
            return {
                "success": False,
                "message": "会话已完成，无法中断",
                "session_id": session.session_id
            }
        
        interrupt_message = AgentMessage(
            session_id=session.session_id,
            role="system",
            content=f"对话已中断: {request.reason}",
            event_type=EventType.INTERRUPT,
            message_metadata={
                "message_id": request.message_id,
                "reason": request.reason
            }
        )
        db.add(interrupt_message)
        
        session.status = "interrupted"
        await db.commit()
        
        logger.info(f"中断 Agent 会话: creation_uuid={creation_uuid}, reason={request.reason}")
        
        return {
            "success": True,
            "message": "对话已中断",
            "session_id": session.session_id
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"中断对话失败: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"中断对话失败: {str(e)}"
        )


@router.post(
    "/{creation_uuid}/agent/reset",
    response_model=ResetResponse,
    summary="重置会话",
    description="重置 Agent 会话，清除历史对话和状态"
)
async def reset_session(
    creation_uuid: str,
    request: ResetRequest,
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(get_current_user)
):
    """
    重置会话
    
    清除内容：
    1. AgentMessage 表中的消息
    2. Creation.extra_data 中的 agent_threads（消息历史）
    3. Creation.extra_data 中的 agent_checkpoints（检查点）
    """
    try:
        stmt = select(AgentSession).where(
            AgentSession.creation_uuid == creation_uuid,
            AgentSession.deleted_at.is_(None)
        ).order_by(desc(AgentSession.created_at))
        
        result = await db.execute(stmt)
        session = result.scalar_one_or_none()
        
        if not session:
            session = await get_or_create_session(db, creation_uuid, current_user.user_id)
            
            if not session:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="创作项目不存在"
                )
        
        # 1. 清除 AgentMessage 表中的消息
        if not request.keep_assets:
            await db.execute(
                delete(AgentMessage).where(AgentMessage.session_id == session.session_id)
            )
        
        # 2. 清除 Creation.extra_data 中的 agent_threads 和 agent_checkpoints
        stmt_creation = select(Creation).where(Creation.uuid == creation_uuid)
        result_creation = await db.execute(stmt_creation)
        creation = result_creation.scalar_one_or_none()
        
        if creation:
            extra_data = creation.extra_data or {}
            # 清除消息历史
            if "agent_threads" in extra_data:
                del extra_data["agent_threads"]
                logger.info(f"[Reset] 清除 agent_threads: {creation_uuid}")
            # 清除检查点
            if "agent_checkpoints" in extra_data:
                del extra_data["agent_checkpoints"]
                logger.info(f"[Reset] 清除 agent_checkpoints: {creation_uuid}")
            # 清除最后检查点ID
            if "last_checkpoint_id" in extra_data:
                del extra_data["last_checkpoint_id"]
            
            creation.extra_data = extra_data
            from sqlalchemy.orm.attributes import flag_modified
            flag_modified(creation, "extra_data")
        
        session.current_stage = "init"
        session.status = "reset"
        await db.commit()
        
        reset_message = AgentMessage(
            session_id=session.session_id,
            role="system",
            content="会话已重置",
            event_type=EventType.SESSION_RESET,
            message_metadata={"keep_assets": request.keep_assets}
        )
        db.add(reset_message)
        await db.commit()
        
        logger.info(f"重置 Agent 会话: creation_uuid={creation_uuid}, keep_assets={request.keep_assets}")
        
        return {
            "success": True,
            "message": "会话已重置",
            "creation_uuid": creation_uuid
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"重置会话失败: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"重置会话失败: {str(e)}"
        )


@router.get(
    "/{creation_uuid}/agent/status",
    summary="获取会话状态",
    description="获取当前创作会话的状态和进度"
)
async def get_session_status(
    creation_uuid: str,
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(get_current_user)
):
    """
    获取会话状态
    """
    try:
        stmt = select(Creation).where(
            Creation.uuid == creation_uuid,
            Creation.owner_id == current_user.user_id
        )
        result = await db.execute(stmt)
        creation = result.scalar_one_or_none()
        
        if not creation:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="创作项目不存在或无权限访问"
            )
        
        session_stmt = select(AgentSession).where(
            AgentSession.creation_uuid == creation_uuid,
            AgentSession.user_id == current_user.user_id,
            AgentSession.deleted_at.is_(None)  # 只查活跃的 Session
        ).order_by(AgentSession.created_at.desc())
        
        result = await db.execute(session_stmt)
        session = result.scalar_one_or_none()
        
        if not session:
            return {
                "creation_uuid": creation_uuid,
                "current_stage": None,
                "status": None,
                "messages": []
            }
        
        msg_stmt = select(AgentMessage).where(
            AgentMessage.session_id == session.session_id
        ).order_by(AgentMessage.created_at.desc()).limit(20)
        
        result = await db.execute(msg_stmt)
        messages = result.scalars().all()
        
        return {
            "creation_uuid": creation_uuid,
            "session_id": session.session_id,
            "thread_id": session.thread_id,
            "current_stage": session.current_stage,
            "status": session.status,
            "workflow_mode": creation.workflow_mode,
            "created_at": session.created_at.isoformat() if session.created_at else None,
            "updated_at": session.updated_at.isoformat() if session.updated_at else None,
            "messages": [
                {
                    "role": msg.role,
                    "content": msg.content,
                    "event_type": msg.event_type,
                    "created_at": msg.created_at.isoformat() if msg.created_at else None
                }
                for msg in reversed(messages)
            ]
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"获取会话状态失败: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"获取会话状态失败: {str(e)}"
        )
