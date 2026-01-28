from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from pydantic import BaseModel
from typing import Optional
from app.schemas.character import CharacterUpdate, Character as CharacterSchema, CharacterGenerateImagesRequest, CharacterRegenerateImageRequest
from app.core.exceptions import BaseServiceException
from app.services.character_async_service import CharacterAsyncService
from app.api.deps import get_async_db, get_current_user
from app.models.user import User
from app.utils.response import success_response

router = APIRouter()


@router.get("/creation/{creation_uuid}")
async def get_creation_characters(
    creation_uuid: str,
    db: AsyncSession = Depends(get_async_db),
    user: User = Depends(get_current_user)
):
    """获取创作项目的角色列表"""
    from app.models.creation import Creation
    from app.models.character import Character
    
    result = await db.execute(
        select(Creation).where(Creation.uuid == creation_uuid)
    )
    creation = result.scalar_one_or_none()
    
    if not creation:
        raise HTTPException(status_code=404, detail="创作项目不存在")
    
    if creation.owner_id != user.user_id:
        raise HTTPException(status_code=403, detail="无权限访问该创作项目")
    
    result = await db.execute(
        select(Character).where(
            Character.creation_id == creation.creation_id,
            Character.deleted_at.is_(None)
        ).order_by(Character.character_id.asc())
    )
    characters = result.scalars().all()
    
    return success_response(
        data=[CharacterSchema.model_validate(char).model_dump() for char in characters],
        message="获取角色列表成功"
    )


@router.post("/")
async def create_character():
    """创建新角色"""
    pass


@router.get("/{character_uuid}")
async def get_character(
    character_uuid: str,
    db: AsyncSession = Depends(get_async_db),
    user: User = Depends(get_current_user)
):
    """根据UUID获取角色详情"""
    from app.models.character import Character
    from app.models.creation import Creation
    
    result = await db.execute(
        select(Character).where(Character.uuid == character_uuid)
    )
    character = result.scalar_one_or_none()
    
    if not character:
        raise HTTPException(status_code=404, detail="角色不存在")
    
    if character.creation_id:
        result = await db.execute(
            select(Creation).where(Creation.creation_id == character.creation_id)
        )
        creation = result.scalar_one_or_none()
        if creation and creation.owner_id != user.user_id:
            raise HTTPException(status_code=403, detail="无权限访问该角色")
    
    return success_response(
        data=CharacterSchema.model_validate(character).model_dump(),
        message="获取角色成功"
    )


@router.put("/{character_uuid}")
async def update_character(
    character_uuid: str,
    character_update: CharacterUpdate,
    db: AsyncSession = Depends(get_async_db),
    user: User = Depends(get_current_user)
):
    """更新角色信息"""
    from app.models.character import Character
    from app.models.creation import Creation
    
    result = await db.execute(
        select(Character).where(Character.uuid == character_uuid)
    )
    character = result.scalar_one_or_none()
    
    if not character:
        raise HTTPException(status_code=404, detail="角色不存在")
    
    if character.creation_id:
        result = await db.execute(
            select(Creation).where(Creation.creation_id == character.creation_id)
        )
        creation = result.scalar_one_or_none()
        if creation and creation.owner_id != user.user_id:
            raise HTTPException(status_code=403, detail="无权限修改该角色")
    
    try:
        character = await CharacterAsyncService.update_character(character.character_id, character_update, db)
        return success_response(
            data=CharacterSchema.model_validate(character).model_dump(),
            message="角色更新成功"
        )
    except BaseServiceException as e:
        raise HTTPException(status_code=e.status_code, detail=e.detail)


@router.post("/generate-images")
async def generate_character_image(
    request: CharacterGenerateImagesRequest,
    db: AsyncSession = Depends(get_async_db)
):
    """生成角色图片"""
    try:
        result = await CharacterAsyncService.generate_character_image_service(
            character_uuids=request.character_ids,
            visual_style=request.visual_style,
            creation_uuid=request.creation_uuid,
            force_regenerate=request.force_regenerate,
            model_name=request.model_name,
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
    db: AsyncSession = Depends(get_async_db),
    user: User = Depends(get_current_user)
):
    """单个角色重新生成图片"""
    try:
        from app.models.character import Character
        from app.models.creation import Creation

        result = await db.execute(
            select(Character).where(Character.uuid == request.character_uuid)
        )
        character = result.scalar_one_or_none()
        
        if not character:
            raise HTTPException(status_code=404, detail="角色不存在")

        if character.creation_id:
            result = await db.execute(
                select(Creation).where(Creation.creation_id == character.creation_id)
            )
            creation = result.scalar_one_or_none()
            if creation and creation.owner_id != user.user_id:
                raise HTTPException(status_code=403, detail="无权限操作该角色")

        result = await CharacterAsyncService.regenerate_single_character_image(
            character_uuid=request.character_uuid,
            visual_style=request.visual_style,
            creation_uuid=request.creation_uuid,
            model_name=request.model_name,
            image_prompt=request.image_prompt,
            refresh_prompt=request.refresh_prompt,
            db=db
        )
        return success_response(
            data=result,
            message="角色图片重新生成任务已启动"
        )
    except BaseServiceException as e:
        raise HTTPException(status_code=e.status_code, detail=e.detail)


@router.delete("/{character_uuid}")
async def delete_character(
    character_uuid: str,
    db: AsyncSession = Depends(get_async_db),
    user: User = Depends(get_current_user)
):
    """删除角色"""
    from app.models.character import Character
    from app.models.creation import Creation

    result = await db.execute(
        select(Character).where(Character.uuid == character_uuid)
    )
    character = result.scalar_one_or_none()
    
    if not character:
        raise HTTPException(status_code=404, detail="角色不存在")

    if character.creation_id:
        result = await db.execute(
            select(Creation).where(Creation.creation_id == character.creation_id)
        )
        creation = result.scalar_one_or_none()
        if creation and creation.owner_id != user.user_id:
            raise HTTPException(status_code=403, detail="无权限删除该角色")

    await db.delete(character)
    await db.commit()

    return success_response(
        data={"character_uuid": character_uuid},
        message="角色删除成功"
    )


class ApplyImageVersionRequest(BaseModel):
    version_id: str
    image_url: str
    image_prompt: Optional[str] = None


@router.get("/{character_uuid}/image-history")
async def get_character_image_history(
    character_uuid: str,
    db: AsyncSession = Depends(get_async_db),
    user: User = Depends(get_current_user)
):
    """获取角色图片生成历史"""
    from app.models.character import Character
    from app.models.creation import Creation

    result = await db.execute(
        select(Character).where(Character.uuid == character_uuid)
    )
    character = result.scalar_one_or_none()
    
    if not character:
        raise HTTPException(status_code=404, detail="角色不存在")

    if character.creation_id:
        result = await db.execute(
            select(Creation).where(Creation.creation_id == character.creation_id)
        )
        creation = result.scalar_one_or_none()
        if creation and creation.owner_id != user.user_id:
            raise HTTPException(status_code=403, detail="无权限访问该角色")

    image_history = character.status_detail.get('image_history', []) if character.status_detail else []
    
    return success_response(
        data={
            "current_image_url": character.image_url,
            "current_image_prompt": character.image_prompt,
            "image_history": image_history
        },
        message="获取角色图片历史成功"
    )


@router.post("/{character_uuid}/apply-image-version")
async def apply_character_image_version(
    character_uuid: str,
    request: ApplyImageVersionRequest,
    db: AsyncSession = Depends(get_async_db),
    user: User = Depends(get_current_user)
):
    """将历史图片应用为角色的当前图片"""
    from app.models.character import Character
    from app.models.creation import Creation

    result = await db.execute(
        select(Character).where(Character.uuid == character_uuid)
    )
    character = result.scalar_one_or_none()
    
    if not character:
        raise HTTPException(status_code=404, detail="角色不存在")

    if character.creation_id:
        result = await db.execute(
            select(Creation).where(Creation.creation_id == character.creation_id)
        )
        creation = result.scalar_one_or_none()
        if creation and creation.owner_id != user.user_id:
            raise HTTPException(status_code=403, detail="无权限操作该角色")

    image_history = character.status_detail.get('image_history', []) if character.status_detail else []
    
    version_found = any(v.get('version_id') == request.version_id for v in image_history)
    
    if not version_found:
        raise HTTPException(status_code=404, detail="指定的版本不存在")

    character.image_url = request.image_url
    if request.image_prompt:
        character.image_prompt = request.image_prompt

    for version in image_history:
        version['is_current'] = version.get('version_id') == request.version_id
    
    character.status_detail['image_history'] = image_history
    
    await db.commit()
    await db.refresh(character)

    return success_response(
        data={
            "character_uuid": character_uuid,
            "image_url": character.image_url,
            "image_prompt": character.image_prompt
        },
        message="应用历史图片成功"
    )
