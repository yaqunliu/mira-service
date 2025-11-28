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
    def generate_character_image_service(character_ids: List[int], visual_style: str, db: Session):
        """生成角色图片"""
        for character_id in character_ids:
            character = db.query(Character).filter(Character.character_id == character_id).first()
            if not character:
                raise NotFoundError(detail=f"character_id为{character_id}的角色不存在")
        try:
            task = generate_character_image_task.delay(character_ids, visual_style)

            return {"message": "角色图片生成任务已创建", "task_id": task.id}
        except Exception as e:
            raise BaseServiceException(message=f"角色图片生成任务创建失败: {e}")