from sqlalchemy import Column, Integer, String, BigInteger, Enum as SQLEnum, DateTime, func
from sqlalchemy.orm import relationship
from app.db.base import Base
import enum


class AssetType(str, enum.Enum):
    """素材类型枚举"""
    AUDIO = "audio"
    IMAGE = "image"
    VIDEO = "video"


class Asset(Base):
    """素材模型"""
    __tablename__ = "assets"

    asset_id = Column(Integer, primary_key=True, index=True, autoincrement=True, comment="素材ID")
    uuid = Column(String(36), unique=True, index=True, nullable=False, comment="UUID")
    novel_id = Column(Integer, nullable=False, index=True, comment="关联的小说ID")
    type = Column(SQLEnum(AssetType, values_callable=lambda x: [e.value for e in x]), nullable=False, comment="素材类型")
    name = Column(String(255), nullable=False, comment="素材名称")
    url = Column(String(512), nullable=False, comment="US3存储地址")
    size = Column(BigInteger, nullable=True, comment="文件大小(字节)")
    duration = Column(Integer, nullable=True, comment="时长(毫秒),仅音频/视频")
    created_at = Column(DateTime, server_default=func.now(), comment="创建时间")
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now(), comment="更新时间")

    def __repr__(self):
        return f"<Asset(asset_id={self.asset_id}, name={self.name}, type={self.type})>"
