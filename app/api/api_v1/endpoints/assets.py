import uuid
import hmac
import hashlib
import base64
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from typing import List

from app.api.deps import get_async_db, get_current_user
from app.models.user import User
from app.models.asset import Asset, AssetType
from app.schemas.asset import (
    AssetCreate,
    AssetUpdate,
    AssetResponse,
    US3SignatureRequest,
    US3SignatureResponse,
)
from app.utils.response import success_response
from app.core.config import settings
from app.core.logger import logger
from app.utils.upload_helper import upload_helper

router = APIRouter()


@router.post("/upload-signature")
async def get_upload_signature(
    request: US3SignatureRequest,
    user: User = Depends(get_current_user),
):
    """获取US3上传签名"""
    try:
        file_ext = request.file_name.split('.')[-1] if '.' in request.file_name else ''
        timestamp = datetime.now().strftime('%Y%m%d%H%M%S')
        unique_filename = f"{timestamp}_{uuid.uuid4().hex[:8]}.{file_ext}"

        file_key = upload_helper.generate_upload_path(
            user_uuid=user.uuid,
            file_type="assets",
            filename=unique_filename
        )

        bucket_name = settings.US3_BUCKET or settings.DEFAULT_BUCKET or 'novel-agent'
        access_key = settings.US3_PUBLIC_KEY
        secret_key = settings.US3_PRIVATE_KEY
        region = settings.US3_REGION or 'cn-sh2'

        upload_url = f"https://{bucket_name}.{region}.ufileos.com/"

        http_verb = "POST"
        content_md5 = ""
        content_type = request.file_type
        date = ""
        canonicalized_ucloud_headers = ""
        canonicalized_resource = f"/{bucket_name}/{file_key}"

        string_to_sign = f"{http_verb}\n{content_md5}\n{content_type}\n{date}\n{canonicalized_ucloud_headers}{canonicalized_resource}"

        signature = base64.b64encode(
            hmac.new(
                secret_key.encode('utf-8'),
                string_to_sign.encode('utf-8'),
                hashlib.sha1
            ).digest()
        ).decode('utf-8')

        authorization = f"UCloud {access_key}:{signature}"

        download_url = upload_helper.get_external_download_url(file_key)

        response_data = US3SignatureResponse(
            url=upload_url,
            authorization=authorization,
            key=file_key,
            download_url=download_url,
        )

        return success_response(data=response_data)

    except Exception as e:
        logger.error(f"Failed to generate US3 signature: {str(e)}")
        raise HTTPException(status_code=500, detail="生成上传签名失败")


@router.post("")
async def create_asset(
    asset_data: AssetCreate,
    db: AsyncSession = Depends(get_async_db),
    user: User = Depends(get_current_user),
):
    """创建素材记录"""
    try:
        type_value = asset_data.type
        if isinstance(type_value, AssetType):
            type_value = type_value.value

        logger.info(f"Creating asset with type: {type_value} (type: {type(type_value)})")

        asset = Asset(
            uuid=str(uuid.uuid4()),
            novel_id=asset_data.novel_id,
            type=type_value,
            name=asset_data.name,
            url=asset_data.url,
            size=asset_data.size,
            duration=asset_data.duration,
        )

        db.add(asset)
        await db.commit()
        await db.refresh(asset)

        return success_response(data=asset)

    except Exception as e:
        await db.rollback()
        logger.error(f"Failed to create asset: {str(e)}")
        raise HTTPException(status_code=500, detail="创建素材失败")


from typing import List, Optional


@router.get("")
async def get_assets(
    novel_id: Optional[int] = Query(None, description="小说ID"),
    asset_type: Optional[str] = Query(None, description="素材类型"),
    db: AsyncSession = Depends(get_async_db),
    user: User = Depends(get_current_user),
):
    """获取素材列表"""
    try:
        query = select(Asset)
        
        if novel_id is not None:
            query = query.where(Asset.novel_id == novel_id)
        
        if asset_type is not None:
            query = query.where(Asset.type == asset_type)
        
        query = query.order_by(Asset.created_at.desc())
        
        result = await db.execute(query)
        assets = result.scalars().all()

        return success_response(data=assets)

    except Exception as e:
        logger.error(f"Failed to get assets: {str(e)}")
        raise HTTPException(status_code=500, detail="获取素材列表失败")


@router.get("/{asset_uuid}")
async def get_asset(
    asset_uuid: str,
    db: AsyncSession = Depends(get_async_db),
    user: User = Depends(get_current_user),
):
    """获取单个素材"""
    try:
        result = await db.execute(
            select(Asset).where(Asset.uuid == asset_uuid)
        )
        asset = result.scalar_one_or_none()

        if not asset:
            raise HTTPException(status_code=404, detail="素材不存在")

        return success_response(data=asset)

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get asset: {str(e)}")
        raise HTTPException(status_code=500, detail="获取素材失败")


@router.put("/{asset_uuid}")
async def update_asset(
    asset_uuid: str,
    asset_data: AssetUpdate,
    db: AsyncSession = Depends(get_async_db),
    user: User = Depends(get_current_user),
):
    """更新素材"""
    try:
        result = await db.execute(
            select(Asset).where(Asset.uuid == asset_uuid)
        )
        asset = result.scalar_one_or_none()

        if not asset:
            raise HTTPException(status_code=404, detail="素材不存在")

        if asset_data.name is not None:
            asset.name = asset_data.name

        await db.commit()
        await db.refresh(asset)

        return success_response(data=asset)

    except HTTPException:
        raise
    except Exception as e:
        await db.rollback()
        logger.error(f"Failed to update asset: {str(e)}")
        raise HTTPException(status_code=500, detail="更新素材失败")


@router.delete("/{asset_uuid}")
async def delete_asset(
    asset_uuid: str,
    db: AsyncSession = Depends(get_async_db),
    user: User = Depends(get_current_user),
):
    """删除素材"""
    try:
        result = await db.execute(
            select(Asset).where(Asset.uuid == asset_uuid)
        )
        asset = result.scalar_one_or_none()

        if not asset:
            raise HTTPException(status_code=404, detail="素材不存在")

        await db.delete(asset)
        await db.commit()

        return success_response(data=None, message="删除成功")

    except HTTPException:
        raise
    except Exception as e:
        await db.rollback()
        logger.error(f"Failed to delete asset: {str(e)}")
        raise HTTPException(status_code=500, detail="删除素材失败")
