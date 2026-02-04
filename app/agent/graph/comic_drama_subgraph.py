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


# ==================== 阶段顺序定义 ====================

STAGE_ORDER = [
    "script_analysis",
    "asset_generation",
    "storyboard_creation",
    "video_generation",  # 先生成视频
    "audio_processing",  # 再生成音频
    "editing"
]

# 意图 → 目标阶段映射
INTENT_TARGET_STAGE = {
    # 分析类
    "analyze_script": "script_analysis",
    "extract_characters": "script_analysis",
    "extract_scenes": "script_analysis",
    
    # 生成类
    "generate_character_images": "asset_generation",
    "generate_scene_images": "asset_generation",
    "generate_shot_images": "storyboard_creation",
    "generate_videos": "video_generation",
    "generate_audio": "audio_processing",
    "select_voice": "audio_processing",  # 音色选择
    # 一键创作
    "auto_create": "script_analysis",  # 从头开始
}

# 需要人工审核的阶段
REVIEW_STAGES = {
    ProductionStage.SCRIPT_ANALYZED,
    ProductionStage.ASSETS_READY,
    ProductionStage.STORYBOARD_READY,
    ProductionStage.AUDIO_READY,
    ProductionStage.VIDEO_READY,
}


# ==================== 路由函数 ====================

def route_by_production_stage(state: ComicDramaState) -> str:
    """
    子图入口路由：根据当前阶段 + 用户意图，决定从哪里开始执行
    
    核心逻辑：
    1. 先检查当前制作进度
    2. 对比用户意图要求的目标阶段
    3. 如果有前置阶段未完成，先完成前置阶段
    """
    production_stage = state.get("production_stage", ProductionStage.INIT)
    intent = state.get("detected_intent", "")
    
    logger.info(f"[SubgraphRouter] production_stage={production_stage}, intent={intent}")
    
    # 检查是否有错误需要处理
    if state.get("errors"):
        return "error_handler"
    
    # 检查是否需要用户输入，直接跳到 stage_complete 返回主图
    if state.get("needs_input"):
        logger.info("[SubgraphRouter] needs_input=True，跳到 stage_complete")
        return "stage_complete"
    
    # 特殊处理：用户确认操作
    if intent in ["confirm", "approve"]:
        return _handle_confirm_action(state, production_stage)
    
    # 获取目标阶段
    target_stage = INTENT_TARGET_STAGE.get(intent)
    
    if not target_stage:
        # 未知意图，走默认流程：继续下一个未完成的阶段
        return _get_next_incomplete_stage(state)
    
    target_index = STAGE_ORDER.index(target_stage) if target_stage in STAGE_ORDER else 0
    
    # 特殊处理：音色选择可以跳过视频生成阶段
    if intent == "select_voice":
        # 只需要检查 audio_processing 之前的必要阶段（不包括 video_generation）
        required_stages = ["script_analysis", "asset_generation", "storyboard_creation"]
        for stage in required_stages:
            if not _is_stage_completed(state, stage):
                logger.info(f"[SubgraphRouter] 音色选择前置阶段 {stage} 未完成，先执行它")
                return stage
        # 前置阶段都完成了，执行 audio_processing
        logger.info(f"[SubgraphRouter] 执行音色选择目标阶段: audio_processing")
        return "audio_processing"
    
    # 检查前置阶段是否完成
    for i, stage in enumerate(STAGE_ORDER[:target_index]):
        if not _is_stage_completed(state, stage):
            logger.info(f"[SubgraphRouter] 前置阶段 {stage} 未完成，先执行它")
            return stage
    
    # 检查目标阶段是否已完成
    if _is_stage_completed(state, target_stage):
        logger.info(f"[SubgraphRouter] 目标阶段 {target_stage} 已完成，跳到 stage_complete")
        return "stage_complete"
    
    # 前置都完成了，执行目标阶段
    logger.info(f"[SubgraphRouter] 执行目标阶段: {target_stage}")
    return target_stage


def _handle_confirm_action(state: ComicDramaState, production_stage: ProductionStage) -> str:
    """处理用户确认操作后的路由"""
    # 根据当前阶段决定下一步
    stage_to_next = {
        ProductionStage.SCRIPT_ANALYZED: "asset_generation",
        ProductionStage.ASSETS_READY: "storyboard_creation",
        ProductionStage.STORYBOARD_READY: "video_generation",  # 分镜完成 → 视频生成
        ProductionStage.VIDEO_READY: "audio_processing",        # 视频完成 → 音频处理
        ProductionStage.AUDIO_READY: "editing",                 # 音频完成 → 后期编辑
    }
    
    next_stage = stage_to_next.get(production_stage)
    if next_stage:
        logger.info(f"[SubgraphRouter] 用户确认，进入下一阶段: {next_stage}")
        return next_stage
    
    # 默认返回当前阶段
    return _get_next_incomplete_stage(state)


def _get_next_incomplete_stage(state: ComicDramaState) -> str:
    """获取下一个未完成的阶段"""
    for stage in STAGE_ORDER:
        if not _is_stage_completed(state, stage):
            return stage
    return "stage_complete"


def _is_stage_completed(state: ComicDramaState, stage: str) -> bool:
    """检查阶段是否已完成"""
    production_progress = state.get("production_progress", {})
    stage_progress = production_progress.get(stage, {})
    return stage_progress.get("status") == "completed"


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


def check_continue_or_return(state: ComicDramaState) -> str:
    """
    阶段完成后检查：继续执行下一阶段 or 返回主图
    
    如果需要人工审核或用户输入，返回主图
    否则继续下一阶段
    """
    needs_input = state.get("needs_input", False)
    production_stage = state.get("production_stage", ProductionStage.INIT)
    script_text = state.get("script_text")
    
    logger.info(f"[SubgraphRouter] check_continue_or_return: needs_input={needs_input}, stage={production_stage}, has_script={bool(script_text)}")
    
    # 如果需要用户输入，返回主图
    if needs_input:
        logger.info("[SubgraphRouter] 需要用户输入，返回主图")
        return "return"
    
    # 如果在 INIT 阶段且没有剧本，返回主图等待用户上传
    if production_stage == ProductionStage.INIT and not script_text:
        logger.info("[SubgraphRouter] INIT 阶段无剧本，返回主图")
        return "return"
    
    if production_stage in REVIEW_STAGES:
        logger.info(f"[SubgraphRouter] 阶段 {production_stage} 需要人工审核，返回主图")
        return "return"
    
    # 处理异步任务进行中的阶段 - 需要返回等待任务完成
    if production_stage == ProductionStage.ASSETS_GENERATING:
        logger.info("[SubgraphRouter] 资产生成中，返回主图等待任务完成")
        return "return"
    
    if production_stage == ProductionStage.STORYBOARD_GENERATING:
        logger.info("[SubgraphRouter] 分镜图生成中，返回主图等待任务完成")
        return "return"
    
    if production_stage == ProductionStage.AUDIO_GENERATING:
        logger.info("[SubgraphRouter] 音频生成中，返回主图等待任务完成")
        return "return"
        
    if production_stage == ProductionStage.AUDIO_PROCESSING:
        logger.info("[SubgraphRouter] 音频处理中，返回主图等待任务完成")
        return "return"
    
    if production_stage == ProductionStage.VIDEO_GENERATING:
        logger.info("[SubgraphRouter] 视频生成中，返回主图等待任务完成")
        return "return"
    
    if production_stage == ProductionStage.COMPLETED:
        logger.info("[SubgraphRouter] 已完成，返回主图")
        return "return"
    
    if production_stage == ProductionStage.ERROR:
        logger.info("[SubgraphRouter] 出错，返回主图")
        return "return"
    
    logger.info("[SubgraphRouter] 继续下一阶段")
    return "continue"


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


async def stage_complete_node(state: ComicDramaState) -> Dict[str, Any]:
    """
    阶段完成节点
    
    每个阶段执行完毕后经过此节点，更新状态并决定是否需要人工审核
    """
    production_stage = state.get("production_stage", ProductionStage.INIT)
    
    logger.info(f"[SubgraphNode] stage_complete: 当前阶段 {production_stage}")
    
    # 检查是否需要人工审核
    needs_review = production_stage in REVIEW_STAGES
    
    # TODO: 调用 StatePersistence.save() 持久化关键阶段状态
    
    return {
        "pending_approval": needs_review,
    }


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
    
    职责：
    1. 检查剧本是否存在
    2. 调用 LLM 分析剧本，提取角色和场景
    3. 将结果写入数据库
    4. 返回分析结果供用户确认
    """
    logger.info("[SubgraphNode] script_analysis: 执行剧本分析")
    
    # 检查是否有剧本
    script_text = state.get("script_text")
    if not script_text:
        return {
            "response_text": "请先在左侧上传您的剧本文件，或在剧本编辑区粘贴剧本内容。",
            "production_stage": ProductionStage.INIT,
            "needs_input": True,
            "board_actions": [
                {"type": "switch_view", "target": "script"},
                {"type": "highlight", "target": "upload_button"},
            ],
        }
    
    creation_uuid = state.get("creation_uuid")
    creation_id = state.get("creation_id")
    
    # 添加阶段开始消息到 messages
    from datetime import datetime
    messages = list(state.get("messages", []))
    messages.append({
        "role": "assistant",
        "content": "📖 好的，正在分析剧本内容，识别角色和场景信息，请稍候...",
        "timestamp": datetime.now().isoformat(),
        "node": "script_analysis",
        "metadata": {"stage": "script_analysis", "action": "start"},
    })
    
    try:
        # 1. 使用 ScriptAnalystNode 进行 LLM 分析（不依赖 Tool）
        from app.agent.graph.nodes.teams.script_analyst import ScriptAnalystNode
        
        analyst = ScriptAnalystNode()
        analysis_result = await analyst.run(state)
        
        if not analysis_result.get("success"):
            return {
                "response_text": f"剧本分析失败：{analysis_result.get('error', '未知错误')}",
                "production_stage": ProductionStage.INIT,
                "errors": [{"message": analysis_result.get("error")}],
            }
        
        characters = analysis_result.get("characters", [])
        scenes = analysis_result.get("scenes", [])
        
        # 2. 调用 Tool 将角色和场景写入数据库
        from app.agent.tools.db_tools import save_characters, save_scenes
        
        char_result = await save_characters.ainvoke({
            "creation_uuid": creation_uuid,
            "characters": characters,
        })
        
        scene_result = await save_scenes.ainvoke({
            "creation_uuid": creation_uuid,
            "scenes": scenes,
        })
        
        saved_characters = char_result.get("saved", [])
        skipped_characters = char_result.get("skipped", [])
        saved_scenes = scene_result.get("saved", [])
        skipped_scenes = scene_result.get("skipped", [])
        
        logger.info(f"[SubgraphNode] Tool 调用完成: 新增角色={saved_characters}, 新增场景={saved_scenes}")
        
        # 3. 更新进度
        production_progress = dict(state.get("production_progress", {}))
        production_progress["script_analysis"] = {
            "status": "completed",
            "characters": len(characters),
            "scenes": len(scenes),
        }
        
        # 4. 构建响应（不显示原始分析数据，只显示友好提示）
        total_chars = len(saved_characters) + len(skipped_characters)
        total_scenes = len(saved_scenes) + len(skipped_scenes)
        
        response = f"""✅ **资产分析完成！**

📊 **分析结果**：
- 👥 识别到 **{total_chars}** 个角色
- 🎬 识别到 **{total_scenes}** 个场景

角色和场景已保存到左侧看板，请确认是否准确。

---
🎨 **下一步**：是否开始为角色和场景生成图片？"""
        
        return {
            "response_text": response,
            "production_stage": ProductionStage.SCRIPT_ANALYZED,
            "production_progress": production_progress,
            "pending_approval": True,
            "characters": characters,
            "scenes": scenes,
            "checkpoint_data": {
                "checkpoint_type": "script_analysis",
                "data": {
                    "characters_count": total_chars,
                    "scenes_count": total_scenes,
                    "summary": analysis_result.get("summary", ""),
                },
                "message": "请确认角色和场景识别是否准确",
            },
            "board_actions": [
                {"type": "switch_view", "target": "characters"},
                {"type": "refresh"},
            ],
            # Worker 结果反馈给 Supervisor
            "worker_result": {
                "worker": "script_analyst",
                "summary": f"识别到 {total_chars} 个角色和 {total_scenes} 个场景",
                "success": True,
                "completed": True,
                "response_text": response,  # Supervisor 可以直接使用
            },
        }
        
    except Exception as e:
        logger.error(f"[SubgraphNode] script_analysis 失败: {e}")
        return {
            "response_text": f"剧本分析过程中出现错误：{str(e)}",
            "production_stage": ProductionStage.INIT,
            "errors": [{"message": str(e)}],
        }


async def asset_generation_node(state: ComicDramaState) -> Dict[str, Any]:
    """
    资产生成节点
    
    委托给 AssetDirectorNode 执行
    """
    logger.info("[SubgraphNode] asset_generation: 委托给 AssetDirectorNode")
    
    # 添加阶段开始消息到 messages
    from datetime import datetime
    messages = list(state.get("messages", []))
    messages.append({
        "role": "assistant",
        "content": "🎨 好的，开始为您生成角色和场景图片，请稍候...",
        "timestamp": datetime.now().isoformat(),
        "node": "asset_generation",
        "metadata": {"stage": "asset_generation", "action": "start"},
    })
    
    from app.agent.graph.nodes.teams.asset_director import AssetDirectorNode
    director = AssetDirectorNode()
    
    # 将更新后的 messages 传给 director
    updated_state = dict(state)
    updated_state["messages"] = messages
    
    result = await director.run(updated_state)
    
    # 确保 messages 被保留
    if "messages" not in result:
        result["messages"] = messages
    
    # 添加 worker_result 供 Supervisor 使用
    char_count = result.get("generated_characters", 0)
    scene_count = result.get("generated_scenes", 0)
    response_text = result.get("response_text", f"资产生成完成：{char_count} 个角色，{scene_count} 个场景")
    
    result["worker_result"] = {
        "worker": "asset_designer",
        "summary": f"生成了 {char_count} 个角色图片和 {scene_count} 个场景图片",
        "success": True,
        "completed": True,
        "response_text": response_text,
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
    workflow.add_node("asset_generation", asset_generation_node)
    workflow.add_node("storyboard_creation", storyboard_creation_node)
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
            "asset_generation": "asset_generation",
            "storyboard_creation": "storyboard_creation",
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
        "asset_generation",
        "storyboard_creation",
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

