"""
音频团队 - Audio Team

负责生成配音和背景音乐
"""

from typing import Dict, Any, List, Optional
from langchain_core.messages import SystemMessage, HumanMessage
from langchain_openai import ChatOpenAI
from app.agent.state.schemas import ComicDramaState
# 使用新的 LangChain @tool 函数
from app.agent.tools.agent_generation_tools import generate_audio
from app.core.logger import logger
from app.core.config import settings
import json


class AudioTeam:
    """音频团队"""
    
    def __init__(self, creation_uuid: str = ""):
        """初始化音频团队"""
        self.creation_uuid = creation_uuid
        self.llm = ChatOpenAI(
            model=settings.LLM_MODEL_SCRIPT_GENERATION,
            api_key=settings.OPENAI_API_KEY,
            base_url=settings.OPENAI_BASE_URL,
            temperature=0.3
        )
        # 不再实例化旧的 Tool 类，而是使用导入的 @tool 函数
        logger.info("音频团队初始化完成")
    
    async def extract_dialogues(
        self,
        state: ComicDramaState
    ) -> Dict[str, Any]:
        """
        从剧本中提取对话
        
        Args:
            state: 当前状态
            
        Returns:
            对话列表
        """
        script_text = state.get("script_text", "")
        
        if not script_text:
            return {"success": False, "error": "剧本内容为空", "dialogues": []}
        
        try:
            system_prompt = """请从剧本中提取所有对话内容，按场景分组。

输出格式：
{
    "dialogues": [
        {
            "scene_index": 0,
            "scene_name": "场景名称",
            "lines": [
                {
                    "character": "角色名",
                    "text": "对话内容",
                    "is_narration": false,
                    "emotion": "情绪（可选）"
                }
            ]
        }
    ]
}"""

            messages = [
                SystemMessage(content=system_prompt),
                HumanMessage(content=f"请提取以下剧本中的对话：\n\n{script_text}")
            ]
            
            response = await self.llm.ainvoke(messages)
            content = response.content
            
            # 解析 JSON
            import re
            json_match = re.search(r"```json\s*(.*?)\s*```", content, re.DOTALL)
            if json_match:
                json_str = json_match.group(1)
            else:
                json_str = content
            
            result = json.loads(json_str)
            
            return {
                "success": True,
                "dialogues": result.get("dialogues", [])
            }
            
        except Exception as e:
            logger.error(f"提取对话失败: {e}")
            return {"success": False, "error": str(e), "dialogues": []}
    
    async def generate_voiceovers(
        self,
        state: ComicDramaState,
        voice_ids: Optional[Dict[str, str]] = None
    ) -> Dict[str, Any]:
        """
        生成配音
        
        Args:
            state: 当前状态
            voice_ids: 角色到音色的映射
            
        Returns:
            配音列表
        """
        dialogues_result = await self.extract_dialogues(state)
        
        if not dialogues_result["success"]:
            return dialogues_result
        
        dialogues = dialogues_result.get("dialogues", [])
        characters = state.get("characters", [])
        
        voice_map = voice_ids or {}
        for char in characters:
            char_name = char.get("name", "")
            if char_name and "voice_id" in char:
                voice_map[char_name] = char["voice_id"]
        
        creation_uuid = state.get("creation_uuid", self.creation_uuid)
        results = []
        
        for scene in dialogues:
            scene_name = scene.get("scene_name", "")
            lines = scene.get("lines", [])
            
            for i, line in enumerate(lines):
                character = line.get("character", "")
                text = line.get("text", "")
                
                if not text:
                    continue
                
                voice_id = voice_map.get(character)
                
                try:
                    logger.info(f"生成配音: {character} - {text[:30]}...")
                    
                    # 使用新的 @tool 函数
                    audio_result = await generate_audio.ainvoke({
                        "creation_uuid": creation_uuid,
                        "shot_id": scene.get("scene_index", 0) * 100 + i,  # 生成唯一 shot_id
                        "text": text,
                        "voice_id": voice_id or settings.FISH_AUDIO_DEFAULT_VOICE_ID,
                        "audio_type": "narration" if line.get("is_narration") else "dialogue",
                        "speed": 1.0,
                    })
                    
                    is_success = audio_result.get("status") == "success"
                    
                    audio_segment = {
                        "id": f"audio_{scene.get('scene_index', 0)}_{i}",
                        "scene_index": scene.get("scene_index", 0),
                        "scene_name": scene_name,
                        "character": character,
                        "text": text,
                        "audio_url": audio_result.get("audio_url") if is_success else None,
                        "duration": audio_result.get("duration"),
                        "voice_id": voice_id,
                        "emotion": line.get("emotion"),
                        "status": "completed" if is_success else "failed",
                        "error": audio_result.get("error") if not is_success else None
                    }
                    
                    results.append(audio_segment)
                    
                except Exception as e:
                    logger.error(f"生成配音失败: {e}")
                    results.append({
                        "id": f"audio_{scene.get('scene_index', 0)}_{i}",
                        "scene_index": scene.get("scene_index", 0),
                        "scene_name": scene_name,
                        "character": character,
                        "text": text,
                        "status": "failed",
                        "error": str(e)
                    })
        
        success_count = sum(1 for r in results if r.get("status") == "completed")
        
        return {
            "success": success_count > 0,
            "total": len(results),
            "success_count": success_count,
            "audio_segments": results
        }
    
    async def generate_background_music(
        self,
        state: ComicDramaState,
        mood: str = "neutral",
        duration: int = 60
    ) -> Dict[str, Any]:
        """
        生成背景音乐
        
        Args:
            state: 当前状态
            mood: 音乐情绪（happy, sad, tense, neutral, epic, calm）
            duration: 时长（秒）
            
        Returns:
            背景音乐信息
        """
        try:
            logger.info(f"生成背景音乐: mood={mood}, duration={duration}s")
            
            system_prompt = f"""根据给定的情绪生成背景音乐提示词。

情绪: {mood}
时长: {duration}秒

请输出 JSON 格式：
{{
    "music_prompt": "详细的音乐描述，包括风格、节奏、乐器等",
    "suggested_style": "音乐风格",
    "tempo": "BPM 估算",
    "instruments": ["乐器列表"]
}}"""

            messages = [
                SystemMessage(content=system_prompt),
                HumanMessage(content="请生成背景音乐提示词")
            ]
            
            response = await self.llm.ainvoke(messages)
            content = response.content
            
            # 解析 JSON
            import re
            json_match = re.search(r"```json\s*(.*?)\s*```", content, re.DOTALL)
            if json_match:
                json_str = json_match.group(1)
            else:
                json_str = content
            
            result = json.loads(json_str)
            
            return {
                "success": True,
                "mood": mood,
                "duration": duration,
                "music_prompt": result.get("music_prompt", ""),
                "suggested_style": result.get("suggested_style", ""),
                "tempo": result.get("tempo", ""),
                "instruments": result.get("instruments", [])
            }
            
        except Exception as e:
            logger.error(f"生成背景音乐失败: {e}")
            return {"success": False, "error": str(e)}
    
    async def sync_audio_to_video(
        self,
        state: ComicDramaState,
        storyboard_index: int,
        audio_id: str,
        start_time: float
    ) -> Dict[str, Any]:
        """
        同步音频到视频时间线
        
        Args:
            state: 当前状态
            storyboard_index: 分镜索引
            audio_id: 音频 ID
            start_time: 起始时间（秒）
            
        Returns:
            同步结果
        """
        audio_segments = state.get("audio_segments", [])
        video_segments = state.get("video_segments", [])
        
        audio = next((a for a in audio_segments if a.get("id") == audio_id), None)
        
        if not audio:
            return {"success": False, "error": f"音频不存在: {audio_id}"}
        
        if storyboard_index < len(video_segments):
            video_segments[storyboard_index]["audio_sync"] = {
                "audio_id": audio_id,
                "start_time": start_time
            }
        
        return {
            "success": True,
            "storyboard_index": storyboard_index,
            "audio_id": audio_id,
            "start_time": start_time
        }
    
    def calculate_audio_timeline(self, state: ComicDramaState) -> Dict[str, Any]:
        """
        计算音频时间线
        
        Args:
            state: 当前状态
            
        Returns:
            时间线信息
        """
        audio_segments = state.get("audio_segments", [])
        
        total_duration = 0
        by_scene = {}
        
        for audio in audio_segments:
            duration = audio.get("duration", 0) or 0
            scene_index = audio.get("scene_index", 0)
            scene_name = audio.get("scene_name", f"场景{scene_index}")
            
            total_duration += duration
            
            if scene_name not in by_scene:
                by_scene[scene_name] = {
                    "duration": 0,
                    "segments": []
                }
            
            by_scene[scene_name]["duration"] += duration
            by_scene[scene_name]["segments"].append({
                "id": audio.get("id"),
                "start_time": audio.get("start_time", 0),
                "duration": duration,
                "character": audio.get("character")
            })
        
        return {
            "total_duration": total_duration,
            "audio_count": len(audio_segments),
            "by_scene": by_scene
        }


# 导出节点函数
async def generate_voiceovers_node(state: ComicDramaState) -> ComicDramaState:
    """
    LangGraph 节点：生成配音
    """
    team = AudioTeam()
    
    result = await team.generate_voiceovers(state)
    
    audio_segments = []
    messages = list(state.get("messages", []))
    errors = list(state.get("errors", []))
    
    if result["success"]:
        audio_segments = result.get("audio_segments", [])
        messages.append({
            "role": "system",
            "content": f"配音生成完成: {result['success_count']}/{result['total']} 条"
        })
        
        timeline = team.calculate_audio_timeline(state)
        messages.append({
            "role": "system",
            "content": f"音频总时长: {timeline['total_duration']:.1f} 秒"
        })
    else:
        errors.append(f"生成配音失败: {result.get('error')}")
    
    return {
        "audio_segments": audio_segments,
        "messages": messages,
        "errors": errors
    }


async def generate_bgm_node(state: ComicDramaState) -> ComicDramaState:
    """
    LangGraph 节点：生成背景音乐
    """
    team = AudioTeam()
    
    storyboards = state.get("storyboards", [])
    mood = "neutral"
    
    if storyboards:
        mood = storyboards[0].get("mood", "neutral")
    
    result = await team.generate_background_music(
        state=state,
        mood=mood,
        duration=120
    )
    
    messages = list(state.get("messages", []))
    errors = list(state.get("errors", []))
    
    if result["success"]:
        return {
            "background_music": result,
            "messages": messages,
            "errors": errors
        }
    else:
        errors.append(f"生成背景音乐失败: {result.get('error')}")
        return {
            "messages": messages,
            "errors": errors
        }
