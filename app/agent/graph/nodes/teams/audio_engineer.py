"""
音频工程师 Node - Audio Engineer

负责为分镜生成配音音频，包括：
1. 为角色选择合适的 Fish Audio 音色
2. 为 narration 添加音频标签（voice_id, emotion_tags, voice_speed）
3. 批量生成音频
"""

import json
from datetime import datetime
from typing import Dict, Any, List, Optional
from langchain_core.messages import SystemMessage, HumanMessage
from langchain_openai import ChatOpenAI
from app.agent.state.schemas import ComicDramaState, ProductionStage, CharacterState
from app.agent.tools.voice_selection_tools import (
    SelectVoiceForCharacterTool,
    BatchSelectVoiceTool,
    RematchVoiceTool
)
from app.core.logger import logger
from app.core.config import settings


class AudioEngineerNode:
    """
    音频工程师 Node
    
    职责：
    1. 查询待配音的分镜和角色
    2. 为没有 voice_id 的角色选择合适的 Fish Audio 音色
    3. 为每个 narration 条目添加音频标签（voice_id, emotion_tags, voice_speed）
    4. 创建批量音频生成任务
    """
    
    def __init__(self):
        """初始化 LLM 和工具"""
        self.llm = ChatOpenAI(
            model="Qwen/Qwen-Plus",
            api_key=settings.OPENAI_API_KEY,
            base_url=settings.OPENAI_BASE_URL,
            temperature=0.3,
            timeout=30,
            max_retries=2,
        )
        self.voice_selector = SelectVoiceForCharacterTool()
        self.batch_voice_selector = BatchSelectVoiceTool()
        self.rematch_tool = RematchVoiceTool()
        
        # 默认旁白音色
        self.default_narration_voice_id = getattr(
            settings, 'FISH_AUDIO_NARRATION_VOICE_ID',
            settings.FISH_AUDIO_DEFAULT_VOICE_ID
        )
    
    async def run(self, state: ComicDramaState) -> Dict[str, Any]:
        """
        执行音频处理
        
        Args:
            state: 当前状态
            
        Returns:
            执行结果
        """
        creation_uuid = state.get("creation_uuid")
        
        # 使用单一 db 会话处理所有操作
        from app.agent.tools.async_db import get_async_db_session
        from app.models.creation import Creation
        from app.models.shot import Shot
        from app.models.character import Character
        from app.models.scene import Scene
        from sqlalchemy import select
        from app.agent.tools.audio_tools import GenerateNarrationAudioBatchTool
        
        def parse_narration(narration_json):
            """解析旁白 JSON"""
            if not narration_json:
                return []
            try:
                if isinstance(narration_json, str):
                    return json.loads(narration_json)
                return narration_json
            except (json.JSONDecodeError, TypeError):
                return [{"角色": "旁白", "内容": narration_json}]
        
        try:
            async with get_async_db_session() as db:
                # 1. 查询 creation
                stmt = select(Creation).where(Creation.uuid == creation_uuid)
                result = await db.execute(stmt)
                creation = result.scalar_one_or_none()
                
                if not creation:
                    return {
                        "response_text": "创作项目不存在",
                        "production_stage": ProductionStage.STORYBOARD_READY,
                        "errors": [{"message": "创作项目不存在"}],
                    }
                
                creation_id = creation.creation_id
                
                # 2. 查询所有角色
                char_stmt = select(Character).where(
                    Character.creation_id == creation_id,
                    Character.deleted_at.is_(None),
                )
                char_result = await db.execute(char_stmt)
                characters = char_result.scalars().all()
                
                # 转换为字典列表
                character_list = []
                for char in characters:
                    # 从 basic_info 或 voice_description 推断性别
                    gender = self._infer_gender(char.basic_info, char.voice_description, char.name)
                    
                    character_list.append({
                        "character_id": char.character_id,
                        "name": char.name,
                        "description": char.voice_description or char.basic_info or "",  # 优先使用 voice_description
                        "voice_id": char.voice_id,
                        "voice_speed": char.voice_speed,
                        "gender": gender,
                    })
                
                # 3. 查询所有分镜和 narration
                shot_stmt = select(Shot).join(Scene).where(
                    Scene.creation_id == creation_id,
                    Shot.narration.isnot(None),
                )
                shot_result = await db.execute(shot_stmt)
                shots = shot_result.scalars().all()
                
                # 解析 narration，找出需要生成音频的项
                audio_items = []
                for shot in shots:
                    narration_list = parse_narration(shot.narration)
                    for idx, narration in enumerate(narration_list):
                        speaker = narration.get("角色", "旁白")
                        text = narration.get("内容", "")
                        
                        if not text:
                            continue
                        
                        # 检查是否已有音频
                        has_audio = narration.get("audio_url") is not None
                        
                        audio_items.append({
                            "shot_id": shot.shot_id,
                            "narration_index": idx,
                            "speaker": speaker,
                            "text": text,
                            "has_audio": has_audio,
                        })
                
                # 4. 为没有 voice_id 的角色选择音色
                logger.info(f"[AudioEngineer] 开始为角色选择音色...")
                voice_selection_results = await self._select_voices_for_characters(state, character_list, db)
                
                # 检查是否是仅选择音色的意图
                intent = state.get("detected_intent", "")
                if intent == "select_voice" and not audio_items:
                    voice_summary = self._build_voice_summary(voice_selection_results)
                    return {
                        "response_text": f"已为角色选择合适的音色！\n\n{voice_summary}",
                        "production_stage": ProductionStage.STORYBOARD_READY,
                        "worker_result": {"worker": "audio_engineer", "completed": True, "response_text": f"已为角色选择合适的音色！"},
                    }
                
                if not audio_items:
                    production_progress = dict(state.get("production_progress", {}))
                    production_progress["audio_processing"] = {"status": "completed"}
                    return {
                        "response_text": "所有音频已生成完成！请在分镜中试听确认。",
                        "production_stage": ProductionStage.AUDIO_READY,
                        "worker_result": {"worker": "audio_engineer", "completed": True, "response_text": "所有音频已生成完成！"},
                    }
                
                # 5. 提取需要生成音频的 shot_ids
                shot_ids = list(set([item.get("shot_id") for item in audio_items if item.get("shot_id")]))
                logger.info(f"[AudioEngineer] 需要生成音频的 shots: {shot_ids}")

                # 6. 直接在 Node 中批量生成音频（使用同一个 db 会话）
                logger.info(f"[AudioEngineer] 开始批量生成音频，共 {len(shot_ids)} 个分镜")
                
                audio_batch_tool = GenerateNarrationAudioBatchTool()
                
                success_count = 0
                failed_count = 0
                results = []
                
                for shot_id in shot_ids:
                    try:
                        result = await audio_batch_tool.execute(
                            state=state,
                            shot_id=shot_id,
                            force_regenerate=False,
                            db=db  # 传入同一个 db 会话
                        )
                        
                        if result.get("success"):
                            success_count += 1
                            logger.info(f"[AudioEngineer] Shot {shot_id} 音频生成成功")
                        else:
                            failed_count += 1
                            logger.error(f"[AudioEngineer] Shot {shot_id} 音频生成失败: {result.get('error')}")
                        
                        results.append({"shot_id": shot_id, "result": result})
                        
                    except Exception as e:
                        failed_count += 1
                        logger.error(f"[AudioEngineer] Shot {shot_id} 音频生成异常: {e}")
                        results.append({"shot_id": shot_id, "error": str(e)})
                
                # 所有 shot 处理完成后，提交事务
                if success_count > 0:
                    await db.commit()
                    logger.info(f"[AudioEngineer] 已提交 {success_count} 个分镜的音频更新")
            
            # 构建响应文本
            voice_summary = self._build_voice_summary(voice_selection_results)
            
            # 根据生成结果返回不同状态
            if success_count == len(shot_ids):
                # 全部成功
                production_progress = dict(state.get("production_progress", {}))
                production_progress["audio_processing"] = {
                    "status": "completed",
                    "total": len(shot_ids),
                    "completed": success_count,
                }
                
                response_text = f"""配音生成完成！

🎤 **共 {success_count} 个分镜音频生成成功**

{voice_summary}

请在分镜中试听确认配音效果。"""
                return {
                    "response_text": response_text,
                    "production_stage": ProductionStage.AUDIO_READY,
                    "worker_result": {"worker": "audio_engineer", "completed": True, "response_text": response_text},
                    "board_actions": [
                        {"type": "switch_view", "target": "storyboards"},
                    ],
                }
            elif success_count > 0:
                # 部分成功
                production_progress = dict(state.get("production_progress", {}))
                production_progress["audio_processing"] = {
                    "status": "partial",
                    "total": len(shot_ids),
                    "completed": success_count,
                    "failed": failed_count,
                }
                
                response_text = f"""配音生成部分完成！

🎤 **成功：{success_count} 个分镜**
❌ **失败：{failed_count} 个分镜**

{voice_summary}

部分音频生成失败，请检查日志或重试。"""
                return {
                    "response_text": response_text,
                    "production_stage": ProductionStage.AUDIO_READY,
                    "worker_result": {"worker": "audio_engineer", "completed": True, "response_text": response_text},
                    "errors": [{"message": f"{failed_count} 个分镜音频生成失败"}],
                    "board_actions": [
                        {"type": "switch_view", "target": "storyboards"},
                    ],
                }
            else:
                # 全部失败
                return {
                    "response_text": f"音频生成失败，请稍后重试或联系管理员。",
                    "production_stage": ProductionStage.STORYBOARD_READY,
                    "errors": [{"message": "所有分镜音频生成失败"}],
                }
            
        except Exception as e:
            logger.error(f"[AudioEngineer] 执行失败: {e}")
            return {
                "response_text": f"音频处理过程中出现错误：{str(e)}",
                "production_stage": ProductionStage.STORYBOARD_READY,
                "errors": [{"message": str(e)}],
            }
    
    async def _select_voices_for_characters(
        self,
        state: ComicDramaState,
        characters: List[Dict[str, Any]],
        db=None
    ) -> List[Dict[str, Any]]:
        """
        为没有 voice_id 的角色选择音色
        
        Args:
            state: 当前状态
            characters: 角色列表
            db: 数据库会话（可选，用于直接更新）
            
        Returns:
            音色选择结果列表
        """
        results = []
        
        # 检查是否需要重新匹配（从用户意图判断）
        intent = state.get("detected_intent", "")
        user_input = state.get("user_input", "").lower()
        force_rematch = "重新匹配" in user_input or "rematch" in user_input
        
        # 使用批量选择工具
        try:
            batch_result = await self.batch_voice_selector.execute(
                state=state,
                skip_assigned=False,  # 不跳过已有音色的角色，允许重新匹配
                force_rematch=force_rematch
            )
            
            if batch_result.get("success"):
                batch_data = batch_result.get("data", {})
                batch_results = batch_data.get("results", [])
                voice_assignments = batch_data.get("voice_assignments", {})
                
                # 更新每个角色的音色
                for char in characters:
                    char_id = char.get("character_id")
                    char_name = char.get("name")
                    
                    # 查找该角色的选择结果
                    char_result = None
                    for r in batch_results:
                        if r.get("character_name") == char_name:
                            char_result = r
                            break
                    
                    if char_result and char_result.get("status") == "success":
                        voice_id = char_result.get("voice_id")
                        voice_title = char_result.get("voice_title")
                        
                        # 更新内存中的角色信息
                        char["voice_id"] = voice_id
                        char["voice_name"] = voice_title
                        
                        # 更新数据库中的角色 voice_id（使用传入的 db 会话）
                        if char_id and voice_id and db is not None:
                            try:
                                from sqlalchemy import update
                                from app.models.character import Character
                                
                                await db.execute(
                                    update(Character)
                                    .where(Character.character_id == char_id)
                                    .values(
                                        voice_id=voice_id,
                                        voice_speed="1.0",
                                        updated_at=datetime.now()
                                    )
                                )
                                logger.info(f"[AudioEngineer] 已更新角色 {char_name} 的音色到数据库: {voice_id}")
                            except Exception as db_e:
                                logger.error(f"[AudioEngineer] 更新角色 {char_name} 音色到数据库异常: {db_e}")
                        
                        results.append({
                            "character_name": char_name,
                            "voice_id": voice_id,
                            "voice_name": voice_title,
                            "match_score": char_result.get("match_score"),
                            "match_reason": char_result.get("match_reason"),
                            "is_rematch": char_result.get("is_rematch", False),
                            "status": "success"
                        })
                        
                        logger.info(f"[AudioEngineer] 为角色 {char_name} 选择音色: {voice_title}")
                    elif char_result and char_result.get("status") == "skipped":
                        results.append({
                            "character_name": char_name,
                            "voice_id": char_result.get("voice_id"),
                            "status": "skipped",
                            "reason": "已有音色"
                        })
                    else:
                        error_msg = char_result.get("error") if char_result else "未知错误"
                        logger.warning(f"[AudioEngineer] 为角色 {char_name} 选择音色失败: {error_msg}")
                        results.append({
                            "character_name": char_name,
                            "status": "failed",
                            "error": error_msg
                        })
                
                return results
            else:
                logger.error(f"[AudioEngineer] 批量选择音色失败: {batch_result.get('error')}")
                
        except Exception as e:
            logger.error(f"[AudioEngineer] 批量选择音色异常: {e}")
        
        # 如果批量选择失败，回退到逐个选择
        logger.info("[AudioEngineer] 回退到逐个选择音色...")
        
        for char in characters:
            char_id = char.get("id")
            char_name = char.get("name")
            voice_id = char.get("voice_id")
            
            # 如果已有 voice_id 且不强制重新匹配，跳过
            if voice_id and not force_rematch:
                logger.info(f"[AudioEngineer] 角色 {char_name} 已有音色: {voice_id}")
                continue
            
            # 使用 VoiceSelectionTool 选择音色
            try:
                result = await self.voice_selector.execute(
                    state=state,
                    character_name=char_name,
                    character_description=char.get("basic_info", ""),
                    character_personality=char.get("appearance", "")
                )
                
                if result.get("success"):
                    voice_data = result.get("data", {})
                    selected_voice = voice_data.get("voice", {})
                    selected_voice_id = selected_voice.get("voice_id")
                    selected_voice_name = selected_voice.get("title")
                    
                    # 更新内存中的角色信息
                    char["voice_id"] = selected_voice_id
                    char["voice_name"] = selected_voice_name
                    
                    # 更新数据库中的角色 voice_id
                    if char_id and selected_voice_id:
                        try:
                            update_result = await update_character_voice.ainvoke({
                                "character_id": char_id,
                                "voice_id": selected_voice_id,
                                "voice_speed": "1.0"  # 默认语速
                            })
                            if update_result.get("success"):
                                logger.info(f"[AudioEngineer] 已更新角色 {char_name} 的音色到数据库: {selected_voice_id}")
                            else:
                                logger.warning(f"[AudioEngineer] 更新角色 {char_name} 音色到数据库失败: {update_result.get('error')}")
                        except Exception as db_e:
                            logger.error(f"[AudioEngineer] 更新角色 {char_name} 音色到数据库异常: {db_e}")
                    
                    results.append({
                        "character_name": char_name,
                        "voice_id": selected_voice_id,
                        "voice_name": selected_voice_name,
                        "match_score": voice_data.get("match_score"),
                        "status": "success"
                    })
                    
                    logger.info(f"[AudioEngineer] 为角色 {char_name} 选择音色: {selected_voice_name}")
                else:
                    logger.warning(f"[AudioEngineer] 为角色 {char_name} 选择音色失败: {result.get('error')}")
                    results.append({
                        "character_name": char_name,
                        "status": "failed",
                        "error": result.get("error")
                    })
                    
            except Exception as e:
                logger.error(f"[AudioEngineer] 为角色 {char_name} 选择音色异常: {e}")
                results.append({
                    "character_name": char_name,
                    "status": "error",
                    "error": str(e)
                })
        
        return results
    
    async def _tag_audio_items(
        self,
        state: ComicDramaState,
        audio_items: List[Dict[str, Any]],
        characters: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """
        为音频项添加音频标签
        
        Args:
            state: 当前状态
            audio_items: 音频项列表
            characters: 角色列表（用于获取 voice_id）
            
        Returns:
            添加了音频标签的音频项列表
        """
        # 构建角色 voice_id 映射
        char_voice_map = {c.get("name"): c.get("voice_id") for c in characters}
        
        tagged_items = []
        
        for item in audio_items:
            shot_id = item.get("shot_id")
            speaker = item.get("speaker", "旁白")
            text = item.get("text", "")
            
            # 判断是旁白还是对话
            is_narration = speaker in ["旁白", "narration", "解说", "narrator"]
            
            # 获取 voice_id
            if is_narration:
                voice_id = self.default_narration_voice_id
            else:
                voice_id = char_voice_map.get(speaker)
                if not voice_id:
                    voice_id = state.get("creation_voice_id") or settings.FISH_AUDIO_DEFAULT_VOICE_ID
                    logger.warning(f"[AudioEngineer] 角色 {speaker} 没有 voice_id，使用默认值")
            
            # 分析情感标签
            emotion_analysis = self._analyze_emotion(text, speaker, is_narration)
            
            tagged_item = {
                "shot_id": shot_id,
                "text": text,
                "voice_id": voice_id,
                "audio_type": "narration" if is_narration else "dialogue",
                "speed": emotion_analysis.get("voice_speed", 1.0),
                "emotion_tags": emotion_analysis.get("emotion_tags", []),
                "speaker": speaker,
            }
            
            tagged_items.append(tagged_item)
            
            logger.info(
                f"[AudioEngineer] Tagged shot {shot_id}: {speaker} -> "
                f"voice_id={voice_id}, emotions={emotion_analysis.get('emotion_tags')}"
            )
        
        return tagged_items
    
    def _analyze_emotion(
        self,
        text: str,
        speaker: str,
        is_narration: bool
    ) -> Dict[str, Any]:
        """
        分析文本情感，推荐情感标签
        
        Args:
            text: 文本内容
            speaker: 说话者
            is_narration: 是否是旁白
            
        Returns:
            情感分析结果
        """
        # 旁白默认情感
        if is_narration:
            return {
                "emotion_tags": ["calm", "confident"],
                "voice_speed": 1.0
            }
        
        # 角色对话情感分析（基于关键词）
        emotion_tags = []
        voice_speed = 1.0
        
        text_lower = text.lower()
        
        # 情感关键词映射
        emotion_keywords = {
            "happy": ["开心", "高兴", "快乐", "哈哈", "太好了", "棒", "喜欢", "爱", "开心"],
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
    
    def _build_voice_summary(self, voice_results: List[Dict[str, Any]]) -> str:
        """构建音色选择摘要"""
        if not voice_results:
            return ""
        
        success_count = sum(1 for r in voice_results if r.get("status") == "success")
        rematch_count = sum(1 for r in voice_results if r.get("is_rematch"))
        failed_count = sum(1 for r in voice_results if r.get("status") == "failed")
        skipped_count = sum(1 for r in voice_results if r.get("status") == "skipped")
        
        lines = ["🎙️ **音色分配**："]
        
        if rematch_count > 0:
            lines.append(f"\n（已重新匹配 {rematch_count} 个角色的音色）")
        
        for result in voice_results:
            char_name = result.get('character_name', '未知角色')
            if result.get("status") == "success":
                voice_name = result.get('voice_name', '默认音色')
                match_score = result.get('match_score', 0)
                is_rematch = result.get('is_rematch', False)
                
                rematch_mark = " 🔄" if is_rematch else ""
                score_info = f" (匹配度: {match_score:.0f}%)" if match_score else ""
                
                lines.append(f"- {char_name}: {voice_name}{score_info}{rematch_mark}")
            elif result.get("status") == "skipped":
                lines.append(f"- {char_name}: 保持原有音色 ⏭️")
            else:
                lines.append(f"- {char_name}: 分配失败 ❌")
        
        return "\n".join(lines)
    
    def _infer_gender(self, basic_info: str, voice_description: str, name: str) -> str:
        """
        从角色信息推断性别
        
        Args:
            basic_info: 角色基本信息
            voice_description: 声音描述
            name: 角色名称
            
        Returns:
            推断的性别: "male", "female", 或 "unknown"
        """
        # 合并所有文本用于分析
        text = f"{basic_info or ''} {voice_description or ''} {name or ''}".lower()
        
        # 男性关键词
        male_keywords = ['男', 'boy', 'man', 'male', 'he', 'his', 'him', '他', '哥哥', '弟弟', '爸爸', '爷爷', '先生', '男子', '男孩']
        # 女性关键词
        female_keywords = ['女', 'girl', 'woman', 'female', 'she', 'her', 'hers', '她', '姐姐', '妹妹', '妈妈', '奶奶', '女士', '女子', '女孩']
        
        male_count = sum(1 for kw in male_keywords if kw in text)
        female_count = sum(1 for kw in female_keywords if kw in text)
        
        if male_count > female_count:
            return "male"
        elif female_count > male_count:
            return "female"
        else:
            # 无法确定时返回 unknown
            return "unknown"


# 便捷函数
async def process_audio(state: ComicDramaState) -> Dict[str, Any]:
    """LangGraph node 函数"""
    node = AudioEngineerNode()
    return await node.run(state)
