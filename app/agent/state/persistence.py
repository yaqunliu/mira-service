"""
状态持久化模块

处理 Graph 状态的保存和恢复，支持 Checkpoint 机制
"""

from typing import Dict, Any, Optional, List
from datetime import datetime
from uuid import uuid4
import json

from sqlalchemy import select
from app.core.logger import logger


class StatePersistence:
    """Graph 状态持久化管理"""
    
    def __init__(self, creation_uuid: str, thread_id: str):
        self.creation_uuid = creation_uuid
        self.thread_id = thread_id
    
    async def save_checkpoint(
        self,
        state: Dict[str, Any],
        checkpoint_type: str = "auto",
    ) -> str:
        """
        保存状态检查点
        
        Args:
            state: 当前 Graph 状态
            checkpoint_type: 检查点类型 (auto/manual/error)
            
        Returns:
            检查点 ID
        """
        try:
            # 使用正确的数据库会话
            from app.db.base import _get_async_session_factory
            from app.models.creation import Creation
            
            checkpoint_id = str(uuid4())
            session = _get_async_session_factory()()
            
            try:
                # 获取 Creation 记录
                result = await session.execute(
                    select(Creation).where(Creation.uuid == self.creation_uuid)
                )
                creation = result.scalar_one_or_none()
                
                if not creation:
                    logger.error(f"[Persistence] Creation 不存在: {self.creation_uuid}")
                    return ""
                
                # 准备检查点数据
                checkpoint_data = {
                    "checkpoint_id": checkpoint_id,
                    "thread_id": self.thread_id,
                    "checkpoint_type": checkpoint_type,
                    "timestamp": datetime.now().isoformat(),
                    "state": _serialize_state(state),
                }
                
                # 保存到 extra_data
                extra_data = creation.extra_data or {}
                checkpoints = extra_data.get("agent_checkpoints", [])
                checkpoints.append(checkpoint_data)
                
                # 只保留最近 10 个检查点
                if len(checkpoints) > 10:
                    checkpoints = checkpoints[-10:]
                
                extra_data["agent_checkpoints"] = checkpoints
                extra_data["last_checkpoint_id"] = checkpoint_id
                
                creation.extra_data = extra_data
                await session.commit()
                
                logger.info(f"[Persistence] 保存检查点: {checkpoint_id}, type={checkpoint_type}")
                return checkpoint_id
            finally:
                await session.close()
                
        except Exception as e:
            logger.error(f"[Persistence] 保存检查点失败: {e}")
            return ""
    
    async def load_checkpoint(
        self,
        checkpoint_id: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        """
        加载状态检查点
        
        Args:
            checkpoint_id: 检查点 ID，None 则加载最新检查点
            
        Returns:
            恢复的状态或 None
        """
        try:
            from app.db.base import _get_async_session_factory
            from app.models.creation import Creation
            
            session = _get_async_session_factory()()
            
            try:
                result = await session.execute(
                    select(Creation).where(Creation.uuid == self.creation_uuid)
                )
                creation = result.scalar_one_or_none()
                
                if not creation:
                    return None
                
                extra_data = creation.extra_data or {}
                checkpoints = extra_data.get("agent_checkpoints", [])
                
                if not checkpoints:
                    return None
                
                # 查找目标检查点
                if checkpoint_id:
                    for cp in checkpoints:
                        if cp.get("checkpoint_id") == checkpoint_id:
                            return _deserialize_state(cp.get("state", {}))
                    return None
                else:
                    # 返回最新检查点
                    latest = checkpoints[-1]
                    return _deserialize_state(latest.get("state", {}))
            finally:
                await session.close()
                
        except Exception as e:
            logger.error(f"[Persistence] 加载检查点失败: {e}")
            return None
    
    async def get_checkpoint_list(self) -> List[Dict[str, Any]]:
        """获取所有检查点列表（仅元数据）"""
        from sqlalchemy import select
        
        try:
            from app.db.base import _get_async_session_factory
            from app.models.creation import Creation
            
            session = _get_async_session_factory()()
            
            try:
                result = await session.execute(
                    select(Creation).where(Creation.uuid == self.creation_uuid)
                )
                creation = result.scalar_one_or_none()
                
                if not creation:
                    return []
                
                extra_data = creation.extra_data or {}
                checkpoints = extra_data.get("agent_checkpoints", [])
                
                # 只返回元数据
                return [
                    {
                        "checkpoint_id": cp.get("checkpoint_id"),
                        "checkpoint_type": cp.get("checkpoint_type"),
                        "timestamp": cp.get("timestamp"),
                    }
                    for cp in checkpoints
                ]
            finally:
                await session.close()
                
        except Exception as e:
            logger.error(f"[Persistence] 获取检查点列表失败: {e}")
            return []
    
    async def clear_checkpoints(self):
        """清除所有检查点"""
        from sqlalchemy import select
        
        try:
            from app.db.base import _get_async_session_factory
            from app.models.creation import Creation
            
            session = _get_async_session_factory()()
            
            try:
                result = await session.execute(
                    select(Creation).where(Creation.uuid == self.creation_uuid)
                )
                creation = result.scalar_one_or_none()
                
                if creation:
                    extra_data = creation.extra_data or {}
                    extra_data["agent_checkpoints"] = []
                    extra_data.pop("last_checkpoint_id", None)
                    creation.extra_data = extra_data
                    await session.commit()
                    
                    logger.info(f"[Persistence] 清除所有检查点: {self.creation_uuid}")
            finally:
                await session.close()
                    
        except Exception as e:
            logger.error(f"[Persistence] 清除检查点失败: {e}")


def _serialize_state(state: Dict[str, Any]) -> Dict[str, Any]:
    """序列化状态（移除不可序列化的对象）"""
    serializable = {}
    
    # 需要保存的关键字段
    keys_to_save = [
        "creation_uuid",
        "thread_id",
        "user_id",
        "current_stage",
        "detected_intent",
        "intent_category",
        "intent_confidence",
        "pending_approval",
        "pending_action",
        "errors",
    ]
    
    for key in keys_to_save:
        if key in state:
            value = state[key]
            try:
                # 测试是否可序列化
                json.dumps(value)
                serializable[key] = value
            except (TypeError, ValueError):
                # 跳过不可序列化的值
                pass
    
    return serializable


def _deserialize_state(data: Dict[str, Any]) -> Dict[str, Any]:
    """反序列化状态"""
    return data
