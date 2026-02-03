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
    params: Optional[str] = None,
) -> Dict[str, Any]:
    """
    调度任务到指定的 Worker Node
    
    Args:
        worker: Worker 类型 (script_analyst | asset_designer | storyboard_director | video_editor)
        task: 任务描述
        params: 任务参数（JSON 字符串，可选）
        
    Returns:
        调度结果
    """
    import json as json_lib
    
    logger.info(f"[Supervisor] 调度到 Worker: {worker}, task={task}")
    
    valid_workers = ["script_analyst", "asset_designer", "storyboard_director", "video_editor"]
    
    if worker not in valid_workers:
        return {"success": False, "error": f"无效的 Worker: {worker}"}
    
    # 解析 params（支持字符串或字典）
    parsed_params = {}
    if params:
        if isinstance(params, str):
            try:
                parsed_params = json_lib.loads(params)
            except json_lib.JSONDecodeError:
                parsed_params = {"raw": params}
        elif isinstance(params, dict):
            parsed_params = params
    
    # 返回调度指令（由子图路由处理）
    return {
        "success": True,
        "action": "route_to_worker",
        "worker": worker,
        "task": task,
        "params": parsed_params,
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
    
    try:
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
                        logger.info(f"[Node] supervisor: 调度到 Worker {next_worker}")
                        
                    elif action == "request_confirmation":
                        needs_input = True
                        final_response = tool_result.get("message", "")
                        
                    # 更新缓存
                    if tool_name == "query_production_status":
                        updated_cache = tool_result
                
                # 添加工具结果到消息
                messages.append(ToolMessage(
                    content=str(tool_result),
                    tool_call_id=tool_id,
                ))
        
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
