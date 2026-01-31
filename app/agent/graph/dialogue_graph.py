"""
对话调度层 Graph

双层架构的主图，处理用户对话并调度业务执行层
"""

from typing import Dict, Any, Literal
from langgraph.graph import StateGraph, END
from langgraph.checkpoint.memory import MemorySaver

from app.agent.state.schemas import ComicDramaState
from app.agent.graph.nodes import (
    entry_node,
    intent_detection_node,
    router_node,
    status_query_node,
    clarify_node,
    response_formatter_node,
    human_review_node,
)
from app.agent.graph.comic_drama_subgraph import build_comic_drama_subgraph
from app.core.logger import logger


# 路由目标类型
RouterTarget = Literal["status_query", "task_execution", "clarify", "response_formatter", "end"]


def build_dialogue_graph() -> StateGraph:
    """
    构建对话调度层 Graph
    
    流程：
    entry → intent_detection → router → [status_query | task_execution | clarify]
                                                      ↓
                                             response_formatter → [human_review | end]
    
    Returns:
        编译后的 StateGraph
    """
    logger.info("[DialogueGraph] 构建对话调度层 Graph...")
    
    # 创建状态图
    workflow = StateGraph(ComicDramaState)
    
    # ==================== 添加节点 ====================
    
    # 入口节点
    workflow.add_node("entry", entry_node)
    
    # 意图识别节点
    workflow.add_node("intent_detection", intent_detection_node)
    
    # 路由节点（纯逻辑，不改状态）
    # 注意：router_node 返回目标节点名称，用作条件边
    
    # 处理节点
    workflow.add_node("status_query", status_query_node)
    
    # task_execution 使用子图而不是普通节点
    comic_drama_subgraph = build_comic_drama_subgraph()
    workflow.add_node("task_execution", comic_drama_subgraph)
    
    workflow.add_node("clarify", clarify_node)
    
    # 输出节点
    workflow.add_node("response_formatter", response_formatter_node)
    workflow.add_node("human_review", human_review_node)
    
    # ==================== 设置边 ====================
    
    # 入口点
    workflow.set_entry_point("entry")
    
    # entry → intent_detection
    workflow.add_edge("entry", "intent_detection")
    
    # intent_detection → router (条件边)
    workflow.add_conditional_edges(
        "intent_detection",
        _route_by_intent,
        {
            "status_query": "status_query",
            "task_execution": "task_execution",
            "clarify": "clarify",
        }
    )
    
    # 处理节点 → response_formatter
    workflow.add_edge("status_query", "response_formatter")
    workflow.add_edge("task_execution", "response_formatter")
    workflow.add_edge("clarify", "response_formatter")
    
    # response_formatter → [human_review | end]
    workflow.add_conditional_edges(
        "response_formatter",
        _route_after_response,
        {
            "human_review": "human_review",
            "end": END,
        }
    )
    
    # human_review → end
    workflow.add_edge("human_review", END)
    
    logger.info("[DialogueGraph] Graph 构建完成")
    return workflow


def _route_by_intent(state: ComicDramaState) -> str:
    """
    根据意图分类路由到对应节点
    
    使用 router_node 的逻辑
    """
    return router_node(state)


def _route_after_response(state: ComicDramaState) -> str:
    """
    响应格式化后路由
    
    如果需要人工确认则进入 human_review，否则结束
    """
    if state.get("pending_approval"):
        return "human_review"
    return "end"


class DialogueGraphRunner:
    """
    对话调度层 Graph 执行器
    
    封装 StateGraph 的编译和执行
    """
    
    def __init__(self, checkpointer=None):
        """
        初始化执行器
        
        Args:
            checkpointer: LangGraph checkpointer（可选）
        """
        self.checkpointer = checkpointer or MemorySaver()
        self.graph = None
        self._compile()
    
    def _compile(self):
        """编译 Graph"""
        workflow = build_dialogue_graph()
        self.graph = workflow.compile(checkpointer=self.checkpointer)
        logger.info("[DialogueGraph] Graph 已编译")
    
    async def invoke(
        self,
        state: Dict[str, Any],
        thread_id: str,
    ) -> Dict[str, Any]:
        """
        同步执行 Graph
        
        Args:
            state: 初始状态
            thread_id: 线程 ID（用于 checkpointer）
            
        Returns:
            最终状态
        """
        config = {"configurable": {"thread_id": thread_id}}
        result = await self.graph.ainvoke(state, config)
        return result
    
    async def stream(
        self,
        state: Dict[str, Any],
        thread_id: str,
    ):
        """
        流式执行 Graph
        
        Args:
            state: 初始状态
            thread_id: 线程 ID
            
        Yields:
            每个节点的输出事件
        """
        config = {"configurable": {"thread_id": thread_id}}
        
        async for event in self.graph.astream(state, config, stream_mode="updates"):
            yield event
    
    async def stream_events(
        self,
        state: Dict[str, Any],
        thread_id: str,
    ):
        """
        流式输出事件（包含 LLM token 级别）
        
        Args:
            state: 初始状态
            thread_id: 线程 ID
            
        Yields:
            详细事件流（适合前端 SSE）
        """
        config = {"configurable": {"thread_id": thread_id}}
        
        async for event in self.graph.astream_events(state, config, version="v2"):
            yield event
    
    def get_state(self, thread_id: str) -> Dict[str, Any]:
        """获取指定线程的当前状态"""
        config = {"configurable": {"thread_id": thread_id}}
        return self.graph.get_state(config)
    
    def update_state(self, thread_id: str, updates: Dict[str, Any]):
        """更新指定线程的状态"""
        config = {"configurable": {"thread_id": thread_id}}
        self.graph.update_state(config, updates)


# 全局实例（懒加载）
_dialogue_runner: DialogueGraphRunner = None


def get_dialogue_runner() -> DialogueGraphRunner:
    """获取全局 DialogueGraphRunner 实例"""
    global _dialogue_runner
    if _dialogue_runner is None:
        _dialogue_runner = DialogueGraphRunner()
    return _dialogue_runner
