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

SUPERVISOR_SYSTEM_PROMPT = """你是漫剧创作总导演，负责调度创作流程并做出智能决策。

## 你的核心职责

分析当前状态和用户意图，使用 `supervisor_decision` 工具返回你的决策：
- next_worker: 下一个要调度的 Worker（可选）
- needs_input: 是否需要等待用户输入
- board_actions: 前端交互指令列表
- response_text: 给用户的消息

## Workers 列表

| Worker | 职责 |
|--------|------|
| script_analyst | 剧本分析 → 提取角色、场景 |
| asset_designer | 资产生成 → 生成角色/场景图片（需在 task 中指定：生成角色图片/生成场景图片/生成所有资产图片）|
| storyboard_director | 分镜创作 → 生成分镜图片 |
| video_editor | 视频生成 → 生成分镜视频 |
| audio_engineer | 音频生成 → 生成语音和配音 |
| asset_regenerator | 资产重新生成 → 重新生成指定的角色/场景/分镜/视频 |

### asset_designer 调用示例
- 生成所有资产：task="生成所有角色和场景图片"
- 仅生成角色：task="生成所有角色图片"
- 仅生成场景：task="生成所有场景图片"

## 工作流指导规则

| Worker 完成后 | 建议行为 | 下一阶段 | board_action |
|--------------|----------|----------|--------------|
| script_analyst | 自动继续 | asset_designer | switch_view → characters |
| asset_designer | 暂停确认 | storyboard_director | approve_reject |
| storyboard_director | 暂停确认 | video_editor | approve_reject |
| video_editor | 暂停确认 | - | approve_reject |
| asset_regenerator | 暂停确认 | - | approve_reject |

## Board Actions (前端交互指令)

### 视图控制类
| type | target | 说明 |
|------|--------|------|
| switch_view | characters/scenes/storyboards/preview | 切换看板视图 |
| refresh | - | 刷新当前视图数据 |
| highlight | element_id | 高亮指定元素 |
| scroll | element_id | 滚动到指定元素 |

### 人工介入类
| type | 参数 | 说明 |
|------|------|------|
| approve_reject | message | 请求用户确认/拒绝 |
| text_input | message, input_placeholder | 请求用户输入文本 |
| select_options | message, options | 请求用户选择选项 |

## 默认工作流

用户说"开始创作"或"继续"时，按当前阶段决策：
- INIT / SCRIPT_UPLOADED → next_worker: script_analyst
- SCRIPT_ANALYZED → next_worker: asset_designer
- ASSETS_READY → next_worker: storyboard_director
- STORYBOARD_READY → next_worker: video_editor
- VIDEO_READY / COMPLETED → needs_input: false, response: "创作已完成！"

## 资产重新生成

当用户要求"重新生成"、"修改"、"优化"时 → next_worker: asset_regenerator

## 当前状态

创作 UUID: {creation_uuid}
当前阶段: {production_stage}
缓存: {production_cache}
Worker 执行结果: {worker_result}

## 用户消息

{user_message}

## 决策示例

1. 剧本分析完成后:
   supervisor_decision(next_worker="asset_designer", needs_input=False, board_actions=[{{"type": "switch_view", "target": "characters"}}], response_text="剧本分析完成，正在生成资产...")

2. 资产生成完成后:
   supervisor_decision(next_worker=None, needs_input=True, board_actions=[{{"type": "approve_reject", "message": "请确认角色和场景形象"}}], response_text="资产生成完成，请确认后继续。")

3. 用户问进度:
   supervisor_decision(next_worker=None, needs_input=False, board_actions=[], response_text="当前进度...")

## 重要规则！

1. 你必须始终调用 supervisor_decision 工具返回决策，禁止直接返回文本。

2. 当 next_worker=None 且 needs_input=True 时，必须提供人工介入类 board_action：
   - approve_reject: 请求用户确认/拒绝
   - text_input: 请求用户输入文本
   - select_options: 请求用户选择选项
   
   注意：如果 next_worker 有值（要调度到 Worker），则不要设置人工介入类 action！
   
   示例：
   ❌ 错误: supervisor_decision(next_worker="asset_designer", needs_input=True, board_actions=[{{"type": "approve_reject"}}], ...)
   ❌ 错误: supervisor_decision(next_worker=None, needs_input=True, board_actions=[], response_text="请确认")
   ✅ 正确: supervisor_decision(next_worker="asset_designer", needs_input=False, board_actions=[], response_text="正在生成...")
   ✅ 正确: supervisor_decision(next_worker=None, needs_input=True, board_actions=[{{"type": "approve_reject", "message": "请确认"}}], response_text="请确认后继续")
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


@tool
async def supervisor_decision(
    next_worker: Optional[str] = None,
    needs_input: bool = False,
    board_actions: List[Dict[str, Any]] = None,
    response_text: str = "",
) -> Dict[str, Any]:
    """
    返回 Supervisor 的智能决策结果
    
    Args:
        next_worker: 下一个要调度的 Worker（可选：script_analyst/asset_designer/storyboard_director/video_editor/asset_regenerator）
        needs_input: 是否需要等待用户输入
        board_actions: 前端交互指令列表（如 switch_view, refresh, approve_reject 等）
        response_text: 给用户的消息
        
    Returns:
        决策结果
    """
    logger.info(f"[Supervisor] 决策: next_worker={next_worker}, needs_input={needs_input}, board_actions={board_actions}")
    
    return {
        "success": True,
        "action": "supervisor_decision",
        "next_worker": next_worker,
        "needs_input": needs_input,
        "board_actions": board_actions or [],
        "response_text": response_text,
    }


def _get_supervisor_tools() -> List:
    """获取 Supervisor 专用工具"""
    from app.agent.tools.context_tools import check_constraints
    
    return [
        query_production_status,
        check_constraints,
        supervisor_decision,  # 主决策工具
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
        # ===== LLM 智能决策：分析 worker_result 并决定下一步 =====
        tools = _get_supervisor_tools()
        
        llm = ChatOpenAI(
            model=settings.LLM_MODEL_DEFAULT,
            api_key=settings.OPENAI_API_KEY,
            base_url=settings.OPENAI_BASE_URL,
            temperature=0.3,
        )
        # 强制 LLM 必须调用 supervisor_decision 工具
        llm_with_tools = llm.bind_tools(
            tools, 
            tool_choice={"type": "function", "function": {"name": "supervisor_decision"}}
        )
        
        # 构建上下文消息
        context_message = user_message
        if worker_result:
            worker_name = worker_result.get("worker", "unknown")
            worker_response = worker_result.get("response_text", "完成")
            context_message = f"[Worker 执行结果]\nWorker: {worker_name}\n结果: {worker_response}\n\n[用户消息]\n{user_message}"
        
        # 格式化 worker_result 给 LLM
        worker_result_str = "无" if not worker_result else f"{worker_result.get('worker')}: {worker_result.get('response_text', '完成')}"
        
        system_prompt = SUPERVISOR_SYSTEM_PROMPT.format(
            creation_uuid=creation_uuid or "未指定",
            production_stage=production_stage.name if hasattr(production_stage, 'name') else str(production_stage),
            production_cache=production_cache,
            worker_result=worker_result_str,
            user_message=context_message,
        )
        
        messages = [
            SystemMessage(content=system_prompt),
            HumanMessage(content=context_message),
        ]
        
        # ===== LLM 决策 =====
        next_worker = None
        needs_input = False
        board_actions = []
        final_response = ""
        updated_cache = production_cache.copy()
        
        response = await llm_with_tools.ainvoke(messages)
        
        # 检查工具调用
        if response.tool_calls:
            for tool_call in response.tool_calls:
                tool_name = tool_call["name"]
                tool_args = tool_call["args"]
                
                logger.info(f"[Node] supervisor: 决策 -> {tool_name}, args={tool_args}")
                
                if tool_name == "supervisor_decision":
                    # 智能决策结果
                    next_worker = tool_args.get("next_worker")
                    needs_input = tool_args.get("needs_input", False)
                    board_actions = tool_args.get("board_actions", [])
                    final_response = tool_args.get("response_text", "")
                    logger.info(f"[Node] supervisor: 智能决策 -> next_worker={next_worker}, needs_input={needs_input}, board_actions={board_actions}")
                    break
                    
                elif tool_name == "query_production_status":
                    # 查询状态工具 - 执行后继续决策
                    tool_result = await _execute_supervisor_tool(tools, tool_name, tool_args)
                    if isinstance(tool_result, dict):
                        updated_cache = tool_result
        else:
            # 无工具调用 → 使用 LLM 的直接回复作为 response_text
            final_response = response.content.strip() or "请告诉我您需要什么帮助？"
            needs_input = True
            logger.warning("[Node] supervisor: LLM 未调用工具，使用直接回复")
        
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
            "board_actions": board_actions,
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
