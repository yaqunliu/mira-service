from .user import User, UserCreate, UserUpdate
from .novel import Novel, NovelCreate, NovelUpdate
from .creation import Creation, CreationCreate, CreationUpdate
from .character import Character, CharacterCreate, CharacterUpdate
from .scene import Scene, SceneCreate, SceneUpdate
from .shot import Shot, ShotCreate, ShotUpdate
from .chapter import Chapter, ChapterCreate
from .voice import VoiceItem, VoiceListResponse, VoiceTag, VoiceSample, VoiceAuthor

# 重建模型以解析前向引用
Creation.model_rebuild()
Scene.model_rebuild()
Shot.model_rebuild()

__all__ = [
    "User", "UserCreate", "UserUpdate",
    "Novel", "NovelCreate", "NovelUpdate", 
    "Chapter", "ChapterCreate",
    "Creation", "CreationCreate", "CreationUpdate",
    "Character", "CharacterCreate", "CharacterUpdate",
    "Scene", "SceneCreate", "SceneUpdate",
    "Shot", "ShotCreate", "ShotUpdate",
    "VoiceItem", "VoiceListResponse", "VoiceTag", "VoiceSample", "VoiceAuthor",
]
