from __future__ import annotations

import json
from typing import Optional, List, Any, Dict
from pydantic import BaseModel, Field, field_validator
from datetime import datetime


class NarrationItem(BaseModel):
    """旁白/台词项"""
    角色: str = Field(..., alias="角色")
    内容: str = Field(..., alias="内容")

    class Config:
        populate_by_name = True


class CharacterBrief(BaseModel):
    """角色简要信息（用于镜头响应中）"""
    character_id: int
    name: str
    
    class Config:
        from_attributes = True


class ShotBase(BaseModel):
    title: str
    shot_number: int
    description: Optional[str] = None
    narration: Optional[List[NarrationItem]] = None
    image_prompt: Optional[str] = None


class ShotCreate(BaseModel):
    """创建镜头的请求体"""
    title: str
    shot_number: Optional[int] = None  # 如果不提供，自动生成
    description: Optional[str] = None
    narration: Optional[List[NarrationItem]] = None
    image_prompt: Optional[str] = None
    scene_id: int
    associated_characters: Optional[List[int]] = Field(None, alias="associated_characters")  # 关联的角色ID列表

    @field_validator('narration', mode='before')
    @classmethod
    def validate_narration(cls, v: Any) -> Optional[List[NarrationItem]]:
        if v is None:
            return []
        if isinstance(v, str):
            try:
                data = json.loads(v)
                if isinstance(data, list):
                    # 处理旧格式 [ "xxx" ] 或新格式 [ {"角色": "xxx", "内容": "xxx"} ]
                    result = []
                    for item in data:
                        if isinstance(item, dict) and "角色" in item and "内容" in item:
                            result.append(NarrationItem(**item))
                        elif isinstance(item, str):
                            # 兼容旧格式，默认为旁白
                            result.append(NarrationItem(角色="旁白", 内容=item))
                    return result
                return [NarrationItem(角色="旁白", 内容=v)]
            except:
                return [NarrationItem(角色="旁白", 内容=v)]
        if isinstance(v, list):
            result = []
            for item in v:
                if isinstance(item, dict):
                    result.append(NarrationItem(**item))
                elif isinstance(item, NarrationItem):
                    result.append(item)
                elif isinstance(item, str):
                    result.append(NarrationItem(角色="旁白", 内容=item))
            return result
        return []


class ShotUpdate(BaseModel):
    """更新镜头的请求体"""
    title: Optional[str] = None
    shot_number: Optional[int] = None
    description: Optional[str] = None
    narration: Optional[List[NarrationItem]] = None
    image_prompt: Optional[str] = None
    image_url: Optional[str] = None
    audio_url: Optional[str] = None
    video_url: Optional[str] = None  # 视频URL
    video_duration: Optional[int] = None
    associated_characters: Optional[List[int]] = Field(None, alias="associated_characters")  # 更新关联的角色
    scene_id: Optional[int] = None  # 更新关联的场景
    extra_data: Optional[Dict[str, Any]] = None  # 更新额外数据（如视频提示词）

    @field_validator('narration', mode='before')
    @classmethod
    def validate_narration(cls, v: Any) -> Optional[List[NarrationItem]]:
        if v is None:
            return None
        if isinstance(v, str):
            try:
                data = json.loads(v)
                if isinstance(data, list):
                    result = []
                    for item in data:
                        if isinstance(item, dict) and "角色" in item and "内容" in item:
                            result.append(NarrationItem(**item))
                        elif isinstance(item, str):
                            result.append(NarrationItem(角色="旁白", 内容=item))
                    return result
                return [NarrationItem(角色="旁白", 内容=v)]
            except:
                return [NarrationItem(角色="旁白", 内容=v)]
        if isinstance(v, list):
            result = []
            for item in v:
                if isinstance(item, dict):
                    result.append(NarrationItem(**item))
                elif isinstance(item, NarrationItem):
                    result.append(item)
                elif isinstance(item, str):
                    result.append(NarrationItem(角色="旁白", 内容=item))
            return result
        return []


class Shot(ShotBase):
    """镜头响应模型"""
    shot_id: int
    uuid: str
    scene_id: int
    image_url: Optional[str] = None
    audio_url: Optional[str] = None
    video_url: Optional[str] = None
    video_status: Optional[str] = None
    video_duration: Optional[int] = None
    audio_duration: Optional[int] = None  # 音频时长（毫秒）
    status_detail: Optional[Dict[str, Any]] = None
    extra_data: Optional[Dict[str, Any]] = None
    created_at: datetime
    updated_at: Optional[datetime] = None
    characters: Optional[List[CharacterBrief]] = None

    class Config:
        from_attributes = True


class ShotResponse(BaseModel):
    """镜头响应（前端格式）"""
    shot_id: int
    uuid: str
    scene_id: int
    title: str
    associated_characters: List[int] = Field(default_factory=list)
    characters: List[CharacterBrief] = Field(default_factory=list)  # 添加完整的角色对象列表
    description: Optional[str] = None
    narration: List[NarrationItem] = Field(default_factory=list)
    image_prompt: Optional[str] = None
    image_url: Optional[str] = None
    audio_url: Optional[str] = None
    video_url: Optional[str] = None
    video_status: Optional[str] = None
    video_duration: Optional[int] = None
    status_detail: Optional[Dict[str, Any]] = None
    extra_data: Optional[Dict[str, Any]] = None
    shot_number: int

    @field_validator('narration', mode='before')
    @classmethod
    def validate_narration_response(cls, v: Any) -> List[NarrationItem]:
        """验证 narration 字段，支持从 JSON 字符串解析"""
        if v is None:
            return []
        if isinstance(v, list):
            return v
        if isinstance(v, str):
            try:
                data = json.loads(v)
                if isinstance(data, list):
                    result = []
                    for item in data:
                        if isinstance(item, dict) and "角色" in item and "内容" in item:
                            result.append(NarrationItem(**item))
                        elif isinstance(item, str):
                            result.append(NarrationItem(角色="旁白", 内容=item))
                    return result
                else:
                    return [NarrationItem(角色="旁白", 内容=str(data))]
            except (json.JSONDecodeError, TypeError):
                return [NarrationItem(角色="旁白", 内容=v)]
        return []

    class Config:
        from_attributes = True
    
    @classmethod
    def from_db_model(cls, shot) -> "ShotResponse":
        """从数据库模型转换"""
        narration_list = []
        if shot.narration:
            try:
                # 尝试解析 JSON 字符串
                data = json.loads(shot.narration)
                if isinstance(data, list):
                    for item in data:
                        if isinstance(item, dict) and "角色" in item and "内容" in item:
                            narration_list.append(NarrationItem(**item))
                        elif isinstance(item, str):
                            # 兼容旧格式
                            narration_list.append(NarrationItem(角色="旁白", 内容=item))
                else:
                    narration_list = [NarrationItem(角色="旁白", 内容=str(data))]
            except (json.JSONDecodeError, TypeError):
                # 如果不是有效的 JSON，则作为单条旁白
                narration_list = [NarrationItem(角色="旁白", 内容=shot.narration)]

        # 构建角色列表
        characters_list = []
        associated_characters_list = []
        if shot.characters:
            for char in shot.characters:
                associated_characters_list.append(char.character_id)
                characters_list.append(CharacterBrief(
                    character_id=char.character_id,
                    name=char.name
                ))

        return cls(
            shot_id=shot.shot_id,
            uuid=shot.uuid,
            scene_id=shot.scene_id,
            title=shot.title,
            associated_characters=associated_characters_list,
            characters=characters_list,  # 添加完整的角色对象列表
            description=shot.description,
            narration=narration_list,
            image_prompt=shot.image_prompt,
            image_url=shot.image_url,
            audio_url=shot.audio_url,
            video_url=shot.video_url,
            video_status=shot.video_status,
            video_duration=shot.video_duration,
            status_detail=shot.status_detail,
            extra_data=shot.extra_data,
            shot_number=shot.shot_number
        )


class ShotListResponse(BaseModel):
    """镜头列表响应"""
    items: List[ShotResponse]
    total: int


class ShotRegenerateRequest(BaseModel):
    """重新生成分镜图片的请求体"""
    image_prompt: Optional[str] = None  # 新的图片提示词（可选，不传则使用现有提示词）
    model_name: Optional[str] = None  # 使用的模型名称
    refresh_prompt: bool = False  # 是否重新生成提示词（忽略现有提示词）
    frame_type: str = "both"  # 生成帧类型: "start"=仅首帧, "end"=仅尾帧, "both"=首尾帧


class ShotRegenerateVideoRequest(BaseModel):
    """重新生成分镜视频的请求体"""
    model_name: Optional[str] = None  # 使用的模型名称
    last_frame_image_url: Optional[str] = None  # 尾帧图片URL


class ShotGenerateVideoRequest(BaseModel):
    """生成分镜视频的请求体"""
    model_name: Optional[str] = None  # 使用的模型名称
    last_frame_image_url: Optional[str] = None  # 尾帧图片URL


class ShotCharactersUpdateRequest(BaseModel):
    """更新分镜关联角色的请求体"""
    character_ids: List[int] = Field(...)


class ShotNarrationUpdateRequest(BaseModel):
    """更新分镜旁白的请求体"""
    narration: List[NarrationItem]
