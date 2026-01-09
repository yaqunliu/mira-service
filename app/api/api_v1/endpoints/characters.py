from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from app.schemas.character import CharacterUpdate, Character as CharacterSchema, CharacterGenerateImagesRequest, CharacterRegenerateImageRequest
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
    characters = db.query(Character).filter(
        Character.creation_id == creation.creation_id,
        Character.deleted_at.is_(None)
    ).order_by(Character.character_id.asc()).all()
    
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
    - creation_uuid: 创作UUID
    - force_regenerate: 是否强制重新生成（默认False）
      - False: 跳过已有图片的角色（批量生成）
      - True: 强制重新生成所有角色图片（重新生成）
    """
    try:
        result = CharacterService.generate_character_image_service(
            character_uuids=request.character_ids,
            visual_style=request.visual_style,
            creation_uuid=request.creation_uuid,
            force_regenerate=request.force_regenerate,
            db=db
        )
        return success_response(
            data=result,
            message="角色图片生成任务已启动"
        )
    except BaseServiceException as e:
        raise HTTPException(status_code=e.status_code, detail=e.detail)


@router.post("/regenerate-image")
async def regenerate_character_image(
    request: CharacterRegenerateImageRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user)
):
    """
    单个角色重新生成图片

    请求体参数：
    - character_uuid: 角色UUID
    - visual_style: 视觉风格
    - creation_uuid: 创作UUID

    注意：此接口不会触发页面跳转，只返回任务ID供前端轮询
    """
    try:
        # 验证角色是否存在和权限
        from app.models.character import Character
        from app.models.creation import Creation

        character = db.query(Character).filter(Character.uuid == request.character_uuid).first()
        if not character:
            raise HTTPException(status_code=404, detail="角色不存在")

        # 验证权限
        if character.creation_id:
            creation = db.query(Creation).filter(Creation.creation_id == character.creation_id).first()
            if creation and creation.owner_id != user.user_id:
                raise HTTPException(status_code=403, detail="无权限操作该角色")

        # 调用service层生成单个角色图片
        result = CharacterService.regenerate_single_character_image(
            character_uuid=request.character_uuid,
            visual_style=request.visual_style,
            creation_uuid=request.creation_uuid,
            db=db
        )
        return success_response(
            data=result,
            message="角色图片重新生成任务已启动"
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
