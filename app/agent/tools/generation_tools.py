"""
生成工具 - Generation Tools

提供 Agent 调用 AI 服务生成内容的工具
集成现有的 AIClient 和 Celery 任务
"""

from typing import Dict, Any, List, Optional
import asyncio
from app.agent.tools.base import BaseTool
from app.agent.state.schemas import ComicDramaState
from app.utils.ai_client import AIClient
from app.core.logger import logger
from app.core.config import settings


class GenerateCharacterImageTool(BaseTool):
    """生成角色图片工具"""
    
    name = "generate_character_image"
    description = "根据角色描述生成角色参考图"
    
    async def execute(
        self,
        state: ComicDramaState,
        character_description: str,
        character_name: str,
        style_prompt: Optional[str] = None,
        **kwargs
    ) -> Dict[str, Any]:
        """
        生成角色图片
        
        Args:
            character_description: 角色描述
            character_name: 角色名称
            style_prompt: 风格提示词（可选）
        """
        try:
            ai_client = AIClient()
            
            # 构建提示词
            base_prompt = f"Character: {character_name}. {character_description}"
            if style_prompt:
                full_prompt = f"{base_prompt}. Style: {style_prompt}"
            else:
                full_prompt = base_prompt
            
            logger.info(f"生成角色图片: {character_name}")
            
            # 调用文生图
            result = await asyncio.to_thread(
                ai_client.generate_image,
                prompt=full_prompt,
                model=settings.IMAGE_MODEL_TEXT_TO_IMAGE
            )
            
            if result.get("success"):
                return {
                    "success": True,
                    "image_url": result.get("image_url"),
                    "character_name": character_name,
                    "prompt_used": full_prompt
                }
            else:
                return {
                    "success": False,
                    "error": result.get("error", "图片生成失败")
                }
                
        except Exception as e:
            logger.error(f"生成角色图片失败: {e}")
            return {"success": False, "error": str(e)}


class GenerateSceneImageTool(BaseTool):
    """生成场景图片工具"""
    
    name = "generate_scene_image"
    description = "根据场景描述生成场景参考图"
    
    async def execute(
        self,
        state: ComicDramaState,
        scene_description: str,
        scene_name: str,
        style_prompt: Optional[str] = None,
        **kwargs
    ) -> Dict[str, Any]:
        """生成场景图片"""
        try:
            ai_client = AIClient()
            
            base_prompt = f"Scene: {scene_name}. {scene_description}"
            if style_prompt:
                full_prompt = f"{base_prompt}. Style: {style_prompt}"
            else:
                full_prompt = base_prompt
            
            logger.info(f"生成场景图片: {scene_name}")
            
            result = await asyncio.to_thread(
                ai_client.generate_image,
                prompt=full_prompt,
                model=settings.IMAGE_MODEL_TEXT_TO_IMAGE
            )
            
            if result.get("success"):
                return {
                    "success": True,
                    "image_url": result.get("image_url"),
                    "scene_name": scene_name,
                    "prompt_used": full_prompt
                }
            else:
                return {
                    "success": False,
                    "error": result.get("error", "图片生成失败")
                }
                
        except Exception as e:
            logger.error(f"生成场景图片失败: {e}")
            return {"success": False, "error": str(e)}


class GenerateStoryboardImageTool(BaseTool):
    """生成分镜图片工具"""
    
    name = "generate_storyboard_image"
    description = "根据分镜描述和参考图生成分镜图片"
    
    async def execute(
        self,
        state: ComicDramaState,
        storyboard_description: str,
        reference_image_url: Optional[str] = None,
        character_refs: Optional[List[str]] = None,
        scene_ref: Optional[str] = None,
        **kwargs
    ) -> Dict[str, Any]:
        """
        生成分镜图片
        
        Args:
            storyboard_description: 分镜描述
            reference_image_url: 参考图片 URL（可选）
            character_refs: 角色参考图列表（可选）
            scene_ref: 场景参考图（可选）
        """
        try:
            ai_client = AIClient()
            
            logger.info("生成分镜图片")
            
            # 构建提示词
            prompt = storyboard_description
            
            # 调用图生图（如果有参考图）或文生图
            if reference_image_url:
                result = await asyncio.to_thread(
                    ai_client.generate_image_with_reference,
                    prompt=prompt,
                    reference_image_url=reference_image_url,
                    model=settings.IMAGE_MODEL_IMAGE_TO_IMAGE
                )
            else:
                result = await asyncio.to_thread(
                    ai_client.generate_image,
                    prompt=prompt,
                    model=settings.IMAGE_MODEL_TEXT_TO_IMAGE
                )
            
            if result.get("success"):
                return {
                    "success": True,
                    "image_url": result.get("image_url"),
                    "prompt_used": prompt
                }
            else:
                return {
                    "success": False,
                    "error": result.get("error", "分镜图片生成失败")
                }
                
        except Exception as e:
            logger.error(f"生成分镜图片失败: {e}")
            return {"success": False, "error": str(e)}


class GenerateVideoTool(BaseTool):
    """生成视频工具"""
    
    name = "generate_video"
    description = "根据图片生成视频片段"
    
    async def execute(
        self,
        state: ComicDramaState,
        image_url: str,
        video_prompt: str,
        duration: int = 5,
        **kwargs
    ) -> Dict[str, Any]:
        """
        生成视频
        
        Args:
            image_url: 输入图片 URL
            video_prompt: 视频运动描述
            duration: 视频时长（秒）
        """
        try:
            ai_client = AIClient()
            
            logger.info(f"生成视频: {video_prompt[:50]}...")
            
            result = await asyncio.to_thread(
                ai_client.generate_video,
                image_url=image_url,
                prompt=video_prompt,
                duration=duration
            )
            
            if result.get("success"):
                return {
                    "success": True,
                    "video_url": result.get("video_url"),
                    "task_id": result.get("task_id"),
                    "duration": duration
                }
            else:
                return {
                    "success": False,
                    "error": result.get("error", "视频生成失败")
                }
                
        except Exception as e:
            logger.error(f"生成视频失败: {e}")
            return {"success": False, "error": str(e)}


class GenerateAudioTool(BaseTool):
    """生成音频工具"""
    
    name = "generate_audio"
    description = "根据文本生成配音音频"
    
    async def execute(
        self,
        state: ComicDramaState,
        text: str,
        voice_id: Optional[str] = None,
        speed: float = 1.0,
        **kwargs
    ) -> Dict[str, Any]:
        """
        生成音频
        
        Args:
            text: 要合成的文本
            voice_id: 音色 ID（可选，默认使用角色音色）
            speed: 语速（0.5-2.0）
        """
        try:
            from app.services.audio_service import AudioService
            
            logger.info(f"生成音频: {text[:50]}...")
            
            # 使用 AudioService 生成音频
            audio_service = AudioService()
            result = await audio_service.generate_speech(
                text=text,
                voice_id=voice_id or settings.FISH_AUDIO_DEFAULT_VOICE_ID,
                speed=speed
            )
            
            return {
                "success": True,
                "audio_url": result.get("audio_url"),
                "duration": result.get("duration"),
                "voice_id": voice_id
            }
                
        except Exception as e:
            logger.error(f"生成音频失败: {e}")
            return {"success": False, "error": str(e)}


class LLMAnalysisTool(BaseTool):
    """LLM 分析工具"""
    
    name = "llm_analysis"
    description = "使用 LLM 分析文本内容"
    
    async def execute(
        self,
        state: ComicDramaState,
        prompt: str,
        content: str,
        response_format: str = "json",
        model: Optional[str] = None,
        **kwargs
    ) -> Dict[str, Any]:
        """
        LLM 分析
        
        Args:
            prompt: 系统提示词
            content: 要分析的内容
            response_format: 响应格式（json 或 text）
            model: 模型名称（可选）
        """
        try:
            ai_client = AIClient()
            
            messages = [
                {"role": "system", "content": prompt},
                {"role": "user", "content": content}
            ]
            
            logger.info("执行 LLM 分析")
            
            result = await asyncio.to_thread(
                ai_client.chat_completion,
                messages=messages,
                model=model,
                response_format={"type": "json_object"} if response_format == "json" else None
            )
            
            return {
                "success": True,
                "content": result.get("content"),
                "usage": result.get("usage"),
                "model": result.get("model")
            }
                
        except Exception as e:
            logger.error(f"LLM 分析失败: {e}")
            return {"success": False, "error": str(e)}


class GeneratePromptTool(BaseTool):
    """生成提示词工具"""
    
    name = "generate_prompt"
    description = "根据描述生成优化后的 AI 提示词"
    
    async def execute(
        self,
        state: ComicDramaState,
        description: str,
        prompt_type: str = "image",  # image, video, audio
        **kwargs
    ) -> Dict[str, Any]:
        """
        生成优化提示词
        
        Args:
            description: 原始描述
            prompt_type: 提示词类型（image/video/audio）
        """
        try:
            ai_client = AIClient()
            
            system_prompt = f"""你是一个专业的 AI 提示词工程师。
请将以下描述转换为高质量的 {prompt_type} 生成提示词。
要求：
1. 使用英文输出
2. 包含详细的视觉描述
3. 指定风格、光线、构图等要素
4. 保持提示词简洁但信息丰富"""
            
            messages = [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": f"描述：{description}"}
            ]
            
            result = await asyncio.to_thread(
                ai_client.chat_completion,
                messages=messages,
                model=settings.LLM_MODEL_PROMPT_GENERATION
            )
            
            return {
                "success": True,
                "prompt": result.get("content", "").strip(),
                "original_description": description,
                "prompt_type": prompt_type
            }
                
        except Exception as e:
            logger.error(f"生成提示词失败: {e}")
            return {"success": False, "error": str(e)}
