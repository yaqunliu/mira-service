"""
Chat Supervisor Agent - 使用 LangGraph 官方 create_react_agent

Agent 自动理解用户消息，决定调用什么工具：
- ask_video_type: 让用户选择视频类型
- ask_vocab_config: 让用户填写单词视频参数
- save_vocab_params: 保存参数
- generate_video: 生成视频
- query_status: 查询状态
"""

from typing import Dict, Any, List, Optional
from langgraph.prebuilt import create_react_agent
from langchain_openai import ChatOpenAI
from langchain_core.tools import tool

from app.core.logger import logger
from app.core.config import settings
from app.agent.graph.nodes.chat_supervisor_tools import get_chat_supervisor_tools


class ChatSupervisorAgent:
    """
    Chat Supervisor Agent
    
    使用 create_react_agent，让 LLM 自动决定如何响应用户
    """
    
    SYSTEM_PROMPT = """你是智能视频创作助手，帮助用户创建三类视频：
1. 单词视频(vocab_video) - 英语单词教学视频
2. 搞笑短视频(gaoxiao_video) - 有趣的搞笑内容  
3. 故事动画视频(story_video) - 将故事变成动画

## 当前状态信息
- 任务ID：{creation_uuid}
- 视频类型：{video_type}
- 当前参数：{vocab_config}
- 用户已确认生成：{should_generate}

## 重要：通信模式说明
**本对话使用 SSE（Server-Sent Events）长连接，是同步模式**：
- 用户点击"确认生成"后，连接会保持打开状态
- 在视频生成过程中（通常需要几分钟），用户**无法发送新消息**
- 系统会通过同一连接持续推送进度更新
- 因此，一旦开始生成，你**不应该**问用户问题或期待回复
- 生成完成后，连接会自动关闭，用户才能继续对话

## 工具使用指南（必须严格遵守）

### 1. ask_video_type 工具
**用途**：让用户选择要创建的视频类型
**调用时机**：
- 用户首次进入对话，还没有选择视频类型时（video_type为空）
- 用户明确说"我想换一种类型"或"重新开始"
**禁止**：用户已经选择过类型后，不要重复调用

### 2. set_video_type 工具
**用途**：保存用户选择的视频类型到系统
**调用时机**：
- 用户明确选择了视频类型后，必须立即调用
- 参数：video_type必须是 "vocab_video"、"gaoxiao_video" 或 "story_video"
**重要**：这是保存类型的唯一方式，必须通过工具调用

### 3. ask_vocab_config 工具
**用途**：显示单词视频参数配置卡片，让用户填写
**调用时机**：
- 用户选择了"单词视频"类型后，且还没有填写参数（vocab_config为空或words为空）
- 用户说"修改参数"、"重新配置"等
**禁止**：参数已经齐全且用户已确认生成后，不要再显示配置卡片

### 4. save_vocab_params 工具
**用途**：保存用户填写的单词视频参数
**调用时机**：
- 用户在配置卡片中填写/修改参数后，必须调用此工具保存
- 参数包括：words(单词列表)、difficulty(难度)、word_repeat(重复次数)、translation_repeat(翻译重复次数)、voice_gender(配音性别)
**重要**：
- 所有参数变化都必须通过此工具保存
- **此工具只保存参数，不会显示确认卡片**
- 保存成功后，你需要单独调用 ask_confirm_generation 显示确认按钮

### 5. ask_confirm_generation 工具
**用途**：显示"确认生成视频"按钮卡片
**调用时机**（必须同时满足）：
- 参数已经齐全（对于单词视频：words不为空）
- 用户还没有确认生成（should_generate=False）
- 视频还没有开始生成（状态不是 generating/processing/exporting/completed）
**禁止**：
- 用户已经确认生成后（should_generate=True），不要再显示确认卡片
- 视频已经开始生成后，不要再显示确认卡片

### 6. query_creation_status 工具
**用途**：查询当前任务的最新状态
**调用时机**：
- 用户问"视频生成好了吗"、"进度如何"等
- 用户已确认生成（should_generate=True）后，需要查询当前状态
- 不确定视频是否已完成时

### 7. reset_and_restart_video 工具
**用途**：重置失败的视频生成任务并重新开始
**调用时机**：
- 用户问"视频是不是生成失败了"、"重新生成"、"再试一次"等
- 查询状态后发现是 failed 或长时间停留在某个步骤没有进展
- **注意**：只有确认视频确实失败时才调用此工具
**重要**：此工具会将状态重置为 pending 并返回 needs_restart=True，你需要将此作为 next_node="vocab_worker" 的条件

## 工作流程（严格按顺序）

### 阶段1：选择类型
1. 新用户 → 调用 ask_video_type 显示类型选择
2. 用户选择类型 → 调用 set_video_type 保存类型

### 阶段2：收集参数（以单词视频为例）
3. 类型为 vocab_video 且 vocab_config 为空 → 调用 ask_vocab_config 显示配置卡片
4. 用户填写参数 → 调用 save_vocab_params 保存参数
5. 保存成功后 → 调用 ask_confirm_generation 显示确认按钮

### 阶段3：确认生成
6. 用户点击确认 → should_generate 变为 True

### 阶段4：开始生成（关键！）
7. should_generate=True → **先调用 query_creation_status 查询状态**
8. **如果状态是 pending**（未开始）：
   - 告知用户"视频开始生成，请稍候..."
   - 返回 next_node="vocab_worker" 让系统调度到 Worker
   - **重要**：不要问用户问题，因为用户此时无法回复
9. **如果状态是 generating/processing/exporting**：
   - 告知用户"视频正在生成中，进度 X%..."
   - 返回 next_node="vocab_worker"
10. **如果状态是 completed**：
    - 告知用户"视频已完成！"
    - 提供视频链接
    - 不要调度到 Worker

## 关键判断规则

### 什么时候说"视频开始生成"？
- 仅当 should_generate=True 且查询状态为 pending
- 回复应该是："视频开始生成，请稍候..."（陈述句，不问问题）

### 什么时候说"视频正在生成中"？
- 仅当 should_generate=True 且查询状态为 generating/processing/exporting
- 回复应该是："视频正在生成中，进度 X%...预计还需要几分钟"（陈述句，不问问题）

### 什么时候显示确认卡片？
- 仅当参数齐全、should_generate=False、状态为 pending
- 必须调用 ask_confirm_generation 工具

### 什么时候告诉用户视频已完成？
- 查询状态为 completed 且有 video_url
- 回复视频链接

### 什么时候调用 reset_and_restart_video？
- 查询状态为 failed（生成失败）
- 用户问"视频是不是生成失败了"、"重新生成"、"再试一次"等
- 调用此工具后会重置状态为 pending 并返回 needs_restart=True，你需要设置 next_node="vocab_worker"

## 禁止事项（违反会导致严重问题）
- **禁止在 should_generate=True 后还显示确认卡片**
- **禁止在视频开始生成后说"视频已成功创建"**（应该说"正在生成中"）
- **禁止在生成期间问用户问题**（如"需要我稍后提醒吗"）- 用户无法回复
- **禁止重复调用相同工具（如连续多次显示配置卡片）**
- **禁止让用户修改已经开始生成的视频的参数**
- **creation_uuid 必须使用系统提供的，禁止自己生成**

## 回复风格
- 简洁友好，每次回复不超过3句话
- 明确告诉用户当前处于哪个阶段
- **生成期间使用陈述句，不要问问题**"""
    
    def __init__(self):
        self.llm = ChatOpenAI(
            model=settings.LLM_MODEL_DEFAULT,
            temperature=0.3,
        )
        self.agent = None
        self.creation_uuid = ""
        self.video_type = ""
        self.vocab_config = {}
        self.history_messages = []
        self.should_generate = False

    @property
    def _current_system_prompt(self) -> str:
        """获取当前格式化后的 system prompt"""
        return self.SYSTEM_PROMPT.format(
            creation_uuid=self.creation_uuid or "未知",
            video_type=self.video_type or "未选择",
            vocab_config=str(self.vocab_config) if self.vocab_config else "无",
            should_generate=str(self.should_generate)
        )
        
    def _create_agent(self):
        """创建 Agent"""
        if self.agent:
            return self.agent
            
        # 从工具模块获取 Tools
        tools = get_chat_supervisor_tools()
        
        # 使用固定的 system prompt（会在 invoke 时覆盖）
        chat_system_prompt = self._current_system_prompt
        
        self.agent = create_react_agent(
            model=self.llm,
            tools=tools,
            prompt=chat_system_prompt,
        )
        
        return self.agent
    
    def get_tools(self):
        """获取工具列表"""
        return get_chat_supervisor_tools()
    
    async def invoke(self, state: Dict[str, Any]) -> Dict[str, Any]:
        """
        执行 Agent
        
        Args:
            state: 包含 user_message, video_type, vocab_config, messages 等
        
        Returns:
            更新后的 state
        """
        user_message = state.get("user_message", "")
        video_type = state.get("video_type")
        vocab_config = state.get("vocab_config", {})
        history_messages = state.get("messages", [])
        user_id = state.get("user_id", 1)
        creation_uuid = state.get("creation_uuid", "")
        # 从 state 获取 should_generate（当用户点击确认按钮时设置）
        should_generate = state.get("should_generate", False)
        
        # 设置实例变量，供 Agent 使用
        self.creation_uuid = creation_uuid
        self.video_type = video_type or ""
        self.vocab_config = vocab_config or {}
        self.history_messages = history_messages
        self.should_generate = should_generate
        logger.info(f"[ChatSupervisor] 处理消息: {user_message[:100]}...")
        logger.info(f"[ChatSupervisor] 当前状态: video_type={video_type}, vocab_config={vocab_config}, user_id={user_id}, 历史消息数={len(history_messages)}")
        
        try:
            agent = self._create_agent()
            
            # 构建消息列表
            messages = []
            
            # 添加系统提示词
            # 最近的10条历史消息（只取 user 和 assistant 的对话）
            recent_messages = history_messages[-10:] if history_messages else []
            
            # 添加历史消息到上下文
            # 构建 history context
            history_context = ""
            if recent_messages:
                history_lines = []
                for msg in recent_messages:
                    role = msg.get("role", "unknown")
                    content = msg.get("content", "")
                    if content:
                        history_lines.append(f"{role}: {content[:100]}")
                if history_lines:
                    history_context = "对话历史：\n" + "\n".join(history_lines) + "\n\n"
            
            # 添加 system prompt（包含当前状态和历史）
            full_prompt = self._current_system_prompt + "\n\n" + history_context
            messages.append(("system", full_prompt))
            
            # 简化 user_content，只包含用户消息
            
            # 构建用户消息，包含当前状态信息
            status_info = []
            if should_generate:
                status_info.append("【状态：用户已确认生成，正在处理中...】")
            elif vocab_config and vocab_config.get("words"):
                status_info.append("【状态：参数已齐全，等待用户确认生成】")
            
            user_content = f"用户消息：{user_message}"
            if status_info:
                user_content += "\n" + "\n".join(status_info)
            
            messages.append(("user", user_content))
            
            # 调用 Agent
            result = await agent.ainvoke({"messages": messages})
            
            # 提取响应
            response_messages = result.get("messages", [])
            
            # 初始化结果状态
            result_state = {}
            
            # 收集所有响应和工具调用
            response_text = ""
            board_actions = []
            
            # 处理工具返回的参数
            for msg in response_messages:
                # 提取 AI 的最终响应
                if hasattr(msg, "type") and msg.type == "ai":
                    if hasattr(msg, "content") and msg.content:
                        response_text = msg.content
                
                # 处理工具返回结果
                if hasattr(msg, "type") and msg.type == "tool":
                    try:
                        tool_result = msg.content
                        if isinstance(tool_result, str):
                            import json
                            import re
                            match = re.search(r'\{[\s\S]*\}', tool_result)
                            if match:
                                tool_result = json.loads(match.group())
                        
                        if isinstance(tool_result, dict):
                            # 提取 board_actions
                            if "board_actions" in tool_result:
                                board_actions.extend(tool_result["board_actions"])
                            # 提取文本响应
                            if "response_text" in tool_result and not response_text:
                                response_text = tool_result["response_text"]
                            # 提取 params 并更新 vocab_config
                            if "params" in tool_result:
                                vocab_config = tool_result["params"]
                                # 添加必要信息
                                vocab_config["user_id"] = user_id
                                vocab_config["creation_uuid"] = creation_uuid
                                logger.info(f"[ChatSupervisor] 更新 vocab_config: {vocab_config}")
                            
                            # 提取 video_type
                            if "video_type" in tool_result:
                                video_type = tool_result["video_type"]
                                logger.info(f"[ChatSupervisor] 更新 video_type: {video_type}")
                            
                            # 提取 task_id 和 creation_id
                            if "task_id" in tool_result:
                                result_state["task_id"] = tool_result["task_id"]
                                logger.info(f"[ChatSupervisor] 更新 task_id: {tool_result['task_id']}")
                            if "creation_id" in tool_result:
                                result_state["creation_id"] = tool_result["creation_id"]
                                logger.info(f"[ChatSupervisor] 更新 creation_id: {tool_result['creation_id']}")
                            
                            # 提取 needs_restart（重置并重新开始）
                            if tool_result.get("needs_restart"):
                                should_generate = True  # 设置为 True 以便重新调度到 Worker
                                logger.info(f"[ChatSupervisor] 检测到 needs_restart=True，设置 should_generate=True")
                    except Exception as e:
                        logger.warning(f"[ChatSupervisor] 解析工具结果失败: {e}")
            
            logger.info(f"[ChatSupervisor] 响应: {response_text[:200] if response_text else '无'}")
            
            # 如果 should_generate=True（用户已确认），清空 board_actions
            if should_generate:
                board_actions = []
                logger.info("[ChatSupervisor] should_generate=True，清空 board_actions")
            
            logger.info(f"[ChatSupervisor] board_actions 数量: {len(board_actions)}")
            
            # 确定 next_node
            next_node = None
            logger.info(f"[ChatSupervisor] 确定 next_node: should_generate={should_generate}, video_type={video_type}")
            
            # 如果 should_generate=True，直接调度到 Worker
            # 如果是单词视频但没有 vocab_config，自动显示配置卡片
            if video_type == "vocab_video" and not vocab_config.get("words"):
                # 需要调用 ask_vocab_config
                from app.agent.graph.nodes.chat_supervisor_tools import ask_vocab_config
                config_result = await ask_vocab_config.ainvoke({})
                board_actions = config_result.get("board_actions", [])
                response_text = config_result.get("response_text", "请填写单词视频参数")
                logger.info(f"[ChatSupervisor] 自动显示 vocab 配置卡片")
            
            if should_generate and video_type == "vocab_video":
                # 先检查数据库状态，如果已完成或正在生成就不调度
                from sqlalchemy import select
                from app.db.base import _get_async_session_factory
                from app.models.creation import Creation
                
                creation_uuid = state.get("creation_uuid")
                if creation_uuid:
                    try:
                        db = _get_async_session_factory()()
                        try:
                            result = await db.execute(
                                select(Creation).where(Creation.uuid == creation_uuid)
                            )
                            creation = result.scalar_one_or_none()
                            # 如果状态是 completed/exporting/generating/processing，说明正在处理中，不需要调度
                            if creation and creation.status in ["completed", "exporting", "generating", "processing"]:
                                extra = creation.extra_data or {}
                                video_url = extra.get("video_url") or getattr(creation, "video_url", "")
                                if video_url or creation.status == "completed":
                                    # 视频已完成，不需要调度
                                    logger.info(f"[ChatSupervisor] 视频已完成，status={creation.status}，video_url={video_url}，不需要再调度")
                                    should_generate = False  # 清除标记
                                else:
                                    # 视频正在生成中，不需要调度，直接返回进度信息
                                    logger.info(f"[ChatSupervisor] 视频正在生成中，status={creation.status}，不需要再调度")
                                    should_generate = False  # 清除标记
                            else:
                                # 状态是 pending 或其他，需要开始生成
                                next_node = "vocab_worker"
                                logger.info(f"[ChatSupervisor] 调度到: {next_node}")
                        finally:
                            await db.close()
                    except Exception as e:
                        logger.error(f"[ChatSupervisor] 查询状态失败: {e}")
                        next_node = "vocab_worker"
                else:
                    next_node = "vocab_worker"
                    logger.info(f"[ChatSupervisor] 调度到: {next_node}")
            # 合并 result_state 到返回结果
            return_result = {
                "response_text": response_text or "收到你的消息了",
                "board_actions": board_actions,
                "video_type": video_type,
                "vocab_config": vocab_config,
                "next_node": next_node,
                "should_generate": should_generate,  # 确保返回 should_generate
            }
            return_result.update(result_state)
            logger.info(f"[ChatSupervisor] 返回结果: next_node={next_node}, should_generate={should_generate}, keys={return_result.keys()}")
            return return_result
            
        except Exception as e:
            logger.error(f"[ChatSupervisor] 错误: {e}", exc_info=True)
            return {
                "response_text": f"处理出错: {str(e)}",
                "board_actions": [],
                "video_type": video_type,
                "vocab_config": vocab_config,
            }


# 全局实例
_chat_supervisor_agent = None

def get_chat_supervisor_agent() -> ChatSupervisorAgent:
    """获取 Chat Supervisor Agent 实例"""
    global _chat_supervisor_agent
    if _chat_supervisor_agent is None:
        _chat_supervisor_agent = ChatSupervisorAgent()
    return _chat_supervisor_agent
