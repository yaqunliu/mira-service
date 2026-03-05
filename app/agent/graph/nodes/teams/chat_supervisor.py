"""
Chat Supervisor - Chat 类型创作的 Supervisor (调度者)

使用 Command Pattern 返回：
- Command(goto="vocab_worker") → 调度到 Worker 执行
- Command(goto=END) → 结束，发送响应给用户
"""

from typing import Dict, Any
from datetime import datetime
from langgraph.graph import END
from langgraph.types import Command

from app.agent.state.chat_schemas import ChatState, ChatStage
from app.core.logger import logger


CREATION_TYPES = {
    "vocab_video": {
        "name": "英文单词视频",
        "description": "制作精美的单词教学视频",
        "required_params": ["words"],
    },
}


def validate_params(video_type: str, config: Dict[str, Any]) -> tuple[bool, list, Dict[str, Any]]:
    """验证参数是否齐全"""
    if video_type not in CREATION_TYPES:
        return False, ["unknown_type"], {}
    
    type_config = CREATION_TYPES[video_type]
    required = type_config["required_params"]
    
    missing = []
    current = {}
    
    for param in required:
        value = config.get(param)
        if not value or (isinstance(value, list) and len(value) == 0):
            missing.append(param)
        else:
            current[param] = value
    
    # 添加默认值
    current.setdefault("sentence_level", config.get("sentence_level", "primary"))
    current.setdefault("word_repeat_count", config.get("word_repeat_count", 2))
    current.setdefault("translation_repeat_count", config.get("translation_repeat_count", 1))
    current.setdefault("voice_gender", config.get("voice_gender", "random"))
    
    return len(missing) == 0, missing, current


async def chat_supervisor_node(state: ChatState) -> Command:
    """
    Chat Supervisor 节点 (调度者)
    
    使用 Command Pattern 返回，决定下一步：
    - 需要生成视频 → Command(goto="vocab_worker")
    - 需要用户补充参数 → Command(goto=END)，发送配置卡片
    """
    logger.info("[ChatSupervisor] 开始处理")
    
    user_message = state.get("user_message", "")
    video_type = state.get("video_type")
    vocab_config = state.get("vocab_config", {})
    
    response_text = ""
    board_actions = []
    
    try:
        # 使用 LLM 理解用户消息，提取意图和参数
        from langchain_openai import ChatOpenAI
        
        prompt = f"""你是智能创作助手，理解用户消息并做出决策。只返回纯文本回复，不要 JSON。

当前状态：
- 视频类型：{video_type if video_type else '未选择'}
- 当前参数：{vocab_config}

用户消息：{user_message}

决策规则：

1. 如果用户还没有选择视频类型：
   - 用户说"单词视频" → 设置 video_type=vocab_video，显示类型选择卡片
   - 用户说"搞笑视频" → 设置 video_type=gaoxiao_video，显示类型选择卡片
   - 用户说"故事视频" → 设置 video_type=story_video，显示类型选择卡片
   - 其他 → 显示类型选择卡片
   
2. 如果用户已经选择了类型（{video_type}）：
   - 用户提供了参数（单词、难度等）→ 提取参数，检查是否齐全
   - 用户要求开始生成视频 → 开始生成
   - 其他 → 检查参数是否齐全

请直接给出回复文本（纯文本，不要 JSON）：
"""

        from pydantic import BaseModel
        from typing import Optional, List
        
        class IntentResult(BaseModel):
            intent: str
            video_type: Optional[str] = None
            words: Optional[List[str]] = None
            response_text: str
        
        llm = ChatOpenAI(model="gpt-4o-mini", temperature=0.3, max_tokens=600)
        llm_with_structured = llm.with_structured_output(IntentResult)
        
        # 构建完整 prompt
        full_prompt = f"""当前状态：
- 视频类型：{video_type if video_type else '未选择'}
- 当前参数：{vocab_config}

用户消息：{user_message}

决策规则：
1. 如果用户还没有选择视频类型 → intent=select_type
2. 如果用户说"单词视频" → intent=confirm_type, video_type=vocab_video
3. 如果用户说"搞笑视频" → intent=confirm_type, video_type=gaoxiao_video
4. 如果用户说"故事视频" → intent=confirm_type, video_type=story_video
5. 如果用户已选择类型并提供参数 → intent=configure
6. 如果用户要求开始生成 → intent=start_creation"""

        response: IntentResult = await llm_with_structured.ainvoke(full_prompt)
        
        intent = response.intent
        detected_video_type = response.video_type
        words = response.words or []
        response_text = response.response_text
        
        logger.info(f"[ChatSupervisor] 意图: {intent}, 类型: {detected_video_type}, 单词: {words}, 回复: {response_text[:30]}...")
        
        # 更新参数
        if words:
            vocab_config["words"] = words
        
        # 处理决策
        if intent == "select_type":
            # 发送类型选择
            board_actions.append({
                "type": "select_options",
                "message": "请选择创作类型：",
                "options": [
                    {"id": "vocab_video", "label": "📚 英文单词视频", "value": "我要创作英文单词视频"},
                    {"id": "gaoxiao_video", "label": "😄 搞笑短视频", "value": "我要创作搞笑视频"},
                    {"id": "story_video", "label": "📖 故事动画视频", "value": "我要创作故事视频"},
                ]
            })
            response_text = response_text or "你好！我是智能创作助手 🎬\n\n请选择你想创作的视频类型："
            
            return Command(
                goto=END,
                update={
                    "response_text": response_text,
                    "board_actions": board_actions,
                    "vocab_config": vocab_config,
                    "video_type": video_type,
                    "chat_stage": ChatStage.INIT,
                    "updated_at": datetime.now().isoformat(),
                }
            )
            
        elif intent == "confirm_type" and detected_video_type:
            # 用户确认了类型，发送配置卡片
            video_type = detected_video_type
            
            board_actions.append({
                "type": "show_config_card",
                "card_type": "vocab_config",
                "title": "🎬 配置单词视频参数",
                "description": "请填写以下参数，都有默认值可以直接确认",
                "fields": [
                    {"name": "words", "label": "📝 单词列表", "type": "tags", "placeholder": "输入英文单词（1-5个）", "required": True, "default": [], "max": 5},
                    {"name": "sentence_level", "label": "📚 句子难度", "type": "select", "options": [{"value": "kindergarten", "label": "🍼 幼儿园"}, {"value": "primary", "label": "📖 小学"}, {"value": "middle", "label": "🎓 中学"}], "default": "primary"},
                    {"name": "word_repeat_count", "label": "🔁 单词重复", "type": "select", "options": [{"value": 1, "label": "1次"}, {"value": 2, "label": "2次"}], "default": 2},
                    {"name": "translation_repeat_count", "label": "🔁 翻译重复", "type": "select", "options": [{"value": 1, "label": "1次"}, {"value": 2, "label": "2次"}], "default": 1},
                    {"name": "voice_gender", "label": "🎙️ 配音性别", "type": "select", "options": [{"value": "female", "label": "👩 女声"}, {"value": "male", "label": "👨 男声"}, {"value": "random", "label": "🎲 随机"}], "default": "random"},
                ],
                "submit_text": "✨ 确认并开始创作"
            })
            response_text = response_text or f"✅ 已选择 **{CREATION_TYPES[video_type]['name']}**\n\n请配置参数后开始创作～"
            
            return Command(
                goto=END,
                update={
                    "response_text": response_text,
                    "board_actions": board_actions,
                    "vocab_config": vocab_config,
                    "video_type": video_type,
                    "chat_stage": ChatStage.CONFIGURING,
                    "updated_at": datetime.now().isoformat(),
                }
            )
            
        elif intent in ["configure", "start_creation"]:
            # 检查参数是否齐全
            if video_type:
                is_complete, missing, current = validate_params(video_type, vocab_config)
                
                if is_complete:
                    # 参数齐全，调度到 Worker
                    vocab_config.update(current)
                    response_text = response_text or "参数已齐全！开始生成视频..."
                    
                    return Command(
                        goto="vocab_worker",
                        update={
                            "response_text": response_text,
                            "vocab_config": vocab_config,
                            "video_type": video_type,
                            "chat_stage": ChatStage.GENERATING,
                            "updated_at": datetime.now().isoformat(),
                        }
                    )
                else:
                    # 参数不足，发送配置卡片
                    response_text = f"当前参数：{vocab_config}\n\n缺少：{', '.join(missing)}\n\n请补充参数～"
                    
                    board_actions.append({
                        "type": "show_config_card",
                        "card_type": "vocab_config",
                        "title": "🎬 补充参数",
                        "fields": [
                            {"name": "words", "label": "📝 单词列表", "type": "tags", "placeholder": "输入英文单词（1-5个）", "required": True, "default": vocab_config.get("words", []), "max": 5},
                            {"name": "sentence_level", "label": "📚 句子难度", "type": "select", "options": [{"value": "kindergarten", "label": "🍼 幼儿园"}, {"value": "primary", "label": "📖 小学"}, {"value": "middle", "label": "🎓 中学"}], "default": vocab_config.get("sentence_level", "primary")},
                            {"name": "word_repeat_count", "label": "🔁 单词重复", "type": "select", "options": [{"value": 1, "label": "1次"}, {"value": 2, "label": "2次"}], "default": vocab_config.get("word_repeat_count", 2)},
                            {"name": "translation_repeat_count", "label": "🔁 翻译重复", "type": "select", "options": [{"value": 1, "label": "1次"}, {"value": 2, "label": "2次"}], "default": vocab_config.get("translation_repeat_count", 1)},
                            {"name": "voice_gender", "label": "🎙️ 配音性别", "type": "select", "options": [{"value": "female", "label": "👩 女声"}, {"value": "male", "label": "👨 男声"}, {"value": "random", "label": "🎲 随机"}], "default": vocab_config.get("voice_gender", "random")},
                        ],
                        "submit_text": "✨ 确认并开始创作"
                    })
                    
                    return Command(
                        goto=END,
                        update={
                            "response_text": response_text,
                            "board_actions": board_actions,
                            "vocab_config": vocab_config,
                            "video_type": video_type,
                            "chat_stage": ChatStage.CONFIGURING,
                            "updated_at": datetime.now().isoformat(),
                        }
                    )
            else:
                # 未选择类型
                response_text = "请先选择创作类型～"
                board_actions.append({
                    "type": "select_options",
                    "message": "请选择创作类型：",
                    "options": [
                        {"id": "vocab_video", "label": "📚 英文单词视频", "value": "我要创作英文单词视频"},
                    ]
                })
                
                return Command(
                    goto=END,
                    update={
                        "response_text": response_text,
                        "board_actions": board_actions,
                        "vocab_config": vocab_config,
                        "video_type": video_type,
                        "chat_stage": ChatStage.INIT,
                        "updated_at": datetime.now().isoformat(),
                    }
                )
        
        # 默认结束
        return Command(
            goto=END,
            update={
                "response_text": response_text,
                "vocab_config": vocab_config,
                "video_type": video_type,
                "chat_stage": ChatStage.COMPLETED,
                "updated_at": datetime.now().isoformat(),
            }
        )
        
    except Exception as e:
        logger.error(f"[ChatSupervisor] 处理失败: {e}", exc_info=True)
        return Command(
            goto=END,
            update={
                "response_text": f"处理出错: {str(e)}",
                "vocab_config": vocab_config,
                "video_type": video_type,
                "chat_stage": ChatStage.FAILED,
            }
        )
