from pydantic import BaseModel, Field
from typing import Optional
from datetime import datetime
from app.models.asset import AssetType


class AssetBase(BaseModel):
    """素材基础模型"""
    name: str = Field(..., description="素材名称")
    type: AssetType = Field(..., description="素材类型")
    url: str = Field(..., description="US3存储地址")
    size: Optional[int] = Field(None, description="文件大小(字节)")
    duration: Optional[int] = Field(None, description="时长(毫秒)")


class AssetCreate(AssetBase):
    """创建素材请求"""
    novel_id: int = Field(..., description="关联的小说ID")


class AssetUpdate(BaseModel):
    """更新素材请求"""
    name: Optional[str] = Field(None, description="素材名称")


class AssetResponse(AssetBase):
    """素材响应"""
    asset_id: int
    uuid: str
    novel_id: int
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class US3SignatureRequest(BaseModel):
    """US3上传签名请求"""
    file_name: str = Field(..., description="文件名")
    file_type: str = Field(..., description="文件MIME类型")


class US3SignatureResponse(BaseModel):
    """US3上传签名响应"""
    url: str = Field(..., description="上传URL")
    authorization: str = Field(..., description="签名")
    key: str = Field(..., description="文件路径")
    download_url: str = Field(..., description="下载URL")
