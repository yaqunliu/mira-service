"""
制片经理 - Production Manager

负责协调整体创作流程，管理 Agent 团队协作
"""

from typing import Dict, Any, Optional
from app.agent.roles.base import BaseAgent
from app.agent.state.schemas import ComicDramaState
from app.core.logger import logger


class ProductionManagerAgent(BaseAgent):
    """
    制片经理 Agent

    职责：
    1. 协调整体创作流程
    2. 管理 Agent 团队协作
    3. 处理用户反馈和检查点
    4. 监控进度和错误
    5. 最终交付审核
    """

    @property
    def name(self) -> str:
        return "制片经理"

    @property
    def role(self) -> str:
        return "负责协调整体创作流程，管理 Agent 团队协作"

    @property
    def system_prompt(self) -> str:
        return """你是一位专业的制片经理，负责协调漫剧创作项目的整体流程。

## 你的职责

1. **流程协调**
   - 管理创作流程的各个阶段
   - 协调不同 Agent 之间的协作
   - 确保流程顺利推进

2. **检查点管理**
   - 设置关键检查点
   - 收集用户反馈
   - 根据反馈调整流程

3. **进度监控**
   - 跟踪各阶段完成情况
   - 监控任务执行状态
   - 及时发现和处理问题

4. **错误处理**
   - 识别失败的任务
   - 决定重试策略
   - 记录问题和解决方案

5. **最终交付**
   - 汇总所有创作成果
   - 提交最终审核
   - 生成交付报告

## 创作流程阶段

1. **初始化（init）**
   - 创建创作项目
   - 初始化状态
   - 准备剧本文件

2. **剧本分析（script_analysis）**
   - 委托剧本分析师执行
   - 等待检查点审核
   - 处理用户反馈

3. **资产生成（asset_generation）**
   - 委托资产总监执行
   - 等待检查点审核
   - 处理失败重试

4. **分镜创建（storyboard_creation）**
   - 委托分镜导演执行
   - 批次审核分镜
   - 处理用户反馈

5. **音频处理（audio_processing）**
   - 生成对话和旁白音频
   - 合成音轨
   - 生成字幕

6. **视频生成（video_generation）**
   - 生成分镜视频
   - （已在分镜创建阶段完成）

7. **剪辑合成（editing）**
   - 合并视频片段
   - 添加音轨和字幕
   - 生成最终视频

8. **完成（completed）**
   - 提交最终审核
   - 生成交付报告
   - 归档项目

## 检查点处理

当收到用户反馈时：

```json
{
  "action": "approve/reject/modify",
  "comments": "用户反馈意见",
  "modifications": {...},
  "approved_items": [...],
  "rejected_items": [...]
}
```

根据反馈采取行动：

- **approve**：进入下一阶段
- **reject**：重新执行当前阶段
- **modify**：应用修改后重新执行
- **partial**：重新处理驳回的项目

## 输出格式

请以 JSON 格式输出你的决策和行动：

```json
{
  "思考过程": "你的思考和判断",
  "当前阶段": "script_analysis/asset_generation/...",
  "下一步行动": "delegate_to_agent/wait_for_checkpoint/process_feedback/complete",
  "委托Agent": "ScriptAnalysisAgent/AssetDirectorAgent/...",
  "进度信息": {
    "completed_stages": [...],
    "current_stage": "...",
    "pending_stages": [...]
  }
}
```

## 决策逻辑

1. **阶段判断**
   - 检查当前阶段
   - 评估阶段完成情况
   - 决定是否进入下一阶段

2. **Agent 委托**
   - 根据当前阶段选择合适的 Agent
   - 传递必要的上下文和参数
   - 等待 Agent 执行结果

3. **检查点处理**
   - 检查是否有待审核的检查点
   - 等待用户反馈
   - 根据反馈调整流程

4. **错误处理**
   - 识别错误类型
   - 决定重试还是跳过
   - 记录错误日志

5. **流程控制**
   - 维护状态一致性
   - 防止死循环
   - 确保可恢复性

## 注意事项

- 始终维护状态的准确性
- 及时响应用户反馈
- 合理设置重试次数（最多 3 次）
- 记录详细的执行日志
- 在关键节点设置检查点
- 确保流程可中断和恢复
"""

    def get_available_tools(self) -> list:
        # 制片经理不直接调用工具，而是委托给其他 Agent
        return []

    async def execute(
        self,
        state: ComicDramaState,
        user_input: Optional[str] = None,
        **kwargs
    ) -> Dict[str, Any]:
        """
        执行制片管理

        流程：
        1. 检查当前阶段
        2. 判断是否有待处理的检查点
        3. 处理用户反馈
        4. 委托给相应的 Agent
        5. 监控进度
        """
        current_stage = state.get("current_stage", "init")
        pending_approval = state.get("pending_approval", False)
        user_feedback = state.get("user_feedback")

        logger.info(
            f"{self.name} 开始执行，当前阶段: {current_stage}, "
            f"待审核: {pending_approval}"
        )

        # 1. 处理待审核的检查点
        if pending_approval:
            if not user_feedback:
                return {
                    "next_action": "wait_for_checkpoint",
                    "message": "等待用户审核检查点",
                    "current_stage": current_stage
                }

            # 有用户反馈，处理反馈
            action = user_feedback.get("action")

            if action == "approve":
                # 用户通过，进入下一阶段
                next_stage = self._get_next_stage(current_stage)
                return {
                    "next_action": "proceed_to_next_stage",
                    "next_stage": next_stage,
                    "message": f"检查点通过，进入 {next_stage} 阶段"
                }

            elif action == "reject":
                # 用户驳回，重新执行当前阶段
                return {
                    "next_action": "retry_current_stage",
                    "message": f"检查点驳回，重新执行 {current_stage} 阶段",
                    "feedback_comments": user_feedback.get("comments")
                }

            elif action == "modify":
                # 用户要求修改，应用修改后重新执行
                return {
                    "next_action": "apply_modifications",
                    "modifications": user_feedback.get("modifications"),
                    "message": "应用用户修改，重新执行"
                }

            elif action == "partial":
                # 部分通过，重新处理驳回的项目
                return {
                    "next_action": "handle_partial_approval",
                    "approved_items": user_feedback.get("approved_items"),
                    "rejected_items": user_feedback.get("rejected_items"),
                    "message": "处理部分通过的检查点"
                }

        # 2. 根据当前阶段委托给相应的 Agent
        agent_to_delegate = self._get_agent_for_stage(current_stage)

        if agent_to_delegate:
            return {
                "next_action": "delegate_to_agent",
                "agent": agent_to_delegate,
                "current_stage": current_stage,
                "message": f"委托给 {agent_to_delegate} 执行"
            }

        # 3. 检查是否完成
        if current_stage == "completed":
            return {
                "next_action": "finalize",
                "message": "创作流程已完成，准备最终交付"
            }

        # 4. 未知状态
        return {
            "next_action": "error",
            "message": f"未知阶段: {current_stage}",
            "error": "Invalid stage"
        }

    def _get_next_stage(self, current_stage: str) -> str:
        """
        获取下一个阶段

        Args:
            current_stage: 当前阶段

        Returns:
            下一个阶段名称
        """
        stage_flow = {
            "init": "script_analysis",
            "script_analysis": "asset_generation",
            "asset_generation": "storyboard_creation",
            "storyboard_creation": "audio_processing",
            "audio_processing": "video_generation",
            "video_generation": "editing",
            "editing": "completed"
        }

        return stage_flow.get(current_stage, "error")

    def _get_agent_for_stage(self, stage: str) -> Optional[str]:
        """
        根据阶段选择 Agent

        Args:
            stage: 当前阶段

        Returns:
            Agent 名称或 None
        """
        agent_mapping = {
            "script_analysis": "ScriptAnalysisAgent",
            "asset_generation": "AssetDirectorAgent",
            "storyboard_creation": "StoryboardDirectorAgent",
            # "audio_processing": "AudioEngineerAgent",  # 待实现
            # "editing": "VideoEditorAgent"  # 待实现
        }

        return agent_mapping.get(stage)
