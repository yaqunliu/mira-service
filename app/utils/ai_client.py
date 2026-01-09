"""
AI 生成内容工具类
用于调用基于 OpenAI 的 LLM 或其他生图模型
"""

import os
import json
import re
import time
import base64
import httpx
import requests
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, Optional, List
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError
from app.core.config import settings
from app.core.logger import logger
from app.core.exceptions import (
    AIContentModerationError,
    AITimeoutError,
    AIRetryExhaustedError
)
from app.utils.points_deduction import deduct_points_for_llm
from app.services.model_config_service import ModelConfigService
from app.db.session import SessionLocal
import openai


class AIClient:
    """AI 生成内容客户端

    统一管理 AI 模型调用，支持 LLM 文本生成、图片生成、音频生成等功能
    """

    def __init__(
        self, api_key: str = None, base_url: str = None, llm_model_name: str = None,
        image_model_name: str = None, text_to_image_model: str = None, image_to_image_model: str = None,
        character_analysis_model: str = None, scene_analysis_model: str = None,
        shot_analysis_model: str = None, script_generation_model: str = None,
        prompt_generation_model: str = None,
        ark_api_key: str = None, ark_base_url: str = None, ark_image_model: str = None, ark_video_model: str = None,
        sora2_model: str = None
    ):
        """
        初始化 AIGC 客户端

        Args:
            api_key: OpenAI API 密钥，默认从配置读取（也用于 Sora2）
            base_url: API 基础 URL，默认从配置读取（也用于 Sora2）
            llm_model_name: 默认LLM模型名称，默认从配置读取
            image_model_name: 图片模型名称（向后兼容，已废弃）
            text_to_image_model: 文生图模型名称（用于生成角色图片）
            image_to_image_model: 图生图模型名称（用于生成分镜图片）
            character_analysis_model: 人物解析模型，默认使用 zai-org/glm-4.6
            scene_analysis_model: 场景解析模型，默认使用 zai-org/glm-4.6
            shot_analysis_model: 分镜解析模型，默认使用 zai-org/glm-4.6
            script_generation_model: 剧本生成模型，默认使用 zai-org/glm-4.6
            prompt_generation_model: 提示词生成模型，默认使用 Qwen/Qwen-Plus
            ark_api_key: 火山云AI API 密钥，默认从配置读取
            ark_base_url: 火山云AI API 基础 URL，默认从配置读取
            ark_image_model: 火山云AI 图片模型名称，默认从配置读取
            ark_video_model: 火山云AI 视频模型名称，默认从配置读取
            sora2_model: Sora2 视频模型名称，默认从配置读取
        """
        self.api_key = api_key or settings.OPENAI_API_KEY
        self.base_url = base_url or settings.OPENAI_BASE_URL
        self.llm_model_name = llm_model_name or settings.LLM_MODEL_NAME

        # 图片模型配置：优先使用新配置，否则使用旧配置（向后兼容）
        self.text_to_image_model = text_to_image_model or settings.IMAGE_MODEL_TEXT_TO_IMAGE or settings.IMAGE_MODEL_NAME
        self.image_to_image_model = image_to_image_model or settings.IMAGE_MODEL_IMAGE_TO_IMAGE or settings.IMAGE_MODEL_NAME
        # 向后兼容：保留旧属性
        self.image_model_name = image_model_name or self.text_to_image_model

        # 专用LLM模型配置
        # self.character_analysis_model = character_analysis_model or llm_model_name or getattr(settings, 'LLM_MODEL_CHARACTER_ANALYSIS', 'zai-org/glm-4.6')
        # self.scene_analysis_model = scene_analysis_model or llm_model_name or getattr(settings, 'LLM_MODEL_SCENE_ANALYSIS', 'zai-org/glm-4.6')
        # self.shot_analysis_model = shot_analysis_model or llm_model_name or getattr(settings, 'LLM_MODEL_SHOT_ANALYSIS', 'zai-org/glm-4.6')
        # self.script_generation_model = script_generation_model or llm_model_name or getattr(settings, 'LLM_MODEL_SCRIPT_GENERATION', 'zai-org/glm-4.6')
        # self.prompt_generation_model = prompt_generation_model or llm_model_name or getattr(settings, 'LLM_MODEL_PROMPT_GENERATION', 'Qwen/Qwen-Plus')
        self.character_analysis_model = character_analysis_model or getattr(settings, 'LLM_MODEL_CHARACTER_ANALYSIS', 'zai-org/glm-4.6')
        self.scene_analysis_model = scene_analysis_model or getattr(settings, 'LLM_MODEL_SCENE_ANALYSIS', 'zai-org/glm-4.6')
        self.shot_analysis_model = shot_analysis_model or getattr(settings, 'LLM_MODEL_SHOT_ANALYSIS', 'zai-org/glm-4.6')
        self.script_generation_model = script_generation_model or getattr(settings, 'LLM_MODEL_SCRIPT_GENERATION', 'zai-org/glm-4.6')
        self.prompt_generation_model = prompt_generation_model or getattr(settings, 'LLM_MODEL_PROMPT_GENERATION', 'Qwen/Qwen-Plus')

        # 火山云AI配置
        self.ark_api_key = ark_api_key or settings.ARK_API_KEY
        self.ark_base_url = ark_base_url or settings.ARK_BASE_URL
        self.ark_image_model = ark_image_model or settings.ARK_IMAGE_MODEL
        self.ark_video_model = ark_video_model or settings.ARK_VIDEO_MODEL

        # Sora2配置 - 直接使用 OpenAI 配置
        self.sora2_api_key = self.api_key
        self.sora2_base_url = self.base_url
        self.sora2_model = sora2_model or settings.SORA2_MODEL

        logger.info(f"文生图模型（角色）: {self.text_to_image_model}")
        logger.info(f"图生图模型（分镜）: {self.image_to_image_model}")
        logger.info(f"人物解析模型: {self.character_analysis_model}")
        logger.info(f"场景解析模型: {self.scene_analysis_model}")
        logger.info(f"分镜解析模型: {self.shot_analysis_model}")
        logger.info(f"剧本生成模型: {self.script_generation_model}")
        logger.info(f"提示词生成模型: {self.prompt_generation_model}")
        logger.info(f"火山云AI图片模型: {self.ark_image_model}")
        logger.info(f"火山云AI视频模型: {self.ark_video_model}")
        logger.info(f"Sora2视频模型: {self.sora2_model}")

        if not self.api_key:
            raise ValueError("OpenAI API Key 未配置")
        if not self.base_url:
            raise ValueError("OpenAI Base URL 未配置")
        if not self.llm_model_name:
            raise ValueError("Model Name 未配置")

        # 初始化 OpenAI 客户端（可复用）
        self.ai_client = openai.OpenAI(api_key=self.api_key, base_url=self.base_url)

        # 重试配置
        self.max_retries = settings.AI_MAX_RETRIES
        self.timeout = settings.AI_TIMEOUT
        self.retry_delay = settings.AI_RETRY_DELAY

        # 火山云视频生成配置
        self.ark_video_timeout = settings.ARK_VIDEO_TIMEOUT
        self.ark_video_retry_delay = settings.ARK_VIDEO_RETRY_DELAY

        # Sora2视频生成配置
        self.sora2_timeout = settings.SORA2_TIMEOUT
        self.sora2_retry_delay = settings.SORA2_RETRY_DELAY

        logger.info(f"AIGC客户端初始化成功，BaseURL: {self.base_url}")
        if self.ark_api_key and self.ark_base_url:
            logger.info(f"火山云AI配置成功，BaseURL: {self.ark_base_url}")
        logger.info(f"Sora2配置成功，使用 OpenAI 配置，BaseURL: {self.sora2_base_url}, Model: {self.sora2_model}")

    def _save_ai_response(
        self,
        content: Any,
        model: str = None,
        file_type: str = "txt",
        metadata: Dict[str, Any] = None
    ) -> str:
        """
        将 AI 调用的请求/响应保存到文件，便于排查
        
        Args:
            content: AI 返回的内容（字符串或可JSON序列化对象）
            model: 使用的模型名称
            metadata: 额外要记录的上下文（如 prompt、请求参数、用户/创作ID 等）
            
        Returns:
            保存的文件路径
        """
        try:
            # 创建 ai_res 目录（在项目根目录下）
            app_dir = Path(__file__).parent.parent.parent
            ai_res_dir = app_dir / "ai_res"
            ai_res_dir.mkdir(exist_ok=True)
            
            # 生成文件名：时间戳_模型名.json
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")[:-3]  # 精确到毫秒
            llm_model_name = (model or self.llm_model_name).replace("/", "_").replace(":", "_")
            filename = f"{timestamp}_{llm_model_name}.{file_type}"
            file_path = ai_res_dir / filename
            
            # 组合保存内容：始终以 JSON 结构落盘，便于后续排查
            payload = {
                "timestamp": datetime.now().isoformat(),
                "model": model or self.llm_model_name,
                "metadata": metadata or {},
                "response": content,
            }
            
            # 写入文件
            with open(file_path, 'w', encoding='utf-8') as f:
                json.dump(payload, f, ensure_ascii=False, indent=2)
            
            logger.debug(f"AI 响应已保存到: {file_path}")
            return str(file_path)
            
        except Exception as e:
            # 保存失败不应该影响主流程，只记录警告
            logger.warning(f"保存 AI 响应到文件失败: {e}")
            return ""
    
    def _sanitize_json_content(self, content: str) -> str:
        """
        清理 JSON 内容，处理中文标点等问题
        """
        if not content:
            return content
            
        # 1. Replace quotes around keys: “key”: -> "key":
        # 匹配 “key”: 模式
        content = re.sub(r'“([^”\n]+)”(?=\s*:)', r'"\1"', content)
        
        # 2. Replace opening quotes for values: : “ -> : "
        content = re.sub(r'(:\s*)“', r'\1"', content)
        
        # 3. Replace opening quotes for array items: [ “ -> [ "
        content = re.sub(r'(\[\s*)“', r'\1"', content)
        
        # 4. Replace opening quotes after comma: , “ -> , "
        content = re.sub(r'(,\s*)“', r'\1"', content)
        
        # 5. Replace opening quotes for first key in object: { “ -> { "
        content = re.sub(r'(\{\s*)“', r'\1"', content)
        
        # 6. Replace closing quotes before comma + quote: ”, “ -> ", "
        # 这里的 quote 可能是 " (已被前面步骤替换) 或 “ (尚未替换)
        content = re.sub(r'”(?=\s*,\s*["“])', r'"', content)
        
        # 7. Replace closing quotes before closing brace/bracket: ”} or ”]
        content = re.sub(r'”(?=\s*[}\]])', r'"', content)
        
        return content

    def _parse_json_response(self, content: str) -> Dict[str, Any]:
        """
        从 AI 响应中解析 JSON 内容

        Args:
            content: AI 返回的文本内容

        Returns:
            解析后的 JSON 字典

        Raises:
            json.JSONDecodeError: JSON 解析失败
        """
        # 尝试从代码块中提取 JSON
        json_match = re.search(r"```json\s*(.*?)\s*```", content, re.DOTALL)
        if json_match:
            json_str = json_match.group(1)
        else:
            # 如果没有代码块，尝试直接解析整个内容
            json_str = content
            
        # 处理中文标点符号（智能替换）
        json_str = self._sanitize_json_content(json_str)

        try:
            data = json.loads(json_str)
            return data
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse JSON: {json_str[:200]}...")
            raise json.JSONDecodeError(
                f"Failed to parse JSON: {json_str[:200]}...", json_str, e.pos
            )

    def _do_chat_completion(
        self, messages: List[Dict[str, str]], model: str, max_tokens: int = None, **kwargs
    ) -> Dict[str, Any]:
        """
        执行 LLM 调用的内部方法（不包含重试逻辑）
        
        Args:
            messages: 消息列表
            model: 模型名称
            max_tokens: 最大token数，如果为None则从模型配置中获取
            **kwargs: 其他参数
            
        Returns:
            AI 响应内容
        """
        # 如果没有指定 max_tokens，尝试从模型配置中获取
        if max_tokens is None:
            try:
                model_config = ModelConfigService.get_model_config(model, "llm")
                if model_config and "max_tokens" in model_config:
                    max_tokens = model_config["max_tokens"]
                else:
                    max_tokens = 12288  # 默认值
            except Exception as e:
                logger.warning(f"获取模型配置失败，使用默认 max_tokens: {e}")
                max_tokens = 12288  # 默认值
        
        response = self.ai_client.chat.completions.create(
            model=model, 
            messages=messages, 
            max_tokens=max_tokens,
            **kwargs
        )
        
        if response.usage:
            logger.info(
                f"LLM 调用结束，模型: {model}，使用 token 统计: "
                f"总tokens: {response.usage.total_tokens}，"
                f"提示tokens: {response.usage.prompt_tokens}，"
                f"完成tokens: {response.usage.completion_tokens}"
            )
        
        return {
            'content': response.choices[0].message.content,
            'usage': response.usage.model_dump() if response.usage else None,
            'model': response.model
        }

    def chat_completion(
        self, 
        messages: List[Dict[str, str]], 
        model: str = None,
        user_id: int = None,
        creation_id: int = None,
        novel_id: int = None,
        **kwargs
    ) -> Dict[str, Any]:
        """
        调用 LLM 进行文本生成（带重试机制）

        Args:
            messages: 消息列表
            model: 模型名称，默认使用初始化时的模型
            user_id: 用户ID（用于积分扣除，可选）
            creation_id: 创作ID（用于积分扣除，可选）
            novel_id: 小说ID（用于积分扣除，可选）
            **kwargs: 其他参数（如 temperature, max_tokens 等）

        Returns:
            AI 响应内容
            
        Raises:
            AIContentModerationError: 内容审核失败（如涉及暴恐等敏感内容）
            AITimeoutError: 调用超时
            AIRetryExhaustedError: 重试次数耗尽
        """
        model = model or self.llm_model_name
        logger.debug(f"LLM 调用开始，模型: {model}")

        last_error = None
        
        for attempt in range(1, self.max_retries + 1):
            try:
                logger.info(f"LLM 调用尝试 {attempt}/{self.max_retries}，模型: {model}")
                
                # 使用线程池实现超时控制
                with ThreadPoolExecutor(max_workers=1) as executor:
                    future = executor.submit(
                        self._do_chat_completion,
                        messages=messages,
                        model=model,
                        **kwargs
                    )
                    
                    try:
                        response = future.result(timeout=self.timeout)
                    except FuturesTimeoutError:
                        raise TimeoutError(f"LLM 调用超时（{self.timeout}秒）")
                
                logger.debug(f"LLM 调用成功，模型: {model}")
                
                # 扣除积分（后扣机制，如果提供了用户信息）
                if user_id and response.get('usage'):
                    usage = response['usage']
                    try:
                        db = SessionLocal()
                        try:
                            deduct_points_for_llm(
                                db=db,
                                user_id=user_id,
                                model_name=model,
                                prompt_tokens=usage.get('prompt_tokens', 0),
                                completion_tokens=usage.get('completion_tokens', 0),
                                total_tokens=usage.get('total_tokens', 0),
                                creation_id=creation_id,
                                novel_id=novel_id
                            )
                        finally:
                            db.close()
                    except Exception as e:
                        logger.error(f"LLM调用积分扣除失败: {str(e)}", exc_info=True)
                        # 积分扣除失败不影响LLM调用流程，只记录错误
                
                return response
                
            except TimeoutError as e:
                last_error = e
                logger.warning(f"LLM 调用超时（尝试 {attempt}/{self.max_retries}）: {e}")
                
            except Exception as e:
                last_error = e
                try:
                    error_type = type(e).__name__
                    error_msg = str(e)
                except Exception:
                    error_type = "Unknown"
                    error_msg = "无法获取错误信息"
                
                # 检查是否为内容审核错误
                if self._is_content_moderation_error(e):
                    error_detail = (
                        f"内容审核未通过，可能涉及敏感内容（如暴恐、色情等）。"
                        f"错误信息: {error_msg}"
                    )
                    logger.error(
                        f"{error_detail} | "
                        f"模型: {model} | "
                        f"消息数量: {len(messages)}"
                    )
                    raise AIContentModerationError(error_detail) from e
                
                # 检查是否为可重试的错误
                if not self._is_retryable_error(e):
                    # 不可重试的错误直接抛出
                    error_detail = f"LLM 调用失败 ({error_type}): {error_msg}"
                    logger.error(
                        f"{error_detail} | "
                        f"模型: {model} | "
                        f"消息数量: {len(messages)}"
                    )
                    raise Exception(error_detail) from e
                
                # 可重试的错误记录警告
                logger.warning(
                    f"LLM 调用失败（尝试 {attempt}/{self.max_retries}）: {error_type}: {error_msg}"
                )
            
            # 如果不是最后一次尝试，等待后重试
            if attempt < self.max_retries:
                logger.info(f"等待 {self.retry_delay} 秒后重试...")
                time.sleep(self.retry_delay)
        
        # 所有重试都失败
        if isinstance(last_error, TimeoutError):
            error_msg = f"LLM 调用超时，已重试 {self.max_retries} 次，每次超时时间: {self.timeout}秒"
            logger.error(error_msg)
            raise AITimeoutError(error_msg) from last_error
        else:
            error_msg = f"LLM 调用失败，已重试 {self.max_retries} 次: {last_error}"
            logger.error(error_msg)
            raise AIRetryExhaustedError(error_msg) from last_error

    def gen_playbook_by_chapter(
        self, 
        prompt: str, 
        chapter_content: str, 
        model: str = None,
        user_id: int = None,
        creation_id: int = None,
        novel_id: int = None
    ) -> Dict[str, Any]:
        """
        根据章节内容生成剧本（Playbook）
        
        注意：此方法已废弃，请使用 gen_character_analysis 和 gen_playbook_by_characters 替代

        Args:
            prompt: 提示词
            chapter_content: 章节内容
            model: 模型名称，默认使用初始化时的模型
            user_id: 用户ID（用于积分扣除，可选）
            creation_id: 创作ID（用于积分扣除，可选）
            novel_id: 小说ID（用于积分扣除，可选）

        Returns:
            解析后的 JSON 数据
        """
        messages = [
            {
                "role": "user",
                "content": f"{prompt}\n\n下面是章节内容：\n{chapter_content}",
            }
        ]

        try:
            ##X## Debug 模式下抛出测试异常 - 测试角色分析LLM调用错误（生成剧本）
            # if settings.DEBUG:
            #     raise Exception("测试角色分析LLM调用错误（生成剧本）")
            
            response = self.chat_completion(
                messages=messages, 
                model=model, 
                response_format={"type": "json_object"},
                user_id=user_id,
                creation_id=creation_id,
                novel_id=novel_id
            )
            ai_content = response.get("content", "")
            logger.info(f"AI 返回内容: {ai_content}")

            if not ai_content:
                raise ValueError("AI 返回内容为空")
            
            # 将 AI 返回内容写入文件以便分析
            self._save_ai_response(
                ai_content,
                model=model or self.llm_model_name,
                file_type="json",
                metadata={
                    "prompt": prompt,
                    "messages": messages,
                    "user_id": user_id,
                    "creation_id": creation_id,
                    "novel_id": novel_id
                }
            )
            
            logger.info(f"AI 返回内容解析: {self._parse_json_response(ai_content)}")
            return self._parse_json_response(ai_content)

        except Exception as e:
            logger.error(f"生成剧本失败: {e}")
            raise
    
    def gen_character_analysis(
        self,
        prompt: str,
        chapter_content: str,
        historical_characters: Dict[str, Any] = None,
        model: str = None,
        user_id: int = None,
        creation_id: int = None,
        novel_id: int = None
    ) -> Dict[str, Any]:
        """
        根据章节内容进行角色分析

        Args:
            prompt: 角色分析提示词
            chapter_content: 章节内容
            historical_characters: 历史角色库（可选），格式：{"角色名": {...特征...}}
            model: 模型名称，默认使用 character_analysis_model
            user_id: 用户ID（用于积分扣除，可选）
            creation_id: 创作ID（用于积分扣除，可选）
            novel_id: 小说ID（用于积分扣除，可选）

        Returns:
            解析后的 JSON 数据，包含章节信息和人物特征库
        """
        # 默认使用人物解析专用模型
        model = model or self.character_analysis_model

        # 构建历史角色库的文本描述
        historical_characters_text = ""
        if historical_characters:
            historical_characters_text = "\n\n以下是之前已存在的角色特征库（如果当前章节中出现同名角色且状态相同，请复用这些特征；如果同一角色出现不同状态，必须创建新的独立角色条目）：\n"
            historical_characters_text += json.dumps(historical_characters, ensure_ascii=False, indent=2)

        messages = [
            {
                "role": "user",
                "content": f"{prompt}{historical_characters_text}\n\n下面是章节内容：\n{chapter_content}",
            }
        ]

        logger.info(f"角色分析 Prompt: {messages[0]['content']}")

        try:
            response = self.chat_completion(
                messages=messages,
                model=model,
                response_format={"type": "json_object"},
                user_id=user_id,
                creation_id=creation_id,
                novel_id=novel_id
            )
            ai_content = response.get("content", "")
            logger.info(f"角色分析 AI 返回内容: {ai_content}")

            if not ai_content:
                raise ValueError("AI 返回内容为空")

            # 将 AI 返回内容写入文件以便分析
            self._save_ai_response(
                ai_content,
                model=model,
                file_type="json",
                metadata={
                    "prompt": prompt,
                    "messages": messages,
                    "user_id": user_id,
                    "creation_id": creation_id,
                    "novel_id": novel_id,
                    "historical_characters": historical_characters,
                }
            )

            parsed_data = self._parse_json_response(ai_content)
            logger.info(f"角色分析完成，识别到 {len(parsed_data.get('人物特征库', {}))} 个角色")
            return parsed_data

        except Exception as e:
            logger.error(f"角色分析失败: {e}")
            raise
    
    def gen_scene_decomposition(
        self,
        prompt: str,
        chapter_content: str,
        model: str = None,
        user_id: int = None,
        creation_id: int = None,
        novel_id: int = None
    ) -> Dict[str, Any]:
        """
        根据章节内容进行场景拆解

        Args:
            prompt: 场景拆解提示词
            chapter_content: 章节内容
            model: 模型名称，默认使用 scene_analysis_model
            user_id: 用户ID（用于积分扣除，可选）
            creation_id: 创作ID（用于积分扣除，可选）
            novel_id: 小说ID（用于积分扣除，可选）

        Returns:
            解析后的 JSON 数据，包含场景列表
        """
        # 默认使用场景解析专用模型
        model = model or self.scene_analysis_model

        messages = [
            {
                "role": "user",
                "content": f"{prompt}\n\n下面是章节内容：\n{chapter_content}",
            }
        ]

        logger.info(f"场景拆解 Prompt: {messages[0]['content']}")

        try:
            response = self.chat_completion(
                messages=messages,
                model=model,
                response_format={"type": "json_object"},
                user_id=user_id,
                creation_id=creation_id,
                novel_id=novel_id
            )
            ai_content = response.get("content", "")
            logger.info(f"场景拆解 AI 返回内容: {ai_content}")

            if not ai_content:
                raise ValueError("AI 返回内容为空")

            # 将 AI 返回内容写入文件以便分析
            self._save_ai_response(
                ai_content,
                model=model,
                file_type="json",
                metadata={
                    "prompt": prompt,
                    "messages": messages,
                    "user_id": user_id,
                    "creation_id": creation_id,
                    "novel_id": novel_id,
                }
            )

            parsed_data = self._parse_json_response(ai_content)
            logger.info(f"场景拆解完成，解析到 {len(parsed_data.get('场景列表', []))} 个场景")
            return parsed_data

        except Exception as e:
            logger.error(f"场景拆解失败: {e}")
            raise
    
    def gen_playbook_by_characters(
        self,
        prompt: str,
        chapter_content: str,
        characters_data: Dict[str, Any],
        model: str = None,
        user_id: int = None,
        creation_id: int = None,
        novel_id: int = None
    ) -> Dict[str, Any]:
        """
        根据章节内容和角色特征库生成分镜脚本

        Args:
            prompt: 分镜拆分提示词
            chapter_content: 章节内容
            characters_data: 人物特征库，格式：{"角色名": {...特征...}}
            model: 模型名称，默认使用初始化时的模型
            user_id: 用户ID（用于积分扣除，可选）
            creation_id: 创作ID（用于积分扣除，可选）
            novel_id: 小说ID（用于积分扣除，可选）

        Returns:
            解析后的 JSON 数据，包含场景拆解信息
        """
        # 构建人物特征库的文本描述
        characters_text = "\n\n以下是人物特征库（生成图片提示词时必须从该库中提取角色信息）：\n"
        characters_text += json.dumps(characters_data, ensure_ascii=False, indent=2)
        
        messages = [
            {
                "role": "user",
                "content": f"{prompt}{characters_text}\n\n下面是章节内容：\n{chapter_content}",
            }
        ]

        logger.info(f"分镜拆分 Prompt: {messages[0]['content']}")

        try:
            response = self.chat_completion(
                messages=messages,
                model=model,
                response_format={"type": "json_object"},
                user_id=user_id,
                creation_id=creation_id,
                novel_id=novel_id
            )
            ai_content = response.get("content", "")
            logger.info(f"分镜拆分 AI 返回内容: {ai_content}")

            if not ai_content:
                raise ValueError("AI 返回内容为空")
            
            # 将 AI 返回内容写入文件以便分析
            self._save_ai_response(
                ai_content,
                model=model or self.llm_model_name,
                file_type="json",
                metadata={
                    "prompt": prompt,
                    "messages": messages,
                    "user_id": user_id,
                    "creation_id": creation_id,
                    "novel_id": novel_id,
                    "characters_data": characters_data,
                }
            )
            
            parsed_data = self._parse_json_response(ai_content)
            scenes_count = len(parsed_data.get('场景拆解', []))
            total_shots = sum(len(scene.get('分镜列表', [])) for scene in parsed_data.get('场景拆解', []))
            logger.info(f"分镜拆分完成，生成 {scenes_count} 个场景，{total_shots} 个分镜")
            return parsed_data

        except Exception as e:
            logger.error(f"分镜拆分失败: {e}")
            raise

    def gen_shot_analysis(
        self,
        scenes_data: List[Dict[str, Any]],
        characters_data: Dict[str, Any],
        original_text: str,
        model: str = None,
        user_id: int = None,
        creation_id: int = None,
        novel_id: int = None
    ) -> Dict[str, Any]:
        """
        根据场景信息、角色特征库和原文文案进行分镜拆解

        Args:
            scenes_data: 场景列表
            characters_data: 角色特征库（包含出镜角色和声音角色）
            original_text: 原文文案
            model: 模型名称，默认使用 shot_analysis_model
            user_id: 用户ID（用于积分扣除，可选）
            creation_id: 创作ID（用于积分扣除，可选）
            novel_id: 小说ID（用于积分扣除，可选）

        Returns:
            分镜列表（JSON格式）
        """
        # 默认使用分镜解析专用模型
        model = model or self.shot_analysis_model

        # 加载提示词模板
        prompt_template = self._load_prompt_template("shot_decomposition_new")

        # 提取角色名称列表（合并出镜角色和声音角色）
        on_screen_characters = characters_data.get('出镜角色', {})
        voice_characters = characters_data.get('声音角色', {})
        all_character_names = list(on_screen_characters.keys()) + list(voice_characters.keys())
        character_list_str = "\n".join([f"- {name}" for name in all_character_names])

        # 格式化场景信息（去除场景内容字段，因为已经单独传入原文）
        scenes_for_prompt = []
        for scene in scenes_data:
            scene_copy = scene.copy()
            # 移除场景内容字段，只保留环境设定
            if "场景内容" in scene_copy:
                del scene_copy["场景内容"]
            scenes_for_prompt.append(scene_copy)

        scenes_json = json.dumps(scenes_for_prompt, ensure_ascii=False, indent=2)

        # 替换模板中的占位符
        full_prompt = prompt_template.replace("{{ORIGINAL_TEXT}}", original_text)
        full_prompt = full_prompt.replace("{{CHARACTER_LIST}}", character_list_str)
        full_prompt = full_prompt.replace("{{SCENES}}", scenes_json)

        # 确保 prompt 包含 JSON 输出要求和 XML 标签包裹要求
        if "请使用 JSON 格式输出" not in full_prompt:
             full_prompt += "\n\n请使用 JSON 格式输出，并使用 <分镜拆解> 和 </分镜拆解> 标签包裹 JSON 内容。"
        
        messages = [
            {
                "role": "user",
                "content": full_prompt
            }
        ]

        logger.info(f"分镜拆解 Prompt: {full_prompt}")

        try:
            response = self.chat_completion(
                messages=messages,
                model=model,
                user_id=user_id,
                creation_id=creation_id,
                novel_id=novel_id
            )
            ai_content = response.get("content", "").strip()
            
            # 从返回内容中提取 <分镜拆解> 标签内的 JSON
            json_str = None
            json_match = re.search(r"<分镜拆解>(.*?)</分镜拆解>", ai_content, re.DOTALL)
            if json_match:
                json_str = json_match.group(1).strip()
            else:
                # 尝试提取 JSON 代码块
                code_block_match = re.search(r"```(?:json|JSON)?\s*(.*?)\s*```", ai_content, re.DOTALL)
                if code_block_match:
                    json_str = code_block_match.group(1).strip()
                else:
                    # 查找完整的 JSON 对象
                    json_obj_match = re.search(r'\{.*\}', ai_content, re.DOTALL)
                    if json_obj_match:
                        json_str = json_obj_match.group(0)
                    else:
                        json_str = ai_content

            # 清理 JSON 字符串（处理可能存在的尾部乱码或多余标签）
            json_str = re.sub(r'</分镜拆解>.*$', '', json_str, flags=re.DOTALL)
            json_str = re.sub(r'^```(?:json|JSON)?\s*', '', json_str)
            json_str = re.sub(r'\s*```$', '', json_str)
            json_str = json_str.strip()

            # 处理中文标点符号（智能替换）
            json_str = self._sanitize_json_content(json_str)

            # 保存响应记录
            self._save_ai_response(
                ai_content,
                model=model,
                file_type="json",
                metadata={
                    "prompt": full_prompt[:200] + "...",  # 只保存部分 prompt 以节省空间
                    "user_id": user_id,
                    "creation_id": creation_id
                }
            )

            try:
                result = json.loads(json_str)
                # 验证数据结构
                if "分镜列表" not in result:
                    raise ValueError("缺少'分镜列表'字段")
                return result
            except json.JSONDecodeError as e:
                logger.error(f"JSON 解析失败: {e}")
                logger.error(f"AI 返回内容: {ai_content}")
                raise

        except Exception as e:
            logger.error(f"分镜拆解失败: {e}")
            raise
    
    def _do_generate_image_by_prompt(
        self, prompt: str, model: str, aspectRatio: str, guidance_scale: float = None
    ) -> str:
        """
        执行图片生成调用的内部方法（不包含重试逻辑）
        
        Args:
            prompt: 提示词
            model: 模型名称
            aspectRatio: 图片尺寸
            guidance_scale: 引导尺度
        Returns:
            生成的图片URL
        """
        # 检查是否为 Nano Banana2 模型 (Gemini)
        if model == "gemini-3-pro-image-preview":
            logger.info(f"使用 Nano Banana2 (Gemini) API 进行文生图")
            
            # 统一使用 2K
            image_size = "2K"
            
            # 转换 aspectRatio 为 16:9 格式（Gemini 需要这种格式）
            aspect_ratio = aspectRatio
            if "x" in aspectRatio:
                # 如果是 1024x576 这种格式，转换为 16:9
                w, h = aspectRatio.split("x")
                if int(w) > int(h):
                    aspect_ratio = "16:9"
                elif int(w) < int(h):
                    aspect_ratio = "9:16"
                else:
                    aspect_ratio = "1:1"
            
            # 调用 Gemini API
            image_base64 = self._call_gemini_image_api(
                prompt=prompt,
                reference_images_base64=[], # 文生图没有参考图
                aspect_ratio=aspect_ratio,
                image_size=image_size
            )
            
            # 将 Base64 图片转换为临时文件并返回 URL
            temp_url = self._save_base64_image_to_temp_url(image_base64)
            return temp_url

        # 检查是否使用火山云AI模型
        if model == self.ark_image_model:
            return self._ark_generate_image(prompt, aspectRatio)
        else:
            # 使用OpenAI兼容的图片生成
            response = None
            if guidance_scale:
                response = self.ai_client.images.generate(model=model, prompt=prompt, size=aspectRatio, guidance_scale=guidance_scale)
            else:
                response = self.ai_client.images.generate(model=model, prompt=prompt, size=aspectRatio)
            image_url = response.data[0].url
            return image_url
            
    def _ark_generate_image(self, prompt: str, aspectRatio: str) -> str:
        """
        使用火山云AI Seedream模型生成图片
        
        Args:
            prompt: 提示词
            aspectRatio: 图片尺寸
        Returns:
            生成的图片URL
        """
        # 构建火山云AI API请求
        url = f"{self.ark_base_url}/contents/generations/tasks"
        headers = {
            "Authorization": f"Bearer {self.ark_api_key}",
            "Content-Type": "application/json"
        }
        
        # 转换aspectRatio为火山云AI支持的格式
        aspect_ratio_mapping = {
            "1024x576": "16:9",
            "576x1024": "9:16",
            "1024x1024": "1:1",
            "1280x720": "16:9",
            "720x1280": "9:16",
            "1024x768": "4:3",
            "768x1024": "3:4"
        }
        
        aspect_ratio = aspect_ratio_mapping.get(aspectRatio, "16:9")
        
        # 构建请求体
        payload = {
            "model": self.ark_image_model,
            "content": {
                "text": prompt
            },
            "params": {
                "aspect_ratio": aspect_ratio
            }
        }
        
        logger.info(f"调用火山云AI图片生成API，模型: {self.ark_image_model}, 比例: {aspect_ratio}")
        
        # 发送请求
        response = requests.post(url, headers=headers, json=payload, timeout=self.timeout)
        response.raise_for_status()
        
        # 解析响应
        result = response.json()
        task_id = result.get("id")
        
        if not task_id:
            raise Exception("火山云AI图片生成API返回的响应中没有任务ID")
        
        # 轮询任务状态
        start_time = time.time()
        while time.time() - start_time < self.ark_video_timeout:
            task_url = f"{self.ark_base_url}/contents/generations/tasks/{task_id}"
            task_response = requests.get(task_url, headers=headers, timeout=self.timeout)
            task_response.raise_for_status()
            
            task_result = task_response.json()
            status = task_result.get("status")
            
            if status == "succeeded":
                # 任务成功，返回图片URL
                image_url = task_result.get("content", {}).get("image_url")
                if image_url:
                    logger.info(f"火山云AI图片生成成功，URL: {image_url}")
                    return image_url
                else:
                    raise Exception("火山云AI图片生成成功，但未返回图片URL")
            elif status == "failed":
                # 任务失败
                error_msg = task_result.get("error", {}).get("message", "未知错误")
                raise Exception(f"火山云AI图片生成失败: {error_msg}")
            elif status in ["pending", "running"]:
                # 任务进行中，继续轮询
                time.sleep(self.ark_video_retry_delay)
            else:
                # 未知状态
                raise Exception(f"火山云AI图片生成任务状态未知: {status}")
        
        # 超时
        raise AITimeoutError(f"火山云AI图片生成超时，超过 {self.ark_video_timeout} 秒")
        
    def generate_video_by_prompt(self, prompt: str, model: str = None, aspectRatio: str = None, duration: int = None) -> str:
        """
        使用火山云AI Seedance模型根据提示词生成视频
        
        Args:
            prompt: 提示词
            model: 模型名称，默认使用初始化时的模型
            aspectRatio: 视频尺寸
            duration: 视频时长（秒）
        Returns:
            生成的视频URL
        
        Raises:
            ValueError: 参数错误
            AIContentModerationError: 内容审核失败
            AITimeoutError: 调用超时
            Exception: 其他错误
        """
        # 检查火山云AI配置
        if not self.ark_api_key or not self.ark_base_url:
            raise ValueError("火山云AI API配置未设置")
        
        # 使用火山云AI视频模型
        model = model or self.ark_video_model
        
        # 默认参数
        if aspectRatio is None:
            aspectRatio = "16:9"
        if duration is None:
            duration = 10  # 默认10秒
        
        logger.info(f"生成视频开始，模型: {model}, 比例: {aspectRatio}, 时长: {duration}秒, 提示词长度: {len(prompt)}")
        logger.info(f"【视频生成提示词】: {prompt}")
        
        # 构建火山云AI API请求
        url = f"{self.ark_base_url}/contents/generations/tasks"
        headers = {
            "Authorization": f"Bearer {self.ark_api_key}",
            "Content-Type": "application/json"
        }
        
        # 构建请求体
        payload = {
            "model": model,
            "content": {
                "text": prompt
            },
            "params": {
                "aspect_ratio": aspectRatio,
                "duration": duration
            }
        }
        
        logger.info(f"调用火山云AI视频生成API，模型: {model}, 比例: {aspectRatio}, 时长: {duration}秒")
        
        # 发送请求
        response = requests.post(url, headers=headers, json=payload, timeout=self.timeout)
        response.raise_for_status()
        
        # 解析响应
        result = response.json()
        task_id = result.get("id")
        
        if not task_id:
            raise Exception("火山云AI视频生成API返回的响应中没有任务ID")
        
        logger.info(f"火山云AI视频生成任务创建成功，任务ID: {task_id}")
        
        # 轮询任务状态
        start_time = time.time()
        while time.time() - start_time < self.ark_video_timeout:
            task_url = f"{self.ark_base_url}/contents/generations/tasks/{task_id}"
            task_response = requests.get(task_url, headers=headers, timeout=self.timeout)
            task_response.raise_for_status()
            
            task_result = task_response.json()
            status = task_result.get("status")
            
            logger.debug(f"火山云AI视频生成任务状态: {status}, 任务ID: {task_id}")
            
            if status == "succeeded":
                # 任务成功，返回视频URL
                video_url = task_result.get("content", {}).get("video_url")
                if video_url:
                    logger.info(f"火山云AI视频生成成功，URL: {video_url}")
                    return video_url
                else:
                    raise Exception("火山云AI视频生成成功，但未返回视频URL")
            elif status == "failed":
                # 任务失败
                error_msg = task_result.get("error", {}).get("message", "未知错误")
                raise Exception(f"火山云AI视频生成失败: {error_msg}")
            elif status in ["pending", "running"]:
                # 任务进行中，继续轮询
                time.sleep(self.ark_video_retry_delay)
            else:
                # 未知状态
                raise Exception(f"火山云AI视频生成任务状态未知: {status}")
        
        # 超时
        raise AITimeoutError(f"火山云AI视频生成超时，超过 {self.ark_video_timeout} 秒")

    def generate_video_by_image_sora2(self, image_url: str, prompt: str = None, duration: int = 4) -> str:
        """
        使用 UCloud Sora2 I2V 模型根据图片生成视频（图生视频）

        Args:
            image_url: 首帧图片URL（可以是URL或Base64）
            prompt: 提示词，用于指导视频生成，可选
            duration: 视频生成时长（秒），可选值 4, 8, 12，默认为 4

        Returns:
            生成的视频URL

        Raises:
            ValueError: 参数错误
            AIContentModerationError: 内容审核失败
            AITimeoutError: 调用超时
            Exception: 其他错误
        """
        # 检查Sora2配置
        if not self.sora2_api_key or not self.sora2_base_url:
            raise ValueError("Sora2 API配置未设置")

        # 验证duration参数
        if duration not in [4, 8, 12]:
            logger.warning(f"不支持的视频时长 {duration}秒，使用默认值 4秒")
            duration = 4

        logger.info(f"Sora2 图生视频开始，模型: {self.sora2_model}, 时长: {duration}秒")
        if prompt:
            logger.info(f"【Sora2 视频生成提示词】: {prompt}")

        # 步骤1: 提交任务
        submit_url = f"{self.sora2_base_url}/tasks/submit"
        headers = {
            "Authorization": self.sora2_api_key,
            "Content-Type": "application/json"
        }

        # 构建请求体 - size参数留空让API使用默认值
        payload = {
            "model": self.sora2_model,
            "input": {
                "first_frame_url": image_url
            },
            "parameters": {
                "duration": duration
            }
        }

        # 如果提供了prompt，添加到请求中
        if prompt:
            payload["input"]["prompt"] = prompt

        logger.info(f"提交Sora2视频生成任务，图片URL: {image_url[:100]}...")

        # 提交任务时添加重试机制（针对502等临时网络错误）
        max_retries = 3
        retry_delay = 2  # 秒
        task_id = None

        for attempt in range(max_retries):
            try:
                # 发送提交请求
                response = requests.post(submit_url, headers=headers, json=payload, timeout=self.timeout)
                response.raise_for_status()

                # 解析响应
                result = response.json()
                task_id = result.get("output", {}).get("task_id")

                if not task_id:
                    raise Exception("Sora2 API返回的响应中没有任务ID")

                logger.info(f"Sora2视频生成任务创建成功，任务ID: {task_id}")
                break  # 成功，跳出重试循环

            except requests.exceptions.HTTPError as e:
                # 检查是否是502等可重试的错误
                if e.response and e.response.status_code in [502, 503, 504]:
                    if attempt < max_retries - 1:
                        logger.warning(f"提交Sora2任务遇到{e.response.status_code}错误，{retry_delay}秒后重试 ({attempt + 1}/{max_retries})")
                        time.sleep(retry_delay)
                        retry_delay *= 2  # 指数退避
                        continue
                    else:
                        logger.error(f"提交Sora2任务失败，已达最大重试次数: {str(e)}")
                        raise Exception(f"提交Sora2任务失败（已重试{max_retries}次）: {str(e)}")
                else:
                    # 其他HTTP错误不重试
                    logger.error(f"提交Sora2任务失败: {str(e)}")
                    raise Exception(f"提交Sora2任务失败: {str(e)}")

            except requests.exceptions.RequestException as e:
                # 网络连接错误，可重试
                if attempt < max_retries - 1:
                    logger.warning(f"提交Sora2任务遇到网络错误，{retry_delay}秒后重试 ({attempt + 1}/{max_retries}): {str(e)}")
                    time.sleep(retry_delay)
                    retry_delay *= 2
                    continue
                else:
                    logger.error(f"提交Sora2任务失败，已达最大重试次数: {str(e)}")
                    raise Exception(f"提交Sora2任务失败（已重试{max_retries}次）: {str(e)}")

        if not task_id:
            raise Exception("提交Sora2任务失败：未能获取任务ID")

        # 步骤2: 轮询任务状态
        start_time = time.time()
        status_url = f"{self.sora2_base_url}/tasks/status"

        while time.time() - start_time < self.sora2_timeout:
            try:
                # 查询任务状态
                status_response = requests.get(
                    status_url,
                    headers=headers,
                    params={"task_id": task_id},
                    timeout=self.timeout
                )
                status_response.raise_for_status()

                status_result = status_response.json()
                task_status = status_result.get("output", {}).get("task_status")

                logger.debug(f"Sora2视频生成任务状态: {task_status}, 任务ID: {task_id}")

                if task_status == "Success":
                    # 任务成功，返回视频URL
                    urls = status_result.get("output", {}).get("urls", [])
                    if urls and len(urls) > 0:
                        video_url = urls[0]
                        logger.info(f"Sora2视频生成成功，URL: {video_url}")
                        return video_url
                    else:
                        raise Exception("Sora2视频生成成功，但未返回视频URL")

                elif task_status == "Failure":
                    # 任务失败
                    error_msg = status_result.get("output", {}).get("error_message", "未知错误")
                    logger.error(f"Sora2视频生成失败: {error_msg}")
                    raise Exception(f"Sora2视频生成失败: {error_msg}")

                elif task_status in ["Pending", "Running"]:
                    # 任务进行中，继续轮询
                    time.sleep(self.sora2_retry_delay)

                else:
                    # 未知状态
                    logger.warning(f"Sora2视频生成任务状态未知: {task_status}")
                    time.sleep(self.sora2_retry_delay)

            except requests.exceptions.RequestException as e:
                logger.warning(f"查询Sora2任务状态失败: {str(e)}，将重试")
                time.sleep(self.sora2_retry_delay)
                continue

        # 超时
        logger.error(f"Sora2视频生成超时，超过 {self.sora2_timeout} 秒，任务ID: {task_id}")
        raise AITimeoutError(f"Sora2视频生成超时，超过 {self.sora2_timeout} 秒")

    def generate_image_by_prompt(self, prompt: str, model: str = None, aspectRatio: str = None) -> str:
        """
        根据提示词生成图片（文生图，带重试机制）
        
        Args:
            prompt: 提示词
            model: 模型名称，默认使用初始化时的模型
            aspectRatio: 图片尺寸，如果为None则从模型配置中获取
            
        Returns:
            生成的图片URL
            
        Raises:
            AIContentModerationError: 内容审核失败（如涉及暴恐等敏感内容）
            AITimeoutError: 调用超时
            AIRetryExhaustedError: 重试次数耗尽
        """
        # 文生图使用 text_to_image_model
        model = model or self.text_to_image_model
        
        # 如果没有指定 aspectRatio，从模型配置中获取
        if aspectRatio is None:
            try:
                model_config = ModelConfigService.get_model_config(model, "text_to_image")
                if model_config and "aspect_ratio" in model_config:
                    aspectRatio = model_config["aspect_ratio"]
                else:
                    aspectRatio = "1024x576"  # 默认值
            except Exception as e:
                logger.warning(f"获取模型配置失败，使用默认 aspectRatio: {e}")
                aspectRatio = "1024x576"  # 默认值
        
        logger.info(f"生成图片开始（文生图），模型: {model}, aspectRatio: {aspectRatio}, 提示词长度: {len(prompt)}")
        logger.info(f"【文生图提示词】: {prompt}")
        
        last_error = None
        
        for attempt in range(1, self.max_retries + 1):
            try:
                logger.info(f"生成图片尝试 {attempt}/{self.max_retries}，模型: {model}")
                
                # 使用线程池实现超时控制
                with ThreadPoolExecutor(max_workers=1) as executor:
                    future = executor.submit(
                        self._do_generate_image_by_prompt,
                        prompt=prompt,
                        model=model,
                        aspectRatio=aspectRatio
                    )
                    
                    try:
                        image_url = future.result(timeout=self.timeout)
                    except FuturesTimeoutError:
                        raise TimeoutError(f"图片生成超时（{self.timeout}秒）")
                
                logger.info(f"生成图片成功: {image_url}")
                return image_url
                
            except TimeoutError as e:
                last_error = e
                logger.warning(f"图片生成超时（尝试 {attempt}/{self.max_retries}）: {e}")
                
            except Exception as e:
                last_error = e
                error_type = type(e).__name__
                error_msg = str(e)
                
                # 检查是否为内容审核错误
                if self._is_content_moderation_error(e):
                    error_detail = (
                        f"图片生成内容审核未通过，可能涉及敏感内容（如暴恐、色情等）。"
                        f"错误信息: {error_msg}"
                    )
                    logger.error(f"{error_detail} | 模型: {model} | 提示词长度: {len(prompt)}")
                    raise AIContentModerationError(error_detail) from e
                
                # 检查是否为可重试的错误
                if not self._is_retryable_error(e):
                    # 不可重试的错误直接抛出
                    error_detail = f"图片生成失败 ({error_type}): {error_msg}"
                    logger.error(f"{error_detail} | 模型: {model}")
                    raise Exception(error_detail) from e
                
                # 可重试的错误记录警告
                logger.warning(
                    f"图片生成失败（尝试 {attempt}/{self.max_retries}）: {error_type}: {error_msg}"
                )
            
            # 如果不是最后一次尝试，等待后重试
            if attempt < self.max_retries:
                logger.info(f"等待 {self.retry_delay} 秒后重试...")
                time.sleep(self.retry_delay)
        
        # 所有重试都失败
        if isinstance(last_error, TimeoutError):
            error_msg = f"图片生成超时，已重试 {self.max_retries} 次，每次超时时间: {self.timeout}秒"
            logger.error(error_msg)
            raise AITimeoutError(error_msg) from last_error
        else:
            error_msg = f"图片生成失败，已重试 {self.max_retries} 次: {last_error}"
            logger.error(error_msg)
            raise AIRetryExhaustedError(error_msg) from last_error
    
    def _download_image_to_base64(self, image_url: str) -> str:
        """
        下载图片并转换为 Base64 编码（支持本地文件路径和URL）
        
        Args:
            image_url: 图片URL或本地文件路径
            
        Returns:
            Base64 编码的图片数据
        """
        try:
            # 检查是否为本地文件路径
            if os.path.exists(image_url) or image_url.startswith("file://"):
                # 处理本地文件路径
                file_path = image_url.replace("file://", "") if image_url.startswith("file://") else image_url
                if not os.path.exists(file_path):
                    raise FileNotFoundError(f"本地文件不存在: {file_path}")
                with open(file_path, 'rb') as f:
                    image_data = f.read()
                # 转换为 Base64
                base64_data = base64.b64encode(image_data).decode('utf-8')
                logger.info(f"成功读取本地文件并转换为 Base64: {file_path}")
                return base64_data
            else:
                # 从URL下载
                timeout_config = httpx.Timeout(
                    connect=10.0,  # 连接超时10秒
                    read=settings.AI_IMAGE_DOWNLOAD_TIMEOUT,  # 读取超时使用配置的值（默认60秒）
                    write=10.0,  # 写入超时10秒
                    pool=10.0,  # 连接池超时10秒
                )
                with httpx.Client(timeout=timeout_config) as client:
                    response = client.get(image_url)
                    response.raise_for_status()
                    image_data = response.content
                    # 转换为 Base64
                    base64_data = base64.b64encode(image_data).decode('utf-8')
                    return base64_data
        except httpx.TimeoutException as e:
            logger.error(f"下载图片超时: {image_url}, timeout={settings.AI_IMAGE_DOWNLOAD_TIMEOUT}秒, error={e}")
            raise
        except Exception as e:
            logger.error(f"下载图片并转换为 Base64 失败: {e}")
            raise
    
    def _call_gemini_image_api(
        self,
        prompt: str,
        reference_images_base64: List[str],
        aspect_ratio: str = "16:9",
        image_size: str = "2K"
    ) -> str:
        """
        调用 Gemini 3 Pro Image API（Nano Banana2）
        
        Args:
            prompt: 图片生成提示词（中文）
            reference_images_base64: 参考图片的 Base64 编码列表
            aspect_ratio: 图片宽高比，默认 "16:9"
            image_size: 图片分辨率，默认 "2K"
            
        Returns:
            生成的图片 Base64 编码
        """
        # 构建请求体
        contents_parts = [{"text": prompt}]
        
        # 添加参考图片（输入图像）
        for img_base64 in reference_images_base64:
            contents_parts.append({
                "inlineData": {
                    "mimeType": "image/png",
                    "data": img_base64
                }
            })
        
        request_body = {
            "contents": [{
                "role": "user",
                "parts": contents_parts
            }],
            "generationConfig": {
                "responseModalities": ["TEXT", "IMAGE"],
                "imageConfig": {
                    "aspectRatio": aspect_ratio,
                    "imageSize": image_size
                }
            }
        }
        
        # 构建 API URL
        api_url = "https://api.modelverse.cn/v1beta/models/gemini-3-pro-image-preview:generateContent"
        
        # 发送请求
        headers = {
            "x-goog-api-key": self.api_key,
            "Content-Type": "application/json"
        }
        
        with httpx.Client(timeout=self.timeout) as client:
            response = client.post(api_url, json=request_body, headers=headers)
            response.raise_for_status()
            result = response.json()
        
        # 解析响应
        if "error" in result:
            error_msg = result["error"].get("message", "未知错误")
            raise Exception(f"Gemini API 错误: {error_msg}")
        
        # 从响应中提取图片数据
        candidates = result.get("candidates", [])
        if not candidates:
            raise Exception("Gemini API 返回空结果")
        
        content = candidates[0].get("content", {})
        parts = content.get("parts", [])
        
        # 查找图片数据
        for part in parts:
            if "inlineData" in part:
                image_base64 = part["inlineData"]["data"]
                return image_base64
        
        raise Exception("Gemini API 响应中未找到图片数据")
    
    def _save_base64_image_to_temp_url(self, image_base64: str) -> str:
        """
        将 Base64 编码的图片保存为临时文件并返回本地标识
        
        Args:
            image_base64: Base64 编码的图片数据
            
        Returns:
            本地文件标识（格式为 "local://<abs_path>"，调用方可直接上传）
        """
        # 解码 Base64 图片
        image_data = base64.b64decode(image_base64)
        
        # 保存到临时文件
        import tempfile
        temp_fd, temp_file_path = tempfile.mkstemp(suffix='.png')
        try:
            with os.fdopen(temp_fd, 'wb') as tmp_file:
                tmp_file.write(image_data)
            # 返回本地文件标识，使用 "local://" 前缀以便调用方识别
            return f"local://{temp_file_path}"
        except Exception as e:
            # 确保文件描述符和临时文件被清理，防止磁盘空间不足时残留空文件
            try:
                os.close(temp_fd)
            except Exception:
                pass
            try:
                if temp_file_path and os.path.exists(temp_file_path):
                    os.remove(temp_file_path)
            except Exception:
                pass
            raise Exception(f"保存临时图片失败: {e}")
    
    def _do_generate_image_by_reference(
        self,
        prompt: str,
        reference_images: List[str],
        model: str,
        aspect_ratio: str,
        guidance_scale: float = None
    ) -> str:
        """
        执行图生图调用的内部方法（不包含重试逻辑）
        
        Args:
            prompt: 图片生成提示词（英文或中文，根据模型决定）
            reference_images: 参考图片URL列表
            model: 模型名称
            aspect_ratio: 图片宽高比
            guidance_scale: 引导尺度（Nano Banana2 不支持此参数）
        Returns:
            生成的图片URL
        """
        # 检查是否为 Nano Banana2 模型
        if model == "gemini-3-pro-image-preview":
            # 使用 Gemini API
            logger.info(f"使用 Nano Banana2 (Gemini) API 进行图生图")
            
            # 强制使用 2K
            image_size = "2K"
            
            # 下载参考图片并转换为 Base64
            reference_images_base64 = []
            for img_url in reference_images:
                try:
                    base64_data = self._download_image_to_base64(img_url)
                    reference_images_base64.append(base64_data)
                    logger.info(f"成功下载并转换参考图片: {img_url}")
                except Exception as e:
                    logger.warning(f"下载参考图片失败，跳过: {e}")
            
            # if not reference_images_base64:
            #     raise Exception("Nano Banana2 图生图需要至少一张参考图片，但所有参考图片下载失败")
            
            # 调用 Gemini API
            image_base64 = self._call_gemini_image_api(
                prompt=prompt,
                reference_images_base64=reference_images_base64,
                aspect_ratio=aspect_ratio,
                image_size=image_size
            )
            
            # 将 Base64 图片转换为临时文件并返回 URL
            # 注意：这里返回的是临时文件路径，实际使用时需要上传到US3
            # 为了保持接口一致性，我们创建一个临时URL
            # 实际的上传逻辑在调用方（shot_task.py）中处理
            temp_url = self._save_base64_image_to_temp_url(image_base64)
            return temp_url
        else:
            # 使用原有的 OpenAI 兼容 API
            # 构建extra_body参数
            extra_body = {
                "images": reference_images,
                "aspect_ratio": aspect_ratio,
                "guidance_scale": guidance_scale if guidance_scale else 3.5,
                "negative_prompt": "bad hand, extra fingers, too dark, overexposed, color shift, monochromatic, ugly"
            }
            
            response = self.ai_client.images.generate(
                model=model,
                prompt=prompt,
                extra_body=extra_body,
            )
            
            image_url = response.data[0].url
            return image_url
    
    def generate_image_by_reference(
        self, 
        prompt: str, 
        reference_images: List[str], 
        model: str = None,
        aspect_ratio: str = None
    ) -> str:
        """
        根据提示词和参考图片生成图片（图生图，带重试机制）
        
        Args:
            prompt: 图片生成提示词（英文或中文，根据模型决定）
            reference_images: 参考图片URL列表（shot关联的角色图片）
            model: 模型名称，默认使用 image_to_image_model（图生图模型）
            aspect_ratio: 图片宽高比，格式为 "宽度:高度"，如果为None则从模型配置中获取
            
        Returns:
            生成的图片URL（对于 Nano Banana2，返回临时文件路径，格式为 "temp://..."）
            
        Raises:
            AIContentModerationError: 内容审核失败（如涉及暴恐等敏感内容）
            AITimeoutError: 调用超时
            AIRetryExhaustedError: 重试次数耗尽
        """
        # 图生图使用 image_to_image_model
        model = model or self.image_to_image_model
        
        # 如果没有指定 aspect_ratio，从模型配置中获取
        if aspect_ratio is None:
            try:
                model_config = ModelConfigService.get_model_config(model, "image_to_image")
                if model_config and "aspect_ratio" in model_config:
                    aspect_ratio = model_config["aspect_ratio"]
                else:
                    aspect_ratio = "16:9"  # 默认值
            except Exception as e:
                logger.warning(f"获取模型配置失败，使用默认 aspect_ratio: {e}")
                aspect_ratio = "16:9"  # 默认值
        
        logger.info(f"图生图开始，模型: {model}, aspect_ratio: {aspect_ratio}, 提示词长度: {len(prompt)}, 参考图片数量: {len(reference_images)}")
        logger.info(f"【图生图提示词】: {prompt}")
        logger.info(f"【图生图参考图片】: {reference_images}")
        
        last_error = None
        
        for attempt in range(1, self.max_retries + 1):
            try:
                logger.info(f"图生图尝试 {attempt}/{self.max_retries}，模型: {model}")
                
                # 使用线程池实现超时控制
                with ThreadPoolExecutor(max_workers=1) as executor:
                    future = executor.submit(
                        self._do_generate_image_by_reference,
                        prompt=prompt,
                        reference_images=reference_images,
                        model=model,
                        aspect_ratio=aspect_ratio,
                        guidance_scale=3.5
                    )
                    
                    try:
                        image_url = future.result(timeout=self.timeout)
                    except FuturesTimeoutError:
                        raise TimeoutError(f"图生图超时（{self.timeout}秒）")
                
                logger.info(f"图生图成功: {image_url}")
                return image_url
                
            except TimeoutError as e:
                last_error = e
                logger.warning(f"图生图超时（尝试 {attempt}/{self.max_retries}）: {e}")
                
            except Exception as e:
                last_error = e
                error_type = type(e).__name__
                error_msg = str(e)
                
                # 检查是否为内容审核错误
                if self._is_content_moderation_error(e):
                    error_detail = (
                        f"图生图内容审核未通过，可能涉及敏感内容（如暴恐、色情等）。"
                        f"错误信息: {error_msg}"
                    )
                    logger.error(
                        f"{error_detail} | 模型: {model} | "
                        f"提示词长度: {len(prompt)} | 参考图片数量: {len(reference_images)}"
                    )
                    raise AIContentModerationError(error_detail) from e
                
                # 检查是否为可重试的错误
                if not self._is_retryable_error(e):
                    # 不可重试的错误直接抛出
                    error_detail = f"图生图失败 ({error_type}): {error_msg}"
                    logger.error(f"{error_detail} | 模型: {model}")
                    raise Exception(error_detail) from e
                
                # 可重试的错误记录警告
                logger.warning(
                    f"图生图失败（尝试 {attempt}/{self.max_retries}）: {error_type}: {error_msg}"
                )
            
            # 如果不是最后一次尝试，等待后重试
            if attempt < self.max_retries:
                logger.info(f"等待 {self.retry_delay} 秒后重试...")
                time.sleep(self.retry_delay)
        
        # 所有重试都失败
        if isinstance(last_error, TimeoutError):
            error_msg = f"图生图超时，已重试 {self.max_retries} 次，每次超时时间: {self.timeout}秒"
            logger.error(error_msg)
            raise AITimeoutError(error_msg) from last_error
        else:
            error_msg = f"图生图失败，已重试 {self.max_retries} 次: {last_error}"
            logger.error(error_msg)
            raise AIRetryExhaustedError(error_msg) from last_error
    
    def _load_prompt_template(self, template_name: str) -> str:
        """
        从 prompt 文件夹加载提示词模板
        
        Args:
            template_name: 模板文件名（不含扩展名），如 "shot_image"
            
        Returns:
            模板内容字符串
        """
        try:
            # 获取 prompt 文件夹路径
            app_dir = Path(__file__).parent.parent
            prompt_file = app_dir / "prompt" / f"{template_name}.md"
            
            if not prompt_file.exists():
                raise FileNotFoundError(f"提示词模板文件不存在: {prompt_file}")
            
            with open(prompt_file, 'r', encoding='utf-8') as f:
                template = f.read()
            
            logger.debug(f"成功加载提示词模板: {prompt_file}")
            return template
        except Exception as e:
            logger.error(f"加载提示词模板失败: {e}")
            raise
    
    def _is_content_moderation_error(self, error: Exception) -> bool:
        """
        判断是否为内容审核失败错误（如涉及暴恐、色情等敏感内容）
        
        Args:
            error: 异常对象
            
        Returns:
            是否为内容审核错误
        """
        try:
            error_msg = str(error).lower()
        except Exception:
            error_msg = ""
        
        error_type = type(error).__name__
        
        # 检查错误消息中是否包含内容审核相关的关键词
        moderation_keywords = [
            'content policy',
            'content moderation',
            'safety',
            'violence',
            'terrorism',
            'terrorist',
            'violent',
            'inappropriate',
            'prohibited',
            'policy violation',
            '审核',
            '敏感',
            '违规',
            '禁止',
            '暴恐',
            '色情',
            '政治',
            'policy',
            'moderation',
            'rejected',
            'blocked'
        ]
        
        # 排除的关键词（这些明确表示不是审核错误）
        exclusion_keywords = [
            'model not support',
            'model not found',
            'invalid param',
            'param_error',
            'invalid_request_error',
            'not found',
            'unauthorized',
            'forbidden',
            'rate limit',
            'timeout',
            'connection',
            'network'
        ]
        
        # 先检查排除关键词，如果匹配则肯定不是审核错误
        for exclusion_keyword in exclusion_keywords:
            if exclusion_keyword in error_msg:
                return False
        
        # 检查是否为特定的 OpenAI API 错误类型
        if isinstance(error, openai.APIError):
            try:
                # 检查错误代码和类型
                if hasattr(error, 'code') and error.code is not None:
                    error_code = str(error.code).lower()
                    # 参数错误、模型不支持等不是审核错误
                    if any(excl in error_code for excl in ['param', 'model', 'invalid', 'not_found']):
                        return False
                
                # 检查错误消息中的详细信息
                if hasattr(error, 'message') and error.message is not None:
                    error_detail = str(error.message).lower()
                    # 如果错误消息中包含排除关键词，不是审核错误
                    for exclusion_keyword in exclusion_keywords:
                        if exclusion_keyword in error_detail:
                            return False
                    # 如果错误消息中包含审核关键词，是审核错误
                    for keyword in moderation_keywords:
                        if keyword in error_detail:
                            return True
                
                # 安全地访问 error.body（如果存在）
                if hasattr(error, 'body') and error.body is not None:
                    try:
                        # body 可能是字典或字符串
                        if isinstance(error.body, dict):
                            body_str = str(error.body).lower()
                        else:
                            body_str = str(error.body).lower()
                        # 检查 body 中是否包含审核关键词
                        for keyword in moderation_keywords:
                            if keyword in body_str:
                                return True
                    except (KeyError, AttributeError, TypeError):
                        # 如果访问 body 时出错，忽略并继续
                        pass
            except (KeyError, AttributeError, TypeError) as e:
                # 如果访问异常属性时出错，记录警告但继续处理
                logger.warning(f"访问 OpenAI 异常属性时出错: {e}")
        
        # 检查错误消息中是否包含审核关键词
        for keyword in moderation_keywords:
            if keyword in error_msg:
                return True
        
        return False
    
    def _is_retryable_error(self, error: Exception) -> bool:
        """
        判断是否为可重试的错误
        
        Args:
            error: 异常对象
            
        Returns:
            是否为可重试的错误
        """
        try:
            # 内容审核错误不可重试
            if self._is_content_moderation_error(error):
                return False
            
            # 超时错误可重试
            if isinstance(error, (TimeoutError, FuturesTimeoutError)):
                return True
            
            # 网络错误可重试
            if isinstance(error, (openai.APIConnectionError, openai.APITimeoutError)):
                return True
            
            # 5xx 服务器错误可重试
            if isinstance(error, openai.APIError):
                try:
                    if hasattr(error, 'status_code') and error.status_code is not None:
                        status_code = error.status_code
                        if 500 <= status_code < 600:
                            return True
                except (KeyError, AttributeError, TypeError):
                    # 如果访问 status_code 时出错，忽略并继续
                    pass
            
            # 429 限流错误可重试
            if isinstance(error, openai.RateLimitError):
                return True
            
            return False
        except Exception as e:
            # 如果判断过程中出现任何异常，记录警告并返回 False（不可重试）
            logger.warning(f"判断错误是否可重试时出错: {e}")
            return False
    
    def generate_shot_image_prompt(
        self,
        character_profiles: List[str],
        previous_shot_description: Optional[str],
        current_shot_description: str,
        model: str = None,
        image_model: str = None
    ) -> str:
        """
        生成分镜图片的提示词（支持英文/中文输出）

        Args:
            character_profiles: 角色档案列表（1-4个角色的外貌特征描述，中文）
            previous_shot_description: 上一分镜描述（中文，可选）
            current_shot_description: 当前分镜描述（中文）
            model: LLM模型名称，默认使用 prompt_generation_model
            image_model: 图片模型名称（用于确定输出语言），默认使用 image_to_image_model

        Returns:
            提示词（英文或中文，根据图片模型配置决定）
        """
        # 默认使用提示词生成专用模型
        model = model or self.prompt_generation_model

        # 从文件加载prompt模板
        prompt_template = self._load_prompt_template("shot_image")

        # 确定输出语言：从图片模型配置中获取支持的语言
        image_model = image_model or self.image_to_image_model
        output_language = "英文"  # 默认英文
        word_unit = "单词"  # 默认单词
        max_words = 150  # 默认字数上限

        try:
            model_config = ModelConfigService.get_model_config(image_model, "image_to_image")
            if model_config and "languages" in model_config:
                languages = model_config["languages"]
                # 如果模型支持中文，使用中文输出
                if "zh" in languages or "chinese" in [lang.lower() for lang in languages]:
                    output_language = "中文"
                    word_unit = "字"
            if model_config and "max_words" in model_config:
                max_words = model_config.get("max_words", max_words)
        except Exception as e:
            logger.warning(f"获取图片模型配置失败，使用默认英文输出: {e}")

        # 格式化角色档案
        character_profiles_text = "\n".join([f"- {profile}" for profile in character_profiles]) if character_profiles else "无"

        # 格式化上一分镜（如果为空则使用"无"）
        previous_shot_text = previous_shot_description if previous_shot_description else "无"

        # 格式化prompt（包含语言参数）
        formatted_prompt = prompt_template.format(
            character_profiles=character_profiles_text,
            previous_shot=previous_shot_text,
            current_shot=current_shot_description,
            output_language=output_language,
            word_unit=word_unit,
            max_words=max_words
        )

        messages = [
            {
                "role": "user",
                "content": formatted_prompt
            }
        ]

        try:
            ##X## Debug 模式下抛出测试异常 - 测试角色分析LLM调用错误（生成分镜提示词）
            # if settings.DEBUG:
            #     raise Exception("测试角色分析LLM调用错误（生成分镜提示词）")

            response = self.chat_completion(messages=messages, model=model)
            prompt_text = response.get("content", "").strip()

            # # 确保末尾包含强制后缀
            # if not prompt_text.endswith("strictly preserve reference face and hairstyle"):
            #     prompt_text += ", strictly preserve reference face and hairstyle"

            logger.info(f"生成的图片提示词长度: {len(prompt_text)}")
            return prompt_text
        except Exception as e:
            logger.error(f"生成图片提示词失败: {e}")
            raise

