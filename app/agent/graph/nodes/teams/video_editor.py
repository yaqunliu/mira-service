"""
Video Editor Worker Node - 视频编辑 Worker

职责：
1. 生成分镜视频提示词
2. 生成分镜视频
3. 支持单个生成和全部生成

基于 ReActWorkerNode 实现，支持多轮思考和工具调用。
"""

from typing import Dict, Any, List, Optional
from datetime import datetime

from app.agent.state.schemas import ComicDramaState, ProductionStage
from app.agent.graph.nodes.teams.react_worker_base import ReActWorkerNode
from app.core.logger import logger


class VideoEditorNode(ReActWorkerNode):
    """
    视频编辑 Worker Node

    仅处理：
    - shot_video: 分镜视频提示词 + 视频生成

    工作流程：
    1. Thought: 分析任务（视频？提示词/视频？全部/单个？）
    2. Action: 调用查询工具获取分镜信息
    3. Action: 调用模板工具获取提示词模板
    4. Action: 调用知识库工具获取专业知识（视频生成需要）
    5. Thought: Node 自身生成视频提示词
    6. Action: 调用保存工具保存到数据库
    7. Action: 调用提交工具启动生成（如需要）
    8. Action: 调用状态查询工具等待完成
    9. Thought: 汇报生成结果
    """

    USE_REACT = True

    def __init__(self):
        super().__init__(model="Qwen/Qwen-Plus", temperature=0.3)

    def _get_supervisor_params(self, state: ComicDramaState) -> Optional[Dict[str, Any]]:
        """
        从 Supervisor 传递的参数中获取意图信息

        支持任务数组格式：
        {
          "user_intent": "用户意图总结",
          "tasks": [
            {
              "target": "shot_video",
              "actions": ["prompt", "video"],
              "scope": "all/single",
              "shot_id": int (optional)
            }
          ]
        }
        """
        task_params = state.get("task_params", {})
        if task_params:
            logger.info(f"[VideoEditor] 从 Supervisor 获取参数: {task_params}")
            return task_params
        return None

    def _parse_tasks_from_params(self, supervisor_params: Dict[str, Any]) -> List[Dict[str, Any]]:
        """
        从参数中解析任务列表，只保留 shot_video 任务
        """
        if "tasks" in supervisor_params and isinstance(supervisor_params["tasks"], list):
            tasks = supervisor_params["tasks"]
            # 过滤：只保留 shot_video
            filtered_tasks = [
                task for task in tasks
                if task.get("target") == "shot_video"
            ]
            logger.info(f"[VideoEditor] 过滤后任务数: {len(filtered_tasks)}")
            return filtered_tasks

        return []

    def _get_visual_style_for_creation(self, creation_uuid: str) -> str:
        """
        获取创作的视觉风格描述

        Args:
            creation_uuid: 创作 UUID

        Returns:
            风格描述字符串
        """
        from app.agent.config import get_visual_style_description
        from app.db.session import get_sync_session
        from app.models.creation import Creation

        try:
            with get_sync_session() as db:
                creation = db.query(Creation).filter(Creation.uuid == creation_uuid).first()
                if creation and creation.extra_data:
                    visual_style_key = creation.extra_data.get("visual_style", "anime")
                    return get_visual_style_description(visual_style_key)
        except Exception as e:
            logger.warning(f"[VideoEditor] 获取风格失败: {e}")

        return get_visual_style_description("anime")

    def _build_prompt_from_tasks(
        self,
        tasks: List[Dict[str, Any]],
        creation_uuid: str,
        user_intent: str,
        visual_style: str
    ) -> str:
        """根据任务列表构建系统提示词"""
        from app.utils.file_utils import read_prompt_file

        prompt_parts = []
        if user_intent:
            prompt_parts.append(f"# 用户意图\n\n{user_intent}\n")

        task_descriptions = []

        for i, task in enumerate(tasks):
            actions = task.get("actions", ["video"])
            scope = task.get("scope", "all")
            shot_id = task.get("shot_id")

            action_descriptions = {
                "prompt": "提示词",
                "video": "视频",
            }
            action_str = " + ".join([action_descriptions.get(a, a) for a in actions])

            if scope == "single" and shot_id:
                task_descriptions.append(f"{i+1}. 分镜视频（ID={shot_id}）：{action_str}")
            else:
                task_descriptions.append(f"{i+1}. 分镜视频（全部）：{action_str}")

            # 获取视频提示词模板
            template = read_prompt_file("agent_video_prompt_gen.md")
            if template:
                template = template.replace("{{CREATION_UUID}}", creation_uuid)
                template = template.replace("{{SCOPE}}", scope)
                template = template.replace("{{VISUAL_STYLE}}", visual_style)
                if shot_id:
                    template = template.replace("{{SHOT_ID}}", str(shot_id))

                prompt_parts.append(
                    f"\n## 任务 {i+1}：分镜视频（{action_str}）\n{template}"
                )

        # 构建主提示词
        main_prompt = f"# 分镜视频生成任务\n\n"
        main_prompt += f"## 创作项目信息\n\n"
        main_prompt += f"- **创作 UUID**: `{creation_uuid}`\n"
        main_prompt += f"- **视觉风格**: {visual_style}\n\n"
        main_prompt += f"## 任务列表\n\n"
        main_prompt += f"你需要完成以下任务：\n"
        main_prompt += "\n".join(task_descriptions)

        # 检查连续生成模式
        has_continuous = any(
            "prompt" in task.get("actions", []) and
            "video" in task.get("actions", [])
            for task in tasks
        )

        if has_continuous:
            main_prompt += "\n\n## ⚠️ 连续生成模式（关键！）\n"
            main_prompt += "检测到需要同时生成提示词和视频，你必须：\n"
            main_prompt += "1. **首先完成所有视频提示词的生成和保存**（使用 batch_save_shot_video_prompts）\n"
            main_prompt += "2. **然后立即继续生成所有视频**（使用 batch_submit_shot_videos）\n"
            main_prompt += "3. **不要中途停止或返回**，必须连续完成两个步骤！\n"
            main_prompt += "4. 最后使用 query_generation_tasks_status 等待所有视频生成完成\n"
            main_prompt += "5. 汇报完整的生成结果（提示词生成情况 + 视频生成情况）\n"

        main_prompt += "\n".join(prompt_parts)

        return main_prompt

    def get_system_prompt(self, state: ComicDramaState) -> str:
        """
        获取系统提示词

        从 Supervisor 传递的参数中构建提示词
        """
        user_message = state.get("user_message", "")
        creation_uuid = state.get("creation_uuid", "")

        # 获取 Supervisor 参数
        supervisor_params = self._get_supervisor_params(state)
        user_intent = ""
        tasks = []

        if supervisor_params and isinstance(supervisor_params, dict):
            user_intent = supervisor_params.get("user_intent", "")
            tasks = self._parse_tasks_from_params(supervisor_params)

        if not tasks:
            logger.warning(f"[VideoEditor] 未获取到有效任务，返回默认提示词")
            return f"# 分镜视频生成任务\n\n未获取到有效任务参数。\n\n用户消息：{user_message}"

        # 获取视觉风格
        visual_style = self._get_visual_style_for_creation(creation_uuid)

        # 构建提示词
        prompt = self._build_prompt_from_tasks(
            tasks,
            creation_uuid,
            user_intent,
            visual_style
        )

        return prompt

    def get_tools(self) -> List:
        """
        获取可用工具列表

        只保留视频相关的工具
        """
        from app.agent.tools.regenerate_worker_tools import (
            query_all_shots,
            query_generation_tasks_status,
            batch_save_shot_video_prompts,
            batch_submit_shot_videos,
        )
        from app.agent.tools.template_tools import get_prompt_template
        from app.agent.tools.video_knowledge_tools import batch_query_knowledge_for_video

        return [
            # === 1. 查询类 ===
            query_all_shots,
            query_generation_tasks_status,

            # === 2. 提示词模板 ===
            get_prompt_template,

            # === 3. 知识库（批量查询，一次调用替代多次）===
            batch_query_knowledge_for_video,

            # === 4. 批量保存提示词 ===
            batch_save_shot_video_prompts,

            # === 5. 批量提交生成任务 ===
            batch_submit_shot_videos,
        ]

    async def process_result(
        self,
        state: ComicDramaState,
        final_response: str,
        tool_results: List[Dict]
    ) -> Dict[str, Any]:
        """
        处理 ReAct 循环的最终结果

        统计各步骤执行情况，构建响应
        """
        logger.info(f"[VideoEditor] 处理结果，工具调用次数: {len(tool_results)}")

        # 分类统计
        query_count = 0
        template_count = 0
        save_count = 0
        submit_count = 0
        status_query_count = 0
        knowledge_count = 0

        success_count = 0
        failed_count = 0

        for result in tool_results:
            tool_name = result.get("tool", "")
            tool_result = result.get("result", {})

            if "query" in tool_name and "status" not in tool_name:
                query_count += 1
            elif "template" in tool_name:
                template_count += 1
            elif "save" in tool_name:
                save_count += 1
            elif "submit" in tool_name:
                submit_count += 1
            elif "status" in tool_name:
                status_query_count += 1
            elif "knowledge" in tool_name:
                knowledge_count += 1

            if tool_result.get("success"):
                success_count += 1
            else:
                failed_count += 1

        # 构建状态更新
        production_progress = dict(state.get("production_progress", {}))

        # 判断是否成功
        # 如果提交了视频任务（submit_count > 0），则认为成功
        # 如果没有任何成功的工具调用，则认为失败
        is_success = submit_count > 0 or (success_count > 0 and failed_count == 0)

        logger.info(f"[VideoEditor] 结果统计: 成功={success_count}, 失败={failed_count}, 提交视频={submit_count}")
        logger.info(f"[VideoEditor] 判断结果: is_success={is_success}")

        # 如果失败，返回错误状态
        if not is_success:
            error_msg = "视频生成失败：未能成功提交视频生成任务或所有工具调用均失败"
            logger.error(f"[VideoEditor] {error_msg}")

            # 不更新 production_stage，保持当前阶段
            return {
                "response_text": final_response if final_response else error_msg,
                "production_progress": production_progress,
                # 不设置 production_stage，保持原状态
                "tool_usage_summary": {
                    "query_count": query_count,
                    "template_count": template_count,
                    "save_count": save_count,
                    "submit_count": submit_count,
                    "status_query_count": status_query_count,
                    "knowledge_count": knowledge_count,
                    "success_count": success_count,
                    "failed_count": failed_count,
                },
                "worker_result": {
                    "worker": "video_editor",
                    "response_text": final_response if final_response else error_msg,
                    "success": False,
                    "completed": True,  # 虽然失败了，但执行已完成
                    "error": error_msg,
                },
            }

        # 成功：视频生成完成，进入 COMPLETED 阶段
        production_progress["video_generation"] = {
            "status": "completed",
            "submit_count": submit_count,
            "save_count": save_count,
        }

        result = {
            "response_text": final_response,
            "production_progress": production_progress,
            "production_stage": ProductionStage.COMPLETED.value,  # 转换为字符串
            "generated_videos": submit_count,  # 添加视频数量统计
            "tool_usage_summary": {
                "query_count": query_count,
                "template_count": template_count,
                "save_count": save_count,
                "submit_count": submit_count,
                "status_query_count": status_query_count,
                "knowledge_count": knowledge_count,
                "success_count": success_count,
                "failed_count": failed_count,
            },
            "worker_result": {
                "worker": "video_editor",
                "response_text": final_response,
                "production_stage": ProductionStage.COMPLETED.value,
                "success": True,
                "completed": True,
            },
        }

        return result


class FinalEditorNode:
    """
    剪辑合成 Node

    职责：完成最终合成
    """

    async def run(self, state: ComicDramaState) -> Dict[str, Any]:
        """执行剪辑合成"""
        logger.info("[FinalEditor] 执行剪辑合成")

        response_text = "🎉 恭喜！您的漫剧制作完成！"
        return {
            "response_text": response_text,
            "production_stage": ProductionStage.COMPLETED,
            "worker_result": {"worker": "final_editor", "completed": True, "response_text": response_text},
            "board_actions": [
                {"type": "switch_view", "target": "preview"},
            ],
        }


# 便捷函数，用于直接调用
async def generate_video_worker(state: ComicDramaState) -> Dict[str, Any]:
    """
    视频编辑 Worker 便捷函数

    用于在 Graph 中直接调用
    """
    node = VideoEditorNode()
    return await node.run(state)


async def finalize_editing(state: ComicDramaState) -> Dict[str, Any]:
    """LangGraph node 函数"""
    node = FinalEditorNode()
    return await node.run(state)
