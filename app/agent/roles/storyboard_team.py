"""
分镜导演 - Storyboard Director

负责分镜图片和视频的生成和质量把控
"""

from typing import Dict, Any, Optional
from app.agent.roles.base import BaseAgent
from app.agent.state.schemas import ComicDramaState
from app.core.logger import logger


class StoryboardDirectorAgent(BaseAgent):
    """
    分镜导演 Agent

    职责：
    1. 规划分镜生成策略（批次大小、优先级）
    2. 调用工具生成分镜图片（首帧/尾帧）
    3. 生成视频提示词
    4. 调用工具生成分镜视频
    5. 批次审核（每 N 个分镜提交一次检查点）
    """

    @property
    def name(self) -> str:
        return "分镜导演"

    @property
    def role(self) -> str:
        return "负责分镜图片和视频的生成，把控分镜质量和节奏"

    @property
    def system_prompt(self) -> str:
        return """你是一位专业的分镜导演，负责漫剧创作项目的分镜生成工作。

## 你的职责

1. **规划分镜策略**
   - 评估分镜总数和复杂度
   - 决定批次大小（建议每批 5-10 个）
   - 确定优先级（关键分镜优先）

2. **分镜图片生成**
   - 调用工具生成分镜图片（首帧/尾帧）
   - 确保图片与分镜描述一致
   - 处理角色定位和场景融合

3. **视频提示词生成**
   - 为每个分镜生成视频提示词
   - 结合首尾帧、对话、运镜信息
   - 确保视频连贯性

4. **分镜视频生成**
   - 调用工具生成分镜视频
   - 监控生成进度
   - 处理失败重试

5. **批次审核**
   - 每生成 N 个分镜提交一次检查点
   - 展示分镜图片和视频供用户审核
   - 根据反馈调整后续分镜

## 可用工具

{tools}

## 工作流程

1. 评估分镜数量和批次大小
2. 批次生成分镜图片：
   - 调用 `generate_shot_images_batch`
3. 批次生成视频提示词：
   - 调用 `generate_video_prompt`
4. 批次生成分镜视频：
   - 调用 `generate_scene_videos` 或 `generate_single_shot_video`
5. 提交批次检查点等待审核
6. 根据反馈继续下一批或调整

## 输出格式

请以 JSON 格式输出你的决策和行动：

```json
{{
  "思考过程": "你的思考和判断",
  "下一步行动": "generate_shot_images/generate_video_prompts/generate_videos/submit_checkpoint",
  "当前批次": 1,
  "总批次": 5,
  "工具参数": {{}},
  "检查点数据": {{}}
}}
```

## 批次审核策略

- **配置参数**：`AGENT_STORYBOARD_BATCH_SIZE`（默认 5）
- **审核时机**：每完成 N 个分镜提交一次检查点
- **审核内容**：展示该批次的分镜图片和视频
- **用户反馈**：
  - 全部通过：继续下一批
  - 部分通过：重新生成驳回的分镜
  - 全部驳回：调整策略重新生成

## 质量标准

- **分镜图片**：
  - 准确还原分镜描述
  - 角色定位合理
  - 场景融合自然
  - 首尾帧连贯

- **分镜视频**：
  - 运镜流畅
  - 符合视频提示词
  - 时长准确
  - 画面质量高

## 注意事项

- 分镜生成耗时较长，合理设置超时时间
- 监控生成进度，及时发现失败项
- 失败项最多重试 3 次
- 批次审核时清晰标注批次信息
- 记录用户反馈用于优化后续生成
"""

    def get_available_tools(self) -> list:
        return [
            "generate_shot_images_batch",
            "generate_single_shot_image",
            "generate_video_prompt",
            "generate_scene_videos",
            "generate_single_shot_video"
        ]

    async def execute(
        self,
        state: ComicDramaState,
        user_input: Optional[str] = None,
        **kwargs
    ) -> Dict[str, Any]:
        """
        执行分镜生成

        流程：
        1. 检查当前阶段
        2. 确定当前批次
        3. 生成分镜图片 → 视频提示词 → 视频
        4. 提交批次检查点
        """
        current_stage = state.get("current_stage", "init")
        logger.info(f"{self.name} 开始执行，当前阶段: {current_stage}")

        if current_stage != "storyboard_creation":
            return {
                "next_action": "wait",
                "message": f"当前阶段 {current_stage} 不需要分镜生成"
            }

        storyboards = state.get("storyboards", [])
        batch_size = state.get("config", {}).get("storyboard_batch_size", 5)

        # 检查分镜图片生成状态
        images_needed = any(
            not sb.get("image_url") for sb in storyboards
        )

        if images_needed:
            return {
                "next_action": "generate_shot_images_batch",
                "message": f"开始生成分镜图片"
            }

        # 检查视频提示词生成状态
        prompts_needed = any(
            not sb.get("video_prompt") for sb in storyboards
            if sb.get("image_url")  # 只有图片已生成的才需要提示词
        )

        if prompts_needed:
            return {
                "next_action": "generate_video_prompts",
                "message": "开始生成视频提示词"
            }

        # 检查视频生成状态
        videos_needed = any(
            not sb.get("video_url") for sb in storyboards
            if sb.get("video_prompt")  # 只有提示词已生成的才需要视频
        )

        if videos_needed:
            return {
                "next_action": "generate_videos",
                "message": "开始生成分镜视频"
            }

        # 计算已完成的批次
        completed_count = len([
            sb for sb in storyboards if sb.get("video_url")
        ])
        current_batch = (completed_count // batch_size) + 1
        total_batches = (len(storyboards) + batch_size - 1) // batch_size

        # 检查是否需要提交批次检查点
        if completed_count % batch_size == 0 and completed_count < len(storyboards):
            batch_start = completed_count - batch_size
            batch_end = completed_count
            batch_storyboards = storyboards[batch_start:batch_end]

            return {
                "next_action": "submit_checkpoint",
                "checkpoint_type": "storyboard_batch",
                "current_batch": current_batch - 1,
                "total_batches": total_batches,
                "checkpoint_data": {
                    "batch_number": current_batch - 1,
                    "total_batches": total_batches,
                    "storyboards": batch_storyboards,
                    "message": f"第 {current_batch - 1}/{total_batches} 批分镜已完成，请审核"
                },
                "message": f"批次 {current_batch - 1} 完成，提交审核"
            }

        # 所有分镜已完成
        if completed_count == len(storyboards):
            return {
                "next_action": "complete",
                "message": "所有分镜生成完成"
            }

        return {
            "next_action": "continue",
            "message": f"继续生成分镜 ({completed_count}/{len(storyboards)})"
        }
