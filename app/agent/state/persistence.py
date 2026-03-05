"""
状态持久化模块

使用 AgentSession 表保存 Graph 状态
"""

from typing import Dict, Any, Optional, List
from datetime import datetime
from uuid import uuid4
import json

from sqlalchemy import select
from app.core.logger import logger


class StatePersistence:
    """Graph 状态持久化管理 - 使用 AgentSession 表"""
    
    def __init__(self, creation_uuid: str, thread_id: str):
        self.creation_uuid = creation_uuid
        self.thread_id = thread_id
    
    async def save_checkpoint(
        self,
        state: Dict[str, Any],
        checkpoint_type: str = "auto",
    ) -> str:
        """
        保存状态检查点到 AgentSession 表
        
        Args:
            state: 当前 Graph 状态
            checkpoint_type: 检查点类型 (auto/manual/error)
            
        Returns:
            检查点 ID
        """
        try:
            from app.db.base import _get_async_session_factory
            from app.models.agent_session import AgentSession
            
            session = _get_async_session_factory()()
            
            try:
                # 查找 AgentSession
                result = await session.execute(
                    select(AgentSession).where(AgentSession.thread_id == self.thread_id)
                )
                agent_session = result.scalar_one_or_none()
                
                if not agent_session:
                    logger.warning(f"[Persistence] AgentSession 不存在: thread_id={self.thread_id}")
                    return ""
                
                # 更新 session 状态
                agent_session.checkpoint_data = state
                
                await session.commit()
                logger.info(f"[Persistence] 保存状态成功: thread_id={self.thread_id}, checkpoint_type={checkpoint_type}")
                
                return str(uuid4())
                
            except Exception as e:
                await session.rollback()
                logger.error(f"[Persistence] 保存状态失败: {e}")
                return ""
            finally:
                await session.close()
                
        except Exception as e:
            logger.error(f"[Persistence] 保存状态异常: {e}")
            return ""
    
    async def load_checkpoint(
        self,
        checkpoint_id: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        """
        从 AgentSession 表加载状态检查点
        
        Args:
            checkpoint_id: 检查点 ID，None 则加载最新
            
        Returns:
            恢复的状态或 None
        """
        try:
            from app.db.base import _get_async_session_factory
            from app.models.agent_session import AgentSession
            
            session = _get_async_session_factory()()
            
            try:
                result = await session.execute(
                    select(AgentSession).where(AgentSession.thread_id == self.thread_id)
                )
                agent_session = result.scalar_one_or_none()
                
                if not agent_session:
                    logger.warning(f"[Persistence] AgentSession 不存在: thread_id={self.thread_id}")
                    return None
                
                checkpoint_data = agent_session.checkpoint_data
                
                if checkpoint_data:
                    logger.info(f"[Persistence] 加载状态成功: thread_id={self.thread_id}")
                    return checkpoint_data
                else:
                    logger.info(f"[Persistence] 无保存的状态: thread_id={self.thread_id}")
                    return None
                    
            finally:
                await session.close()
                
        except Exception as e:
            logger.error(f"[Persistence] 加载状态失败: {e}")
            return None
