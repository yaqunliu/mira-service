"""
独立创作意图识别服务

用于识别用户创建独立内容的意图（不依赖于小说/章节）
"""

import json
from typing import Dict, Any, List, Optional
from pydantic import BaseModel

from langchain_openai import ChatOpenAI

from app.agent.prompts import load_prompt, format_prompt, get_prompt_config
from app.core.config import settings
from app.core.logger import logger


class IntentResult(BaseModel):
    """意图识别结果"""
    intent: str
    intent_category: str
    confidence: float
    can_proceed: bool
    redirect_to_legacy: bool = False
    legacy_url: str = ""
    extracted_params: Dict[str, Any]
    missing_required: List[str]
    missing_optional: List[str]
    details: Dict[str, Any]


class StandaloneIntentService:
    """独立创作意图识别服务"""
    
    def __init__(self):
        self.prompt_name = "standalone_intent_detection"
    
    async def detect_intent(
        self,
        message: str,
        chat_history: Optional[List[Dict[str, str]]] = None
    ) -> IntentResult:
        """
        识别用户意图
        
        Args:
            message: 用户消息
            chat_history: 对话历史（可选）
            
        Returns:
            IntentResult: 意图识别结果
        """
        logger.info(f"[StandaloneIntent] 识别意图: {message[:100]}...")
        
        # 加载提示词
        prompt_data = load_prompt(self.prompt_name)
        
        # 构建上下文
        context = {
            "user_message": message,
            "chat_history": chat_history or [],
        }
        
        # 渲染提示词
        prompt = format_prompt(prompt_data, context)
        
        # 获取模型配置
        model = get_prompt_config(prompt_data, "model", "gpt-4o-mini")
        temperature = get_prompt_config(prompt_data, "temperature", 0.3)
        
        # 调用 LLM
        try:
            llm = ChatOpenAI(
                model=model,
                temperature=temperature,
                api_key=settings.OPENAI_API_KEY,
            )
            
            response = await llm.ainvoke(prompt)
            result = self._parse_response(response.content)
            
            logger.info(
                f"[StandaloneIntent] 识别结果: "
                f"intent={result.intent}, "
                f"can_proceed={result.can_proceed}, "
                f"params={result.extracted_params}"
            )
            
            return result
            
        except Exception as e:
            logger.error(f"[StandaloneIntent] LLM 调用失败: {e}")
            # 降级处理
            return IntentResult(
                intent="unknown",
                intent_category="standalone",
                confidence=0.0,
                can_proceed=False,
                extracted_params={},
                missing_required=["unknown"],
                missing_optional=[],
                details={"error": str(e)}
            )
    
    def _parse_response(self, content: str) -> IntentResult:
        """解析 LLM 返回的 JSON 响应"""
        # 移除可能的 markdown 代码块标记
        content = content.strip()
        if content.startswith("```json"):
            content = content[7:]
        if content.startswith("```"):
            content = content[3:]
        if content.endswith("```"):
            content = content[:-3]
        content = content.strip()
        
        try:
            data = json.loads(content)
            return IntentResult(
                intent=data.get("intent", "unknown"),
                intent_category=data.get("intent_category", "standalone"),
                confidence=data.get("confidence", 0.0),
                can_proceed=data.get("can_proceed", False),
                redirect_to_legacy=data.get("redirect_to_legacy", False),
                legacy_url=data.get("legacy_url", "/create-dynamic-comic"),
                extracted_params=data.get("extracted_params", {}),
                missing_required=data.get("missing_required", []),
                missing_optional=data.get("missing_optional", []),
                details=data.get("details", {})
            )
        except json.JSONDecodeError as e:
            logger.warning(f"[StandaloneIntent] JSON 解析失败: {e}, content: {content[:100]}")
            return IntentResult(
                intent="unknown",
                intent_category="standalone",
                confidence=0.0,
                can_proceed=False,
                extracted_params={},
                missing_required=["parse_error"],
                missing_optional=[],
                details={"parse_error": str(e), "raw_content": content[:200]}
            )


# 全局服务实例
standalone_intent_service = StandaloneIntentService()
