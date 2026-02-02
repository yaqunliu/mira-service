import json
from typing import List, Dict, Any, Optional, Callable
from datetime import datetime
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.tools.base import BaseTool
from app.agent.state.schemas import ComicDramaState
from app.core.logger import logger
from app.core.config import settings
from app.agent.tools.async_db import get_async_db_session
from app.utils.us3 import US3Client


class GenerateNarrationAudioBatchTool(BaseTool):
    """批量生成 Narration 音频工具

    为 shot 的 narration 数组批量生成音频：
    1. 解析 narration 数组
    2. 根据说话者获取 voice_id 和 voice_speed
    3. 根据情绪添加情感标签
    4. 生成音频并上传到 US3
    5. 保存音频 URL 到 shot.audio_url
    6. 保存音频历史到 audio_historys
    """

    @property
    def name(self) -> str:
        return "generate_narration_audio_batch"

    @property
    def description(self) -> str:
        return """批量生成 narration 音频。

功能：
1. 解析 shot.narration 数组（格式: [{"角色": "...", "内容": "..."}])
2. 根据说话者名称关联角色的 voice_id 和 voice_speed
3. 根据文本情绪自动添加情感标签
4. 调用 Fish Audio 生成音频
5. 上传音频到 US3
6. 保存音频 URL 到 shot.audio_url
7. 保存音频历史到 shot.audio_historys（JSONB 数组）

输入：
- shot_id: 分镜 ID
- force_regenerate: 是否强制重新生成（默认 False）

返回：
- 生成的音频信息列表
- 每个音频包含：audio_url, speaker, text, voice_id, emotion_tags 等
"""

    def __init__(self, db_factory=None):
        super().__init__(db_factory)
        self.us3_client = None


    def _get_us3_client(self) -> US3Client:
        """获取 US3 客户端"""
        if self.us3_client is None:
            self.us3_client = US3Client()
        return self.us3_client

    async def _generate_audio(
        self,
        state: ComicDramaState,
        text: str,
        voice_id: str,
        speed: float = 1.0,
    ) -> Dict[str, Any]:
        """生成音频
        
        使用 FishAudioClient 生成音频并上传到 US3
        
        Args:
            state: 当前状态
            text: 要合成的文本
            voice_id: 音色 ID
            speed: 语速 (0.5-2.0)
        """
        import asyncio
        import re
        
        try:
            from app.utils.fish_audio import FishAudioClient
            
            client = FishAudioClient()
            
            loop = asyncio.get_event_loop()
            audio_bytes = await loop.run_in_executor(
                None,
                lambda: client.text_to_speech(
                    text=text,
                    reference_id=voice_id or settings.FISH_AUDIO_DEFAULT_VOICE_ID,
                    speed=speed if speed != 1.0 else None
                )
            )
            
            # 上传到 US3
            us3_client = self._get_us3_client()
            creation_uuid = state.get("creation_uuid") or "default"
            
            safe_text = re.sub(r'[^\w\u4e00-\u9fff]+', '_', text[:10]).strip('_')
            if not safe_text:
                safe_text = "audio"
            file_name = f"audio/{creation_uuid}/{safe_text}.mp3"
            
            header = {'Content-Type': 'audio/mpeg'}
            
            upload_result = await loop.run_in_executor(
                None,
                lambda: us3_client.upload_file_stream(
                    file_stream=audio_bytes,
                    put_key=file_name,
                    header=header,
                    content_type="audio/mpeg"
                )
            )
            
            if isinstance(upload_result, dict) and upload_result.get("success"):
                audio_url = us3_client.get_file_url(file_name)
                return {"success": True, "audio_url": audio_url, "voice_id": voice_id}
            else:
                error_msg = upload_result.get("message", "上传失败") if isinstance(upload_result, dict) else "上传失败"
                return {"success": False, "error": f"US3上传失败: {error_msg}"}
                
        except Exception as e:
            logger.error(f"生成音频失败: {e}")
            return {"success": False, "error": str(e)}


    def _parse_narration(self, narration_data) -> List[Dict[str, str]]:
        """解析 narration 数据"""
        if not narration_data:
            return []

        try:
            if isinstance(narration_data, str):
                return json.loads(narration_data)
            return narration_data
        except (json.JSONDecodeError, TypeError):
            logger.error(f"解析 narration 失败: {narration_data}")
            return []

    def _analyze_emotion(self, text: str, speaker: str) -> Dict[str, Any]:
        """分析文本情感，返回情感标签和语速"""
        emotion_tags = []
        voice_speed = 1.0

        # 旁白默认情感
        if speaker in ["旁白", "narration", "解说", "narrator"]:
            emotion_tags = ["calm", "confident"]
            voice_speed = 1.0
        else:
            # 角色对话情感分析（基于关键词）
            emotion_keywords = {
                "happy": ["开心", "高兴", "快乐", "哈哈", "太好了", "棒", "喜欢", "爱"],
                "sad": ["难过", "伤心", "哭", "泪", "痛苦", "悲伤", "失望", "遗憾"],
                "angry": ["生气", "愤怒", "讨厌", "恨", "滚", "混蛋", "可恶"],
                "excited": ["兴奋", "激动", "太棒了", "哇", "天哪", "不可思议"],
                "nervous": ["紧张", "害怕", "担心", "焦虑", "不安", "忐忑"],
                "surprised": ["惊讶", "震惊", "没想到", "竟然", "真的吗"],
                "worried": ["担心", "忧虑", "怎么办", "会不会", "万一"],
                "confident": ["肯定", "一定", "没问题", "相信我", "放心"],
                "whispering": ["小声", "悄悄", "耳语", "低声"],
                "laughing": ["哈哈", "嘿嘿", "呵呵", "嘻嘻"],
                "sighing": ["叹气", "叹息", "唉", "哎"],
            }

            for emotion, keywords in emotion_keywords.items():
                if any(kw in text for kw in keywords):
                    emotion_tags.append(emotion)

            # 如果没有检测到情感，使用默认
            if not emotion_tags:
                emotion_tags = ["neutral"]

            # 根据文本长度调整语速
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
        shot_id: int,
        force_regenerate: bool = False,
        db: AsyncSession = None,
        **kwargs
    ) -> Dict[str, Any]:
        """
        批量生成 narration 音频

        Args:
            state: 当前状态
            shot_id: 分镜 ID
            force_regenerate: 是否强制重新生成
            db: 外部传入的数据库会话（可选）

        Returns:
            包含生成结果的字典
        """
        # 如果外部传入 db 会话，直接使用（不提交，由调用方控制）
        if db is not None:
            return await self._execute_with_db(state, shot_id, force_regenerate, db, auto_commit=False)

        # 否则创建新会话，自动提交
        async with get_async_db_session() as db:
            return await self._execute_with_db(state, shot_id, force_regenerate, db, auto_commit=True)

    async def _execute_with_db(
        self,
        state: ComicDramaState,
        shot_id: int,
        force_regenerate: bool,
        db: AsyncSession,
        auto_commit: bool = True
    ) -> Dict[str, Any]:
        """使用已存在的 db 会话执行
        
        Args:
            auto_commit: 是否自动提交事务。当使用外部传入的会话时应设为 False
        """
        from app.models.shot import Shot
        from app.models.character import Character
        from sqlalchemy import select, update

        try:
            # 获取 shot
            shot = await db.get(Shot, shot_id)
            if not shot:
                return self._create_error_result(
                    message=f"分镜 {shot_id} 不存在",
                    error="Shot not found"
                )

            # 检查是否已有音频且不强制重新生成
            if shot.audio_url and not force_regenerate:
                return self._create_success_result(
                    message=f"分镜 {shot_id} 已有音频，跳过生成",
                    data={"audio_url": shot.audio_url, "skipped": True}
                )

            # 解析 narration
            narration_list = self._parse_narration(shot.narration)
            if not narration_list:
                return self._create_error_result(
                    message="分镜没有 narration 内容",
                    error="No narration content"
                )

            # 获取所有角色信息（用于查找 voice_id）
            # 使用显式查询而不是 relationship 属性，避免 greenlet 问题
            char_voice_map = {}
            try:
                from app.models.character import Character
                from app.models.shot import shot_characters
                
                # 查询与该 shot 关联的所有角色
                char_stmt = select(Character).join(
                    shot_characters, 
                    Character.character_id == shot_characters.c.character_id
                ).where(shot_characters.c.shot_id == shot_id)
                
                char_result = await db.execute(char_stmt)
                characters = char_result.scalars().all()
                
                for char in characters:
                    char_voice_map[char.name] = {
                        "voice_id": char.voice_id,
                        "voice_speed": float(char.voice_speed) if char.voice_speed else 1.0,
                        "character_id": char.character_id
                    }
                
                logger.info(f"[GenerateNarrationAudio] Shot {shot_id} 关联角色: {list(char_voice_map.keys())}")
            except Exception as char_e:
                logger.warning(f"[GenerateNarrationAudio] 获取角色信息失败: {char_e}")

            # 获取 creation 的默认 voice_id
            creation_voice_id = state.get("creation_voice_id") or settings.FISH_AUDIO_DEFAULT_VOICE_ID

            # 批量生成音频
            updated_narration_list = []
            success_count = 0

            for idx, narration in enumerate(narration_list):
                speaker = narration.get("角色", "旁白")
                text = narration.get("内容", "")

                if not text:
                    logger.warning(f"Narration {idx} 内容为空，跳过")
                    updated_narration_list.append(narration)
                    continue

                # 判断是旁白还是对话
                is_narration = speaker in ["旁白", "narration", "解说", "narrator"]

                # 获取 voice_id 和 voice_speed
                if is_narration:
                    voice_id = creation_voice_id
                    voice_speed = 1.0
                    character_id = None
                else:
                    char_info = char_voice_map.get(speaker, {})
                    voice_id = char_info.get("voice_id") or creation_voice_id
                    voice_speed = char_info.get("voice_speed", 1.0)
                    character_id = char_info.get("character_id")

                # 分析情感
                emotion_analysis = self._analyze_emotion(text, speaker)

                # 如果角色有特定语速，优先使用
                if not is_narration and char_info.get("voice_speed"):
                    voice_speed = char_info["voice_speed"]
                else:
                    voice_speed = emotion_analysis["voice_speed"]

                logger.info(f"[GenerateNarrationAudio] Shot {shot_id}, Narration {idx}: speaker={speaker}, voice_id={voice_id}")

                # 生成音频 - 直接使用 FishAudioClient
                audio_result = await self._generate_audio(
                    state=state,
                    text=text,
                    voice_id=voice_id,
                    speed=voice_speed
                )

                # 构建更新的 narration 项
                updated_narration = dict(narration)

                if audio_result.get("success"):
                    audio_url = audio_result.get("audio_url")

                    # 添加 audio_url
                    updated_narration["audio_url"] = audio_url

                    # 添加/更新 audio_historys
                    if "audio_historys" not in updated_narration:
                        updated_narration["audio_historys"] = []
                    elif not isinstance(updated_narration["audio_historys"], list):
                        updated_narration["audio_historys"] = []

                    # 添加新的音频到历史
                    updated_narration["audio_historys"].append(audio_url)

                    # 保留最近 10 条历史
                    if len(updated_narration["audio_historys"]) > 10:
                        updated_narration["audio_historys"] = updated_narration["audio_historys"][-10:]

                    success_count += 1
                    logger.info(f"[GenerateNarrationAudio] 成功生成音频 {idx}: {audio_url}")
                else:
                    logger.error(f"[GenerateNarrationAudio] 生成音频失败 {idx}: {audio_result.get('error')}")
                    updated_narration["audio_error"] = audio_result.get("error")


                updated_narration_list.append(updated_narration)

            # 更新 shot 记录
            update_values = {
                "narration": json.dumps(updated_narration_list, ensure_ascii=False),
                "updated_at": datetime.now()
            }

            # 设置主 audio_url（使用第一个成功的音频）
            for narration in updated_narration_list:
                if narration.get("audio_url"):
                    update_values["audio_url"] = narration["audio_url"]
                    break

            await db.execute(
                update(Shot)
                .where(Shot.shot_id == shot_id)
                .values(**update_values)
            )
            
            # 只有在 auto_commit=True 时才提交
            if auto_commit:
                await db.commit()
                logger.info(f"[GenerateNarrationAudio] 已更新 shot {shot_id} 的 narration 字段并提交")
            else:
                logger.info(f"[GenerateNarrationAudio] 已更新 shot {shot_id} 的 narration 字段（未提交，由调用方控制）")

            return self._create_success_result(
                message=f"成功生成 {success_count}/{len(narration_list)} 个音频",
                data={
                    "shot_id": shot_id,
                    "audio_url": update_values.get("audio_url"),
                    "success_count": success_count,
                    "total_narrations": len(narration_list),
                    "narrations": updated_narration_list
                }
            )

        except Exception as e:
            logger.exception(f"[GenerateNarrationAudio] 批量生成音频失败: {e}")
            return self._create_error_result(
                message="批量生成音频失败",
                error=str(e)
            )
