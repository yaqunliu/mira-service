from __future__ import annotations

import json
from typing import Optional, List, Any, Dict
from pydantic import BaseModel, Field, field_validator
from datetime import datetime
from app.schemas.shot import NarrationItem


class SceneSetting(BaseModel):
    """场景设置"""
    time: Optional[str] = Field(None, description="时间设置")
    location: Optional[str] = Field(None, description="地点")
    space: Optional[str] = Field(None, description="空间类型: 室内/室外")
    atmosphere: Optional[str] = Field(None, description="氛围描述")


class SceneBase(BaseModel):
    title: str
    duration: Optional[str] = None
    time_setting: Optional[str] = None
    location: Optional[str] = None
    space_type: Optional[str] = None
    atmosphere: Optional[str] = None


class SceneCreate(BaseModel):
    """创建场景的请求体"""
    title: str
    duration: Optional[str] = None
    scene_setting: Optional[SceneSetting] = None
    creation_id: int


class SceneUpdate(BaseModel):
    """更新场景的请求体"""
    title: Optional[str] = None
    duration: Optional[str] = None
    scene_setting: Optional[SceneSetting] = None


class ShotBrief(BaseModel):
    """镜头简要信息（用于场景响应中）"""
    shot_id: int
    uuid: str
    title: str
    shot_number: int
    image_prompt: str | None
    image_url: str | None
    narration: List[NarrationItem] = Field(default_factory=list)
    description: str | None
    
    class Config:
        from_attributes = True

    @field_validator('narration', mode='before')
    @classmethod
    def validate_narration(cls, v: Any) -> List[NarrationItem]:
        if not v:
            return []
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
                return [NarrationItem(角色="旁白", 内容=str(data))]
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


class ShotDetail(BaseModel):
    """镜头详细信息（用于场景响应中，包含图片URL）"""
    shot_id: int
    uuid: str
    title: str
    shot_number: int
    image_url: Optional[str] = None
    image_prompt: Optional[str] = None
    narration: List[NarrationItem] = Field(default_factory=list)
    description: Optional[str] = None
    video_url: Optional[str] = None
    audio_url: Optional[str] = None
    duration: Optional[float] = None
    video_status: Optional[str] = None
    video_duration: Optional[int] = None
    status_detail: Optional[Dict[str, Any]] = None
    extra_data: Optional[Dict[str, Any]] = None

    class Config:
        from_attributes = True

    @field_validator('narration', mode='before')
    @classmethod
    def validate_narration(cls, v: Any) -> List[NarrationItem]:
        if not v:
            return []
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
                return [NarrationItem(角色="旁白", 内容=str(data))]
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
    
    @classmethod
    def from_db_model(cls, shot) -> "ShotDetail":
        """从数据库模型转换"""
        narration_list = []
        if shot.narration:
            try:
                data = json.loads(shot.narration)
                if isinstance(data, list):
                    for item in data:
                        if isinstance(item, dict) and "角色" in item and "内容" in item:
                            narration_list.append(NarrationItem(**item))
                        elif isinstance(item, str):
                            narration_list.append(NarrationItem(角色="旁白", 内容=item))
                else:
                    narration_list = [NarrationItem(角色="旁白", 内容=str(data))]
            except (json.JSONDecodeError, TypeError):
                narration_list = [NarrationItem(角色="旁白", 内容=shot.narration)]
        
        return cls(
            shot_id=shot.shot_id,
            uuid=shot.uuid,
            title=shot.title,
            shot_number=shot.shot_number,
            image_url=shot.image_url,
            image_prompt=shot.image_prompt,
            narration=narration_list,
            description=shot.description,
            video_url=shot.video_url,
            audio_url=shot.audio_url,
            duration=shot.video_duration,
            video_status=shot.video_status,
            video_duration=shot.video_duration,
            status_detail=shot.status_detail,
            extra_data=shot.extra_data
        )


class Scene(SceneBase):
    """场景响应模型"""
    scene_id: int
    uuid: str
    creation_id: int
    image_url: Optional[str] = None
    created_at: datetime
    updated_at: Optional[datetime] = None
    shots: Optional[List["ShotBrief"]] = None
    
    class Config:
        from_attributes = True


class SceneResponse(BaseModel):
    """场景响应（前端格式）"""
    scene_id: int = Field(..., alias="sceneId")
    uuid: str = Field(..., alias="uuid")
    title: str
    duration: Optional[str] = None
    image_url: Optional[str] = Field(None, alias="imageUrl")
    scene_setting: SceneSetting = Field(..., alias="sceneSetting")
    shot_list: List[int] = Field(default_factory=list, alias="shotList")
    
    class Config:
        from_attributes = True
        populate_by_name = True
    
    @classmethod
    def from_db_model(cls, scene) -> "SceneResponse":
        """从数据库模型转换"""
        return cls(
            sceneId=scene.scene_id,
            uuid=scene.uuid,
            title=scene.title,
            duration=scene.duration,
            imageUrl=scene.image_url,
            sceneSetting=SceneSetting(
                time=scene.time_setting,
                location=scene.location,
                space=scene.space_type,
                atmosphere=scene.atmosphere
            ),
            shotList=[shot.shot_id for shot in sorted(scene.shots, key=lambda s: s.shot_id)] if scene.shots else []
        )


class SceneListResponse(BaseModel):
    """场景列表响应"""
    items: List[SceneResponse]
    total: int


class SceneWithShotsResponse(BaseModel):
    """场景响应（包含完整分镜详情）"""
    scene_id: int
    uuid: str
    title: str
    duration: Optional[str] = None
    scene_setting: SceneSetting
    shots: List[ShotDetail] = Field(default_factory=list)
    
    class Config:
        from_attributes = True
    
    @classmethod
    def from_db_model(cls, scene) -> "SceneWithShotsResponse":
        """从数据库模型转换"""
        return cls(
            scene_id=scene.scene_id,
            uuid=scene.uuid,
            title=scene.title,
            duration=scene.duration,
            scene_setting=SceneSetting(
                time=scene.time_setting,
                location=scene.location,
                space=scene.space_type,
                atmosphere=scene.atmosphere
            ),
            shots=[ShotDetail.from_db_model(shot) for shot in sorted(scene.shots, key=lambda s: s.shot_id)] if scene.shots else []
        )
