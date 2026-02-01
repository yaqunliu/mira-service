"""
音频处理 Agent - Audio Agent

负责协调音频生成工具，为漫画短剧的各个分镜生成高质量音频
"""

from typing import Dict, Any, List, Optional
from langchain_core.messages import SystemMessage, HumanMessage
from langchain_openai import ChatOpenAI
from app.agent.state.schemas import ComicDramaState
from app.agent.tools.audio_tools import (
    GenerateAudioWithEmotionTool,
    AnalyzeEmotionTool,
    GenerateShotAudioTool,
    SaveAudioToShotTool,
)
from app.agent.tools.async_db import get_async_db_session
from app.core.logger import logger
from app.core.config import settings
from sqlalchemy import select
import json


class AudioAgent:
    """音频处理 Agent - 协调音频生成工作流"""
    
    def __init__(self):
        """初始化音频 Agent"""
        self.llm = ChatOpenAI(
            model=settings.LLM_MODEL_SCRIPT_GENERATION,
            api_key=settings.OPENAI_API_KEY,
            base_url=settings.OPENAI_BASE_URL,
            temperature=0.2
        )
        
        self.generate_audio_tool = GenerateAudioWithEmotionTool()
        self.analyze_emotion_tool = AnalyzeEmotionTool()
        self.generate_shot_audio_tool = GenerateShotAudioTool()
        self.save_audio_tool = SaveAudioToShotTool()
        
        logger.info("音频 Agent 初始化完成")
    
    async def generate_audio_for_shot(
        self,
        state: ComicDramaState,
        shot_id: int,
        narration_index: int = 0
    ) -> Dict[str, Any]:
        """
        为单个分镜生成音频
        
        Args:
            state: 当前状态
            shot_id: 分镜 ID
            narration_index: 旁白索引
            
        Returns:
            生成结果
        """
        return await self.generate_shot_audio_tool.execute(
            state=state,
            shot_id=shot_id,
            narration_index=narration_index
        )
    
    async def generate_audio_for_all_shots(
        self,
        state: ComicDramaState,
        scene_id: Optional[int] = None,
        shot_ids: Optional[List[int]] = None
    ) -> Dict[str, Any]:
        """
        为多个分镜生成音频
        
        Args:
            state: 当前状态
            scene_id: 场景 ID（可选）
            shot_ids: 分镜 ID 列表（可选）
            
        Returns:
            生成结果汇总
        """
        try:
            from app.models.shot import Shot
            
            async with get_async_db_session() as db:
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
                        return self._create_error_result(
                            message="未指定场景 ID",
                            error="No scene_id provided"
                        )
                    result = await db.execute(
                        select(Shot)
                        .where(Shot.scene_id == current_scene_id)
                        .order_by(Shot.shot_number)
                    )
                    shots = result.scalars().all()
            
            if not shots:
                return self._create_error_result(
                    message="没有找到需要生成音频的分镜",
                    error="No shots found"
                )
            
            results = []
            for shot in shots:
                narration_list = self._parse_narration(shot.narration)
                
                for i, narration in enumerate(narration_list):
                    result = await self.generate_audio_for_shot(
                        state=state,
                        shot_id=shot.shot_id,
                        narration_index=i
                    )
                    results.append({
                        "shot_id": shot.shot_id,
                        "shot_title": shot.title,
                        "narration_index": i,
                        "speaker": narration.get("角色", "旁白"),
                        "result": result
                    })
            
            success_count = sum(1 for r in results if r.get("result", {}).get("success"))
            failed_count = len(results) - success_count
            
            return {
                "success": True,
                "message": f"音频生成完成: {success_count} 成功, {failed_count} 失败",
                "data": {
                    "total": len(results),
                    "success_count": success_count,
                    "failed_count": failed_count,
                    "results": results
                }
            }
            
        except Exception as e:
            logger.exception(f"批量生成音频失败: {e}")
            return self._create_error_result(
                message="批量生成音频失败",
                error=str(e)
            )
    
    async def analyze_script_audio_needs(
        self,
        state: ComicDramaState
    ) -> Dict[str, Any]:
        """
        分析剧本中的音频需求
        
        Returns:
            分析结果，包含旁白数量、角色对话数量等
        """
        try:
            from app.models.scene import Scene
            
            current_scene_id = state.get("current_scene_id")
            if not current_scene_id:
                return {"success": True, "message": "未指定场景，跳过分析", "data": {}}
            
            async with get_async_db_session() as db:
                scene = await db.get(Scene, current_scene_id)
                if not scene:
                    return {"success": True, "message": "场景不存在，跳过分析", "data": {}}
                
                narration_count = 0
                character_dialogue_count = 0
                total_duration_estimate = 0
                
                for shot in scene.shots:
                    narration_list = self._parse_narration(shot.narration)
                    for narration in narration_list:
                        speaker = narration.get("角色", "")
                        text = narration.get("内容", "")
                        
                        if speaker in ["旁白", "narration"]:
                            narration_count += 1
                        else:
                            character_dialogue_count += 1
                        
                        total_duration_estimate += len(text) * 0.5
                
                return {
                    "success": True,
                    "message": "剧本分析完成",
                    "data": {
                        "narration_count": narration_count,
                        "character_dialogue_count": character_dialogue_count,
                        "total_audio_segments": narration_count + character_dialogue_count,
                        "estimated_duration_seconds": int(total_duration_estimate)
                    }
                }
                
        except Exception as e:
            logger.exception(f"剧本分析失败: {e}")
            return {"success": False, "message": "剧本分析失败", "error": str(e)}
    
    async def review_generated_audios(
        self,
        state: ComicDramaState,
        generate_result: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        审核生成的音频
        
        Args:
            generate_result: generate_audio_for_all_shots 的返回结果
            
        Returns:
            审核结果
        """
        results = generate_result.get("data", {}).get("results", [])
        
        audio_segments = []
        for result in results:
            if result.get("success"):
                audio_info = result.get("data", {})
                audio_segments.append({
                    "shot_id": audio_info.get("shot_id"),
                    "audio_url": audio_info.get("audio_url"),
                    "speaker": audio_info.get("speaker"),
                    "voice_id": audio_info.get("voice_id"),
                    "emotion_tags": audio_info.get("emotion_tags", [])
                })
        
        return {
            "success": True,
            "message": f"音频审核完成，共 {len(audio_segments)} 个音频片段",
            "data": {
                "audio_segments": audio_segments,
                "total_duration": None
            }
        }
    
    async def analyze_and_recommend_voice(
        self,
        state: ComicDramaState,
        text: str,
        character_name: Optional[str] = None,
        character_description: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        分析文本和角色，推荐合适的语音配置
        
        Args:
            state: 当前状态
            text: 要分析的文本
            character_name: 角色名称
            character_description: 角色描述
            
        Returns:
            推荐配置
        """
        try:
            system_prompt = """你是一个语音选择专家，负责为文本推荐最适合的 Fish Audio 语音配置。

分析维度：
1. 文本类型：旁白、对话、独白、内心OS
2. 说话者特征：年龄、性别、性格、情绪
3. 场景氛围：紧张、轻松、悲伤、欢快

请输出 JSON 格式：
{
    "voice_type": "narration|character",
    "recommended_voice_id": "voice_id 或 null",
    "voice_speed": 1.0,
    "emotion_tags": ["tag1", "tag2"],
    "reason": "推荐理由"
}
"""

            user_content = f"待分析文本：{text}"
            if character_name:
                user_content += f"\n角色名称：{character_name}"
            if character_description:
                user_content += f"\n角色描述：{character_description}"

            messages = [
                SystemMessage(content=system_prompt),
                HumanMessage(content=user_content)
            ]

            response = await self.llm.ainvoke(messages)
            content = response.content

            import re
            json_match = re.search(r"```json\s*(.*?)\s*```", content, re.DOTALL)
            if json_match:
                json_str = json_match.group(1)
            else:
                json_str = content

            config = json.loads(json_str)

            logger.info(f"语音配置推荐: {config}")

            return {
                "success": True,
                "message": "语音配置推荐完成",
                "data": config
            }

        except Exception as e:
            logger.exception(f"语音配置推荐失败: {e}")
            return self._create_error_result(
                message="语音配置推荐失败",
                error=str(e)
            )
    
    def _parse_narration(self, narration_json: str) -> List[Dict[str, str]]:
        """解析旁白 JSON"""
        if not narration_json:
            return []
        
        try:
            if isinstance(narration_json, str):
                return json.loads(narration_json)
            return narration_json
        except (json.JSONDecodeError, TypeError):
            return []
    
    def _create_error_result(self, message: str, error: str) -> Dict[str, Any]:
        """创建错误结果"""
        return {
            "success": False,
            "message": message,
            "data": None,
            "error": error
        }


async def audio_processing_node(state: ComicDramaState) -> ComicDramaState:
    """
    LangGraph 节点：音频处理
    
    处理当前场景/分镜的音频生成
    """
    audio_agent = AudioAgent()
    
    current_scene_id = state.get("current_scene_id")
    current_shot_id = state.get("current_shot_id")
    messages = list(state.get("messages", []))
    
    try:
        if current_shot_id:
            result = await audio_agent.generate_audio_for_shot(
                state=state,
                shot_id=current_shot_id
            )
            
            if result.get("success"):
                audio_url = result.get("data", {}).get("audio_url")
                messages.append({
                    "role": "system",
                    "content": f"🎙️ 音频生成成功: {audio_url}"
                })
                
                audio_segments = list(state.get("audio_segments", []))
                audio_segments.append({
                    "shot_id": current_shot_id,
                    "audio_url": audio_url
                })
                
                return {
                    "messages": messages,
                    "audio_segments": audio_segments
                }
            else:
                messages.append({
                    "role": "system",
                    "content": f"❌ 音频生成失败: {result.get('error')}"
                })
                errors = list(state.get("errors", []))
                errors.append(f"音频生成失败: {result.get('error')}")
                return {
                    "messages": messages,
                    "errors": errors
                }
        
        elif current_scene_id:
            result = await audio_agent.generate_audio_for_all_shots(
                state=state,
                scene_id=current_scene_id
            )
            
            if result.get("success"):
                messages.append({
                    "role": "system",
                    "content": f"🎙️ 场景音频批量生成完成: {result.get('message')}"
                })
                
                audio_segments = list(state.get("audio_segments", []))
                generate_data = result.get("data", {})
                for shot_result in generate_data.get("results", []):
                    if shot_result.get("result", {}).get("success"):
                        audio_info = shot_result.get("result", {}).get("data", {})
                        audio_segments.append({
                            "shot_id": audio_info.get("shot_id"),
                            "audio_url": audio_info.get("audio_url")
                        })
                
                return {
                    "messages": messages,
                    "audio_segments": audio_segments
                }
            else:
                messages.append({
                    "role": "system",
                    "content": f"❌ 音频生成失败: {result.get('error')}"
                })
                errors = list(state.get("errors", []))
                errors.append(f"音频生成失败: {result.get('error')}")
                return {
                    "messages": messages,
                    "errors": errors
                }
        
        return {"messages": messages}
        
    except Exception as e:
        logger.exception(f"音频处理节点执行失败: {e}")
        messages.append({
            "role": "system",
            "content": f"❌ 音频处理异常: {str(e)}"
        })
        errors = list(state.get("errors", []))
        errors.append(str(e))
        return {
            "messages": messages,
            "errors": errors
        }


def route_from_audio(state: ComicDramaState) -> str:
    """
    路由函数：根据音频处理结果返回下一个节点
    
    用于 LangGraph 的条件边
    """
    current_stage = state.get("current_stage", "init")
    errors = state.get("errors", [])
    
    if errors and len(errors) > 0:
        return "error_handler"
    
    return "video_generation"
