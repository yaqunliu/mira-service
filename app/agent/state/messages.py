"""
消息历史管理模块

管理 Agent 对话的消息历史
"""

from typing import Dict, Any, Optional, List
from datetime import datetime

from app.core.logger import logger


class MessageHistory:
    """消息历史管理"""
    
    def __init__(self, creation_uuid: str, thread_id: str, max_messages: int = 100):
        self.creation_uuid = creation_uuid
        self.thread_id = thread_id
        self.max_messages = max_messages
        self._cache: List[Dict[str, Any]] = []
    
    async def load(self) -> List[Dict[str, Any]]:
        """
        加载消息历史
        
        Returns:
            消息列表
        """
        from sqlalchemy import select
        from app.core.database import get_async_session
        from app.models.creation import Creation
        
        try:
            async with get_async_session() as session:
                result = await session.execute(
                    select(Creation).where(Creation.uuid == self.creation_uuid)
                )
                creation = result.scalar_one_or_none()
                
                if not creation:
                    return []
                
                extra_data = creation.extra_data or {}
                threads = extra_data.get("agent_threads", {})
                thread_data = threads.get(self.thread_id, {})
                
                self._cache = thread_data.get("messages", [])
                return self._cache
                
        except Exception as e:
            logger.error(f"[Messages] 加载消息历史失败: {e}")
            return []
    
    async def save(self, messages: List[Dict[str, Any]]):
        """
        保存消息历史
        
        Args:
            messages: 消息列表
        """
        from sqlalchemy import select
        from app.core.database import get_async_session
        from app.models.creation import Creation
        
        # 限制消息数量
        if len(messages) > self.max_messages:
            messages = messages[-self.max_messages:]
        
        try:
            async with get_async_session() as session:
                result = await session.execute(
                    select(Creation).where(Creation.uuid == self.creation_uuid)
                )
                creation = result.scalar_one_or_none()
                
                if not creation:
                    logger.error(f"[Messages] Creation 不存在: {self.creation_uuid}")
                    return
                
                extra_data = creation.extra_data or {}
                threads = extra_data.get("agent_threads", {})
                
                threads[self.thread_id] = {
                    "messages": messages,
                    "updated_at": datetime.now().isoformat(),
                }
                
                extra_data["agent_threads"] = threads
                creation.extra_data = extra_data
                await session.commit()
                
                self._cache = messages
                logger.debug(f"[Messages] 保存 {len(messages)} 条消息")
                
        except Exception as e:
            logger.error(f"[Messages] 保存消息历史失败: {e}")
    
    async def append(self, message: Dict[str, Any]):
        """
        追加单条消息
        
        Args:
            message: 消息内容
        """
        messages = await self.load()
        
        # 确保必要字段
        if "timestamp" not in message:
            message["timestamp"] = datetime.now().isoformat()
        if "id" not in message:
            from uuid import uuid4
            message["id"] = str(uuid4())
        
        messages.append(message)
        await self.save(messages)
    
    async def append_batch(self, new_messages: List[Dict[str, Any]]):
        """
        批量追加消息
        
        Args:
            new_messages: 消息列表
        """
        messages = await self.load()
        
        for msg in new_messages:
            if "timestamp" not in msg:
                msg["timestamp"] = datetime.now().isoformat()
            if "id" not in msg:
                from uuid import uuid4
                msg["id"] = str(uuid4())
        
        messages.extend(new_messages)
        await self.save(messages)
    
    async def get_recent(self, count: int = 10) -> List[Dict[str, Any]]:
        """
        获取最近的消息
        
        Args:
            count: 消息数量
            
        Returns:
            最近的消息列表
        """
        messages = self._cache or await self.load()
        return messages[-count:] if messages else []
    
    async def clear(self):
        """清空消息历史"""
        await self.save([])
    
    def format_for_llm(self, messages: Optional[List[Dict[str, Any]]] = None) -> str:
        """
        格式化消息用于 LLM 上下文
        
        Args:
            messages: 消息列表，None 则使用缓存
            
        Returns:
            格式化的对话历史字符串
        """
        msgs = messages or self._cache
        
        if not msgs:
            return "（无历史消息）"
        
        formatted = []
        for msg in msgs[-10:]:  # 只取最近 10 条
            role = msg.get("role", "unknown")
            content = msg.get("content", "")
            
            if role == "user":
                formatted.append(f"用户: {content}")
            elif role == "assistant":
                formatted.append(f"助手: {content}")
            elif role == "system":
                formatted.append(f"[系统]: {content}")
        
        return "\n".join(formatted)
    
    def to_langchain_messages(
        self,
        messages: Optional[List[Dict[str, Any]]] = None
    ) -> List:
        """
        转换为 LangChain 消息格式
        
        Args:
            messages: 消息列表，None 则使用缓存
            
        Returns:
            LangChain 消息对象列表
        """
        from langchain_core.messages import HumanMessage, AIMessage, SystemMessage
        
        msgs = messages or self._cache
        lc_messages = []
        
        for msg in msgs:
            role = msg.get("role", "")
            content = msg.get("content", "")
            
            if role == "user":
                lc_messages.append(HumanMessage(content=content))
            elif role == "assistant":
                lc_messages.append(AIMessage(content=content))
            elif role == "system":
                lc_messages.append(SystemMessage(content=content))
        
        return lc_messages
