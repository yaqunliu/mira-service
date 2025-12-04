from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from app.schemas.character import CharacterUpdate, Character as CharacterSchema, CharacterGenerateImagesRequest
from app.core.exceptions import BaseServiceException
from app.services.character_service import CharacterService
from app.api.deps import get_db, get_current_user
from app.models.user import User
from app.utils.response import success_response

router = APIRouter()


@router.get("/creation/{creation_uuid}")
async def get_creation_characters(creation_uuid: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """获取创作项目的角色列表"""
    from app.models.creation import Creation
    from app.models.character import Character
    
    # 验证创作项目是否存在
    creation = db.query(Creation).filter(Creation.uuid == creation_uuid).first()
    if not creation:
        raise HTTPException(status_code=404, detail="创作项目不存在")
    
    # 验证权限
    if creation.owner_id != user.user_id:
        raise HTTPException(status_code=403, detail="无权限访问该创作项目")
    
    # 获取角色列表
    characters = db.query(Character).filter(Character.creation_id == creation.creation_id).all()
    
    return success_response(
        data=[CharacterSchema.model_validate(char).model_dump() for char in characters],
        message="获取角色列表成功"
    )


@router.post("/")
async def create_character():
    """创建新角色"""
    # TODO: 实现创建角色逻辑
    pass


@router.get("/{character_uuid}")
async def get_character(character_uuid: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """根据UUID获取角色详情"""
    from app.models.character import Character
    from app.models.creation import Creation
    
    character = db.query(Character).filter(Character.uuid == character_uuid).first()
    if not character:
        raise HTTPException(status_code=404, detail="角色不存在")
    
    # 验证权限
    if character.creation_id:
        creation = db.query(Creation).filter(Creation.creation_id == character.creation_id).first()
        if creation and creation.owner_id != user.user_id:
            raise HTTPException(status_code=403, detail="无权限访问该角色")
    
    return success_response(
        data=CharacterSchema.model_validate(character).model_dump(),
        message="获取角色成功"
    )


@router.put("/{character_uuid}")
async def update_character(character_uuid: str, character_update: CharacterUpdate, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """更新角色信息"""
    from app.models.character import Character
    from app.models.creation import Creation
    
    character = db.query(Character).filter(Character.uuid == character_uuid).first()
    if not character:
        raise HTTPException(status_code=404, detail="角色不存在")
    
    # 验证权限
    if character.creation_id:
        creation = db.query(Creation).filter(Creation.creation_id == character.creation_id).first()
        if creation and creation.owner_id != user.user_id:
            raise HTTPException(status_code=403, detail="无权限修改该角色")
    
    try:
        character = CharacterService.update_character(character.character_id, character_update, db)
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
            character_uuids=request.character_ids,
            visual_style=request.visual_style,
            db=db
        )
        return success_response(
            data=result,
            message="角色图片生成任务已启动"
        )
    except BaseServiceException as e:
        raise HTTPException(status_code=e.status_code, detail=e.detail)


@router.delete("/{character_uuid}")
async def delete_character(character_uuid: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """删除角色"""
    from app.models.character import Character
    from app.models.creation import Creation
    
    character = db.query(Character).filter(Character.uuid == character_uuid).first()
    if not character:
        raise HTTPException(status_code=404, detail="角色不存在")
    
    # 验证权限
    if character.creation_id:
        creation = db.query(Creation).filter(Creation.creation_id == character.creation_id).first()
        if creation and creation.owner_id != user.user_id:
            raise HTTPException(status_code=403, detail="无权限删除该角色")
    
    db.delete(character)
    db.commit()
    
    return success_response(
        data={"character_uuid": character_uuid},
        message="角色删除成功"
    )
