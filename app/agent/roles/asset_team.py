"""
资产总监 - Asset Director

负责角色图和场景图的生成和质量把控
"""

from typing import Dict, Any, Optional, List
from app.agent.roles.base import BaseAgent
from app.agent.state.schemas import ComicDramaState
from app.core.logger import logger


class AssetDirectorAgent(BaseAgent):
    """
    资产总监 Agent

    职责：
    1. 规划资产生成策略（并发 vs 批次）
    2. 调用工具生成角色图和场景图
    3. 监控生成进度和质量
    4. 处理失败重试
    5. 提交检查点等待用户审核
    """

    @property
    def name(self) -> str:
        return "资产总监"

    @property
    def role(self) -> str:
        return "负责角色图和场景图的生成，确保资产质量"

    @property
    def system_prompt(self) -> str:
        return """你是一位专业的资产总监，负责漫剧创作项目的资产生成工作。

## 你的职责

1. **规划生成策略**
   - 评估角色和场景数量
   - 决定并发生成还是分批生成
   - 优化生成顺序（重点角色优先）

2. **角色图生成**
   - 调用工具批量生成角色设定图
   - 监控生成进度
   - 处理失败重试

3. **场景图生成**
   - 调用工具批量生成场景建立图
   - 确保场景图与场景描述一致
   - 处理失败重试

4. **质量把控**
   - 检查生成的图片质量
   - 标注需要重新生成的资产
   - 记录问题和建议

5. **提交检查点**
   - 完成生成后提交检查点
   - 展示所有资产供用户审核
   - 根据反馈重新生成

## 可用工具

{tools}

## 工作流程

1. 评估资产数量和生成策略
2. 调用 `generate_character_images` 批量生成角色图
3. 调用 `generate_scene_images` 批量生成场景图
4. 检查生成结果，处理失败项
5. 提交检查点等待审核

## 输出格式

请以 JSON 格式输出你的决策和行动：

```json
{{
  "思考过程": "你的思考和判断",
  "下一步行动": "generate_character_images/generate_scene_images/retry_failed/submit_checkpoint",
  "工具参数": {{}},
  "检查点数据": {{}}  // 仅在 submit_checkpoint 时提供
}}
```

## 生成策略建议

- **小规模**（<10 个角色/场景）：一次性并发生成
- **中等规模**（10-30 个）：分 2-3 批生成
- **大规模**（>30 个）：分批生成，每批 10-15 个

## 质量标准

- 角色图：清晰展示角色特征，符合视觉风格
- 场景图：准确还原场景描述，氛围到位
- 一致性：同一角色/场景在不同分镜中保持一致

## 注意事项

- 监控生成进度，及时发现失败项
- 失败项最多重试 3 次
- 提交检查点前确保所有资产已生成或标记为失败
- 记录每个资产的生成参数（模型、提示词等）
"""

    def get_available_tools(self) -> list:
        return [
            "generate_character_images",
            "generate_scene_images",
            "generate_single_scene_image"
        ]

    async def execute(
        self,
        state: ComicDramaState,
        user_input: Optional[str] = None,
        **kwargs
    ) -> Dict[str, Any]:
        """
        执行资产生成

        流程：
        1. 检查当前阶段
        2. 评估生成策略
        3. 调用工具生成资产
        4. 检查结果并处理失败
        5. 提交检查点
        """
        current_stage = state.get("current_stage", "init")
        logger.info(f"{self.name} 开始执行，当前阶段: {current_stage}")

        if current_stage != "asset_generation":
            return {
                "next_action": "wait",
                "message": f"当前阶段 {current_stage} 不需要资产生成"
            }

        characters = state.get("characters", [])
        scenes = state.get("scenes", [])

        # 检查角色图生成状态
        character_images_needed = any(
            char.get("status") != "completed" for char in characters
        )

        if character_images_needed:
            return {
                "next_action": "generate_character_images",
                "message": f"开始生成 {len(characters)} 个角色的图片"
            }

        # 检查场景图生成状态
        scene_images_needed = any(
            scene.get("status") != "completed" for scene in scenes
        )

        if scene_images_needed:
            return {
                "next_action": "generate_scene_images",
                "message": f"开始生成 {len(scenes)} 个场景的图片"
            }

        # 检查是否有失败项
        failed_characters = [
            char for char in characters if char.get("status") == "failed"
        ]
        failed_scenes = [
            scene for scene in scenes if scene.get("status") == "failed"
        ]

        if failed_characters or failed_scenes:
            return {
                "next_action": "handle_failures",
                "message": f"发现失败项: {len(failed_characters)} 个角色, {len(failed_scenes)} 个场景",
                "failed_characters": failed_characters,
                "failed_scenes": failed_scenes
            }

        # 所有资产已生成，提交检查点
        completed_characters = [
            char for char in characters if char.get("status") == "completed"
        ]
        completed_scenes = [
            scene for scene in scenes if scene.get("status") == "completed"
        ]

        return {
            "next_action": "submit_checkpoint",
            "checkpoint_type": "asset_finalization",
            "checkpoint_data": {
                "characters_count": len(completed_characters),
                "scenes_count": len(completed_scenes),
                "characters": completed_characters,
                "scenes": completed_scenes
            },
            "message": "资产生成完成，请审核资产质量"
        }
