"""
AI 生成内容工具类
用于调用基于 OpenAI 的 LLM 或其他生图模型
"""

import os
import json
import re
import time
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

    def _save_ai_response(self, content: str, model: str = None, file_type: str = "txt") -> str:
        """
        将 AI 返回内容保存到文件
        
        Args:
            content: AI 返回的内容
            model: 使用的模型名称
            
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
            
            # 写入文件
            with open(file_path, 'w', encoding='utf-8') as f:
                f.write(content)
            
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
        self, messages: List[Dict[str, str]], model: str, **kwargs
    ) -> Dict[str, Any]:
        """
        执行 LLM 调用的内部方法（不包含重试逻辑）
        
        Args:
            messages: 消息列表
            model: 模型名称
            **kwargs: 其他参数
            
        Returns:
            AI 响应内容
        """
        response = self.ai_client.chat.completions.create(
            model=model, 
            messages=messages, 
            max_tokens=12288,
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
            self._save_ai_response(ai_content, model=model or self.llm_model_name, file_type="json")
            
            logger.info(f"AI 返回内容解析: {self._parse_json_response(ai_content)}")
            return self._parse_json_response(ai_content)

        except Exception as e:
            logger.error(f"生成剧本失败: {e}")
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
    
    def generate_image_by_prompt(self, prompt: str, model: str = None, aspectRatio: str = "1024x576") -> str:
        """
        根据提示词生成图片（文生图，带重试机制）
        
        Args:
            prompt: 提示词
            model: 模型名称，默认使用初始化时的模型
            aspectRatio: 图片尺寸
            
        Returns:
            生成的图片URL
            
        Raises:
            AIContentModerationError: 内容审核失败（如涉及暴恐等敏感内容）
            AITimeoutError: 调用超时
            AIRetryExhaustedError: 重试次数耗尽
        """
        # 文生图使用 text_to_image_model
        model = model or self.text_to_image_model
        logger.info(f"生成图片开始（文生图），模型: {model}, 提示词长度: {len(prompt)}")
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
            prompt: 图片生成提示词（英文）
            reference_images: 参考图片URL列表
            model: 模型名称
            aspect_ratio: 图片宽高比
            guidance_scale: 引导尺度
        Returns:
            生成的图片URL
        """
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
        aspect_ratio: str = "16:9"
    ) -> str:
        """
        根据提示词和参考图片生成图片（图生图，带重试机制）
        
        Args:
            prompt: 图片生成提示词（英文）
            reference_images: 参考图片URL列表（shot关联的角色图片）
            model: 模型名称，默认使用 image_to_image_model（图生图模型）
            aspect_ratio: 图片宽高比，格式为 "宽度:高度"，默认 "16:9"
            
        Returns:
            生成的图片URL
            
        Raises:
            AIContentModerationError: 内容审核失败（如涉及暴恐等敏感内容）
            AITimeoutError: 调用超时
            AIRetryExhaustedError: 重试次数耗尽
        """
        # 图生图使用 image_to_image_model
        model = model or self.image_to_image_model
        logger.info(f"图生图开始，模型: {model}, 提示词长度: {len(prompt)}, 参考图片数量: {len(reference_images)}")
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
        model: str = None
    ) -> str:
        """
        生成分镜图片的英文提示词
        
        Args:
            character_profiles: 角色档案列表（1-4个角色的外貌特征描述，中文）
            previous_shot_description: 上一分镜描述（中文，可选）
            current_shot_description: 当前分镜描述（中文）
            model: 模型名称，默认使用初始化时的模型
            
        Returns:
            英文提示词（200词以内，末尾包含 "strictly preserve reference face and hairstyle"）
        """
        # 从文件加载prompt模板
        prompt_template = self._load_prompt_template("shot_image")
        
        # 格式化角色档案
        character_profiles_text = "\n".join([f"- {profile}" for profile in character_profiles]) if character_profiles else "无"
        
        # 格式化上一分镜（如果为空则使用"无"）
        previous_shot_text = previous_shot_description if previous_shot_description else "无"
        
        # 格式化prompt
        formatted_prompt = prompt_template.format(
            character_profiles=character_profiles_text,
            previous_shot=previous_shot_text,
            current_shot=current_shot_description
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
            
            # 确保末尾包含强制后缀
            if not prompt_text.endswith("strictly preserve reference face and hairstyle"):
                prompt_text += ", strictly preserve reference face and hairstyle"
            
            logger.info(f"生成的图片提示词长度: {len(prompt_text)}")
            return prompt_text
        except Exception as e:
            logger.error(f"生成图片提示词失败: {e}")
            raise

