"""
Supervisor Node - 生产子图的 ReAct 调度中心

负责理解用户意图、检查约束、调度 Worker Nodes 执行任务。
实现默认工作流和灵活的任务调度。
"""

from typing import Dict, Any, List, Optional, Literal
from datetime import datetime

from langchain_openai import ChatOpenAI
from langchain_core.messages import SystemMessage, HumanMessage, AIMessage, ToolMessage
from langchain_core.tools import tool
from pydantic import BaseModel, Field

from app.core.logger import logger
from app.core.config import settings
from app.agent.state.schemas import ComicDramaState, ProductionStage


# ==================== 类型定义 ====================

WorkerType = Literal["script_analyst", "asset_designer", "storyboard_director", "video_editor"]


# ==================== 系统提示词 ====================

SUPERVISOR_SYSTEM_PROMPT = """你是漫剧创作总导演，负责调度创作流程。

## 你的职责

1. **理解用户意图** - 判断用户想做什么
2. **检查约束规则** - 确保操作不会破坏一致性
3. **调度工作流程** - 决定下一步该做什么
4. **反馈执行结果** - 告诉用户当前进度

## 默认工作流

用户说"开始创作"或"继续"时，按顺序执行：
1. 剧本分析 → 提取角色、场景、分镜
2. 资产生成 → 生成角色图片、场景图片
3. 分镜创作 → 生成分镜首帧、尾帧图片
4. 视频生成 → 为每个分镜生成视频

## 约束规则

- 分镜图片生成后，修改角色/场景需要先清空分镜
- 视频生成后，修改分镜需要先清空视频

## 当前创作状态

创作 UUID: {creation_uuid}
当前阶段: {production_stage}
进度缓存: {production_cache}

## 用户消息

{user_message}

## 工具使用

- 查询状态 → query_production_status
- 检查约束 → check_constraints  
- 调度 Worker → route_to_worker
- 请求确认 → request_user_confirmation

根据用户意图和当前状态，决定下一步行动。
"""


# ==================== Supervisor 专用工具 ====================

class RouteToWorkerInput(BaseModel):
    """调度 Worker 的输入"""
    worker: WorkerType = Field(..., description="目标 Worker")
    task: str = Field(..., description="任务描述")
    params: Dict[str, Any] = Field(default_factory=dict, description="任务参数")


@tool
async def query_production_status(creation_uuid: str) -> Dict[str, Any]:
    """
    查询创作项目的生产状态（用于 Supervisor 缓存）
    
    Args:
        creation_uuid: 创作项目 UUID
        
    Returns:
        生产状态缓存
    """
    logger.info(f"[Supervisor] 查询生产状态: {creation_uuid}")
    
    from app.agent.tools.db_tools import query_creation_status
    
    status = await query_creation_status.ainvoke({"creation_uuid": creation_uuid})
    
    # 构建缓存
    cache = {
        "has_characters": status.get("characters", {}).get("total", 0) > 0,
        "has_character_images": status.get("characters", {}).get("with_image", 0) > 0,
        "has_scenes": status.get("scenes", {}).get("total", 0) > 0,
        "has_scene_images": status.get("scenes", {}).get("with_image", 0) > 0,
        "has_shots": status.get("shots", {}).get("total", 0) > 0,
        "has_storyboard": status.get("shots", {}).get("with_image", 0) > 0,
        "has_videos": status.get("shots", {}).get("with_video", 0) > 0,
        "raw_status": status,
    }
    
    return cache


@tool
async def route_to_worker(
    worker: str,
    task: str,
    creation_uuid: str = "",
    shot_number: int = 0,
    shot_id: int = 0,
) -> Dict[str, Any]:
    """
    调度任务到指定的 Worker Node
    
    Args:
        worker: Worker 类型 (script_analyst | asset_designer | storyboard_director | video_editor)
        task: 任务描述
        creation_uuid: 创作项目 UUID
        shot_number: 分镜编号（用于视频生成等任务）
        shot_id: 分镜 ID（可选，优先使用 shot_number）
        
    Returns:
        调度结果
    """
    logger.info(f"[Supervisor] 调度到 Worker: {worker}, task={task}")
    
    valid_workers = ["script_analyst", "asset_designer", "storyboard_director", "video_editor"]
    
    if worker not in valid_workers:
        return {"success": False, "error": f"无效的 Worker: {worker}"}
    
    # 构建参数
    params = {}
    if creation_uuid:
        params["creation_uuid"] = creation_uuid
    if shot_number:
        params["shot_number"] = shot_number
    if shot_id:
        params["shot_id"] = shot_id
    
    # 返回调度指令（由子图路由处理）
    return {
        "success": True,
        "action": "route_to_worker",
        "worker": worker,
        "task": task,
        "params": params,
    }


@tool
async def request_user_confirmation(
    message: str,
    options: List[str],
) -> Dict[str, Any]:
    """
    请求用户确认
    
    Args:
        message: 确认消息
        options: 可选项列表
        
    Returns:
        确认请求结果
    """
    logger.info(f"[Supervisor] 请求用户确认: {message}")
    
    return {
        "success": True,
        "action": "request_confirmation",
        "message": message,
        "options": options,
        "needs_input": True,
    }


def _get_supervisor_tools() -> List:
    """获取 Supervisor 专用工具"""
    from app.agent.tools.context_tools import check_constraints
    
    return [
        query_production_status,
        check_constraints,
        route_to_worker,
        request_user_confirmation,
    ]


# ==================== 资源重新生成处理 ====================

async def _handle_regenerate_intent(
    state: ComicDramaState,
    creation_uuid: str,
    intent_details: Dict[str, Any]
) -> Dict[str, Any]:
    """
    处理 regenerate 意图 - 直接执行资源重新生成
    
    支持：
    - 指定编号：target_numbers=[11] -> 重新生成分镜11
    - 指定名称：target_names=["幽影"] -> 重新生成角色幽影
    - 失败重试：scope="failed" -> 重新生成所有失败的资源
    
    当名称匹配到多个资源时，会返回列表让用户选择
    
    Args:
        state: 当前状态
        creation_uuid: 创作UUID
        intent_details: 意图详情
        
    Returns:
        处理结果，可能包含需要用户确认的多选列表
    """
    from app.agent.tools.db_tools import (
        find_resources_by_identifier,
        query_failed_resources,
    )
    from app.agent.tools.regenerate_tools import regenerate
    
    target = intent_details.get("target", "shot")
    target_numbers = intent_details.get("target_numbers", [])
    target_names = intent_details.get("target_names", [])
    scope = intent_details.get("scope", "specific")
    resource_type = intent_details.get("resource_type", "video")
    
    logger.info(f"[Supervisor] 处理 regenerate: target={target}, scope={scope}, "
                f"numbers={target_numbers}, names={target_names}, resource_type={resource_type}")
    
    resources_to_regenerate = []
    ambiguous_matches = []  # 存储有歧义的匹配结果
    
    # 情况1: 失败重试
    if scope == "failed":
        failed_result = await query_failed_resources.ainvoke({
            "creation_uuid": creation_uuid,
            "resource_type": target,
            "resource_subtype": resource_type if target == "shot" else "image"
        })
        
        if failed_result.get("success"):
            resources_to_regenerate = failed_result.get("resources", [])
        
        if not resources_to_regenerate:
            return {
                "success": True,
                "message": f"没有生成失败的{target}资源需要重试。",
                "regenerated_count": 0,
            }
    
    # 情况2: 指定编号 - 使用资源解析工具
    elif target_numbers and target == "shot":
        from app.agent.tools.resource_resolver import resolve_resource_reference
        
        for number in target_numbers:
            user_ref = f"分镜{number}"
            match_result = await resolve_resource_reference.ainvoke({
                "creation_uuid": creation_uuid,
                "target": "shot",
                "user_reference": user_ref,
            })
            
            if match_result.get("success"):
                matched = match_result.get("matched_resources", [])
                if matched:
                    if match_result.get("ambiguous") or len(matched) > 1:
                        ambiguous_matches.append({
                            "identifier": number,
                            "matched_count": len(matched),
                            "resources": matched[:5]
                        })
                    else:
                        resources_to_regenerate.extend(matched)
    
    # 情况3: 指定名称（角色/场景/分镜描述）- 使用资源解析工具
    elif target_names:
        from app.agent.tools.resource_resolver import resolve_resource_reference
        
        for name in target_names:
            match_result = await resolve_resource_reference.ainvoke({
                "creation_uuid": creation_uuid,
                "target": target,
                "user_reference": name,
            })
            
            if match_result.get("success"):
                matched = match_result.get("matched_resources", [])
                if matched:
                    if match_result.get("ambiguous") or len(matched) > 1:
                        ambiguous_matches.append({
                            "identifier": name,
                            "matched_count": len(matched),
                            "resources": matched[:5]
                        })
                    else:
                        resources_to_regenerate.extend(matched)
    
    # 情况4: 全部重新生成
    elif scope == "all":
        # 查询所有资源
        if target == "shot":
            from app.agent.tools.db_tools import query_shots
            result = await query_shots.ainvoke({
                "creation_uuid": creation_uuid,
                "include_details": False
            })
            if result.get("shots"):
                resources_to_regenerate = result.get("shots", [])
        elif target == "character":
            from app.agent.tools.db_tools import query_characters
            result = await query_characters.ainvoke({
                "creation_uuid": creation_uuid,
                "include_images": False
            })
            if result.get("characters"):
                resources_to_regenerate = result.get("characters", [])
    
    # 处理有歧义的匹配 - 需要用户确认
    if ambiguous_matches:
        # 构建确认消息
        confirm_message = f"找到多个匹配的{target}资源，请确认要重新生成哪些：\n\n"
        
        for i, match in enumerate(ambiguous_matches, 1):
            identifier = match["identifier"]
            count = match["matched_count"]
            confirm_message += f"**搜索 '{identifier}' 找到 {count} 个结果：**\n"
            
            for j, resource in enumerate(match["resources"], 1):
                if target == "shot":
                    desc = resource.get("description", "")[:50] if resource.get("description") else ""
                    confirm_message += f"  {j}. 分镜{resource.get('shot_number')} - {desc}...\n"
                elif target == "character":
                    confirm_message += f"  {j}. {resource.get('name')}\n"
                elif target == "scene":
                    confirm_message += f"  {j}. {resource.get('title')}\n"
            
            confirm_message += "\n"
        
        confirm_message += "请回复具体的编号（如'分镜11'）或更精确的名称来指定。"
        
        return {
            "success": False,  # 标记为未完成，需要用户确认
            "needs_confirmation": True,
            "message": confirm_message,
            "ambiguous_matches": ambiguous_matches,
            "regenerated_count": 0,
        }
    
    if not resources_to_regenerate:
        return {
            "success": False,
            "message": f"未找到要重新生成的{target}资源，请检查编号或名称是否正确。",
            "regenerated_count": 0,
        }
    
    # 执行重新生成
    regenerated_count = 0
    failed_count = 0
    results = []
    
    # 获取帧类型（用于分镜图片）
    frame_type = intent_details.get("frame_type", "both")
    # 获取视频生成模式（用于分镜视频）
    video_mode = intent_details.get("video_mode", "first_last_frame")  # 默认首尾帧
    
    for resource in resources_to_regenerate:
        try:
            # 确定 target_type 和 mode
            mode = "auto"
            if target == "shot":
                if resource_type == "video":
                    target_type = "shot_video"
                    # 视频生成模式：
                    # - "first_last_frame": 使用首尾帧（需要先有尾帧）
                    # - "first_frame_only": 只使用首帧
                    # 默认使用首尾帧，除非用户明确要求只用首帧
                    if frame_type == "start":
                        mode = "first_frame_only"
                    else:
                        mode = "first_last_frame"
                elif resource_type == "image":
                    # 根据 frame_type 确定是首帧、尾帧还是两者
                    if frame_type == "start":
                        target_type = "shot_start"
                    elif frame_type == "end":
                        target_type = "shot_end"
                    else:  # both 或其他
                        target_type = "shot_image"  # 同时生成首帧和尾帧
                else:
                    target_type = "shot_video"  # 默认视频
                    mode = "first_last_frame"
            elif target == "character":
                target_type = "character"
            elif target == "scene":
                target_type = "scene"
            else:
                continue
            
            # 调用 regenerate 工具
            result = await regenerate.ainvoke({
                "target_type": target_type,
                "target_id": resource.get("id") or resource.get("shot_id") or resource.get("character_id"),
                "creation_uuid": creation_uuid,
                "save_version": True,
                "mode": mode
            })
            
            if result.get("success"):
                regenerated_count += 1
                results.append({
                    "id": resource.get("id") or resource.get("shot_id"),
                    "name": resource.get("name") or resource.get("shot_number"),
                    "success": True,
                })
            else:
                failed_count += 1
                results.append({
                    "id": resource.get("id") or resource.get("shot_id"),
                    "name": resource.get("name") or resource.get("shot_number"),
                    "success": False,
                    "error": result.get("error", "未知错误")
                })
                
        except Exception as e:
            logger.error(f"[Supervisor] 重新生成失败: {e}")
            failed_count += 1
    
    # 构建响应消息
    if scope == "failed":
        message = f"已为 {regenerated_count} 个失败的{target}资源重新提交生成任务。"
    elif len(target_numbers) == 1 or len(target_names) == 1:
        resource_name = target_numbers[0] if target_numbers else target_names[0]
        message = f"已为{target} {resource_name} 重新提交生成任务。"
    else:
        message = f"已为 {regenerated_count} 个{target}资源重新提交生成任务。"
    
    if failed_count > 0:
        message += f"（{failed_count} 个失败）"
    
    return {
        "success": True,
        "message": message,
        "regenerated_count": regenerated_count,
        "failed_count": failed_count,
        "results": results,
        "target": target,
        "resource_type": resource_type,
    }


# ==================== Supervisor Node ====================

async def supervisor_node(state: ComicDramaState) -> Dict[str, Any]:
    """
    Supervisor Node - ReAct 调度中心
    
    理解用户意图，检查约束，调度 Worker 执行任务。
    
    Args:
        state: 当前 Graph 状态
        
    Returns:
        更新后的状态
    """
    logger.info("[Node] supervisor: 开始处理（ReAct Agent 模式）")
    
    creation_uuid = state.get("creation_uuid")
    user_message = state.get("user_message", "")
    production_stage = state.get("production_stage", ProductionStage.INIT)
    production_cache = state.get("production_cache", {})
    detected_intent = state.get("detected_intent", "")
    intent_details = state.get("intent_details", {})
    
    try:
        # ===== 特殊处理：regenerate 意图直接执行 =====
        if detected_intent == "regenerate" and creation_uuid:
            logger.info("[Node] supervisor: 检测到 regenerate 意图，直接执行")
            
            # 检查是否有足够的资源定位信息
            has_target_info = (
                intent_details.get("target_numbers") or 
                intent_details.get("target_names") or 
                intent_details.get("scope") in ["failed", "all"]
            )
            
            if has_target_info:
                result = await _handle_regenerate_intent(state, creation_uuid, intent_details)
                
                # 检查是否需要用户确认（多个匹配结果）
                if result.get("needs_confirmation"):
                    assistant_message = {
                        "role": "assistant",
                        "content": result.get("message"),
                        "timestamp": datetime.now().isoformat(),
                        "node": "supervisor",
                        "metadata": {
                            "mode": "needs_confirmation",
                            "ambiguous_matches": result.get("ambiguous_matches"),
                        },
                    }
                    
                    state_messages = list(state.get("messages", []))
                    state_messages.append(assistant_message)
                    
                    return {
                        "messages": state_messages,
                        "response_text": result.get("message"),
                        "production_cache": production_cache,
                        "next_worker": None,
                        "needs_input": True,  # 需要用户输入来确认
                        "pending_confirmation": True,
                        "ambiguous_matches": result.get("ambiguous_matches"),
                        "updated_at": datetime.now().isoformat(),
                    }
                
                assistant_message = {
                    "role": "assistant",
                    "content": result.get("message", "重新生成任务已提交"),
                    "timestamp": datetime.now().isoformat(),
                    "node": "supervisor",
                    "metadata": {
                        "mode": "direct_regenerate",
                        "regenerated_count": result.get("regenerated_count", 0),
                        "target": result.get("target"),
                    },
                }
                
                state_messages = list(state.get("messages", []))
                state_messages.append(assistant_message)
                
                return {
                    "messages": state_messages,
                    "response_text": result.get("message"),
                    "production_cache": production_cache,
                    "next_worker": None,  # 不需要调度 Worker，直接完成
                    "needs_input": False,
                    "updated_at": datetime.now().isoformat(),
                }
        
        # ===== 标准 ReAct 流程 =====
        # 1. 准备工具
        tools = _get_supervisor_tools()
        
        # 2. 创建带工具的 LLM
        llm = ChatOpenAI(
            model=settings.LLM_MODEL_DEFAULT,
            api_key=settings.OPENAI_API_KEY,
            base_url=settings.OPENAI_BASE_URL,
            temperature=0.3,
        )
        llm_with_tools = llm.bind_tools(tools)
        
        # 3. 构建消息
        system_prompt = SUPERVISOR_SYSTEM_PROMPT.format(
            creation_uuid=creation_uuid or "未指定",
            production_stage=production_stage.name if hasattr(production_stage, 'name') else str(production_stage),
            production_cache=production_cache,
            user_message=user_message,
        )
        messages = [
            SystemMessage(content=system_prompt),
            HumanMessage(content=user_message),
        ]
        
        # 4. ReAct 循环（最多 5 轮）
        max_iterations = 5
        iteration = 0
        final_response = ""
        next_worker = None
        needs_input = False
        updated_cache = production_cache.copy()
        
        while iteration < max_iterations:
            iteration += 1
            logger.info(f"[Node] supervisor: ReAct 循环 {iteration}/{max_iterations}")
            
            # 调用 LLM
            response = await llm_with_tools.ainvoke(messages)
            messages.append(response)
            
            # 检查是否有工具调用
            if not response.tool_calls:
                final_response = response.content
                logger.info("[Node] supervisor: LLM 直接回答，无工具调用")
                break
            
            # 执行工具调用
            should_break = False
            for tool_call in response.tool_calls:
                tool_name = tool_call["name"]
                tool_args = tool_call["args"]
                tool_id = tool_call["id"]
                
                logger.info(f"[Node] supervisor: 调用工具 {tool_name}, args={tool_args}")
                
                # 执行工具
                tool_result = await _execute_supervisor_tool(tools, tool_name, tool_args)
                
                # 处理特殊结果
                if isinstance(tool_result, dict):
                    action = tool_result.get("action")
                    
                    if action == "route_to_worker":
                        next_worker = tool_result.get("worker")
                        logger.info(f"[Node] supervisor: 调度到 Worker {next_worker}，退出循环")
                        should_break = True  # 决定调度后立即退出
                        
                    elif action == "request_confirmation":
                        needs_input = True
                        final_response = tool_result.get("message", "")
                        should_break = True  # 需要用户确认后立即退出
                        
                    # 更新缓存
                    if tool_name == "query_production_status":
                        updated_cache = tool_result
                
                # 添加工具结果到消息
                messages.append(ToolMessage(
                    content=str(tool_result),
                    tool_call_id=tool_id,
                ))
            
            # 如果需要退出循环（调度到 Worker 或需要用户确认）
            if should_break:
                break
        
        # 如果循环结束还没有最终回复，再调用一次生成总结
        if not final_response:
            logger.info("[Node] supervisor: 生成最终总结")
            final_llm = ChatOpenAI(
                model=settings.LLM_MODEL_DEFAULT,
                api_key=settings.OPENAI_API_KEY,
                base_url=settings.OPENAI_BASE_URL,
                temperature=0.7,
            )
            summary_response = await final_llm.ainvoke(messages)
            final_response = summary_response.content
        
        # 5. 构建返回结果
        assistant_message = {
            "role": "assistant",
            "content": final_response,
            "timestamp": datetime.now().isoformat(),
            "node": "supervisor",
            "metadata": {
                "mode": "react_supervisor",
                "iterations": iteration,
                "next_worker": next_worker,
            },
        }
        
        state_messages = list(state.get("messages", []))
        state_messages.append(assistant_message)
        
        logger.info(f"[Node] supervisor: 完成，迭代={iteration}, next_worker={next_worker}")
        
        return {
            "messages": state_messages,
            "response_text": final_response,
            "production_cache": updated_cache,
            "next_worker": next_worker,
            "needs_input": needs_input,
            "updated_at": datetime.now().isoformat(),
        }
        
    except Exception as e:
        logger.error(f"[Node] supervisor 错误: {e}")
        
        error_message = {
            "role": "assistant",
            "content": f"抱歉，处理您的请求时出现错误：{str(e)}",
            "timestamp": datetime.now().isoformat(),
            "node": "supervisor",
            "error": True,
        }
        
        state_messages = list(state.get("messages", []))
        state_messages.append(error_message)
        
        return {
            "messages": state_messages,
            "response_text": f"抱歉，处理您的请求时出现错误：{str(e)}",
            "errors": state.get("errors", []) + [{"node": "supervisor", "error": str(e)}],
        }


async def _execute_supervisor_tool(tools: List, tool_name: str, tool_args: Dict[str, Any]) -> Any:
    """执行 Supervisor 工具"""
    for tool in tools:
        if tool.name == tool_name:
            try:
                result = await tool.ainvoke(tool_args)
                return result
            except Exception as e:
                logger.error(f"[Node] supervisor: 工具 {tool_name} 执行失败: {e}")
                return {"error": str(e)}
    
    return {"error": f"未找到工具: {tool_name}"}


# ==================== 路由函数 ====================

def route_from_supervisor(state: ComicDramaState) -> str:
    """
    Supervisor 后的路由决策
    
    根据 next_worker 或 needs_input 决定下一步
    """
    next_worker = state.get("next_worker")
    needs_input = state.get("needs_input", False)
    
    logger.info(f"[Router] route_from_supervisor: next_worker={next_worker}, needs_input={needs_input}")
    
    if needs_input:
        return "return_to_main"
    
    if next_worker:
        worker_node_map = {
            "script_analyst": "script_analysis",
            "asset_designer": "asset_generation",
            "storyboard_director": "storyboard_creation",
            "video_editor": "video_generation",
        }
        return worker_node_map.get(next_worker, "stage_complete")
    
    return "stage_complete"
