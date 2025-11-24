"""
AI 生成内容工具类
用于调用基于 OpenAI 的 LLM 或其他生图模型
"""

import os
import json
import re
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, Optional, List
from app.core.config import settings
from app.core.logger import logger
import openai


class AIClient:
    """AI 生成内容客户端

    统一管理 AI 模型调用，支持 LLM 文本生成、图片生成、音频生成等功能
    """

    def __init__(
        self, api_key: str = None, base_url: str = None, llm_model_name: str = None, image_model_name: str = None
    ):
        """
        初始化 AIGC 客户端

        Args:
            api_key: OpenAI API 密钥，默认从配置读取
            base_url: API 基础 URL，默认从配置读取
            llm_model_name: 模型名称，默认从配置读取
        """
        self.api_key = api_key or settings.OPENAI_API_KEY
        self.base_url = base_url or settings.OPENAI_BASE_URL
        self.llm_model_name = llm_model_name or settings.LLM_MODEL_NAME
        self.image_model_name = image_model_name or settings.IMAGE_MODEL_NAME
        logger.info(f"生图模型: {self.image_model_name}")

        if not self.api_key:
            raise ValueError("OpenAI API Key 未配置")
        if not self.base_url:
            raise ValueError("OpenAI Base URL 未配置")
        if not self.llm_model_name:
            raise ValueError("Model Name 未配置")

        # 初始化 OpenAI 客户端（可复用）
        self.ai_client = openai.OpenAI(api_key=self.api_key, base_url=self.base_url)

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

    def chat_completion(
        self, messages: List[Dict[str, str]], model: str = None, **kwargs
    ) -> Dict[str, Any]:
        """
        调用 LLM 进行文本生成

        Args:
            messages: 消息列表
            model: 模型名称，默认使用初始化时的模型
            **kwargs: 其他参数（如 temperature, max_tokens 等）

        Returns:
            AI 响应内容
        """
        model = model or self.llm_model_name
        logger.debug(f"LLM 调用开始，模型: {model}")

        
        try:
            response = self.ai_client.chat.completions.create(
                model=model, 
                messages=messages, 
                max_tokens=12288,
                **kwargs
            )
            logger.debug(f"LLM 调用结束，模型: {model}")

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

        except Exception as e:
            # 处理 OpenAI API 错误
            error_type = type(e).__name__
            error_msg = str(e)
            
            # 尝试提取更详细的错误信息
            if hasattr(e, 'status_code'):
                status_code = e.status_code
                error_detail = f"OpenAI API 错误 (状态码: {status_code}): {error_msg}"
            elif hasattr(e, 'response'):
                error_detail = f"OpenAI API 错误: {error_msg} - 响应: {e.response}"
            else:
                error_detail = f"LLM 调用失败 ({error_type}): {error_msg}"
            
            # 记录详细的错误信息，包括传入的参数（但不包括敏感信息）
            logger.error(
                f"{error_detail} | "
                f"模型: {model} | "
                f"消息数量: {len(messages)} | "
            )
            raise Exception(error_detail) from e

    def gen_playbook_by_chapter(
        self, prompt: str, chapter_content: str, model: str = None
    ) -> Dict[str, Any]:
        """
        根据章节内容生成剧本（Playbook）

        Args:
            prompt: 提示词
            chapter_content: 章节内容
            model: 模型名称，默认使用初始化时的模型

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
            response = self.chat_completion(messages=messages, model=model, response_format={"type": "json_object"})
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
    
    def generate_image_by_prompt(self, prompt: str, model: str = None, aspectRatio: str = "576x1024") -> str:
        """
        根据提示词生成图片
        """
        logger.info(f"生成图片开始，模型: {model or self.image_model_name}, 提示词: {prompt}")
        try:
            response = self.ai_client.images.generate(
                model=model or self.image_model_name,
                prompt=prompt,
                size=aspectRatio,
            )
            logger.info(f"生成图片size: {aspectRatio}")
            image_url = response.data[0].url
            logger.info(f"生成图片成功: {image_url}")
            return image_url
        except Exception as e:
            logger.error(f"生成图片失败: {e}")
            raise

