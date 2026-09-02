from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import ARRAY, UUID, JSONB
from sqlalchemy.sql import func, text as sa_text
from sqlalchemy.orm import relationship
import uuid
from app.db.base import Base


class Character(Base):
    """角色模型"""
    __tablename__ = "characters"
    
    character_id = Column(Integer, primary_key=True, index=True)
    uuid = Column(UUID(as_uuid=False), unique=True, nullable=False, index=True, 
                  default=lambda: str(uuid.uuid4()), 
                  server_default=sa_text('gen_random_uuid()'))
    # 角色显示名：只存人名或身份称呼（如 "Zhou Yu" / "Homeroom Teacher"）
    # 年龄段与临时状态不再拼进 name，改用下方 age_group / state 字段
    name = Column(String(100), nullable=False, index=True)
    status = Column(String(20), default="pending")  # pending, generating, completed, failed
    status_detail = Column(JSONB, nullable=True)  # 详细状态信息
    basic_info = Column(String(500))  # 基本信息描述

    # 角色变体标识：(name, age_group, state) 三元组唯一确定一个角色条目
    age_group = Column(String(20), nullable=True)  # child / teen / youth / middle_aged / elder
    state = Column(String(120), nullable=True)  # 临时外观状态，如 "drenched" / "formal attire"；日常状态为 None
    character_type = Column(String(20), nullable=False, server_default="on_screen")  # on_screen / voice
    voice_channel = Column(String(20), nullable=True)  # 仅 voice：phone / intercom / memory / distant / offscreen

    # 特征描述 (JSON格式存储)
    appearance = Column(Text)  # 外貌描述
    body = Column(Text)  # 身材描述
    hair = Column(Text)  # 发型描述
    clothing = Column(Text)  # 服装描述
    tags = Column(ARRAY(String))  # 标签 (字符串数组)
    voice_description = Column(String(500))  # 声音描述
    voice_id = Column(String(100))  # Fish Audio 语音模型 ID
    voice_speed = Column(String(20), default="1.0")  # 语速 (0.5-2.0)
    
    # 图片相关
    image_prompt = Column(Text)  # 图片生成提示词
    visual_style = Column(String(100))  # 视觉风格
    image_url = Column(String(500))  # 角色图片URL
    
    # 外键
    novel_id = Column(Integer, ForeignKey("novels.novel_id"))
    creation_id = Column(Integer, ForeignKey("creations.creation_id"))
    
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
    deleted_at = Column(DateTime(timezone=True), nullable=True, index=True)  # 软删除时间戳
    
    # 关系
    novel = relationship("Novel", back_populates="characters")
    creation = relationship("Creation", back_populates="characters")
    shots = relationship("Shot", secondary="shot_characters", back_populates="characters")

    # 变体常量
    AGE_GROUPS = ("child", "teen", "youth", "middle_aged", "elder")
    TYPE_ON_SCREEN = "on_screen"
    TYPE_VOICE = "voice"
    # 旧数据用 basic_info 这个字符串哨兵标记声音角色，迁移已搬进 character_type，
    # 此常量仅供 backfill 与兼容判断使用
    LEGACY_VOICE_SENTINEL = "声音角色"

    @property
    def is_voice_only(self) -> bool:
        """是否为只有声音、不出镜的角色"""
        return self.character_type == self.TYPE_VOICE

    @property
    def variant_label(self) -> str:
        """
        人类可读的变体标签，如 "Zhou Yu (teen, school uniform)"。

        仅用于日志与 prompt 注入展示。**绝不可作为匹配键**——
        跨模块引用角色一律使用 character_id。
        """
        parts = [p for p in (self.age_group, self.state) if p]
        return f"{self.name} ({', '.join(parts)})" if parts else self.name

