"""
Supervisor Node - 生产子图的 ReAct 调度中心

负责理解用户意图、检查约束、调度 Worker Nodes 执行任务。
实现默认工作流和灵活的任务调度。
"""

from typing import Dict, Any, List, Optional, Literal, TypedDict
from datetime import datetime

from langchain_openai import ChatOpenAI
from langchain_core.messages import SystemMessage, HumanMessage, AIMessage, ToolMessage
from langchain_core.tools import tool
from pydantic import BaseModel, Field

from app.core.logger import logger
from app.core.config import settings
from app.agent.state.schemas import ComicDramaState, ProductionStage


# ==================== 类型定义 ====================

WorkerType = Literal["script_analyst", "asset_designer", "storyboard_director", "video_editor", "audio_engineer", "asset_regenerator"]


# ==================== 系统提示词 ====================

SUPERVISOR_SYSTEM_PROMPT = """你是漫剧创作总导演，负责调度创作流程。

## 你的决策选项（三选一）

1. **调度 Worker**：用户需要执行任务时 → 调用 `route_to_worker`
2. **请求确认**：需要用户决定下一步时 → 调用 `request_user_confirmation`
3. **直接回复**：回答问题/任务完成/无需操作时 → 直接用自然语言回复，不调用任何工具

## Workers 列表

- script_analyst: 剧本分析 → 提取角色、场景
- asset_designer: 资产生成 → 生成角色/场景提示词、图片（支持单个/全部生成）
- storyboard_director: 分镜创作 → 生成分镜脚本、图片
- video_editor: 视频生成 → 生成分镜视频
- audio_engineer: 音频处理 → 生成配音、音效
- asset_regenerator: 资产重新生成 → 重新生成角色/场景/分镜的提示词、图片、视频

## 资产生成规则（asset_designer）

当用户要求生成资产时，调用 asset_designer：
- "生成角色提示词" / "生成全部角色提示词"
- "生成角色图片" / "生成全部角色图片" / "为所有角色生图"
- "生成场景提示词" / "生成全部场景提示词"
- "生成场景图片" / "生成全部场景图片" / "为所有场景生图"
- "生成分镜提示词" / "生成全部分镜提示词"
- "生成分镜图片" / "生成全部分镜图片" / "为所有分镜生图"
- "生成分镜视频" / "生成全部分镜视频"

支持两种范围：
- **单个**：指定具体角色/场景/分镜（如"生成阿九的图片"）
- **全部**：批量生成所有（如"生成全部角色图片"）

## 资产重新生成规则（asset_regenerator）

当用户要求重新生成时，调用 asset_regenerator：
- "重新生成角色图片" / "重新生成场景图片" / "重新生成分镜图片" / "重新生成分镜视频"
- "修改提示词" / "重新生成提示词"
- "重新生成" / "再生成一次"
- "改一下" / "优化一下"

## 默认工作流

用户说"开始创作"或"继续"时，按当前阶段执行：
- INIT / SCRIPT_UPLOADED → 调度 script_analyst
- SCRIPT_ANALYZED → 调度 asset_designer（生成全部角色/场景图片）
- ASSETS_READY → 调度 storyboard_director
- STORYBOARD_READY → 调度 video_editor
- VIDEO_READY / COMPLETED → 直接回复"创作已完成！"

## 何时"直接回复"（不调用工具）

- 用户问问题（"进度怎样？"、"帮我看看..."）
- 阶段任务已完成，提示用户结果
- 无法理解用户意图时
- 任务完成后的总结

## 当前状态

创作 UUID: {creation_uuid}
当前阶段: {production_stage}
缓存: {production_cache}

## 用户消息

{user_message}

## 注意

- 如果 Worker 刚完成任务，直接告知用户结果，不要再调度 Worker
- 如果当前阶段已是 COMPLETED，直接回复，不要调度任何 Worker
- asset_designer 支持灵活的单个/全部生成，根据用户意图自动判断
"""


# ==================== 工作流配置 ====================

class WorkerConfig(TypedDict):
    completion_behavior: Literal["auto_proceed", "pause_for_review"]
    next_worker: Optional[str]  # 自动流转时的目标 Worker

# 工作流配置：定义每个 Worker 完成后的行为
WORKFLOW_CONFIG: Dict[str, WorkerConfig] = {
    "script_analyst": {
        "completion_behavior": "auto_proceed",
        "next_worker": "asset_designer",  # 剧本分析后 -> 自动进资产生成
    },
    "asset_designer": {
        "completion_behavior": "pause_for_review",  # 资产生成后 -> 暂停审核
        "next_worker": None,
    },
    "storyboard_director": {
        "completion_behavior": "pause_for_review",  # 分镜生成后 -> 暂停审核
        "next_worker": None,
    },
    "asset_regenerator": {
        "completion_behavior": "pause_for_review",  # 重新生成后 -> 暂停审核
        "next_worker": None,
    },
    # 默认行为：pause_for_review
}


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
        worker: Worker 类型 (script_analyst | asset_designer | storyboard_director | video_editor | asset_regenerator)
        task: 任务描述
        creation_uuid: 创作项目 UUID
        shot_number: 分镜编号（用于视频生成等任务）
        shot_id: 分镜 ID（可选，优先使用 shot_number）
        
    Returns:
        调度结果
    """
    logger.info(f"[Supervisor] 调度到 Worker: {worker}, task={task}")
    
    valid_workers = ["script_analyst", "asset_designer", "storyboard_director", "video_editor", "audio_engineer", "asset_regenerator"]
    
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


# ==================== Supervisor Node ====================

async def supervisor_node(state: ComicDramaState) -> Dict[str, Any]:
    """
    Supervisor Node - 单次决策模式
    
    每次调用只做一次 LLM 决策，决定：
    1. 调度到某个 Worker（返回 next_worker）
    2. 需要用户确认（返回 needs_input=True）
    3. 直接回复用户（返回 response_text）
    
    递归循环由 LangGraph 图级别管理:
    supervisor → worker → supervisor → worker → ... → done
    
    Args:
        state: 当前 Graph 状态
        
    Returns:
        更新后的状态
    """
    logger.info("[Node] supervisor: 开始处理（单次决策模式）")
    
    creation_uuid = state.get("creation_uuid")
    user_message = state.get("user_message", "")
    production_stage = state.get("production_stage", ProductionStage.INIT)
    production_cache = state.get("production_cache", {})
    detected_intent = state.get("detected_intent", "")
    intent_details = state.get("intent_details", {})
    
    # Worker 返回的结果（用于决定下一步）
    worker_result = state.get("worker_result")
    if worker_result:
        logger.info(f"[Node] supervisor: 收到 Worker 返回: {worker_result.get('worker')}")
    
    try:
        # ===== 特殊处理：Worker 已完成任务 =====
        # 使用 WORKFLOW_CONFIG 判断 Worker 完成后的行为
        if worker_result and worker_result.get("completed"):
            worker_name = worker_result.get("worker", "unknown")
            config = WORKFLOW_CONFIG.get(worker_name, {})
            completion_behavior = config.get("completion_behavior", "pause_for_review")
            
            logger.info(f"[Node] supervisor: Worker {worker_name} 完成，配置行为: {completion_behavior}")
            
            if completion_behavior == "auto_proceed":
                # 自动流转
                next_worker = config.get("next_worker")
                if next_worker:
                    logger.info(f"[Node] supervisor: 自动流转到下一阶段 -> {next_worker} (跳过 LLM)")
                    return {
                        "response_text": worker_result.get("response_text", ""), # 保留上一阶段的响应
                        "production_cache": production_cache,
                        "next_worker": next_worker,
                        "needs_input": False, # 不需要用户输入
                        "worker_result": None, # 清空
                        "updated_at": datetime.now().isoformat(),
                    }
                else:
                    # 如果没有指定 next_worker，则继续执行 LLM 决策
                    logger.info("[Node] supervisor: 未指定下一阶段 Worker，继续 LLM 决策")
                    pass
            else:
                # 暂停等待审核 (pause_for_review)
                worker_response = worker_result.get("response_text", "")
                
                logger.info(f"[Node] supervisor: 暂停等待审核，直接使用 Worker 响应")
                
                # 直接结束，不再调度
                return {
                    "response_text": worker_response,
                    "production_cache": production_cache,
                    "next_worker": None,
                    "needs_input": True,  # 标记需要用户输入来继续
                    "worker_result": None,  # 清空
                    "updated_at": datetime.now().isoformat(),
                }
        
        # ===== 特殊处理：regenerate 意图直接路由到 AssetRegenerator =====
        detected_intent = state.get("detected_intent", "")
        if detected_intent == "regenerate":
            logger.info(f"[Node] supervisor: 检测到 regenerate 意图，直接路由到 asset_regenerator")
            return {
                "response_text": "",
                "production_cache": production_cache,
                "next_worker": "asset_regenerator",
                "needs_input": False,
                "worker_result": None,
                "updated_at": datetime.now().isoformat(),
            }
        
        tools = _get_supervisor_tools()
        
        llm = ChatOpenAI(
            model=settings.LLM_MODEL_DEFAULT,
            api_key=settings.OPENAI_API_KEY,
            base_url=settings.OPENAI_BASE_URL,
            temperature=0.3,
        )
        llm_with_tools = llm.bind_tools(tools)
        
        # 构建上下文消息
        context_message = user_message
        if worker_result:
            worker_name = worker_result.get("worker", "unknown")
            worker_summary = worker_result.get("summary", "完成")
            context_message = f"[{worker_name} 完成] {worker_summary}\n\n用户请求: {user_message}"
        
        system_prompt = SUPERVISOR_SYSTEM_PROMPT.format(
            creation_uuid=creation_uuid or "未指定",
            production_stage=production_stage.name if hasattr(production_stage, 'name') else str(production_stage),
            production_cache=production_cache,
            user_message=context_message,
        )
        
        messages = [
            SystemMessage(content=system_prompt),
            HumanMessage(content=context_message),
        ]
        
        # ===== 决策模式：直接请求 LLM 决定下一步 =====
        next_worker = None
        needs_input = False
        final_response = ""
        updated_cache = production_cache.copy()
        
        response = await llm_with_tools.ainvoke(messages)
        
        # 检查工具调用（LLM 应该调用 route_to_worker 或 request_user_confirmation）
        if response.tool_calls:
            for tool_call in response.tool_calls:
                tool_name = tool_call["name"]
                tool_args = tool_call["args"]
                
                logger.info(f"[Node] supervisor: 决策 -> {tool_name}, args={tool_args}")
                
                if tool_name == "route_to_worker":
                    # 直接从 LLM 的决策中提取 worker
                    next_worker = tool_args.get("worker")
                    logger.info(f"[Node] supervisor: 调度到 Worker {next_worker}")
                    break
                    
                elif tool_name == "request_user_confirmation":
                    needs_input = True
                    final_response = tool_args.get("message", "请确认")
                    break
                    
                elif tool_name == "query_production_status":
                    # 查询状态工具 - 执行后继续决策
                    tool_result = await _execute_supervisor_tool(tools, tool_name, tool_args)
                    if isinstance(tool_result, dict):
                        updated_cache = tool_result
        else:
            # 无工具调用，LLM 直接回复 → 表示本轮结束
            final_response = response.content
            needs_input = True  # 直接回复意味着需要用户继续提问
            logger.info("[Node] supervisor: LLM 直接回答，本轮结束")
        
        # 构建返回结果
        assistant_message = {
            "role": "assistant",
            "content": final_response,
            "timestamp": datetime.now().isoformat(),
            "node": "supervisor",
            "metadata": {
                "mode": "single_decision",
                "next_worker": next_worker,
            },
        }
        
        state_messages = list(state.get("messages", []))
        state_messages.append(assistant_message)
        
        logger.info(f"[Node] supervisor: 完成，next_worker={next_worker}")
        
        return {
            "messages": state_messages,
            "response_text": final_response,
            "production_cache": updated_cache,
            "next_worker": next_worker,
            "needs_input": needs_input,
            "worker_result": None,  # 清空 worker 结果
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
    Supervisor 决策后的路由
    
    根据 next_worker 或 needs_input 决定下一步:
    - next_worker 有值 → 调度到对应 Worker
    - needs_input=True → 结束（返回主图）
    - 其他情况 → 结束
    """
    next_worker = state.get("next_worker")
    needs_input = state.get("needs_input", False)
    
    logger.info(f"[Router] route_from_supervisor: next_worker={next_worker}, needs_input={needs_input}")
    
    # 需要用户输入 → 结束本轮
    if needs_input:
        return "done"
    
    # 有下一个 Worker → 调度
    if next_worker:
        worker_node_map = {
            "script_analyst": "script_analysis",
            "asset_designer": "asset_generation",
            "storyboard_director": "storyboard_creation",
            "video_editor": "video_generation",
            "audio_engineer": "audio_processing",
            "asset_regenerator": "asset_regeneration",
        }
        return worker_node_map.get(next_worker, "done")
    
    # 默认：结束
    return "done"
