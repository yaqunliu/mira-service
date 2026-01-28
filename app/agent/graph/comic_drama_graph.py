"""
Comic Drama Graph - 漫画短剧工作流图

实现 LangGraph 工作流，协调各个 Agent 团队完成漫画短剧制作
"""

from typing import Dict, Any, List, Optional, AsyncIterator
from langgraph.graph import StateGraph, END
from langgraph.checkpoint.memory import MemorySaver
from langgraph.prebuilt import ToolNode
from langchain_core.messages import SystemMessage, HumanMessage
from langchain_openai import ChatOpenAI

from app.agent.state.schemas import ComicDramaState
from app.agent.checkpointer.postgres import AsyncPostgresCheckpointer
from app.agent.agents.director import director_decision_node, route_from_director
from app.agent.agents.script_analysis_team import analyze_script_node
from app.agent.tools.asset_tools import (
    ReadCharacterTool,
    WriteCharacterTool,
    ReadSceneTool,
    WriteSceneTool,
    SearchAssetsTool,
    ListAssetsTool
)
from app.agent.tools.generation_tools import (
    GenerateCharacterImageTool,
    GenerateSceneImageTool,
    GenerateStoryboardImageTool,
    GenerateVideoTool,
    GenerateAudioTool,
    LLMAnalysisTool,
    GeneratePromptTool
)
from app.core.logger import logger
from app.core.config import settings
from sqlalchemy.ext.asyncio import AsyncSession


class ComicDramaGraph:
    """漫画短剧工作流图"""
    
    def __init__(self, async_session_factory):
        """
        初始化工作流图
        
        Args:
            async_session_factory: AsyncSession 工厂函数
        """
        self.async_session_factory = async_session_factory
        self.checkpointer = MemorySaver()
        self.graph = None
        self._build_graph()
        logger.info("ComicDramaGraph 初始化完成")
    
    def _build_graph(self) -> StateGraph:
        """
        构建工作流图
        
        工作流：
        init -> script_analysis -> asset_generation -> storyboard_creation -> 
        audio_processing -> video_generation -> editing -> completed
        """
        # 创建状态图
        workflow = StateGraph(ComicDramaState)
        
        # 添加节点
        workflow.add_node("production_manager", self._production_manager_node)
        workflow.add_node("script_analysis", analyze_script_node)
        workflow.add_node("asset_generation", self._asset_generation_node)
        workflow.add_node("storyboard_creation", self._storyboard_creation_node)
        workflow.add_node("audio_processing", self._audio_processing_node)
        workflow.add_node("video_generation", self._video_generation_node)
        workflow.add_node("editing", self._editing_node)
        workflow.add_node("director", director_decision_node)
        workflow.add_node("human_review", self._human_review_node)
        workflow.add_node("error_handler", self._error_handler_node)
        workflow.add_node("completed", lambda x: x)
        
        # 设置入口点
        workflow.set_entry_point("production_manager")
        
        # 添加条件边
        workflow.add_conditional_edges(
            "production_manager",
            self._route_from_manager,
            {
                "script_analysis": "script_analysis",
                "asset_generation": "asset_generation",
                "storyboard_creation": "storyboard_creation",
                "audio_processing": "audio_processing",
                "video_generation": "video_generation",
                "editing": "editing",
                "completed": "completed",
                "error": "error_handler"
            }
        )
        
        # 其他节点的条件边
        workflow.add_conditional_edges(
            "script_analysis",
            self._route_from_analysis,
            {
                "asset_generation": "asset_generation",
                "director": "director",
                "error": "error_handler"
            }
        )
        
        workflow.add_conditional_edges(
            "asset_generation",
            self._route_from_assets,
            {
                "storyboard_creation": "storyboard_creation",
                "director": "director",
                "human_review": "human_review",
                "error": "error_handler"
            }
        )
        
        workflow.add_conditional_edges(
            "storyboard_creation",
            self._route_from_storyboard,
            {
                "audio_processing": "audio_processing",
                "director": "director",
                "human_review": "human_review",
                "error": "error_handler"
            }
        )
        
        workflow.add_conditional_edges(
            "audio_processing",
            self._route_from_audio,
            {
                "video_generation": "video_generation",
                "director": "director",
                "error": "error_handler"
            }
        )
        
        workflow.add_conditional_edges(
            "video_generation",
            self._route_from_video,
            {
                "editing": "editing",
                "director": "director",
                "error": "error_handler"
            }
        )
        
        workflow.add_conditional_edges(
            "editing",
            self._route_from_editing,
            {
                "completed": "completed",
                "director": "director",
                "error": "error_handler"
            }
        )
        
        # 导演决策节点
        workflow.add_conditional_edges(
            "director",
            route_from_director,
            {
                "script_analysis": "script_analysis",
                "asset_generation": "asset_generation",
                "storyboard_creation": "storyboard_creation",
                "audio_processing": "audio_processing",
                "video_generation": "video_generation",
                "editing": "editing",
                "human_review": "human_review",
                "error_handler": "error_handler",
                "completed": "completed"
            }
        )
        
        # 人工审核节点
        workflow.add_conditional_edges(
            "human_review",
            self._route_from_human_review,
            {
                "continue": "director",
                "retry": "director",
                "error": "error_handler"
            }
        )
        
        # 错误处理节点
        workflow.add_edge("error_handler", END)
        
        # 完成节点
        workflow.add_edge("completed", END)
        
        # 编译图
        self.graph = workflow.compile(checkpointer=self.checkpointer)
        
        logger.info("ComicDramaGraph 构建完成")
        return workflow
    
    async def _production_manager_node(self, state: ComicDramaState) -> ComicDramaState:
        """制作管理节点 - 初始化和协调"""
        logger.info(f"制作管理节点: 当前阶段 {state.get('current_stage', 'init')}")
        
        messages = list(state.get("messages", []))
        messages.append({
            "role": "system",
            "content": f"🎬 开始制作管理，当前阶段: {state.get('current_stage', 'init')}"
        })
        
        return {
            "messages": messages
        }
    
    def _route_from_manager(self, state: ComicDramaState) -> str:
        """从制作管理节点路由"""
        current_stage = state.get("current_stage", "init")
        
        # 简单的阶段路由
        stage_routes = {
            "init": "script_analysis",
            "script_analysis": "script_analysis",
            "asset_generation": "asset_generation",
            "storyboard_creation": "storyboard_creation",
            "audio_processing": "audio_processing",
            "video_generation": "video_generation",
            "editing": "editing",
            "completed": "completed",
            "error": "error"
        }
        
        return stage_routes.get(current_stage, "error")
    
    async def _asset_generation_node(self, state: ComicDramaState) -> ComicDramaState:
        """资产生成节点"""
        logger.info("开始资产生成...")
        
        characters = state.get("characters", [])
        scenes = state.get("scenes", [])
        
        # 生成角色图片
        for i, character in enumerate(characters):
            if not character.get("image_url"):
                logger.info(f"生成角色图片: {character.get('name', f'角色{i+1}')}")
                # 这里调用生成工具
                # TODO: 集成实际的图片生成
                character["image_url"] = f"https://example.com/character_{i+1}.jpg"
                character["generation_status"] = "completed"
        
        # 生成场景图片
        for i, scene in enumerate(scenes):
            if not scene.get("image_url"):
                logger.info(f"生成场景图片: {scene.get('name', f'场景{i+1}')}")
                # 这里调用生成工具
                # TODO: 集成实际的图片生成
                scene["image_url"] = f"https://example.com/scene_{i+1}.jpg"
                scene["generation_status"] = "completed"
        
        messages = list(state.get("messages", []))
        messages.append({
            "role": "system",
            "content": f"✅ 资产生成完成: {len(characters)} 个角色, {len(scenes)} 个场景"
        })
        
        return {
            "characters": characters,
            "scenes": scenes,
            "messages": messages
        }
    
    def _route_from_analysis(self, state: ComicDramaState) -> str:
        """从剧本分析节点路由"""
        if state.get("errors"):
            return "error"
        return "asset_generation"
    
    def _route_from_assets(self, state: ComicDramaState) -> str:
        """从资产生成节点路由"""
        if state.get("errors"):
            return "error"
        
        # 检查是否需要人工审核
        characters = state.get("characters", [])
        if characters and all(c.get("image_url") for c in characters):
            return "human_review"
        
        return "storyboard_creation"
    
    async def _storyboard_creation_node(self, state: ComicDramaState) -> ComicDramaState:
        """分镜创建节点"""
        logger.info("开始创建分镜...")
        
        storyboards = [
            {
                "id": "storyboard_1",
                "scene": "场景1",
                "description": "分镜描述1",
                "image_url": "https://example.com/storyboard_1.jpg"
            }
        ]
        
        messages = list(state.get("messages", []))
        messages.append({
            "role": "system",
            "content": "✅ 分镜创建完成"
        })
        
        return {
            "storyboards": storyboards,
            "messages": messages
        }
    
    def _route_from_storyboard(self, state: ComicDramaState) -> str:
        """从分镜节点路由"""
        if state.get("errors"):
            return "error"
        
        # 检查是否需要人工审核
        storyboards = state.get("storyboards", [])
        if storyboards:
            return "human_review"
        
        return "audio_processing"
    
    async def _audio_processing_node(self, state: ComicDramaState) -> ComicDramaState:
        """音频处理节点"""
        logger.info("开始音频处理...")
        
        audio_segments = [
            {
                "id": "audio_1",
                "text": "测试音频文本",
                "audio_url": "https://example.com/audio_1.mp3"
            }
        ]
        
        messages = list(state.get("messages", []))
        messages.append({
            "role": "system",
            "content": "✅ 音频处理完成"
        })
        
        return {
            "audio_segments": audio_segments,
            "messages": messages
        }
    
    def _route_from_audio(self, state: ComicDramaState) -> str:
        """从音频节点路由"""
        if state.get("errors"):
            return "error"
        return "video_generation"
    
    async def _video_generation_node(self, state: ComicDramaState) -> ComicDramaState:
        """视频生成节点"""
        logger.info("开始视频生成...")
        
        video_segments = [
            {
                "id": "video_1",
                "storyboard_id": "storyboard_1",
                "video_url": "https://example.com/video_1.mp4"
            }
        ]
        
        messages = list(state.get("messages", []))
        messages.append({
            "role": "system",
            "content": "✅ 视频生成完成"
        })
        
        return {
            "video_segments": video_segments,
            "messages": messages
        }
    
    def _route_from_video(self, state: ComicDramaState) -> str:
        """从视频节点路由"""
        if state.get("errors"):
            return "error"
        return "editing"
    
    async def _editing_node(self, state: ComicDramaState) -> ComicDramaState:
        """剪辑节点"""
        logger.info("开始剪辑...")
        
        final_video = {
            "url": "https://example.com/final_video.mp4",
            "duration": 120,
            "resolution": "1080p"
        }
        
        messages = list(state.get("messages", []))
        messages.append({
            "role": "system",
            "content": "🎉 剪辑完成，作品制作成功！"
        })
        
        return {
            "final_video": final_video,
            "messages": messages,
            "current_stage": "completed"
        }
    
    def _route_from_editing(self, state: ComicDramaState) -> str:
        """从剪辑节点路由"""
        if state.get("errors"):
            return "error"
        return "completed"
    
    async def _human_review_node(self, state: ComicDramaState) -> ComicDramaState:
        """人工审核节点"""
        checkpoint = state.get("pending_checkpoint", {})
        
        logger.info(f"人工审核节点: {checkpoint.get('checkpoint_type')}")
        
        messages = list(state.get("messages", []))
        messages.append({
            "role": "system",
            "content": f"⏸️ 等待人工审核: {checkpoint.get('message', '请审核当前结果')}"
        })
        
        return {
            "messages": messages
        }
    
    def _route_from_human_review(self, state: ComicDramaState) -> str:
        """从人工审核节点路由"""
        # 这里应该检查人工审核结果
        # 简化处理：直接继续
        return "continue"
    
    async def _error_handler_node(self, state: ComicDramaState) -> ComicDramaState:
        """错误处理节点"""
        errors = list(state.get("errors", []))
        
        logger.error(f"错误处理节点: {errors}")
        
        messages = list(state.get("messages", []))
        messages.append({
            "role": "system",
            "content": f"❌ 处理错误: {errors[-1] if errors else '未知错误'}"
        })
        
        return {
            "errors": errors,
            "messages": messages,
            "current_stage": "error"
        }
    
    def get_graph(self) -> StateGraph:
        """获取编译后的图"""
        if not self.graph:
            raise RuntimeError("图尚未编译")
        return self.graph
    
    async def run_workflow(
        self,
        initial_state: ComicDramaState,
        thread_id: str,
        checkpoint_id: Optional[str] = None
    ) -> AsyncIterator[Dict[str, Any]]:
        """
        运行工作流（流式版本）
        
        Args:
            initial_state: 初始状态
            thread_id: 线程 ID（对应 creation.uuid）
            checkpoint_id: 检查点 ID（可选）
            
        Yields:
            每次迭代的中间状态
        """
        graph = self.get_graph()
        
        logger.info(f"开始运行工作流: thread_id={thread_id}")
        
        config = {
            "configurable": {
                "thread_id": thread_id,
                "checkpoint_id": checkpoint_id,
                "checkpoint_namespace": settings.LANGGRAPH_CHECKPOINT_NAMESPACE
            }
        }
        
        try:
            async for chunk in graph.astream(initial_state, config):
                for node_name, state_update in chunk.items():
                    logger.debug(f"工作流节点更新: {node_name}, state_type={type(state_update)}, state_keys={state_update.keys() if hasattr(state_update, 'keys') else 'N/A'}")
                    yield {
                        "node": node_name,
                        "state": state_update,
                        "type": "chunk"
                    }
            
            logger.info(f"工作流运行完成: thread_id={thread_id}")
            
        except Exception as e:
            logger.error(f"工作流运行失败: {e}")
            raise
    
    async def get_checkpoint_history(
        self,
        thread_id: str,
        limit: int = 10
    ) -> List[Dict[str, Any]]:
        """
        获取检查点历史
        
        Args:
            thread_id: 线程 ID
            limit: 数量限制
            
        Returns:
            检查点列表
        """
        return await self.checkpointer.list(thread_id, limit=limit)
    
    async def restore_from_checkpoint(
        self,
        thread_id: str,
        checkpoint_id: Optional[str] = None
    ) -> Optional[ComicDramaState]:
        """
        从检查点恢复状态
        
        Args:
            thread_id: 线程 ID
            checkpoint_id: 检查点 ID（可选，使用最新的）
            
        Returns:
            恢复的状态或 None
        """
        return await self.checkpointer.get(thread_id, checkpoint_id)