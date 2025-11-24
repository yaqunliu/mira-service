from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from app.schemas.character import CharacterUpdate, Character as CharacterSchema, CharacterGenerateImagesRequest
from app.core.exceptions import BaseServiceException
from app.services.character_service import CharacterService
from app.api.deps import get_db
from app.utils.response import success_response

router = APIRouter()


@router.get("/creation/{creation_id}")
async def get_creation_characters(creation_id: int):
    """获取创作项目的角色列表"""
    # TODO: 实现获取角色列表逻辑
    pass


@router.post("/")
async def create_character():
    """创建新角色"""
    # TODO: 实现创建角色逻辑
    pass


@router.get("/{character_id}")
async def get_character(character_id: int):
    """根据ID获取角色详情"""
    # TODO: 实现获取角色详情逻辑
    pass


@router.put("/{character_id}")
async def update_character(character_id: int, character_update: CharacterUpdate, db: Session = Depends(get_db)):
    """更新角色信息"""
    try:
        character = CharacterService.update_character(character_id, character_update, db)
        # 将 SQLAlchemy 模型转换为 Pydantic schema 并返回
        return success_response(
            data=CharacterSchema.model_validate(character).model_dump(),
            message="角色更新成功"
        )
    except BaseServiceException as e:
        raise HTTPException(status_code=e.status_code, detail=e.detail)


@router.post("/generate-images")
async def generate_character_image(
    request: CharacterGenerateImagesRequest,
    db: Session = Depends(get_db)
):
    """
    生成角色图片
    
    请求体参数：
    - character_ids: 角色ID列表
    - visual_style: 视觉风格
    """
    try:
        result = CharacterService.generate_character_image_service(
            character_ids=request.character_ids,
            visual_style=request.visual_style,
            db=db
        )
        return success_response(
            data=result,
            message="角色图片生成任务已启动"
        )
    except BaseServiceException as e:
        raise HTTPException(status_code=e.status_code, detail=e.detail)


@router.delete("/{character_id}")
async def delete_character(character_id: int):
    """删除角色"""
    # TODO: 实现删除角色逻辑
    pass
