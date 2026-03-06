"""
音色选择 Agent - Voice Selection Agent

为角色智能匹配最合适的 Fish Audio 音色
根据角色属性（性别、年龄、性格、特点）匹配合适的声音
"""

from typing import Dict, Any, List, Optional
from langchain_core.messages import SystemMessage, HumanMessage
from langchain_openai import ChatOpenAI
from app.agent.state.schemas import ComicDramaState, CharacterState
from app.agent.tools.voice_selection_tools import (
    LoadVoiceListTool,
    MatchVoiceByAttributesTool,
    SelectVoiceForCharacterTool,
    BatchSelectVoiceTool,
)
from app.core.logger import logger
from app.core.config import settings
import json


class VoiceSelectionAgent:
    """
    音色选择 Agent

    负责为角色选择最合适的 Fish Audio 音色，支持：
    1. 基于角色属性的智能匹配
    2. 批量为多个角色选择音色
    3. 根据角色描述自动选择最接近的声音
    4. 支持中英文音色库
    """

    def __init__(self):
        """初始化音色选择 Agent"""
        self.llm = ChatOpenAI(
            model=settings.LLM_MODEL_SCRIPT_GENERATION,
            api_key=settings.OPENAI_API_KEY,
            base_url=settings.OPENAI_BASE_URL,
            temperature=0.3
        )

        self.load_voice_list_tool = LoadVoiceListTool()
        self.match_voice_tool = MatchVoiceByAttributesTool()
        self.select_voice_tool = SelectVoiceForCharacterTool()
        self.batch_select_voice_tool = BatchSelectVoiceTool()

        logger.info("音色选择 Agent 初始化完成")

    async def select_voice_for_character(
        self,
        state: ComicDramaState,
        character_name: str,
        character_description: Optional[str] = None,
        character_personality: Optional[str] = None,
        force_gender: Optional[str] = None,
        preferred_voice_ids: Optional[List[str]] = None
    ) -> Dict[str, Any]:
        """
        为单个角色选择合适的音色

        Args:
            state: 当前状态
            character_name: 角色名称
            character_description: 角色描述（可选）
            character_personality: 性格特点（可选）
            force_gender: 强制性别（可选，male/female）
            preferred_voice_ids: 偏好的音色 ID 列表（可选）

        Returns:
            选择的音色信息：
            - voice_id: 音色 ID
            - voice_name: 音色名称
            - confidence: 匹配度 (0-1)
            - reason: 选择理由
        """
        return await self.select_voice_tool.execute(
            state=state,
            character_name=character_name,
            character_description=character_description,
            character_personality=character_personality,
            force_gender=force_gender,
            preferred_voice_ids=preferred_voice_ids
        )

    async def select_voice_for_all_characters(
        self,
        state: ComicDramaState,
        character_names: Optional[List[str]] = None,
        skip_named_voices: bool = True
    ) -> Dict[str, Any]:
        """
        为所有角色批量选择音色

        Args:
            state: 当前状态
            character_names: 指定角色名称列表（可选，默认所有角色）
            skip_named_voices: 是否跳过已有 voice_id 的角色

        Returns:
            批量选择结果：
            - success: 是否成功
            - characters: 各角色的音色选择结果
            - summary: 选择摘要
        """
        return await self.batch_select_voice_tool.execute(
            state=state,
            character_names=character_names,
            skip_named_voices=skip_named_voices
        )

    async def match_voice_by_attributes(
        self,
        state: ComicDramaState,
        gender: str,
        age_range: str,
        personality_traits: List[str],
        voice_quality: Optional[List[str]] = None,
        language: str = "zh"
    ) -> Dict[str, Any]:
        """
        根据属性直接匹配音色

        Args:
            state: 当前状态
            gender: 性别 (male/female)
            age_range: 年龄范围 (young/middle-aged/old)
            personality_traits: 性格特点列表
            voice_quality: 声音质量要求（可选）
            language: 语言 (zh/en)

        Returns:
            匹配的音色列表（按匹配度排序）
        """
        return await self.match_voice_tool.execute(
            state=state,
            gender=gender,
            age_range=age_range,
            personality_traits=personality_traits,
            voice_quality=voice_quality,
            language=language
        )

    async def analyze_character_voice_needs(
        self,
        state: ComicDramaState,
        character_name: str,
        dialogues: Optional[List[str]] = None
    ) -> Dict[str, Any]:
        """
        分析角色对音色的需求

        通过分析角色名称、描述和台词，推断最适合的音色属性

        Args:
            state: 当前状态
            character_name: 角色名称
            dialogues: 角色台词列表（可选）

        Returns:
            音色需求分析结果：
            - suggested_gender: 建议性别
            - suggested_age: 建议年龄
            - suggested_personality: 建议性格
            - suggested_voice_quality: 建议声音特点
            - reasoning: 分析理由
        """
        try:
            character = None
            for c in state.get("characters", []):
                if c.get("name") == character_name:
                    character = c
                    break

            character_description = character.get("description", "") if character else ""
            character_personality = character.get("personality", "") if character else ""

            prompt = f"""分析以下角色对音色的需求：

角色名称：{character_name}
角色描述：{character_description}
性格特点：{character_personality}
角色台词：{chr(10).join(dialogues) if dialogues else '无'}

请分析这个角色最适合的音色属性，返回 JSON 格式：
{{
    "suggested_gender": "male/female",
    "suggested_age": "young/middle-aged/old",
    "suggested_personality": ["特点1", "特点2"],
    "suggested_voice_quality": ["要求1", "要求2"],
    "reasoning": "分析理由"
}}

注意：
- 根据角色名称的性别暗示判断性别
- 根据角色描述和台词判断年龄和性格
- 性格特点可以是：energetic, calm, authoritative, warm, gentle, professional, friendly 等
- 声音质量要求可以是：clear, deep, soft, loud, fast, slow 等
"""

            messages = [HumanMessage(content=prompt)]
            response = await self.llm.ainvoke(messages)

            content = response.content if hasattr(response, 'content') else str(response)
            content = content.strip()

            if content.startswith("```json"):
                content = content[7:]
            if content.endswith("```"):
                content = content[:-3]

            result = json.loads(content)
            logger.info(f"角色 {character_name} 音色需求分析完成: {result}")

            return {
                "success": True,
                "data": result,
                "message": f"角色 {character_name} 音色需求分析完成"
            }

        except Exception as e:
            logger.error(f"分析角色 {character_name} 音色需求失败: {e}")
            return {
                "success": False,
                "error": str(e),
                "message": f"分析角色 {character_name} 音色需求失败"
            }

    async def update_character_voice(
        self,
        state: ComicDramaState,
        character_name: str,
        voice_id: str,
        voice_speed: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        更新角色的音色信息

        Args:
            state: 当前状态
            character_name: 角色名称
            voice_id: 要设置的音色 ID
            voice_speed: 语速（可选，0.5-2.0）

        Returns:
            更新结果
        """
        try:
            updated = False
            for character in state.get("characters", []):
                if character.get("name") == character_name:
                    character["voice_id"] = voice_id
                    if voice_speed:
                        character["voice_speed"] = voice_speed
                    updated = True
                    logger.info(f"已更新角色 {character_name} 的音色为 {voice_id}")
                    break

            if not updated:
                return {
                    "success": False,
                    "message": f"未找到角色 {character_name}",
                    "error": "角色不存在"
                }

            return {
                "success": True,
                "message": f"已更新角色 {character_name} 的音色",
                "data": {
                    "character_name": character_name,
                    "voice_id": voice_id,
                    "voice_speed": voice_speed
                }
            }

        except Exception as e:
            logger.error(f"更新角色 {character_name} 音色失败: {e}")
            return {
                "success": False,
                "message": f"更新角色 {character_name} 音色失败",
                "error": str(e)
            }

    def get_available_voices(self, state: ComicDramaState) -> Dict[str, Any]:
        """
        获取可用的音色列表

        Args:
            state: 当前状态

        Returns:
            音色列表信息
        """
        return self.load_voice_list_tool.execute(state=state)
