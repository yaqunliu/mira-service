"""
引导澄清节点

当用户意图不明确时，引导用户提供更多信息
"""

from typing import Dict, Any

from app.core.logger import logger


async def clarify_node(state: Dict[str, Any]) -> Dict[str, Any]:
    """
    引导澄清节点
    
    当意图识别置信度较低或意图不明确时，
    生成引导性问题帮助用户明确需求
    
    优化：当意图明确但缺少资源定位信息时，给出针对性的引导
    
    Args:
        state: 当前 Graph 状态
        
    Returns:
        更新后的状态，包含澄清问题
    """
    logger.info("[Node] clarify: 开始生成引导问题")
    
    from datetime import datetime
    from app.agent.prompts import load_and_format
    
    user_message = state.get("user_message", "")
    detected_intent = state.get("detected_intent", "unknown")
    intent_confidence = state.get("intent_confidence", 0.0)
    intent_details = state.get("intent_details", {})
    current_stage = state.get("current_stage", "init")
    messages = state.get("messages", [])
    
    # ===== 智能澄清：根据意图类型给出针对性引导 =====
    
    # 情况1: regenerate 意图但缺少资源定位信息
    if detected_intent == "regenerate":
        target = intent_details.get("target", "shot")
        has_numbers = bool(intent_details.get("target_numbers"))
        has_names = bool(intent_details.get("target_names"))
        scope = intent_details.get("scope")
        
        # 如果有明确的资源定位信息，不应该走到 clarify
        if has_numbers or has_names or scope in ["failed", "all"]:
            logger.info("[Node] clarify: regenerate 意图已有足够信息，不应走到 clarify")
            # 返回一个提示，让 router 重新路由到 task_execution
            return {
                "messages": messages,
                "response_text": "",
                "awaiting_clarification": False,
                "clarify_skipped": True,
                "reason": "regenerate 意图已有足够信息",
                "updated_at": datetime.now().isoformat(),
            }
        
        # 缺少资源定位信息，给出针对性引导
        if target == "shot":
            response_text = """我可以帮您重新生成分镜。请告诉我：

1. **指定分镜编号** - 例如："分镜11"、"第3个分镜"
2. **重新生成所有失败的分镜** - 说"重新生成失败的分镜"
3. **重新生成所有分镜** - 说"重新生成所有分镜"

您想怎么做？"""
        elif target == "character":
            response_text = """我可以帮您重新生成角色图片。请告诉我：

1. **指定角色名称** - 例如："给幽影重新生成"
2. **重新生成所有角色** - 说"重新生成所有角色"

您想怎么做？"""
        elif target == "scene":
            response_text = """我可以帮您重新生成场景图片。请告诉我：

1. **指定场景编号或名称** - 例如："场景2"、"客栈场景"
2. **重新生成所有场景** - 说"重新生成所有场景"

您想怎么做？"""
        else:
            response_text = """我可以帮您重新生成资源。请告诉我：

- 要重新生成什么？（分镜/角色/场景）
- 具体是哪个？（编号或名称）

例如：给分镜11重新生成视频"""
        
        assistant_message = {
            "role": "assistant",
            "content": response_text,
            "timestamp": datetime.now().isoformat(),
            "node": "clarify",
            "metadata": {
                "original_intent": detected_intent,
                "confidence": intent_confidence,
                "clarify_reason": "regenerate 缺少资源定位信息",
            },
        }
        
        updated_messages = list(messages)
        updated_messages.append(assistant_message)
        
        return {
            "messages": updated_messages,
            "response_text": response_text,
            "awaiting_clarification": True,
            "updated_at": datetime.now().isoformat(),
        }
    
    # 情况2: 标准澄清流程
    try:
        # 构建上下文
        context = {
            "user_message": user_message,
            "detected_intent": detected_intent,
            "intent_confidence": intent_confidence,
            "current_stage": current_stage,
            "chat_history": _format_chat_history(messages[-5:]),  # 最近 5 条
            "available_actions": _get_available_actions(current_stage),
        }
        
        # 使用提示词生成引导问题
        prompt = load_and_format("clarify_response", context)
        
        from langchain_openai import ChatOpenAI
        from app.core.config import settings
        
        llm = ChatOpenAI(
            model=settings.LLM_MODEL_DEFAULT,
            api_key=settings.OPENAI_API_KEY,
            base_url=settings.OPENAI_BASE_URL,
            temperature=0.7,
            streaming=True,  # 启用流式输出
        )
        
        response = await llm.ainvoke(prompt)
        response_text = response.content
        
        # 构建助手消息
        assistant_message = {
            "role": "assistant",
            "content": response_text,
            "timestamp": datetime.now().isoformat(),
            "node": "clarify",
            "metadata": {
                "original_intent": detected_intent,
                "confidence": intent_confidence,
                "clarify_reason": _get_clarify_reason(detected_intent, intent_confidence),
            },
        }
        
        # 更新消息历史
        updated_messages = list(messages)
        updated_messages.append(assistant_message)
        
        logger.info(f"[Node] clarify: 引导问题已生成")
        
        return {
            "messages": updated_messages,
            "response_text": response_text,
            "awaiting_clarification": True,
            "updated_at": datetime.now().isoformat(),
        }
        
    except Exception as e:
        logger.error(f"[Node] clarify 错误: {e}")
        
        # 使用默认引导消息
        fallback_message = _get_fallback_message(current_stage, detected_intent)
        
        return {
            "messages": messages + [{
                "role": "assistant",
                "content": fallback_message,
                "timestamp": datetime.now().isoformat(),
                "node": "clarify",
                "fallback": True,
            }],
            "response_text": fallback_message,
            "awaiting_clarification": True,
            "errors": state.get("errors", []) + [{"node": "clarify", "error": str(e)}],
        }


def _format_chat_history(messages: list) -> str:
    """格式化聊天历史"""
    if not messages:
        return "（无历史消息）"
    
    formatted = []
    for msg in messages:
        role = "用户" if msg.get("role") == "user" else "助手"
        content = msg.get("content", "")[:100]  # 限制长度
        formatted.append(f"{role}: {content}")
    
    return "\n".join(formatted)


def _get_available_actions(current_stage: str) -> str:
    """根据当前阶段获取可用操作"""
    stage_actions = {
        "init": """
- 上传剧本开始创作
- 查看系统功能介绍
""",
        "script_analysis": """
- 查看剧本分析结果
- 修改角色/场景信息
- 确认分析结果并继续
""",
        "asset_generation": """
- 查看/重新生成角色图片
- 查看/重新生成场景图片
- 修改图片提示词
- 查看整体进度
""",
        "storyboard_creation": """
- 查看分镜列表
- 修改分镜内容
- 重新生成分镜图片
- 查看整体进度
""",
        "audio_processing": """
- 查看音频生成进度
- 调整语音参数
- 重新生成某段音频
""",
        "video_generation": """
- 查看视频生成进度
- 重新生成某段视频
- 调整视频参数
""",
        "editing": """
- 查看最终合成进度
- 调整剪辑参数
""",
        "completed": """
- 下载最终视频
- 查看创作统计
- 开始新的创作
""",
    }
    
    return stage_actions.get(current_stage, """
- 查看当前状态
- 获取帮助
""")


def _get_clarify_reason(detected_intent: str, confidence: float) -> str:
    """获取需要澄清的原因"""
    if detected_intent == "out_of_scope":
        return "超出能力范围"
    elif detected_intent == "unknown":
        return "无法识别意图"
    elif confidence < 0.5:
        return f"意图置信度过低 ({confidence:.0%})"
    else:
        return "需要更多上下文信息"


def _get_fallback_message(current_stage: str, detected_intent: str = "unknown") -> str:
    """获取默认引导消息"""
    # 超出能力范围的明确拒绝
    if detected_intent == "out_of_scope":
        return """抱歉，这个问题超出了我的能力范围。

我是**漫剧创作助手**，专注于帮助您：
- 📊 查询创作进度
- 🎬 执行漫剧制作任务（分析剧本、生成图片/视频等）
- 📚 解答漫剧相关知识（构图、镜头、提示词技巧等）

请告诉我您在漫剧创作方面有什么需要帮助的？"""
    
    if current_stage == "init":
        return "您好！我是漫剧创作助手，请问有什么可以帮您的？\n\n您可以：\n- 上传剧本开始创作\n- 询问系统功能"
    elif current_stage in ["script_analysis", "asset_generation"]:
        return "抱歉，我没有完全理解您的意思。\n\n您是想：\n1. 查看当前进度\n2. 修改某个资产\n3. 重新生成某张图片\n\n请告诉我更多细节。"
    elif current_stage in ["storyboard_creation", "audio_processing", "video_generation"]:
        return "抱歉，我没有完全理解您的意思。\n\n请问您是想：\n1. 查看生成进度\n2. 修改某个内容\n3. 其他操作\n\n请具体描述一下您的需求。"
    else:
        return "抱歉，我没有完全理解您的意思，能否再详细描述一下？"
