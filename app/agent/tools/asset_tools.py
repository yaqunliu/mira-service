"""
资产库工具 - Asset Library Tools

提供 Agent 读取和写入角色、场景、道具资产的工具
"""

from typing import Dict, Any, List, Optional, Callable
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update
from app.agent.tools.base import BaseTool
from app.agent.state.schemas import ComicDramaState, CharacterState, SceneState
from app.models.character import Character
from app.models.scene import Scene
from app.models.asset import Asset
from app.core.logger import logger
from app.db.base import AsyncSessionLocal


class ReadCharacterTool(BaseTool):
    """读取角色资产工具"""
    
    name = "read_character"
    description = "读取角色资产的详细信息，包括外貌、性格、参考图等"
    
    async def execute(
        self,
        state: ComicDramaState,
        character_id: Optional[int] = None,
        character_name: Optional[str] = None,
        **kwargs
    ) -> Dict[str, Any]:
        """
        读取角色资产
        
        Args:
            character_id: 角色数据库 ID
            character_name: 角色名称（如果 ID 未提供）
        """
        async with AsyncSessionLocal() as db:
            try:
                if character_id:
                    stmt = select(Character).where(Character.character_id == character_id)
                elif character_name:
                    creation_uuid = state.get("creation_uuid")
                    stmt = select(Character).where(
                        Character.creation_id == creation_uuid,
                        Character.name == character_name
                    )
                else:
                    return {"success": False, "error": "必须提供 character_id 或 character_name"}
                
                result = await db.execute(stmt)
                character = result.scalar_one_or_none()
                
                if not character:
                    return {"success": False, "error": f"未找到角色: {character_id or character_name}"}
                
                return {
                    "success": True,
                    "character": {
                        "character_id": character.character_id,
                        "name": character.name,
                        "description": character.basic_info or "",
                        "appearance": character.appearance or "",
                        "body": character.body or "",
                        "hair": character.hair or "",
                        "clothing": character.clothing or "",
                        "tags": character.tags or [],
                        "image_url": character.image_url or "",
                        "voice_description": character.voice_description or ""
                    }
                }
                
            except Exception as e:
                logger.error(f"读取角色失败: {e}")
                return {"success": False, "error": str(e)}


class WriteCharacterTool(BaseTool):
    """写入角色资产工具"""
    
    name = "write_character"
    description = "保存或更新角色资产到数据库"
    
    async def execute(
        self,
        state: ComicDramaState,
        character_data: Dict[str, Any],
        character_id: Optional[int] = None,
        **kwargs
    ) -> Dict[str, Any]:
        """
        写入角色资产
        
        Args:
            character_data: 角色数据字典
            character_id: 如果提供则更新现有角色，否则创建新角色
        """
        try:
            creation_id = state.get("creation_id")
            
            if character_id:
                # 更新现有角色
                stmt = select(Character).where(Character.character_id == character_id)
                result = await self.db.execute(stmt)
                character = result.scalar_one_or_none()
                
                if not character:
                    return {"success": False, "error": f"角色不存在: {character_id}"}
                
                # 更新字段
                for key, value in character_data.items():
                    if hasattr(character, key):
                        setattr(character, key, value)
                
                await self.db.commit()
                await self.db.refresh(character)
                
                return {
                    "success": True,
                    "character_id": character.character_id,
                    "message": "角色已更新"
                }
            else:
                # 创建新角色
                character = Character(
                    creation_id=creation_id,
                    name=character_data.get("name"),
                    description=character_data.get("description"),
                    personality=character_data.get("personality"),
                    appearance=character_data.get("appearance"),
                    image_url=character_data.get("image_url"),
                    voice_id=character_data.get("voice_id"),
                    reference_images=character_data.get("reference_images", [])
                )
                
                self.db.add(character)
                await self.db.commit()
                await self.db.refresh(character)
                
                return {
                    "success": True,
                    "character_id": character.character_id,
                    "message": "角色已创建"
                }
                
        except Exception as e:
            await self.db.rollback()
            logger.error(f"写入角色失败: {e}")
            return {"success": False, "error": str(e)}


class ReadSceneTool(BaseTool):
    """读取场景资产工具"""
    
    name = "read_scene"
    description = "读取场景资产的详细信息，包括环境描述、氛围、参考图等"
    
    async def execute(
        self,
        state: ComicDramaState,
        scene_id: Optional[int] = None,
        scene_name: Optional[str] = None,
        **kwargs
    ) -> Dict[str, Any]:
        """读取场景资产"""
        try:
            if scene_id:
                stmt = select(Scene).where(Scene.scene_id == scene_id)
            elif scene_name:
                creation_id = state.get("creation_id")
                stmt = select(Scene).where(
                    Scene.creation_id == creation_id,
                    Scene.name == scene_name
                )
            else:
                return {"success": False, "error": "必须提供 scene_id 或 scene_name"}
            
            result = await self.db.execute(stmt)
            scene = result.scalar_one_or_none()
            
            if not scene:
                return {"success": False, "error": f"未找到场景: {scene_id or scene_name}"}
            
            return {
                "success": True,
                "scene": {
                    "scene_id": scene.scene_id,
                    "name": scene.name,
                    "description": scene.description,
                    "location": scene.location,
                    "time": scene.time,
                    "mood": scene.mood,
                    "image_url": scene.image_url,
                    "reference_images": scene.reference_images or []
                }
            }
            
        except Exception as e:
            logger.error(f"读取场景失败: {e}")
            return {"success": False, "error": str(e)}


class WriteSceneTool(BaseTool):
    """写入场景资产工具"""
    
    name = "write_scene"
    description = "保存或更新场景资产到数据库"
    
    async def execute(
        self,
        state: ComicDramaState,
        scene_data: Dict[str, Any],
        scene_id: Optional[int] = None,
        **kwargs
    ) -> Dict[str, Any]:
        """写入场景资产"""
        try:
            creation_id = state.get("creation_id")
            
            if scene_id:
                stmt = select(Scene).where(Scene.scene_id == scene_id)
                result = await self.db.execute(stmt)
                scene = result.scalar_one_or_none()
                
                if not scene:
                    return {"success": False, "error": f"场景不存在: {scene_id}"}
                
                for key, value in scene_data.items():
                    if hasattr(scene, key):
                        setattr(scene, key, value)
                
                await self.db.commit()
                await self.db.refresh(scene)
                
                return {
                    "success": True,
                    "scene_id": scene.scene_id,
                    "message": "场景已更新"
                }
            else:
                scene = Scene(
                    creation_id=creation_id,
                    name=scene_data.get("name"),
                    description=scene_data.get("description"),
                    location=scene_data.get("location"),
                    time=scene_data.get("time"),
                    mood=scene_data.get("mood"),
                    image_url=scene_data.get("image_url"),
                    reference_images=scene_data.get("reference_images", [])
                )
                
                self.db.add(scene)
                await self.db.commit()
                await self.db.refresh(scene)
                
                return {
                    "success": True,
                    "scene_id": scene.scene_id,
                    "message": "场景已创建"
                }
                
        except Exception as e:
            await self.db.rollback()
            logger.error(f"写入场景失败: {e}")
            return {"success": False, "error": str(e)}


class SearchAssetsTool(BaseTool):
    """搜索资产工具"""
    
    name = "search_assets"
    description = "根据关键词搜索资产库中的角色、场景或道具"
    
    async def execute(
        self,
        state: ComicDramaState,
        query: str,
        asset_type: Optional[str] = None,  # "character", "scene", "prop"
        limit: int = 10,
        **kwargs
    ) -> Dict[str, Any]:
        """
        搜索资产
        
        Args:
            query: 搜索关键词
            asset_type: 资产类型过滤
            limit: 返回结果数量限制
        """
        try:
            creation_id = state.get("creation_id")
            results = []
            
            # 搜索角色
            if not asset_type or asset_type == "character":
                stmt = select(Character).where(
                    Character.creation_id == creation_id,
                    (Character.name.ilike(f"%{query}%")) |
                    (Character.description.ilike(f"%{query}%"))
                ).limit(limit)
                
                result = await self.db.execute(stmt)
                characters = result.scalars().all()
                
                for char in characters:
                    results.append({
                        "type": "character",
                        "id": char.character_id,
                        "name": char.name,
                        "description": char.description[:100] + "..." if char.description else ""
                    })
            
            # 搜索场景
            if not asset_type or asset_type == "scene":
                stmt = select(Scene).where(
                    Scene.creation_id == creation_id,
                    (Scene.name.ilike(f"%{query}%")) |
                    (Scene.description.ilike(f"%{query}%"))
                ).limit(limit)
                
                result = await self.db.execute(stmt)
                scenes = result.scalars().all()
                
                for scene in scenes:
                    results.append({
                        "type": "scene",
                        "id": scene.scene_id,
                        "name": scene.name,
                        "description": scene.description[:100] + "..." if scene.description else ""
                    })
            
            return {
                "success": True,
                "query": query,
                "asset_type": asset_type,
                "results": results,
                "total_count": len(results)
            }
            
        except Exception as e:
            logger.error(f"搜索资产失败: {e}")
            return {"success": False, "error": str(e)}


class ListAssetsTool(BaseTool):
    """列出所有资产工具"""
    
    name = "list_assets"
    description = "列出当前创作项目的所有资产（角色、场景）"
    
    async def execute(
        self,
        state: ComicDramaState,
        asset_type: Optional[str] = None,
        **kwargs
    ) -> Dict[str, Any]:
        """列出资产"""
        try:
            creation_id = state.get("creation_id")
            assets = {"characters": [], "scenes": []}
            
            if not asset_type or asset_type == "character":
                stmt = select(Character).where(Character.creation_id == creation_id)
                result = await self.db.execute(stmt)
                characters = result.scalars().all()
                
                assets["characters"] = [
                    {
                        "character_id": c.character_id,
                        "name": c.name,
                        "description": c.description,
                        "image_url": c.image_url,
                        "status": "completed" if c.image_url else "pending"
                    }
                    for c in characters
                ]
            
            if not asset_type or asset_type == "scene":
                stmt = select(Scene).where(Scene.creation_id == creation_id)
                result = await self.db.execute(stmt)
                scenes = result.scalars().all()
                
                assets["scenes"] = [
                    {
                        "scene_id": s.scene_id,
                        "name": s.name,
                        "description": s.description,
                        "image_url": s.image_url,
                        "status": "completed" if s.image_url else "pending"
                    }
                    for s in scenes
                ]
            
            return {
                "success": True,
                "assets": assets,
                "summary": {
                    "total_characters": len(assets["characters"]),
                    "total_scenes": len(assets["scenes"]),
                    "completed_characters": sum(1 for c in assets["characters"] if c["status"] == "completed"),
                    "completed_scenes": sum(1 for s in assets["scenes"] if s["status"] == "completed")
                }
            }
            
        except Exception as e:
            logger.error(f"列出资产失败: {e}")
            return {"success": False, "error": str(e)}
