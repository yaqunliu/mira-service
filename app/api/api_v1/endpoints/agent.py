"""
Agent API 端点

提供 Agent 工作流的 REST API 接口，支持 SSE 流式输出
符合 agent-chat-api.md 文档规范
"""

from typing import Optional, List, AsyncIterator, Dict, Any
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession
from pydantic import BaseModel, Field
from sqlalchemy import select, func, desc, delete
import json
import asyncio
import uuid

from app.db.session import get_async_db
from app.core.logger import logger
from app.core.config import settings
from app.api.deps import get_current_user
from app.models.user import User
from app.models.creation import Creation
from app.models.agent_session import AgentSession
from app.models.agent_message import AgentMessage, EventType
from app.agent.graph.comic_drama_graph import ComicDramaGraph
from app.agent.state.schemas import ComicDramaState
from app.agent.handlers.status_query_handler import ai_status_query_handler
from app.agent.handlers.task_handler import agent_task_handler
from app.agent.tools.script_loader import script_loader


router = APIRouter()


# ==================== 请求/响应模型 ====================

class ChatRequest(BaseModel):
    """发送消息请求"""
    message: str = Field(..., description="用户输入的文本消息")
    attachments: Optional[List[dict]] = Field(None, description="附件列表")
    context: Optional[dict] = Field(None, description="上下文信息")
    action_response: Optional[dict] = Field(None, description="响应之前的 action.request 事件")
    stream: bool = Field(True, description="是否使用流式响应")


class SendMessageResponse(BaseModel):
    """发送消息响应"""
    session_id: str
    message_id: str
    creation_uuid: str
    status: str
    message: str


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
        AgentSession.creation_uuid == creation_uuid
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
    
    - 基于 creation_uuid 自动管理会话上下文
    - 支持多轮对话
    - 返回 SSE 事件流
    """
    async def event_generator():
        """生成 SSE 事件"""
        from app.db.base import _get_async_session_factory
        from app.models.agent_message import MessageRole
        
        session_id = None
        db_inner = None
        assistant_message_id = None
        assistant_content = ""
        
        async def save_user_message(db: AsyncSession, session_id: int, content: str):
            """保存用户消息"""
            try:
                user_msg = AgentMessage(
                    session_id=session_id,
                    role=MessageRole.USER,
                    content=content,
                    event_type=EventType.MESSAGE
                )
                db.add(user_msg)
                await db.commit()
                logger.info(f"已保存用户消息: session_id={session_id}")
            except Exception as e:
                logger.error(f"保存用户消息失败: {e}")
        
        async def save_assistant_message(db: AsyncSession, session_id: int, content: str, intent: str):
            """保存助手消息"""
            try:
                event_map = {
                    "task_intent": EventType.PROGRESS,
                    "status_query": EventType.MESSAGE,
                    "workflow_action": EventType.THINKING,
                }
                assistant_msg = AgentMessage(
                    session_id=session_id,
                    role=MessageRole.ASSISTANT,
                    content=content,
                    event_type=event_map.get("task_intent" if intent in [
                        "analyze_character", "analyze_scene", "analyze_shot",
                        "generate_character_images", "generate_scene_images",
                        "generate_storyboard_images", "generate_videos", "auto_create"
                    ] else "status_query", EventType.MESSAGE),
                    message_metadata={"detected_intent": intent}
                )
                db.add(assistant_msg)
                await db.commit()
                logger.info(f"已保存助手消息: session_id={session_id}, content_length={len(content)}")
            except Exception as e:
                logger.error(f"保存助手消息失败: {e}")
        
        try:
            db_inner = _get_async_session_factory()()
            
            stmt = select(Creation).where(
                Creation.uuid == creation_uuid,
                Creation.owner_id == current_user.user_id
            )
            result = await db_inner.execute(stmt)
            creation = result.scalar_one_or_none()
            
            if not creation:
                yield f"event: error\ndata: {json.dumps({'error': '创作项目不存在或无权限访问'})}\n\n"
                return
            
            session = await get_or_create_session(db_inner, creation_uuid, current_user.user_id)
            
            if not session:
                yield f"event: error\ndata: {json.dumps({'error': '创作项目不存在'})}\n\n"
                return
            
            session_id = session.session_id

            message_id = str(uuid.uuid4())
            yield f"event: message.start\ndata: {json.dumps({'type': 'message.start', 'message_id': message_id})}\n\n"

            user_message = request.message.strip()

            await save_user_message(db_inner, session_id, user_message)

            # 获取聊天历史用于意图判断
            chat_history = []
            try:
                history_stmt = select(AgentMessage).where(
                    AgentMessage.session_id == session_id
                ).order_by(desc(AgentMessage.created_at)).limit(10)
                history_result = await db_inner.execute(history_stmt)
                history_messages = history_result.scalars().all()
                # 反转顺序，使其按时间正序排列
                for msg in reversed(history_messages):
                    chat_history.append({
                        "role": msg.role,
                        "content": msg.content or ""
                    })
            except Exception as e:
                logger.warning(f"获取聊天历史失败: {e}")

            task_intent = await agent_task_handler.detect_task_intent(user_message, chat_history)
            
            debug_info = {
                "user_message": user_message,
                "detected_intent": task_intent,
                "timestamp": datetime.utcnow().isoformat() + "Z"
            }
            yield f"event: debug\ndata: {json.dumps(debug_info)}\n\n"

            task_intents = [
                "analyze_character", "analyze_scene", "analyze_shot",
                "generate_character_images", "generate_scene_images",
                "generate_storyboard_images", "generate_videos", "auto_create"
            ]
            is_task_intent = task_intent in task_intents

            # 新增：设置和提示词相关的意图
            settings_intents = ["modify_settings", "collect_info"]
            is_settings_intent = task_intent in settings_intents

            prompt_intents = ["modify_prompt", "generate_prompt_only"]
            is_prompt_intent = task_intent in prompt_intents

            status_intents = [
                "status_query", "character_query", "scene_query",
                "character_image_query", "scene_image_query", "storyboard_image_query",
                "video_query", "overall_status_query"
            ]
            is_status_query = task_intent in status_intents

            query_types_map = {
                "status_query": ["overall_status"],
                "character_query": ["character_count"],
                "scene_query": ["scene_count"],
                "character_image_query": ["character_image_status"],
                "scene_image_query": ["scene_image_status"],
                "storyboard_image_query": ["storyboard_image_status"],
                "video_query": ["video_status"],
                "overall_status_query": ["overall_status"],
            }

            logger.info(f"意图识别: user_message='{user_message}', intent={task_intent}, is_task={is_task_intent}, is_status={is_status_query}")

            if is_task_intent:
                logger.info(f"检测到任务请求 (intent={task_intent})，进行意图细化分析")

                # 获取上下文信息
                context_info = await agent_task_handler.get_context_for_intent(
                    db_inner, creation_uuid, task_intent
                )

                # 调用意图细化子Agent
                refined_intent = await agent_task_handler.refine_task_intent(
                    intent_type=task_intent,
                    user_message=user_message,
                    chat_history=chat_history,
                    context_info=context_info
                )

                logger.info(f"意图细化结果: {refined_intent}")

                # 发送细化结果到前端（debug事件）
                yield f"event: debug\ndata: {json.dumps({'refined_intent': refined_intent})}\n\n"

                assistant_content = ""
                try:
                    async for sse_chunk in agent_task_handler.execute_refined_task(
                        db_inner, creation_uuid, task_intent, refined_intent
                    ):
                        if sse_chunk:
                            yield sse_chunk
                            if "content" in sse_chunk:
                                try:
                                    data = json.loads(sse_chunk.split("data: ", 1)[1].rstrip("\n\n"))
                                    if "content" in data:
                                        assistant_content += data["content"]
                                except:
                                    pass
                finally:
                    if assistant_content:
                        await save_assistant_message(db_inner, session_id, assistant_content, task_intent)
                    await db_inner.close()
                return

            # 处理设置修改意图
            if is_settings_intent:
                logger.info(f"检测到设置修改请求 (intent={task_intent})")
                assistant_content = ""
                try:
                    async for sse_chunk in agent_task_handler.handle_settings_modification(
                        db_inner, creation_uuid, user_message, chat_history
                    ):
                        if sse_chunk:
                            yield sse_chunk
                            if "delta" in sse_chunk:
                                try:
                                    data = json.loads(sse_chunk.split("data: ", 1)[1].rstrip("\n\n"))
                                    if "delta" in data:
                                        assistant_content += data["delta"]
                                except:
                                    pass
                finally:
                    if assistant_content:
                        await save_assistant_message(db_inner, session_id, assistant_content, task_intent)
                    await db_inner.close()
                return

            # 处理提示词操作意图
            if is_prompt_intent:
                logger.info(f"检测到提示词操作请求 (intent={task_intent})")
                assistant_content = ""
                try:
                    async for sse_chunk in agent_task_handler.handle_prompt_operation(
                        db_inner, creation_uuid, user_message, chat_history, task_intent
                    ):
                        if sse_chunk:
                            yield sse_chunk
                            if "delta" in sse_chunk:
                                try:
                                    data = json.loads(sse_chunk.split("data: ", 1)[1].rstrip("\n\n"))
                                    if "delta" in data:
                                        assistant_content += data["delta"]
                                except:
                                    pass
                finally:
                    if assistant_content:
                        await save_assistant_message(db_inner, session_id, assistant_content, task_intent)
                    await db_inner.close()
                return

            if is_status_query:
                logger.info(f"检测到状态查询 (intent={task_intent})，使用流式输出")

                query_types = query_types_map.get(task_intent, ["overall_status"])
                assistant_content = ""
                try:
                    async for sse_chunk in ai_status_query_handler.generate_ai_response(
                        db_inner, creation_uuid, user_message, query_types
                    ):
                        if sse_chunk:
                            yield sse_chunk
                            if "content" in sse_chunk:
                                try:
                                    data = json.loads(sse_chunk.split("data: ", 1)[1].rstrip("\n\n"))
                                    if "content" in data:
                                        assistant_content += data["content"]
                                except:
                                    pass
                finally:
                    if assistant_content:
                        await save_assistant_message(db_inner, session_id, assistant_content, task_intent)
                    await db_inner.close()
                return

            # 处理 unknown 意图：生成引导性询问
            if task_intent == "unknown":
                logger.info(f"检测到未知意图，生成引导性回复")
                assistant_content = ""
                try:
                    async for sse_chunk in agent_task_handler.generate_clarify_response(user_message, chat_history):
                        if sse_chunk:
                            yield sse_chunk
                            if "delta" in sse_chunk:
                                try:
                                    data = json.loads(sse_chunk.split("data: ", 1)[1].rstrip("\n\n"))
                                    if "delta" in data:
                                        assistant_content += data["delta"]
                                except:
                                    pass
                finally:
                    if assistant_content:
                        await save_assistant_message(db_inner, session_id, assistant_content, task_intent)
                    await db_inner.close()
                return

            await db_inner.close()
            db_inner = None

            script_text = request.context.get("script_text", "") if request.context else ""
            script_url = request.context.get("script_url") if request.context else None

            if not script_text:
                logger.info("尝试从章节获取剧本内容...")
                script_db = _get_async_session_factory()()
                try:
                    script_result = await script_loader.get_script_from_creation(
                        script_db, creation_uuid
                    )
                    if "error" not in script_result:
                        script_text = script_result.get("content", "")
                        logger.info(f"成功获取剧本内容，长度: {len(script_text)}")
                    else:
                        logger.warning(f"获取剧本失败: {script_result.get('error')}")
                finally:
                    await script_db.close()

            graph = ComicDramaGraph(get_async_db)
            
            initial_state: ComicDramaState = {
                "creation_uuid": creation_uuid,
                "thread_id": session.thread_id,
                "user_id": current_user.user_id,
                "session_id": session_id,
                "current_stage": session.current_stage or "init",
                "script_text": script_text,
                "script_url": script_url,
                "characters": [],
                "scenes": [],
                "storyboards": [],
                "audio_segments": [],
                "video_segments": [],
                "final_video": None,
                "messages": [{"role": "system", "content": "工作流已启动"}],
                "errors": [],
                "pending_checkpoint": None,
                "metadata": {}
            }
            
            if request.action_response:
                action_msg = AgentMessage(
                    session_id=session_id,
                    role="user",
                    content=request.message,
                    event_type="action_response",
                    message_metadata=request.action_response
                )
                async_db = _get_async_session_factory()()
                async_db.add(action_msg)
                await async_db.commit()
                await async_db.close()
            
            seen_messages = set()
            assistant_content = ""
            db_for_messages = _get_async_session_factory()()
            
            try:
                async for chunk in graph.run_workflow(
                    initial_state=initial_state,
                    thread_id=session.thread_id
                ):
                    state_update = chunk.get("state", {}) or {}
                    node_name = chunk.get("node", "")
                    
                    logger.info(f"SSE 收到 chunk: node={node_name}, state_type={type(state_update).__name__}")
                    
                    if hasattr(state_update, 'keys'):
                        logger.info(f"SSE state keys: {list(state_update.keys())}")
                    else:
                        logger.warning(f"SSE state 不是字典或为None: {state_update}")
                        continue
                    
                    messages = state_update.get("messages", []) if state_update else []
                    logger.info(f"SSE 消息数量: {len(messages)}, messages={messages}")
                    
                    for msg in messages:
                        msg_content = msg.get("content", "")
                        msg_role = msg.get("role", "assistant")
                        msg_key = f"{msg_role}:{msg_content}"
                        
                        if msg_key not in seen_messages:
                            seen_messages.add(msg_key)
                            
                            if msg_role in ["assistant", "system"]:
                                logger.info(f"SSE 输出消息: role={msg_role}, content={msg_content[:50]}...")
                                msg_data = {
                                    'type': 'message.content',
                                    'message_id': message_id,
                                    'role': 'assistant',
                                    'content': msg_content,
                                    'node': node_name
                                }
                                yield f"event: message\ndata: {json.dumps(msg_data)}\n\n"
                                assistant_content += msg_content + "\n"
                                await asyncio.sleep(0.05)
                    
                    if state_update and state_update.get("errors"):
                        yield f"event: error\ndata: {json.dumps({'error': state_update['errors']})}\n\n"
                        break
                
                yield f"event: message.end\ndata: {json.dumps({'type': 'message.end', 'message_id': message_id, 'finish_reason': 'completed'})}\n\n"
                
            except asyncio.CancelledError:
                yield f"event: message.end\ndata: {json.dumps({'type': 'message.end', 'message_id': message_id, 'finish_reason': 'interrupted'})}\n\n"
            except Exception as e:
                logger.error(f"工作流执行失败: {e}")
                yield f"event: error\ndata: {json.dumps({'error': str(e)})}\n\n"
            finally:
                if assistant_content and db_for_messages:
                    try:
                        await save_assistant_message(db_for_messages, session_id, assistant_content.strip(), "workflow_action")
                    except:
                        pass
                if db_for_messages:
                    await db_for_messages.close()
            
        except Exception as e:
            logger.error(f"SSE 流生成失败: {e}")
            yield f"event: error\ndata: {json.dumps({'error': str(e)})}\n\n"
        finally:
            if db_inner:
                await db_inner.close()
            if 'db_for_messages' in dir() and db_for_messages:
                try:
                    await db_for_messages.close()
                except:
                    pass
    
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
    
    - 基于 creation_uuid 查找会话
    - 返回历史对话记录
    - 支持分页
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
            AgentSession.creation_uuid == creation_uuid
        ).order_by(desc(AgentSession.created_at))
        
        result = await db.execute(session_stmt)
        session = result.scalar_one_or_none()
        
        if not session:
            return {
                "creation_uuid": creation_uuid,
                "messages": [],
                "has_more": False,
                "total_count": 0
            }
        
        msg_stmt = select(AgentMessage).where(
            AgentMessage.session_id == session.session_id
        ).order_by(desc(AgentMessage.created_at)).limit(limit)
        
        result = await db.execute(msg_stmt)
        messages = result.scalars().all()
        
        count_stmt = select(func.count()).select_from(AgentMessage).where(
            AgentMessage.session_id == session.session_id
        )
        count_result = await db.execute(count_stmt)
        total = count_result.scalar()
        
        return {
            "creation_uuid": creation_uuid,
            "messages": [
                {
                    "id": msg.message_id,
                    "role": msg.role,
                    "content": msg.content,
                    "event_type": msg.event_type,
                    "metadata": msg.message_metadata,
                    "timestamp": msg.created_at.isoformat() if msg.created_at else None
                }
                for msg in reversed(messages)
            ],
            "has_more": len(messages) == limit,
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
    
    - 立即终止正在运行的工作流
    - 记录中断事件
    - 返回中断确认
    """
    try:
        stmt = select(AgentSession).where(
            AgentSession.creation_uuid == creation_uuid
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
    
    - 清空对话历史
    - 可选择保留已生成的资产
    - 将会话状态重置为初始状态
    """
    try:
        stmt = select(AgentSession).where(
            AgentSession.creation_uuid == creation_uuid
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
        
        if not request.keep_assets:
            await db.execute(
                delete(AgentMessage).where(AgentMessage.session_id == session.session_id)
            )
        
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
    
    - 返回会话的完整状态信息
    - 包括当前阶段、消息历史、检查点等
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
            AgentSession.user_id == current_user.user_id
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
