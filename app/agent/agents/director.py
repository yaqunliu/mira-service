"""
导演（Supervisor）- Director Agent

负责协调整个制作流程，决定下一步执行哪个团队
"""

from typing import Dict, Any, List, Literal
from langchain_core.messages import SystemMessage, HumanMessage
from langchain_openai import ChatOpenAI
from app.agent.state.schemas import ComicDramaState
from app.core.logger import logger
from app.core.config import settings
import json


class DirectorAgent:
    """导演 Agent - 工作流协调者"""
    
    # 定义所有可能的阶段
    STAGES = [
        "init",
        "script_analysis",
        "asset_generation",
        "storyboard_creation",
        "audio_processing",
        "video_generation",
        "editing",
        "completed",
        "error"
    ]
    
    def __init__(self):
        """初始化导演 Agent"""
        self.llm = ChatOpenAI(
            model=settings.LLM_MODEL_SCRIPT_GENERATION,
            api_key=settings.OPENAI_API_KEY,
            base_url=settings.OPENAI_BASE_URL,
            temperature=0.2
        )
        logger.info("导演 Agent 初始化完成")
    
    def determine_next_stage(self, state: ComicDramaState) -> str:
        """
        根据当前状态决定下一个阶段
        
        这是基于规则的简单决策，实际可以扩展为 LLM 决策
        
        Args:
            state: 当前状态
            
        Returns:
            下一个阶段名称
        """
        current_stage = state.get("current_stage", "init")
        errors = state.get("errors", [])
        pending_checkpoint = state.get("pending_checkpoint")
        
        # 如果有错误，进入错误处理
        if errors and len(errors) > 0:
            logger.warning(f"检测到错误: {errors[-1]}")
            # 如果错误可以恢复，继续；否则进入错误状态
            if self._is_recoverable_error(errors[-1]):
                return current_stage  # 重试当前阶段
            else:
                return "error"
        
        # 如果有待处理的人工检查点，暂停等待
        if pending_checkpoint:
            logger.info(f"等待人工检查点: {pending_checkpoint.get('checkpoint_type')}")
            return "human_review"  # 特殊状态，等待人工审核
        
        # 正常流程推进
        stage_transitions = {
            "init": "script_analysis",
            "script_analysis": "asset_generation",
            "asset_generation": "storyboard_creation",
            "storyboard_creation": "audio_processing",
            "audio_processing": "video_generation",
            "video_generation": "editing",
            "editing": "completed"
        }
        
        next_stage = stage_transitions.get(current_stage, "completed")
        
        logger.info(f"导演决策: {current_stage} -> {next_stage}")
        
        return next_stage
    
    def _is_recoverable_error(self, error: str) -> bool:
        """判断错误是否可恢复"""
        # 可恢复的错误类型
        recoverable_errors = [
            "timeout",
            "rate limit",
            "temporary",
            "network",
            "connection"
        ]
        
        error_lower = error.lower()
        return any(err in error_lower for err in recoverable_errors)
    
    async def make_decision(self, state: ComicDramaState) -> Dict[str, Any]:
        """
        使用 LLM 做出决策（高级决策模式）
        
        Args:
            state: 当前状态
            
        Returns:
            决策结果
        """
        current_stage = state.get("current_stage", "init")
        messages = state.get("messages", [])
        
        # 构建决策提示
        system_prompt = f"""你是漫画短剧制作的导演。根据当前制作状态，决定下一步行动。

当前阶段: {current_stage}

可选行动:
1. CONTINUE - 继续当前阶段
2. NEXT - 进入下一阶段
3. RETRY - 重试当前步骤
4. HUMAN_REVIEW - 需要人工审核
5. ERROR - 报告错误并停止

请输出 JSON 格式:
{{
    "decision": "CONTINUE|NEXT|RETRY|HUMAN_REVIEW|ERROR",
    "reason": "决策原因",
    "next_stage": "如果 decision 是 NEXT，指定下一阶段",
    "requires_human_input": true/false,
    "human_input_prompt": "如果需要人工输入，说明需要什么"
}}"""

        # 构建状态摘要
        state_summary = f"""
当前状态摘要:
- 阶段: {current_stage}
- 角色数: {len(state.get('characters', []))}
- 场景数: {len(state.get('scenes', []))}
- 分镜数: {len(state.get('storyboards', []))}
- 音频片段数: {len(state.get('audio_segments', []))}
- 视频片段数: {len(state.get('video_segments', []))}
- 错误数: {len(state.get('errors', []))}
- 最近消息: {messages[-1]['content'] if messages else '无'}
"""

        try:
            llm_messages = [
                SystemMessage(content=system_prompt),
                HumanMessage(content=state_summary)
            ]
            
            response = await self.llm.ainvoke(llm_messages)
            content = response.content
            
            # 解析 JSON
            import re
            json_match = re.search(r"```json\s*(.*?)\s*```", content, re.DOTALL)
            if json_match:
                json_str = json_match.group(1)
            else:
                json_str = content
            
            result = json.loads(json_str)
            
            logger.info(f"导演 LLM 决策: {result.get('decision')}")
            
            return result
            
        except Exception as e:
            logger.error(f"导演决策失败: {e}")
            # 失败时使用规则决策
            next_stage = self.determine_next_stage(state)
            return {
                "decision": "NEXT" if next_stage != current_stage else "CONTINUE",
                "reason": f"LLM 决策失败，使用规则决策: {str(e)}",
                "next_stage": next_stage,
                "requires_human_input": False
            }
    
    def create_production_plan(self, state: ComicDramaState) -> Dict[str, Any]:
        """
        创建制作计划
        
        Args:
            state: 当前状态
            
        Returns:
            制作计划
        """
        characters = state.get("characters", [])
        scenes = state.get("scenes", [])
        
        plan = {
            "total_stages": len(self.STAGES) - 2,  # 排除 init 和 completed
            "current_stage": state.get("current_stage", "init"),
            "estimated_completion": None,
            "tasks": []
        }
        
        # 生成任务列表
        if state.get("current_stage") == "init":
            plan["tasks"] = [
                {"stage": "script_analysis", "status": "pending", "description": "分析剧本，提取角色和场景"},
                {"stage": "asset_generation", "status": "pending", "description": f"生成 {len(characters)} 个角色和 {len(scenes)} 个场景的图片"},
                {"stage": "storyboard_creation", "status": "pending", "description": "创建分镜脚本"},
                {"stage": "audio_processing", "status": "pending", "description": "生成配音音频"},
                {"stage": "video_generation", "status": "pending", "description": "生成视频片段"},
                {"stage": "editing", "status": "pending", "description": "剪辑合成最终视频"}
            ]
        
        return plan
    
    def should_pause_for_review(self, state: ComicDramaState) -> bool:
        """
        判断是否需要暂停等待人工审核
        
        Args:
            state: 当前状态
            
        Returns:
            是否需要暂停
        """
        # 检查是否有关键资产生成完成
        current_stage = state.get("current_stage", "")
        
        # 在资产生成完成后暂停，让用户审核角色和场景
        if current_stage == "asset_generation":
            characters = state.get("characters", [])
            if characters and all(c.get("image_url") for c in characters):
                return True
        
        # 在分镜创建完成后暂停
        if current_stage == "storyboard_creation":
            storyboards = state.get("storyboards", [])
            if storyboards and len(storyboards) > 0:
                return True
        
        return False


# 导出节点函数
async def director_decision_node(state: ComicDramaState) -> ComicDramaState:
    """
    LangGraph 节点：导演决策
    
    决定工作流的下一步走向
    """
    director = DirectorAgent()
    
    messages = list(state.get("messages", []))
    errors = list(state.get("errors", []))
    current_stage = state.get("current_stage", "init")
    
    if director.should_pause_for_review(state):
        pending_checkpoint = {
            "checkpoint_type": current_stage,
            "message": f"{current_stage} 阶段完成，请审核结果",
            "timestamp": ""
        }
        messages.append({
            "role": "system",
            "content": f"⏸️ {current_stage} 完成，等待人工审核"
        })
        return {
            "pending_checkpoint": pending_checkpoint,
            "messages": messages
        }
    
    decision = await director.make_decision(state)
    
    new_state = {}
    
    if decision.get("decision") == "NEXT":
        next_stage = decision.get("next_stage", "completed")
        new_state["current_stage"] = next_stage
        messages.append({
            "role": "system",
            "content": f"🎬 导演决策: 进入 {next_stage} 阶段"
        })
    elif decision.get("decision") == "RETRY":
        messages.append({
            "role": "system",
            "content": "🔄 导演决策: 重试当前步骤"
        })
    elif decision.get("decision") == "ERROR":
        new_state["current_stage"] = "error"
        errors.append(decision.get("reason", "导演决策错误"))
    
    new_state["messages"] = messages
    new_state["errors"] = errors
    
    return new_state


def route_from_director(state: ComicDramaState) -> str:
    """
    路由函数：根据导演决策返回下一个节点
    
    用于 LangGraph 的条件边
    """
    current_stage = state.get("current_stage", "init")
    pending_checkpoint = state.get("pending_checkpoint")
    
    # 如果有待处理检查点，路由到人工审核
    if pending_checkpoint:
        return "human_review"
    
    # 根据当前阶段路由
    stage_routes = {
        "init": "script_analysis",
        "script_analysis": "asset_generation",
        "asset_generation": "storyboard_creation",
        "storyboard_creation": "audio_processing",
        "audio_processing": "video_generation",
        "video_generation": "editing",
        "editing": "completed",
        "error": "error_handler"
    }
    
    return stage_routes.get(current_stage, "completed")
