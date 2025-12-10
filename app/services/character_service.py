from click import Option
from app.schemas.character import CharacterUpdate
from app.models.character import Character
from app.core.exceptions import NotFoundError, BaseServiceException 
from sqlalchemy.orm import Session
from typing import List, Optional
from app.tasks.character_task import generate_character_image_task


class CharacterService:
    """角色服务类"""

    @staticmethod
    def update_character(character_id: int, character_update: CharacterUpdate, db: Session) -> Character:
        """更新角色信息"""
        character = db.query(Character).filter(Character.character_id == character_id).first()
        if not character:
            raise NotFoundError(detail="角色不存在")
        
        # 更新角色属性（只更新提供的字段）
        update_data = character_update.model_dump(exclude_unset=True)
        for field, value in update_data.items():
            setattr(character, field, value)
        
        db.commit()
        db.refresh(character)
        return character

    @staticmethod
    def get_character(character_id: int, db: Session) -> Character:
        """获取角色信息"""
        character = db.query(Character).filter(Character.character_id == character_id).first()
        if not character:
            raise NotFoundError(detail="角色不存在")
        return character

    @staticmethod
    def generate_character_image_service(
        character_uuids: List[str],
        visual_style: str,
        creation_uuid: str,
        force_regenerate: bool,
        db: Session
    ):
        """生成角色图片"""
        # 将UUID转换为整数ID
        character_ids = []
        for character_uuid in character_uuids:
            character = db.query(Character).filter(Character.uuid == character_uuid).first()
            if not character:
                # raise NotFoundError(detail=f"uuid为{character_uuid}的角色不存在")
                continue

            character_ids.append(character.character_id)

        try:
            # 传递 creation_uuid 到 Celery 任务
            task = generate_character_image_task.delay(
                character_ids,
                visual_style,
                creation_uuid,
                force_regenerate
            )

            return {"message": "角色图片生成任务已创建", "task_id": task.id}
        except Exception as e:
            raise BaseServiceException(message=f"角色图片生成任务创建失败: {e}")

    @staticmethod
    def regenerate_single_character_image(
        character_uuid: str,
        visual_style: str,
        creation_uuid: str,
        db: Session
    ):
        """重新生成单个角色图片（不触发页面跳转，不更新creation状态）"""
        # 将UUID转换为整数ID
        character = db.query(Character).filter(Character.uuid == character_uuid).first()
        if not character:
            raise NotFoundError(detail=f"uuid为{character_uuid}的角色不存在")

        character_ids = [character.character_id]

        try:
            # 传递 creation_uuid 到 Celery 任务
            # force_regenerate=True 强制重新生成
            # 注意：这个任务不会更新 creation 的 current_task_id，因此不会触发页面跳转
            task = generate_character_image_task.delay(
                character_ids,
                visual_style,
                creation_uuid,
                True,  # force_regenerate=True
                False  # update_creation_task=False (不更新creation的current_task_id)
            )

            return {"message": "角色图片重新生成任务已创建", "task_id": task.id}
        except Exception as e:
            raise BaseServiceException(message=f"角色图片重新生成任务创建失败: {e}")