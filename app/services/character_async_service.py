from typing import List, Optional
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.schemas.character import CharacterUpdate
from app.models.character import Character
from app.core.exceptions import NotFoundError, BaseServiceException
from app.tasks.character_task import generate_character_image_task
from app.core.logger import logger


class CharacterAsyncService:
    """角色服务类 - 异步版本"""

    @staticmethod
    async def update_character(
        character_id: int,
        character_update: CharacterUpdate,
        db: AsyncSession
    ) -> Character:
        """更新角色信息"""
        result = await db.execute(
            select(Character).where(Character.character_id == character_id)
        )
        character = result.scalar_one_or_none()
        
        if not character:
            raise NotFoundError(detail="角色不存在")
        
        update_data = character_update.model_dump(exclude_unset=True)
        for field, value in update_data.items():
            setattr(character, field, value)
        
        await db.commit()
        await db.refresh(character)
        return character

    @staticmethod
    async def get_character(character_id: int, db: AsyncSession) -> Character:
        """获取角色信息"""
        result = await db.execute(
            select(Character).where(Character.character_id == character_id)
        )
        character = result.scalar_one_or_none()
        
        if not character:
            raise NotFoundError(detail="角色不存在")
        
        return character

    @staticmethod
    async def generate_character_image_service(
        character_uuids: List[str],
        visual_style: str,
        creation_uuid: str,
        force_regenerate: bool,
        db: AsyncSession,
        model_name: Optional[str] = None
    ):
        """生成角色图片"""
        character_ids = []
        for character_uuid in character_uuids:
            result = await db.execute(
                select(Character).where(Character.uuid == character_uuid)
            )
            character = result.scalar_one_or_none()
            if not character:
                continue
            
            character_ids.append(character.character_id)

        try:
            task = generate_character_image_task.delay(
                character_ids,
                visual_style,
                creation_uuid,
                force_regenerate,
                model_name=model_name
            )
            
            return {"message": "角色图片生成任务已创建", "task_id": task.id}
        except Exception as e:
            raise BaseServiceException(message=f"角色图片生成任务创建失败: {e}")

    @staticmethod
    async def regenerate_single_character_image(
        character_uuid: str,
        visual_style: str,
        creation_uuid: str,
        db: AsyncSession,
        model_name: Optional[str] = None,
        image_prompt: Optional[str] = None,
        refresh_prompt: bool = False
    ):
        """重新生成单个角色图片"""
        result = await db.execute(
            select(Character).where(Character.uuid == character_uuid)
        )
        character = result.scalar_one_or_none()
        
        if not character:
            raise NotFoundError(detail=f"uuid为{character_uuid}的角色不存在")

        character_ids = [character.character_id]

        try:
            character.status = "generating"
            
            if image_prompt:
                character.image_prompt = image_prompt
            elif refresh_prompt:
                character.image_prompt = None
                
            await db.commit()
            
            task = generate_character_image_task.delay(
                character_ids,
                visual_style,
                creation_uuid,
                force_regenerate=True,
                model_name=model_name
            )
            
            return {"message": "角色图片生成任务已创建", "task_id": task.id}
        except Exception as e:
            await db.rollback()
            raise BaseServiceException(message=f"角色图片生成任务创建失败: {e}")
