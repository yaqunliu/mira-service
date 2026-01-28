"""
剧本分析团队 - Script Analysis Team

负责剧本解析和初步分析工作
"""

from typing import Dict, Any, Optional
from app.agent.roles.base import BaseAgent
from app.agent.state.schemas import ComicDramaState
from app.core.logger import logger


class ScriptAnalysisAgent(BaseAgent):
    """
    剧本分析师 Agent

    职责：
    1. 分析剧本文本结构和内容
    2. 调用工具提取角色、场景、分镜信息
    3. 生成剧本分析报告
    4. 提交检查点等待用户审核
    """

    @property
    def name(self) -> str:
        return "剧本分析师"

    @property
    def role(self) -> str:
        return "负责分析剧本文本，提取角色、场景和分镜信息"

    @property
    def system_prompt(self) -> str:
        return """你是一位专业的剧本分析师，负责漫剧创作项目的剧本解析工作。

## 你的职责

1. **角色分析**
   - 识别剧本中的所有角色（出镜角色和声音角色）
   - 提取角色的外貌、性格、服装等特征
   - 支持历史角色库复用

2. **场景分析**
   - 识别剧本中的所有场景
   - 提取场景的地点、时间、氛围、空间描述
   - 支持历史场景库复用

3. **分镜拆解**
   - 将剧本拆解为详细的分镜脚本
   - 为每个分镜生成镜头类型、运镜、对话、画面描述
   - 确保分镜连贯性和节奏感

4. **生成分析报告**
   - 汇总角色、场景、分镜数量
   - 标注重点角色和关键场景
   - 提供创作建议

5. **提交检查点**
   - 完成分析后提交检查点
   - 等待用户审核和反馈
   - 根据反馈调整分析结果

## 可用工具

{tools}

## 工作流程

1. 调用 `character_analysis` 工具分析角色
2. 调用 `scene_analysis` 工具分析场景
3. 调用 `shot_analysis` 工具拆解分镜
4. 生成剧本分析报告
5. 提交检查点等待审核

## 输出格式

请以 JSON 格式输出你的决策和行动：

```json
{{
  "思考过程": "你的思考和判断",
  "下一步行动": "character_analysis/scene_analysis/shot_analysis/submit_checkpoint",
  "工具参数": {{}},
  "检查点数据": {{}}  // 仅在 submit_checkpoint 时提供
}}
```

## 注意事项

- 按顺序执行：角色分析 → 场景分析 → 分镜拆解
- 每个步骤完成后检查结果，确保数据完整
- 发现问题时及时记录到错误列表
- 提交检查点前确保所有分析已完成
"""

    def get_available_tools(self) -> list:
        return [
            "character_analysis",
            "scene_analysis",
            "shot_analysis"
        ]

    async def execute(
        self,
        state: ComicDramaState,
        user_input: Optional[str] = None,
        **kwargs
    ) -> Dict[str, Any]:
        """
        执行剧本分析

        流程：
        1. 检查当前阶段
        2. 根据阶段调用相应工具
        3. 更新状态
        4. 决定下一步行动
        """
        current_stage = state.get("current_stage", "init")
        logger.info(f"{self.name} 开始执行，当前阶段: {current_stage}")

        # 根据当前阶段决定下一步行动
        if current_stage == "init":
            return {
                "next_action": "character_analysis",
                "message": "开始角色分析"
            }
        elif current_stage == "script_analysis":
            # 检查角色分析是否完成
            characters = state.get("characters", [])
            if not characters:
                return {
                    "next_action": "character_analysis",
                    "message": "执行角色分析"
                }

            # 检查场景分析是否完成
            scenes = state.get("scenes", [])
            if not scenes:
                return {
                    "next_action": "scene_analysis",
                    "message": "执行场景分析"
                }

            # 检查分镜拆解是否完成
            storyboards = state.get("storyboards", [])
            if not storyboards:
                return {
                    "next_action": "shot_analysis",
                    "message": "执行分镜拆解"
                }

            # 所有分析已完成，提交检查点
            return {
                "next_action": "submit_checkpoint",
                "checkpoint_type": "script_analysis",
                "checkpoint_data": {
                    "characters_count": len(characters),
                    "scenes_count": len(scenes),
                    "storyboards_count": len(storyboards),
                    "characters": characters,
                    "scenes": scenes,
                    "storyboards": storyboards[:5]  # 只展示前5个分镜
                },
                "message": "剧本分析完成，请审核分析结果"
            }

        return {
            "next_action": "wait",
            "message": f"当前阶段 {current_stage} 不需要剧本分析"
        }
