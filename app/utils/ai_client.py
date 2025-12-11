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
        image_model_name: str = None, text_to_image_model: str = None, image_to_image_model: str = None
    ):
        """
        初始化 AIGC 客户端

        Args:
            api_key: OpenAI API 密钥，默认从配置读取
            base_url: API 基础 URL，默认从配置读取
            llm_model_name: 模型名称，默认从配置读取
            image_model_name: 图片模型名称（向后兼容，已废弃）
            text_to_image_model: 文生图模型名称（用于生成角色图片）
            image_to_image_model: 图生图模型名称（用于生成分镜图片）
        """
        self.api_key = api_key or settings.OPENAI_API_KEY
        self.base_url = base_url or settings.OPENAI_BASE_URL
        self.llm_model_name = llm_model_name or settings.LLM_MODEL_NAME
        
        # 图片模型配置：优先使用新配置，否则使用旧配置（向后兼容）
        self.text_to_image_model = text_to_image_model or settings.IMAGE_MODEL_TEXT_TO_IMAGE or settings.IMAGE_MODEL_NAME
        self.image_to_image_model = image_to_image_model or settings.IMAGE_MODEL_IMAGE_TO_IMAGE or settings.IMAGE_MODEL_NAME
        # 向后兼容：保留旧属性
        self.image_model_name = image_model_name or self.text_to_image_model
        
        logger.info(f"文生图模型（角色）: {self.text_to_image_model}")
        logger.info(f"图生图模型（分镜）: {self.image_to_image_model}")

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

        logger.info(f"AIGC客户端初始化成功，BaseURL: {self.base_url}")

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
            model: 模型名称，默认使用初始化时的模型
            user_id: 用户ID（用于积分扣除，可选）
            creation_id: 创作ID（用于积分扣除，可选）
            novel_id: 小说ID（用于积分扣除，可选）

        Returns:
            解析后的 JSON 数据，包含章节信息和人物特征库
        """
        # 构建历史角色库的文本描述
        historical_characters_text = ""
        if historical_characters:
            historical_characters_text = "\n\n以下是之前已存在的角色特征库（如果当前章节中出现同名角色，请优先复用这些特征）：\n"
            historical_characters_text += json.dumps(historical_characters, ensure_ascii=False, indent=2)
        
        messages = [
            {
                "role": "user",
                "content": f"{prompt}{historical_characters_text}\n\n下面是章节内容：\n{chapter_content}",
            }
        ]

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
                model=model or self.llm_model_name,
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
        response = None
        if guidance_scale:
            response = self.ai_client.images.generate(model=model, prompt=prompt, size=aspectRatio, guidance_scale=guidance_scale)
        else:
            response = self.ai_client.images.generate(model=model, prompt=prompt, size=aspectRatio)
        image_url = response.data[0].url
        return image_url
    
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
        下载图片并转换为 Base64 编码
        
        Args:
            image_url: 图片URL
            
        Returns:
            Base64 编码的图片数据
        """
        try:
            with httpx.Client(timeout=30.0) as client:
                response = client.get(image_url)
                response.raise_for_status()
                image_data = response.content
                # 转换为 Base64
                base64_data = base64.b64encode(image_data).decode('utf-8')
                return base64_data
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
            
            # 从模型配置中获取 image_size（默认 2K）
            try:
                model_config = ModelConfigService.get_model_config(model, "image_to_image")
                image_size = model_config.get("image_size", "2K") if model_config else "2K"
            except Exception as e:
                logger.warning(f"获取模型配置失败，使用默认 image_size: {e}")
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
            model: LLM模型名称，默认使用初始化时的模型
            image_model: 图片模型名称（用于确定输出语言），默认使用 image_to_image_model
            
        Returns:
            提示词（英文或中文，根据图片模型配置决定）
        """
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

