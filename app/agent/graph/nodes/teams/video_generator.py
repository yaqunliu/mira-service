"""
Video Generator Node - 视频生成 Node

职责：
读取 shot.extra_data 中的 video_prompt 和 references，
调用视频生成 API（Seedance 2.0）为每个分镜生成视频。

当前为占位实现，使用 DEBUG_GENERATE_VIDEO_URL 返回固定视频地址。
后续替换为真实 API 调用 + Celery Task。
"""

from typing import Dict, Any, List

from app.agent.state.schemas import ComicDramaState, ProductionStage
from app.agent.graph.nodes.teams.react_worker_base import ReActWorkerNode
from app.core.logger import logger


class VideoGeneratorNode(ReActWorkerNode):
    """
    视频生成 Node (ReAct 版本)

    工作流程：
    1. 调用 query_all_shots 获取所有分镜数据
    2. 筛选出有 video_prompt 但未生成视频的分镜
    3. 调用 batch_submit_video_generation 批量提交视频生成
    4. 汇总结果
    """

    USE_REACT = True

    def __init__(self):
        super().__init__(model="Qwen/Qwen-Plus", temperature=0.1)

    def get_system_prompt(self, state: ComicDramaState) -> str:
        creation_uuid = state.get("creation_uuid", "")

        logger.info("=" * 80)
        logger.info("[VIDEO_GENERATOR] ========== 开始构建系统提示词 ==========")
        logger.info(f"[VIDEO_GENERATOR] creation_uuid: {creation_uuid}")

        return f"""# 视频生成执行器

你的任务是为所有已构建视频提示词的分镜提交视频生成任务。

## 当前创作信息
- 创作 UUID: {creation_uuid}

## 执行流程

### Step 1: 获取所有分镜数据
- 调用 `query_all_shots`，传入 creation_uuid="{creation_uuid}"
- 确认哪些分镜已有 video_prompt（在 extra_data 中）

### Step 2: 批量提交视频生成
- 调用 `batch_submit_video_generation`，传入 creation_uuid="{creation_uuid}"
- 该工具会自动筛选有 video_prompt 但未生成视频的分镜
- 等待工具返回结果

### Step 3: 输出总结
- 报告成功/失败数量
- 列出每个分镜的生成结果

## 注意事项
1. 如果没有需要生成视频的分镜，直接报告即可
2. 如果部分分镜生成失败，报告失败的分镜和错误原因
3. 不要自己生成提示词，提示词由 video_prompt_builder 负责
"""

    def get_tools(self) -> List:
        """获取可用工具列表"""
        from app.agent.tools.regenerate_worker_tools import query_all_shots
        from app.agent.tools.video_generator_tools import (
            submit_video_generation,
            batch_submit_video_generation,
        )

        return [
            query_all_shots,
            submit_video_generation,
            batch_submit_video_generation,
        ]

    async def process_result(
        self, state: ComicDramaState, final_response: str, tool_results: List[Dict]
    ) -> Dict[str, Any]:
        """处理 ReAct 循环的最终结果"""
        logger.info("=" * 80)
        logger.info("[VIDEO_GENERATOR] ========== 处理结果 ==========")
        logger.info(f"[VIDEO_GENERATOR] 工具调用次数: {len(tool_results)}")

        submit_count = 0
        success_count = 0
        failed_count = 0
        pending_count = 0

        for result in tool_results:
            tool_name = result.get("tool", "")
            tool_result = result.get("result", {})

            if "batch_submit_video_generation" in tool_name:
                submit_count = tool_result.get("total", 0)
                completed_count = tool_result.get("completed", 0)
                failed_count = tool_result.get("failed", 0)
                pending_count = tool_result.get("pending", 0)
            elif "submit_video_generation" in tool_name:
                submit_count += 1
                if tool_result.get("success"):
                    success_count += 1
                else:
                    failed_count += 1

        response_text = f"视频生成完成！\n\n"
        response_text += f"统计：\n"
        response_text += f"- 提交生成: {submit_count} 个分镜\n"
        response_text += f"- 成功: {completed_count}\n"
        response_text += f"- 失败: {failed_count}\n"
        if pending_count > 0:
            response_text += f"- 待处理: {pending_count}\n"

        result = {
            "success": completed_count > 0,
            "response_text": response_text,
            "generated_videos": completed_count,
            "production_stage": ProductionStage.VIDEO_READY if completed_count > 0 else None,
            "worker_result": {
                "worker": "video_generator",
                "summary": f"生成了 {completed_count} 个分镜视频",
                "success": completed_count > 0,
                "completed": True,
                "response_text": response_text,
            },
        }

        logger.info(f"[VIDEO_GENERATOR] ========== 完成处理 ==========")
        logger.info(f"[VIDEO_GENERATOR] success: {result['success']}, videos: {success_count}")
        logger.info("=" * 80)

        return result


# 便捷函数
async def video_generator_worker(state: ComicDramaState) -> Dict[str, Any]:
    """LangGraph node 函数"""
    node = VideoGeneratorNode()
    return await node.run(state)
