"""
对话调度层 Graph - 入口分发器

职责：
1. 接收用户消息
2. 根据 creation_type 分发到对应子图
3. 不负责具体业务逻辑

两种类型完全解耦：
- chat -> ChatGraph (使用 ChatState)
- chapter -> ComicDramaGraph (使用 ComicDramaState)
"""

from typing import Dict, Any
from langgraph.graph import StateGraph, END
from langgraph.checkpoint.memory import MemorySaver

from app.agent.state.schemas import ComicDramaState
from app.agent.state.chat_schemas import ChatState
from app.agent.graph.comic_drama_subgraph import build_comic_drama_subgraph
from app.agent.graph.chat_graph import build_chat_graph
from app.core.logger import logger


async def _entry_node(state: Dict[str, Any]) -> Dict[str, Any]:
    """
    入口节点
    
    确保关键字段被正确传递，防止被 checkpointer 覆盖
    """
    creation_type = state.get("creation_type", "chapter")
    user_message = state.get("user_message", "")
    video_type = state.get("video_type")
    logger.info(f"[DialogueGraph] _chat_executor 原始 state: video_type={video_type}, should_generate={state.get('should_generate')}")
    
    vocab_config = state.get("vocab_config", {})
    should_generate = state.get("should_generate", False)
    messages = state.get("messages", [])
    
    logger.info(f"[DialogueGraph] 收到消息: {user_message[:50]}...")
    logger.info(f"[DialogueGraph] entry_node: creation_type={creation_type}")
    
    # 显式返回所有关键字段
    return {
        "creation_type": creation_type,
        "user_message": user_message,
        "video_type": video_type,
        "vocab_config": vocab_config,
        "messages": messages,
        "should_generate": should_generate,
        "creation_uuid": state.get("creation_uuid", ""),
        "thread_id": state.get("thread_id", ""),
        "user_id": state.get("user_id", 0),
    }


def _route_by_type(state: Dict[str, Any]) -> str:
    """
    根据 creation_type 路由
    
    Returns:
        "chat" 或 "chapter"
    """
    creation_type = state.get("creation_type", "chapter")
    logger.info(f"[DialogueGraph] 路由: creation_type={creation_type}")
    return creation_type if creation_type == "chat" else "chapter"


async def _chat_executor(state: Dict[str, Any]) -> Dict[str, Any]:
    """
    Chat 类型执行器
    
    构建 ChatState 并调用 ChatGraph
    """
    logger.info("[DialogueGraph] 执行 ChatGraph")
    
    # 构建 ChatState
    user_message = state.get("user_message", "")
    creation_uuid = state.get("creation_uuid", "")
    vocab_config = state.get("vocab_config", {})
    should_generate = state.get("should_generate", False)
    # 确保 vocab_config 包含 creation_uuid
    if creation_uuid and "creation_uuid" not in vocab_config:
        vocab_config["creation_uuid"] = creation_uuid
    
    logger.info(f"[DialogueGraph] 构建 ChatState: video_type={state.get('video_type')}, vocab_config={vocab_config}, messages_count={len(state.get('messages', []))}")
    logger.info(f"[DialogueGraph] _chat_executor: should_generate={should_generate}, user_action={state.get('user_action')}")
    
    chat_state: ChatState = {
        "creation_uuid": creation_uuid,
        "thread_id": state.get("thread_id", ""),
        "user_id": state.get("user_id", 0),
        "user_message": user_message,
        "messages": state.get("messages", []),
        "video_type": state.get("video_type"),
        "vocab_config": vocab_config,
        "chat_stage": "init",
        "should_generate": should_generate,
        "next_node": state.get("next_worker"),  # 映射到 ChatState 的字段名
    }
    
    # 调用 ChatGraph
    chat_graph = build_chat_graph()
    result = await chat_graph.ainvoke(chat_state)
    
    # 转换回通用格式
    return {
        "response_text": result.get("response_text", ""),
        "vocab_config": result.get("vocab_config", {}),
        "video_type": result.get("video_type"),
        "should_generate": result.get("should_generate", False),
        "errors": result.get("errors", []),
        "creation_uuid": state.get("creation_uuid", ""),
        "thread_id": state.get("thread_id", ""),
        "user_id": state.get("user_id", 0),
    }


async def _chapter_executor(state: Dict[str, Any]) -> Dict[str, Any]:
    """
    Chapter 类型执行器
    
    构建 ComicDramaState 并调用 ComicDramaSubgraph
    """
    logger.info("[DialogueGraph] 执行 ComicDramaSubgraph")
    
    # 直接使用传入的 state（已经是 ComicDramaState 格式）
    comic_drama_subgraph = build_comic_drama_subgraph()
    result = await comic_drama_subgraph.ainvoke(state)
    
    return result


def build_dialogue_graph() -> StateGraph:
    """
    构建对话调度层 Graph
    
    极简流程：
    entry -> [chat_executor | chapter_executor] -> END
    """
    logger.info("[DialogueGraph] 构建对话调度层 Graph...")
    
    # 使用通用 Dict 类型，因为需要兼容两种 State
    workflow = StateGraph(Dict[str, Any])
    
    # 添加节点
    workflow.add_node("entry", _entry_node)
    workflow.add_node("chat_executor", _chat_executor)
    workflow.add_node("chapter_executor", _chapter_executor)
    
    # 设置入口
    workflow.set_entry_point("entry")
    
    # 条件路由
    workflow.add_conditional_edges(
        "entry",
        _route_by_type,
        {
            "chat": "chat_executor",
            "chapter": "chapter_executor",
        }
    )
    
    # 结束边
    workflow.add_edge("chat_executor", END)
    workflow.add_edge("chapter_executor", END)
    
    logger.info("[DialogueGraph] Graph 构建完成")
    return workflow


class DialogueGraphRunner:
    """
    对话调度层 Graph 执行器
    """
    
    def __init__(self, checkpointer=None):
        self.checkpointer = checkpointer or MemorySaver()
        self.graph = None
        self._compile()
    
    def _compile(self):
        """编译 Graph"""
        from app.core.config import settings
        workflow = build_dialogue_graph()
        self.graph = workflow.compile(checkpointer=self.checkpointer)
        recursion_limit = getattr(settings, 'LANGGRAPH_RECURSION_LIMIT', 25)
        self.graph.recursion_limit = recursion_limit
        logger.info(f"[DialogueGraph] Graph 已编译，递归限制: {recursion_limit}")
    
    async def invoke(self, state: Dict[str, Any], thread_id: str) -> Dict[str, Any]:
        """同步执行"""
        config = {"configurable": {"thread_id": thread_id}}
        result = await self.graph.ainvoke(state, config)
        return result
    
    async def stream_events(self, state: Dict[str, Any], thread_id: str):
        """流式执行"""
        config = {"configurable": {"thread_id": thread_id}}
        async for event in self.graph.astream_events(state, config, version="v2"):
            yield event
    
    def get_state(self, thread_id: str) -> Dict[str, Any]:
        """获取状态"""
        config = {"configurable": {"thread_id": thread_id}}
        return self.graph.get_state(config)
    
    def update_state(self, thread_id: str, updates: Dict[str, Any]):
        """更新状态"""
        config = {"configurable": {"thread_id": thread_id}}
        self.graph.update_state(config, updates)


# 全局实例
_dialogue_runner = None


def get_dialogue_runner() -> DialogueGraphRunner:
    """获取全局实例"""
    global _dialogue_runner
    if _dialogue_runner is None:
        _dialogue_runner = DialogueGraphRunner()
    return _dialogue_runner
