"""
Comic Drama Subgraph - 漫剧业务执行子图

作为 DialogueGraph 的嵌套子图，负责实际的业务执行逻辑。

架构：Supervisor Agent 模式
- stage_router: 入口节点，加载创作数据
- supervisor: 决策中心，单次 LLM 决策
- workers: 执行具体任务，完成后回到 supervisor
- 递归由 LangGraph 统一管理（recursion_limit）
"""

from typing import Dict, Any, List
from langgraph.graph import StateGraph, END

from app.agent.state.schemas import ComicDramaState, ProductionStage
from app.core.logger import logger
from app.core.config import settings



# ==================== 辅助函数 ====================


def _infer_stage_from_data(data: dict) -> ProductionStage:
    """根据已有数据推断当前阶段"""
    if data.get("final_video_url"):
        return ProductionStage.COMPLETED
    if data.get("shots") and all(s.get("video_url") for s in data.get("shots", [])):
        return ProductionStage.VIDEO_READY
    # 分镜图片全部生成完成
    if data.get("shots") and all(s.get("image_url") for s in data.get("shots", [])):
        return ProductionStage.STORYBOARD_READY
    # 有分镜但图片未全部生成
    if data.get("shots"):
        return ProductionStage.STORYBOARD_GENERATING
    
    # 检查角色和场景是否都有图片
    characters = data.get("characters", [])
    scenes = data.get("scenes", [])
    if characters and scenes:
        # 检查是否所有角色和场景都有图片
        chars_have_images = all(c.get("image_url") for c in characters)
        scenes_have_images = all(s.get("image_url") for s in scenes)
        if chars_have_images and scenes_have_images:
            return ProductionStage.ASSETS_READY
        else:
            # 有角色和场景但图片未全部生成，处于已分析状态
            return ProductionStage.SCRIPT_ANALYZED
    
    if data.get("script_text"):
        return ProductionStage.SCRIPT_UPLOADED
    return ProductionStage.INIT



# ==================== 节点函数 ====================

async def stage_router_node(state: ComicDramaState) -> Dict[str, Any]:
    """
    阶段路由节点 - 子图入口
    
    职责：
    1. 检查是否需要直接返回（needs_input, errors）
    2. 初始化 production_progress（仅首次）
    3. 从数据库加载创作数据（如果 state 中不存在）
    """
    logger.info("[SubgraphNode] stage_router: 子图入口")
    
    # 检查是否需要立即返回（避免循环）
    if state.get("needs_input"):
        logger.info("[SubgraphNode] stage_router: 检测到 needs_input=True，跳过")
        return {}  # 不做任何更改，让 route_by_production_stage 处理
    
    if state.get("errors"):
        logger.info("[SubgraphNode] stage_router: 检测到 errors，跳过")
        return {}
    
    creation_uuid = state.get("creation_uuid")
    
    # 1. 初始化 production_progress（使用与 STAGE_ORDER 一致的 key）
    # 仅当不存在时才初始化
    existing_progress = state.get("production_progress")
    if not existing_progress:
        production_progress = {
            "script_analysis": {"status": "pending"},
            "asset_generation": {"status": "pending"},
            "storyboard_creation": {"status": "pending"},
            "audio_processing": {"status": "pending"},
            "video_generation": {"status": "pending"},
            "editing": {"status": "pending"},
        }
    else:
        production_progress = existing_progress
    
    result = {
        "production_progress": production_progress,
    }
    
    # 2. 从数据库加载创作数据（如果 state 中不存在）
    if creation_uuid and not state.get("script_text"):
        try:
            from app.agent.tools.db_tools import query_creation_data
            
            creation_data = await query_creation_data(creation_uuid)
            if creation_data:
                inferred_stage = _infer_stage_from_data(creation_data)
                
                # 根据推断的阶段同步更新 production_progress
                # 确保已完成阶段的状态正确设置
                # STORYBOARD_GENERATING 表示有分镜但图片未完成，此时脚本分析和资产生成已完成
                if inferred_stage in [ProductionStage.SCRIPT_ANALYZED, ProductionStage.ASSETS_READY,
                                     ProductionStage.STORYBOARD_GENERATING, ProductionStage.STORYBOARD_READY,
                                     ProductionStage.AUDIO_READY, ProductionStage.VIDEO_READY, ProductionStage.COMPLETED]:
                    # 脚本分析已完成
                    production_progress["script_analysis"] = {
                        "status": "completed",
                        "characters": len(creation_data.get("characters", [])),
                        "scenes": len(creation_data.get("scenes", [])),
                    }
                    
                if inferred_stage in [ProductionStage.ASSETS_READY, ProductionStage.STORYBOARD_GENERATING,
                                     ProductionStage.STORYBOARD_READY, ProductionStage.AUDIO_READY,
                                     ProductionStage.VIDEO_READY, ProductionStage.COMPLETED]:
                    # 资产生成已完成
                    production_progress["asset_generation"] = {"status": "completed"}
                    
                if inferred_stage in [ProductionStage.STORYBOARD_READY, ProductionStage.AUDIO_READY,
                                     ProductionStage.VIDEO_READY, ProductionStage.COMPLETED]:
                    # 分镜创建已完成
                    production_progress["storyboard_creation"] = {
                        "status": "completed",
                        "shots": len(creation_data.get("shots", [])),
                    }
                
                if inferred_stage in [ProductionStage.AUDIO_READY, ProductionStage.VIDEO_READY,
                                     ProductionStage.COMPLETED]:
                    production_progress["audio_processing"] = {"status": "completed"}
                
                if inferred_stage in [ProductionStage.VIDEO_READY, ProductionStage.COMPLETED]:
                    production_progress["video_generation"] = {"status": "completed"}
                
                if inferred_stage == ProductionStage.COMPLETED:
                    production_progress["editing"] = {"status": "completed"}
                
                result.update({
                    "script_text": creation_data.get("script_text"),
                    "script_url": creation_data.get("script_url"),
                    "characters": creation_data.get("characters", []),
                    "scenes": creation_data.get("scenes", []),
                    "production_stage": inferred_stage,
                    "production_progress": production_progress,  # 同步更新
                })
                logger.info(f"[SubgraphNode] 从数据库加载创作数据成功，阶段: {inferred_stage}, progress: {production_progress}")
        except Exception as e:
            logger.error(f"[SubgraphNode] 加载创作数据失败: {e}")
    
    return result




async def error_handler_node(state: ComicDramaState) -> Dict[str, Any]:
    """
    错误处理节点
    
    处理执行过程中的错误，记录日志并返回主图
    """
    errors = state.get("errors", [])
    
    logger.error(f"[SubgraphNode] error_handler: 处理错误 {errors}")
    
    last_error = errors[-1] if errors else {"message": "未知错误"}
    
    return {
        "response_text": f"❌ 执行过程中出现错误：{last_error.get('message', str(last_error))}",
        "production_stage": ProductionStage.ERROR,
        "pending_approval": False,
    }


# ==================== 阶段执行节点 ====================

async def script_analysis_node(state: ComicDramaState) -> Dict[str, Any]:
    """
    剧本分析节点
    
    委托给 ScriptAnalystNode 执行完整流程：
    1. 检查剧本是否存在
    2. 调用 LLM 分析剧本，提取角色和场景
    3. 将结果写入数据库
    4. 返回分析结果供用户确认
    """
    logger.info("[SubgraphNode] script_analysis: 委托给 ScriptAnalystNode")
    
    from app.agent.graph.nodes.teams.script_analyst import ScriptAnalystNode
    
    analyst = ScriptAnalystNode()
    result = await analyst.run(state)
    
    # 添加 worker_result 供 Supervisor 使用
    total_chars = len(result.get("characters", []))
    total_scenes = len(result.get("scenes", []))
    response_text = result.get("response_text", f"识别到 {total_chars} 个角色和 {total_scenes} 个场景")
    
    result["worker_result"] = {
        "worker": "script_analyst",
        "summary": f"识别到 {total_chars} 个角色和 {total_scenes} 个场景",
        "success": True,
        "completed": True,
        "response_text": response_text,
    }
    
    return result

async def character_scene_generation_node(state: ComicDramaState) -> Dict[str, Any]:
    """
    角色场景生成节点

    委托给 CharacterSceneGenerationWorkerNode 执行（ReAct 架构）
    仅生成角色和场景的提示词+图片
    """
    logger.info("[SubgraphNode] character_scene_generation: 委托给 CharacterSceneGenerationWorkerNode")

    # 添加阶段开始消息到 messages
    from datetime import datetime
    messages = list(state.get("messages", []))
    messages.append({
        "role": "assistant",
        "content": "🎨 好的，开始为您生成角色和场景资源，请稍候...",
        "timestamp": datetime.now().isoformat(),
        "node": "character_scene_generation",
        "metadata": {"stage": "character_scene_generation", "action": "start"},
    })

    from app.agent.graph.nodes.teams.character_scene_generation_worker import CharacterSceneGenerationWorkerNode
    worker = CharacterSceneGenerationWorkerNode()

    # 将更新后的 messages 传给 worker
    updated_state = dict(state)
    updated_state["messages"] = messages

    result = await worker.run(updated_state)

    # 确保 messages 被保留
    if "messages" not in result:
        result["messages"] = messages

    # 从 tool_usage_summary 获取统计信息
    tool_summary = result.get("tool_usage_summary", {})
    submit_count = tool_summary.get("submit_count", 0)
    save_count = tool_summary.get("save_count", 0)
    success_count = tool_summary.get("success_count", 0)

    response_text = result.get("response_text", f"角色场景生成完成")

    # 添加 worker_result 供 Supervisor 使用
    result["worker_result"] = {
        "worker": "character_scene_generator",
        "summary": f"角色场景生成完成：提交了 {submit_count} 个生成任务，保存了 {save_count} 个提示词",
        "success": success_count > 0,
        "completed": True,
        "response_text": response_text,
        "tool_summary": tool_summary,
    }

    return result


async def shot_generation_node(state: ComicDramaState) -> Dict[str, Any]:
    """
    分镜图片生成节点

    委托给 ShotGenerationWorkerNode 执行（ReAct 架构）
    仅生成分镜的图片提示词+首尾帧图片
    """
    logger.info("[SubgraphNode] shot_generation: 委托给 ShotGenerationWorkerNode")

    # 添加阶段开始消息到 messages
    from datetime import datetime
    messages = list(state.get("messages", []))
    messages.append({
        "role": "assistant",
        "content": "📸 好的，开始为您生成分镜图片，请稍候...",
        "timestamp": datetime.now().isoformat(),
        "node": "shot_generation",
        "metadata": {"stage": "shot_generation", "action": "start"},
    })

    from app.agent.graph.nodes.teams.shot_generation_worker import ShotGenerationWorkerNode
    worker = ShotGenerationWorkerNode()

    # 将更新后的 messages 传给 worker
    updated_state = dict(state)
    updated_state["messages"] = messages

    result = await worker.run(updated_state)

    # 确保 messages 被保留
    if "messages" not in result:
        result["messages"] = messages

    # 从 tool_usage_summary 获取统计信息
    tool_summary = result.get("tool_usage_summary", {})
    submit_count = tool_summary.get("submit_count", 0)
    save_count = tool_summary.get("save_count", 0)
    success_count = tool_summary.get("success_count", 0)

    response_text = result.get("response_text", f"分镜图片生成完成")

    # 添加 worker_result 供 Supervisor 使用
    result["worker_result"] = {
        "worker": "shot_generator",
        "summary": f"分镜图片生成完成：提交了 {submit_count} 个生成任务，保存了 {save_count} 个提示词",
        "success": success_count > 0,
        "completed": True,
        "response_text": response_text,
        "tool_summary": tool_summary,
    }

    return result


async def storyboard_creation_node(state: ComicDramaState) -> Dict[str, Any]:
    """
    分镜创建节点
    
    委托给 StoryboardDirectorNode 执行
    """
    logger.info("[SubgraphNode] storyboard_creation: 委托给 StoryboardDirectorNode")
    
    from app.agent.graph.nodes.teams.storyboard_director import StoryboardDirectorNode
    director = StoryboardDirectorNode()
    result = await director.run(state)
    
    # 添加 worker_result 供 Supervisor 使用
    shot_count = result.get("generated_shots", 0)
    response_text = result.get("response_text", f"分镜创建完成：{shot_count} 个分镜")
    
    result["worker_result"] = {
        "worker": "storyboard_director",
        "summary": f"创建了 {shot_count} 个分镜",
        "success": True,
        "completed": True,
        "response_text": response_text,
    }
    
    return result


async def audio_processing_node(state: ComicDramaState) -> Dict[str, Any]:
    """
    音频处理节点
    
    委托给 AudioEngineerNode 执行
    """
    logger.info("[SubgraphNode] audio_processing: 委托给 AudioEngineerNode")
    
    from app.agent.graph.nodes.teams.audio_engineer import AudioEngineerNode
    engineer = AudioEngineerNode()
    result = await engineer.run(state)
    
    # 添加 worker_result 供 Supervisor 使用
    audio_count = result.get("generated_audios", 0)
    response_text = result.get("response_text", f"音频处理完成：{audio_count} 个音频")
    
    result["worker_result"] = {
        "worker": "audio_engineer",
        "summary": f"处理了 {audio_count} 个音频",
        "success": True,
        "completed": True,
        "response_text": response_text,
    }
    
    return result


async def video_generation_node(state: ComicDramaState) -> Dict[str, Any]:
    """
    视频生成节点
    
    委托给 VideoEditorNode 执行
    """
    logger.info("[SubgraphNode] video_generation: 委托给 VideoEditorNode")
    
    from app.agent.graph.nodes.teams.video_editor import VideoEditorNode
    editor = VideoEditorNode()
    result = await editor.run(state)
    
    # 添加 worker_result 供 Supervisor 使用
    video_count = result.get("generated_videos", 0)
    response_text = result.get("response_text", f"视频生成完成：{video_count} 个视频")
    
    result["worker_result"] = {
        "worker": "video_editor",
        "summary": f"生成了 {video_count} 个视频",
        "success": True,
        "completed": True,
        "response_text": response_text,
    }
    
    return result


async def editing_node(state: ComicDramaState) -> Dict[str, Any]:
    """
    剪辑合成节点
    
    委托给 FinalEditorNode 执行
    """
    logger.info("[SubgraphNode] editing: 委托给 FinalEditorNode")
    
    from app.agent.graph.nodes.teams.video_editor import FinalEditorNode
    editor = FinalEditorNode()
    result = await editor.run(state)
    
    # 添加 worker_result 供 Supervisor 使用
    response_text = result.get("response_text", "剪辑合成完成")
    
    result["worker_result"] = {
        "worker": "final_editor",
        "summary": "最终剪辑合成完成",
        "success": True,
        "completed": True,
        "response_text": response_text,
    }
    
    return result


async def video_prompt_builder_node(state: ComicDramaState) -> Dict[str, Any]:
    """
    视频提示词构建节点

    委托给 VideoPromptBuilderNode 执行（ReAct 架构）
    为每个分镜构建带 @引用的视频提示词，分析相邻分镜连续性决定 extend/new 模式
    """
    logger.info("[SubgraphNode] video_prompt_builder: 委托给 VideoPromptBuilderNode")

    from datetime import datetime
    messages = list(state.get("messages", []))
    messages.append({
        "role": "assistant",
        "content": "正在为分镜构建视频提示词，分析分镜连续性...",
        "timestamp": datetime.now().isoformat(),
        "node": "video_prompt_builder",
        "metadata": {"stage": "video_prompt_builder", "action": "start"},
    })

    from app.agent.graph.nodes.teams.video_prompt_builder import VideoPromptBuilderNode
    worker = VideoPromptBuilderNode()

    updated_state = dict(state)
    updated_state["messages"] = messages

    result = await worker.run(updated_state)

    if "messages" not in result:
        result["messages"] = messages

    # 确保返回结果包含 worker_result
    if "worker_result" not in result:
        result["worker_result"] = {
            "worker": "video_prompt_builder",
            "summary": result.get("response_text", "视频提示词构建完成"),
            "success": result.get("success", False),
            "completed": True,
            "response_text": result.get("response_text", ""),
        }

    return result


async def asset_regeneration_node(state: ComicDramaState) -> Dict[str, Any]:
    """
    资产重新生成节点
    
    委托给 AssetRegeneratorWorkerNode 执行
    
    支持：
    - 角色图片重新生成
    - 角色提示词重新生成/修改
    - 场景图片重新生成
    - 场景提示词重新生成/修改
    - 分镜首帧/尾帧图片重新生成
    - 分镜视频重新生成
    - 分镜提示词重新生成/修改
    """
    logger.info("[SubgraphNode] asset_regeneration: 委托给 AssetRegeneratorWorkerNode")
    
    from app.agent.graph.nodes.teams.asset_regenerator_worker import AssetRegeneratorWorkerNode
    regenerator = AssetRegeneratorWorkerNode()
    result = await regenerator.run(state)
    
    # 确保返回结果包含 worker_result
    if "worker_result" not in result:
        result["worker_result"] = {
            "worker": "asset_regenerator",
            "summary": result.get("response_text", "重新生成任务已提交"),
            "success": result.get("success", False),
            "completed": True,
            "response_text": result.get("response_text", ""),
        }
    
    return result


# ==================== 构建子图 ====================

def build_comic_drama_subgraph() -> StateGraph:
    """
    构建漫剧业务执行子图 - Supervisor Agent 模式
    
    架构：
    - supervisor: 入口，单次 LLM 决策，决定调度哪个 Worker
    - workers: 执行具体任务，完成后回到 supervisor
    - 递归由 LangGraph 统一管理（recursion_limit）
    
    流程：
    stage_router → supervisor ⇄ workers → END
    
    Returns:
        编译后的 StateGraph，可作为节点嵌入主图
    """
    from app.agent.graph.nodes.teams import supervisor_node, route_from_supervisor
    
    logger.info("[ComicDramaSubgraph] 构建子图（Supervisor Agent 模式）")
    
    workflow = StateGraph(ComicDramaState)
    
    # ===== 添加节点 =====
    workflow.add_node("stage_router", stage_router_node)  # 入口：加载数据
    workflow.add_node("supervisor", supervisor_node)       # 决策中心
    
    # Workers
    workflow.add_node("script_analysis", script_analysis_node)
    workflow.add_node("character_scene_generation", character_scene_generation_node)
    workflow.add_node("storyboard_creation", storyboard_creation_node)
    workflow.add_node("shot_generation", shot_generation_node)
    workflow.add_node("audio_processing", audio_processing_node)
    workflow.add_node("video_generation", video_generation_node)
    workflow.add_node("editing", editing_node)
    workflow.add_node("asset_regeneration", asset_regeneration_node)

    # 辅助节点
    workflow.add_node("error_handler", error_handler_node)
    
    # ===== 设置边 =====
    # 入口：stage_router → supervisor
    workflow.set_entry_point("stage_router")
    workflow.add_edge("stage_router", "supervisor")
    
    # Supervisor 决策路由
    workflow.add_conditional_edges(
        "supervisor",
        route_from_supervisor,
        {
            "script_analysis": "script_analysis",
            "character_scene_generation": "character_scene_generation",
            "storyboard_creation": "storyboard_creation",
            "shot_generation": "shot_generation",
            "audio_processing": "audio_processing",
            "video_generation": "video_generation",
            "editing": "editing",
            "asset_regeneration": "asset_regeneration",
            "done": END,  # 任务完成
        }
    )
    
    # Workers 完成后直接回到 Supervisor（由 LangGraph 管理递归）
    for worker in [
        "script_analysis",
        "character_scene_generation",
        "storyboard_creation",
        "shot_generation",
        "audio_processing",
        "video_generation",
        "editing",
        "asset_regeneration",
    ]:
        workflow.add_edge(worker, "supervisor")
    
    # 错误处理 → 结束
    workflow.add_edge("error_handler", END)
    
    logger.info("[ComicDramaSubgraph] 子图构建完成")
    
    return workflow.compile()

