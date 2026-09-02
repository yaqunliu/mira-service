"""
Narration 音频标签生成工具

为分镜的 narration 字段添加音频相关的元数据标签，包括：
- voice_id: 合适的音色 ID
- emotion_tags: 情感标签列表
- voice_speed: 语速
- audio_type: 音频类型（narration/dialogue）
"""

import json
from typing import Dict, Any, List, Optional
from app.agent.tools.base import BaseTool
from app.agent.state.schemas import ComicDramaState, CharacterState
from app.agent.tools.voice_selection_tools import SelectVoiceForCharacterTool
from app.core.logger import logger
from app.core.config import settings
from app.utils.character_variants import NARRATOR_NAME, is_narrator


class NarrationAudioTaggerTool(BaseTool):
    """
    为 Narration 添加音频标签的工具
    
    功能：
    1. 分析 narration 中的说话者（角色/旁白）
    2. 为角色匹配合适的 voice_id
    3. 根据文本内容分析情感标签
    4. 为每个 narration 条目添加完整的音频元数据
    """
    
    name = "narration_audio_tagger"
    description = """为分镜的 narration 添加音频标签元数据。

输入：
- narration_list: 旁白列表（包含角色和内容的字典列表）
- characters: 角色列表（用于获取 voice_id）
- context: 上下文信息（场景描述、情绪等）

输出：
- 添加了音频标签的 narration 列表，每个条目包含：
  - speaker: 说话者名称
  - content: 内容文本
  - voice_id: 音色 ID
  - emotion_tags: 情感标签列表
  - voice_speed: 语速
  - audio_type: 类型（narration/dialogue）
"""
    
    def __init__(self, db_factory=None):
        super().__init__(db_factory)
        self.voice_selector = SelectVoiceForCharacterTool(db_factory)
        
        # 默认旁白音色
        self.default_narration_voice_id = getattr(
            settings, 'FISH_AUDIO_NARRATION_VOICE_ID', 
            settings.FISH_AUDIO_DEFAULT_VOICE_ID
        )
    
    def _get_character_voice_id(
        self,
        speaker: str,
        characters: List[CharacterState],
        character_id: Optional[int] = None
    ) -> Optional[str]:
        """
        获取角色的 voice_id。

        优先按 character_id 精确定位；老数据的 narration 没有 character_id，
        才退回按角色名匹配（见 en-plan.md Phase 3.5.4）。
        """
        if character_id is not None:
            for char in characters:
                if char.get("character_id") == character_id:
                    return char.get("voice_id")
            logger.warning(f"narration 引用的 character_id={character_id} 不在角色列表中")

        for char in characters:
            if char.get("name") == speaker:
                return char.get("voice_id")
        return None
    
    def _analyze_emotion_for_text(
        self,
        text: str,
        speaker: str,
        context: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        分析文本的情感标签
        
        基于规则的情感分析，可以根据需要扩展为 LLM 分析
        """
        emotion_tags = []
        voice_speed = 1.0
        
        # 旁白默认情感
        if is_narrator(speaker):
            emotion_tags = ["calm", "confident"]
            voice_speed = 1.0
        else:
            # 角色对话情感分析（基于关键词）
            text_lower = text.lower()
            
            # 情感关键词映射
            emotion_keywords = {
                "happy": ["开心", "高兴", "快乐", "哈哈", "太好了", "棒", "喜欢", "爱"],
                "sad": ["难过", "伤心", "哭", "泪", "痛苦", "悲伤", "失望", "遗憾"],
                "angry": ["生气", "愤怒", "讨厌", "恨", "滚", "混蛋", "可恶"],
                "excited": ["兴奋", "激动", "太棒了", "哇", "天哪", "不可思议"],
                "nervous": ["紧张", "害怕", "担心", "焦虑", "不安", "忐忑"],
                "surprised": ["惊讶", "震惊", "没想到", "竟然", "真的吗"],
                "worried": ["担心", "忧虑", "怎么办", "会不会", "万一"],
                "confident": ["肯定", "一定", "没问题", "相信我", "放心"],
            }
            
            for emotion, keywords in emotion_keywords.items():
                if any(kw in text for kw in keywords):
                    emotion_tags.append(emotion)
            
            # 如果没有检测到情感，使用默认
            if not emotion_tags:
                emotion_tags = ["neutral"]
            
            # 根据文本长度调整语速（短句可以稍快）
            text_length = len(text)
            if text_length < 10:
                voice_speed = 1.05
            elif text_length > 50:
                voice_speed = 0.95
        
        return {
            "emotion_tags": emotion_tags,
            "voice_speed": voice_speed
        }
    
    async def execute(
        self,
        state: ComicDramaState,
        narration_list: List[Dict[str, str]],
        characters: Optional[List[CharacterState]] = None,
        context: Optional[str] = None,
        **kwargs
    ) -> Dict[str, Any]:
        """
        为 narration 列表添加音频标签
        
        Args:
            state: 当前状态
            narration_list: 旁白列表，每项包含 "角色" 和 "内容"
            characters: 角色列表（用于获取 voice_id）
            context: 上下文信息
            
        Returns:
            添加了音频标签的 narration 列表
        """
        try:
            characters = characters or state.get("characters", [])
            tagged_narrations = []
            
            for idx, narration in enumerate(narration_list):
                speaker = narration.get("角色") or narration.get("role") or NARRATOR_NAME
                content = narration.get("内容") or narration.get("content") or ""

                if not content:
                    continue

                # 判断是旁白还是对话
                # （原先这里的判定列表里有个 " narrator" 前导空格 typo，永远匹配不上）
                narration_character_id = narration.get("character_id")
                is_narration = narration_character_id is None and is_narrator(speaker)
                audio_type = "narration" if is_narration else "dialogue"

                # 获取 voice_id
                if is_narration:
                    voice_id = self.default_narration_voice_id
                else:
                    voice_id = self._get_character_voice_id(
                        speaker, characters, narration_character_id
                    )

                    # 如果角色没有 voice_id，尝试从状态中获取或使用默认
                    if not voice_id:
                        voice_id = state.get("creation_voice_id") or settings.FISH_AUDIO_DEFAULT_VOICE_ID
                        logger.warning(
                            f"角色 {speaker} (character_id={narration_character_id}) "
                            f"没有分配 voice_id，使用默认值"
                        )
                
                # 分析情感标签
                emotion_analysis = self._analyze_emotion_for_text(content, speaker, context)
                
                # 构建带标签的 narration
                tagged_narration = {
                    "index": idx,
                    "speaker": speaker,
                    "content": content,
                    "voice_id": voice_id,
                    "emotion_tags": emotion_analysis["emotion_tags"],
                    "voice_speed": emotion_analysis["voice_speed"],
                    "audio_type": audio_type,
                    "original": narration  # 保留原始数据
                }
                
                tagged_narrations.append(tagged_narration)
                
                logger.info(
                    f"Narration {idx}: {speaker} -> voice_id={voice_id}, "
                    f"emotions={emotion_analysis['emotion_tags']}"
                )
            
            return {
                "success": True,
                "message": f"已为 {len(tagged_narrations)} 个 narration 添加音频标签",
                "data": {
                    "tagged_narrations": tagged_narrations,
                    "total_count": len(tagged_narrations),
                    "narration_count": sum(1 for n in tagged_narrations if n["audio_type"] == "narration"),
                    "dialogue_count": sum(1 for n in tagged_narrations if n["audio_type"] == "dialogue")
                }
            }
            
        except Exception as e:
            logger.exception(f"添加音频标签失败: {e}")
            return {
                "success": False,
                "message": "添加音频标签失败",
                "error": str(e)
            }


class BatchTagNarrationsTool(BaseTool):
    """
    批量为多个分镜的 narration 添加音频标签
    
    功能：
    1. 从数据库获取分镜列表
    2. 为每个分镜的 narration 添加音频标签
    3. 返回完整的标签化 narration 数据
    """
    
    name = "batch_tag_narrations"
    description = """批量为分镜添加音频标签。

输入：
- shot_ids: 分镜 ID 列表
- scene_id: 场景 ID（可选，用于获取该场景下所有分镜）

输出：
- 每个分镜的标签化 narration 列表
"""
    
    def __init__(self, db_factory=None):
        super().__init__(db_factory)
        self.tagger = NarrationAudioTaggerTool(db_factory)
    
    def _parse_narration(self, narration_json: str) -> List[Dict[str, str]]:
        """解析旁白 JSON"""
        if not narration_json:
            return []
        
        try:
            if isinstance(narration_json, str):
                return json.loads(narration_json)
            return narration_json
        except (json.JSONDecodeError, TypeError):
            logger.warning(f"解析 narration 失败: {narration_json}")
            return []
    
    async def execute(
        self,
        state: ComicDramaState,
        shot_ids: Optional[List[int]] = None,
        scene_id: Optional[int] = None,
        **kwargs
    ) -> Dict[str, Any]:
        """
        批量为分镜添加音频标签
        
        Args:
            state: 当前状态
            shot_ids: 分镜 ID 列表
            scene_id: 场景 ID（可选）
            
        Returns:
            每个分镜的标签化 narration
        """
        try:
            from app.models.shot import Shot
            from app.agent.tools.async_db import get_async_db_session
            from sqlalchemy import select
            
            async with get_async_db_session() as db:
                # 获取分镜列表
                if shot_ids:
                    shots = []
                    for sid in shot_ids:
                        shot = await db.get(Shot, sid)
                        if shot:
                            shots.append(shot)
                elif scene_id:
                    result = await db.execute(
                        select(Shot)
                        .where(Shot.scene_id == scene_id)
                        .order_by(Shot.shot_number)
                    )
                    shots = result.scalars().all()
                else:
                    current_scene_id = state.get("current_scene_id")
                    if not current_scene_id:
                        return {
                            "success": False,
                            "message": "未指定场景 ID 或分镜 ID 列表",
                            "error": "Missing scene_id or shot_ids"
                        }
                    result = await db.execute(
                        select(Shot)
                        .where(Shot.scene_id == current_scene_id)
                        .order_by(Shot.shot_number)
                    )
                    shots = result.scalars().all()
                
                if not shots:
                    return {
                        "success": False,
                        "message": "没有找到分镜",
                        "error": "No shots found"
                    }
                
                # 为每个分镜添加音频标签
                results = []
                for shot in shots:
                    narration_list = self._parse_narration(shot.narration)
                    
                    if not narration_list:
                        logger.warning(f"分镜 {shot.shot_id} 没有 narration")
                        continue
                    
                    # 添加音频标签
                    tag_result = await self.tagger.execute(
                        state=state,
                        narration_list=narration_list,
                        context=shot.description
                    )
                    
                    if tag_result["success"]:
                        results.append({
                            "shot_id": shot.shot_id,
                            "shot_title": shot.title,
                            "shot_number": shot.shot_number,
                            "tagged_narrations": tag_result["data"]["tagged_narrations"]
                        })
                    else:
                        logger.error(f"为分镜 {shot.shot_id} 添加标签失败: {tag_result.get('error')}")
                
                return {
                    "success": True,
                    "message": f"已为 {len(results)} 个分镜添加音频标签",
                    "data": {
                        "shots": results,
                        "total_shots": len(results),
                        "total_narrations": sum(
                            len(s["tagged_narrations"]) for s in results
                        )
                    }
                }
                
        except Exception as e:
            logger.exception(f"批量添加音频标签失败: {e}")
            return {
                "success": False,
                "message": "批量添加音频标签失败",
                "error": str(e)
            }
