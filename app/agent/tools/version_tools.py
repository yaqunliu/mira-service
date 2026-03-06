"""
版本管理工具 - Version Tools

提供资源历史版本的查询和恢复功能
历史版本存储在各资源的 status_details.versions 字段中
"""

from typing import Dict, Any, Optional, List
from datetime import datetime

from langchain_core.tools import tool

from app.core.logger import logger


@tool
async def get_version_history(
    target_type: str,
    target_id: int,
) -> Dict[str, Any]:
    """
    获取资源的历史版本列表
    
    Args:
        target_type: 资源类型 (character | scene | shot)
        target_id: 资源 ID
        
    Returns:
        历史版本列表
    """
    logger.info(f"[Version Tool] 获取版本历史: type={target_type}, id={target_id}")
    
    from app.agent.tools.async_db import get_async_session
    from app.models.character import Character
    from app.models.scene import Scene
    from app.models.shot import Shot
    from sqlalchemy import select
    
    async with get_async_session() as db:
        try:
            if target_type == "character":
                stmt = select(Character).where(Character.character_id == target_id)
                result = await db.execute(stmt)
                resource = result.scalar_one_or_none()
                
            elif target_type == "scene":
                stmt = select(Scene).where(Scene.scene_id == target_id)
                result = await db.execute(stmt)
                resource = result.scalar_one_or_none()
                
            elif target_type == "shot":
                stmt = select(Shot).where(Shot.shot_id == target_id)
                result = await db.execute(stmt)
                resource = result.scalar_one_or_none()
            else:
                return {"success": False, "error": f"不支持的资源类型: {target_type}"}
            
            if not resource:
                return {"success": False, "error": f"资源不存在: {target_type}={target_id}"}
            
            # 从 status_details 获取版本历史
            status_details = resource.status_details or {}
            versions = status_details.get("versions", [])
            
            return {
                "success": True,
                "target_type": target_type,
                "target_id": target_id,
                "versions": versions,
                "total_versions": len(versions),
            }
            
        except Exception as e:
            logger.error(f"[Version Tool] 获取版本历史失败: {e}")
            return {"success": False, "error": str(e)}


@tool
async def restore_version(
    target_type: str,
    target_id: int,
    version: int,
    field: Optional[str] = None,
) -> Dict[str, Any]:
    """
    恢复资源到指定历史版本
    
    Args:
        target_type: 资源类型 (character | scene | shot)
        target_id: 资源 ID
        version: 版本号（从1开始）
        field: 要恢复的字段（可选，默认恢复所有）
        
    Returns:
        恢复结果
    """
    logger.info(f"[Version Tool] 恢复版本: type={target_type}, id={target_id}, version={version}")
    
    from app.agent.tools.async_db import get_async_session
    from app.models.character import Character
    from app.models.scene import Scene
    from app.models.shot import Shot
    from sqlalchemy import select
    
    async with get_async_session() as db:
        try:
            if target_type == "character":
                stmt = select(Character).where(Character.character_id == target_id)
                result = await db.execute(stmt)
                resource = result.scalar_one_or_none()
                
            elif target_type == "scene":
                stmt = select(Scene).where(Scene.scene_id == target_id)
                result = await db.execute(stmt)
                resource = result.scalar_one_or_none()
                
            elif target_type == "shot":
                stmt = select(Shot).where(Shot.shot_id == target_id)
                result = await db.execute(stmt)
                resource = result.scalar_one_or_none()
            else:
                return {"success": False, "error": f"不支持的资源类型: {target_type}"}
            
            if not resource:
                return {"success": False, "error": f"资源不存在: {target_type}={target_id}"}
            
            # 获取版本历史
            status_details = resource.status_details or {}
            versions = status_details.get("versions", [])
            
            # 查找指定版本
            target_version = None
            for v in versions:
                if v.get("version") == version:
                    target_version = v
                    break
            
            if not target_version:
                return {
                    "success": False,
                    "error": f"版本不存在: {version}",
                    "available_versions": [v.get("version") for v in versions],
                }
            
            # 恢复字段值
            field_to_restore = field or target_version.get("field")
            value_to_restore = target_version.get("value")
            
            if field_to_restore == "image_url":
                resource.image_url = value_to_restore
            elif field_to_restore == "video_url" and target_type == "shot":
                resource.video_url = value_to_restore
            elif field_to_restore == "end_frame_url" and target_type == "shot":
                extra_data = resource.extra_data or {}
                extra_data["end_frame_url"] = value_to_restore
                resource.extra_data = extra_data
            else:
                return {"success": False, "error": f"无法恢复字段: {field_to_restore}"}
            
            # 记录恢复操作
            restore_record = {
                "version": len(versions) + 1,
                "created_at": datetime.now().isoformat(),
                "field": field_to_restore,
                "value": getattr(resource, field_to_restore, None) if field_to_restore != "end_frame_url" else value_to_restore,
                "trigger": f"restore_from_v{version}",
            }
            versions.append(restore_record)
            status_details["versions"] = versions
            resource.status_details = status_details
            
            await db.commit()
            
            return {
                "success": True,
                "target_type": target_type,
                "target_id": target_id,
                "restored_version": version,
                "restored_field": field_to_restore,
            }
            
        except Exception as e:
            logger.error(f"[Version Tool] 恢复版本失败: {e}")
            return {"success": False, "error": str(e)}


# ==================== 导出 ====================

VERSION_TOOLS = [
    get_version_history,
    restore_version,
]
