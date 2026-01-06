import uuid
import hmac
import hashlib
import base64
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from typing import List

from app.api.deps import get_db, get_current_user
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
    """
    获取US3上传签名

    Args:
        request: 签名请求(file_name, file_type)

    Returns:
        上传签名信息
    """
    try:
        # 生成符合标准的文件路径
        # 路径格式: {env}/{time_str}/{user_uuid}/{file_type}/{filename}
        file_ext = request.file_name.split('.')[-1] if '.' in request.file_name else ''
        timestamp = datetime.now().strftime('%Y%m%d%H%M%S')
        unique_filename = f"{timestamp}_{uuid.uuid4().hex[:8]}.{file_ext}"

        # 使用标准路径生成函数
        file_key = upload_helper.generate_upload_path(
            user_uuid=user.uuid,
            file_type="assets",
            filename=unique_filename
        )

        # US3配置(需要在settings中配置)
        bucket_name = settings.US3_BUCKET or settings.DEFAULT_BUCKET or 'novel-agent'
        access_key = settings.US3_PUBLIC_KEY
        secret_key = settings.US3_PRIVATE_KEY
        # 注意：region应该包含完整的域名前缀，如 'cn-sh2'
        region = settings.US3_REGION or 'cn-sh2'

        # POST表单上传URL (bucket根路径)
        upload_url = f"https://{bucket_name}.{region}.ufileos.com/"

        # 生成POST表单上传签名
        # 参考: https://docs.ucloud.cn/ufile/api/authorization
        # StringToSign = HTTP-Verb + "\n" +
        #     Content-MD5 + "\n" +
        #     Content-Type + "\n" +
        #     Date + "\n" +
        #     CanonicalizedUCloudHeaders +
        #     CanonicalizedResource
        # CanonicalizedResource = "/" + Bucket + "/" + Key
        # 注意：当使用 POST 表单上传时，签名使用的 Content-Type 字段应该是文件本身的 mimetype

        http_verb = "POST"
        content_md5 = ""  # POST表单上传时为空
        content_type = request.file_type  # 使用文件本身的 MIME 类型
        date = ""  # POST表单上传时为空
        canonicalized_ucloud_headers = ""  # 没有自定义UCloud头部
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

        # 返回完整的下载URL
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
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """
    创建素材记录

    Args:
        asset_data: 素材数据

    Returns:
        创建的素材
    """
    try:
        # 创建素材
        # 确保 type 是字符串值而不是枚举对象
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
        db.commit()
        db.refresh(asset)

        return success_response(data=asset)

    except Exception as e:
        db.rollback()
        logger.error(f"Failed to create asset: {str(e)}")
        raise HTTPException(status_code=500, detail="创建素材失败")


@router.get("")
async def get_assets(
    novel_id: int = Query(..., description="小说ID"),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """
    获取素材列表

    Args:
        novel_id: 小说ID

    Returns:
        素材列表
    """
    try:
        assets = db.query(Asset).filter(
            Asset.novel_id == novel_id
        ).order_by(Asset.created_at.desc()).all()

        return success_response(data=assets)

    except Exception as e:
        logger.error(f"Failed to get assets: {str(e)}")
        raise HTTPException(status_code=500, detail="获取素材列表失败")


@router.get("/{asset_uuid}")
async def get_asset(
    asset_uuid: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """
    获取单个素材

    Args:
        asset_uuid: 素材UUID

    Returns:
        素材详情
    """
    try:
        asset = db.query(Asset).filter(Asset.uuid == asset_uuid).first()

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
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """
    更新素材

    Args:
        asset_uuid: 素材UUID
        asset_data: 更新数据

    Returns:
        更新后的素材
    """
    try:
        asset = db.query(Asset).filter(Asset.uuid == asset_uuid).first()

        if not asset:
            raise HTTPException(status_code=404, detail="素材不存在")

        # 更新字段
        if asset_data.name is not None:
            asset.name = asset_data.name

        db.commit()
        db.refresh(asset)

        return success_response(data=asset)

    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"Failed to update asset: {str(e)}")
        raise HTTPException(status_code=500, detail="更新素材失败")


@router.delete("/{asset_uuid}")
async def delete_asset(
    asset_uuid: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """
    删除素材

    Args:
        asset_uuid: 素材UUID

    Returns:
        成功消息
    """
    try:
        asset = db.query(Asset).filter(Asset.uuid == asset_uuid).first()

        if not asset:
            raise HTTPException(status_code=404, detail="素材不存在")

        db.delete(asset)
        db.commit()

        return success_response(data=None, message="删除成功")

    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"Failed to delete asset: {str(e)}")
        raise HTTPException(status_code=500, detail="删除素材失败")
