"""
Video Prompt Builder Node - 视频提示词构建 Node

职责：
在分镜拆分之后，为每个分镜构建带 @引用语法的视频提示词。
分析相邻分镜的连续性，决定使用"视频延长"还是"新视频"模式。
输出结构化的视频提示词和资产引用列表，供新的视频生成 API 消费。

基于 ReActWorkerNode 实现，按 shot_number 顺序处理所有分镜。
"""

from typing import Dict, Any, List

from app.agent.state.schemas import ComicDramaState
from app.agent.graph.nodes.teams.react_worker_base import ReActWorkerNode
from app.core.logger import logger


class VideoPromptBuilderNode(ReActWorkerNode):
    """
    视频提示词构建 Node (ReAct 版本)

    工作流程：
    1. 调用 query_all_shots 获取所有分镜、角色、场景数据
    2. 按 shot_number 顺序遍历每个分镜
    3. 对每个分镜：
       a. 分析与前一个分镜的连续性（analyze_shot_continuity）
       b. 决定 extend（视频延长）或 new（新视频）模式
       c. 构建带 @引用的视频提示词
       d. 保存结果（save_video_prompt_result）
    4. 汇总所有分镜的处理结果
    """

    USE_REACT = True

    def __init__(self):
        super().__init__(model="Qwen/Qwen-Plus", temperature=0.3)

    def get_system_prompt(self, state: ComicDramaState) -> str:
        """
        加载系统提示词模板并注入动态上下文
        """
        creation_uuid = state.get("creation_uuid", "")
        characters = state.get("characters", [])
        scenes = state.get("scenes", [])

        logger.info("=" * 80)
        logger.info("[VIDEO_PROMPT_BUILDER] ========== 开始构建系统提示词 ==========")
        logger.info(f"[VIDEO_PROMPT_BUILDER] creation_uuid: {creation_uuid}")
        logger.info(f"[VIDEO_PROMPT_BUILDER] 角色数: {len(characters)}, 场景数: {len(scenes)}")

        # 构建角色列表文本
        if characters:
            character_lines = []
            for c in characters:
                cid = c.get("character_id", "?")
                name = c.get("name", "未知")
                desc = c.get("description", c.get("appearance", ""))[:50]
                has_image = "有图" if c.get("image_url") else "无图"
                character_lines.append(f"- {name}（ID: {cid}，{has_image}）{desc}")
            character_list = "\n".join(character_lines)
        else:
            character_list = "（暂无角色数据，请先通过 query_all_shots 获取）"

        # 构建场景列表文本
        if scenes:
            scene_lines = []
            for s in scenes:
                sid = s.get("scene_id", "?")
                title = s.get("name", s.get("title", "未知"))
                location = s.get("location", "")
                has_image = "有图" if s.get("image_url") else "无图"
                scene_lines.append(f"- {title}（ID: {sid}，{has_image}）{location}")
            scene_list = "\n".join(scene_lines)
        else:
            scene_list = "（暂无场景数据，请先通过 query_all_shots 获取）"

        # 加载模板文件
        from app.utils.file_utils import read_prompt_file
        try:
            template = read_prompt_file("video_prompt_builder.md")
        except FileNotFoundError:
            logger.warning("[VIDEO_PROMPT_BUILDER] 模板文件不存在，使用内联模板")
            template = self._get_fallback_prompt()

        # 注入动态变量
        prompt = template.format(
            creation_uuid=creation_uuid,
            total_shots="（通过 query_all_shots 获取）",
            character_list=character_list,
            scene_list=scene_list,
        )

        logger.info("[VIDEO_PROMPT_BUILDER] 系统提示词构建完成")
        return prompt

    def _get_fallback_prompt(self) -> str:
        """内联备用提示词（模板文件不存在时使用）"""
        return """# 视频提示词构建师

你的任务是为每个分镜构建带 @引用的视频提示词。

创作 UUID: {creation_uuid}

角色列表:
{character_list}

场景列表:
{scene_list}

## 流程
1. 调用 query_all_shots 获取分镜数据
2. 按 shot_number 顺序处理每个分镜
3. 对每个分镜调用 analyze_shot_continuity 分析连续性
4. 构建提示词并调用 save_video_prompt_result 保存

## @引用规则
- @角色名 → 角色形象图
- @场景名 → 场景图
- @分镜N → 第N个分镜的视频

## 模式
- extend: 与前一分镜连续（同场景+角色重叠）→ 为@分镜N向后延长Xs，...
- new: 场景变化/第一个分镜 → 把@角色名作为画面主体，场景参考@场景名，...
"""

    def get_tools(self) -> List:
        """获取可用工具列表"""
        from app.agent.tools.regenerate_worker_tools import query_all_shots
        from app.agent.tools.video_prompt_builder_tools import (
            analyze_shot_continuity,
            save_video_prompt_result,
        )
        from app.agent.tools.video_knowledge_tools import (
            batch_query_knowledge_for_video,
            query_camera_techniques,
            query_composition_rules,
        )

        return [
            query_all_shots,
            analyze_shot_continuity,
            save_video_prompt_result,
            # 知识库工具 - 查询专业运镜、构图、灯光、转场技巧
            batch_query_knowledge_for_video,
            query_camera_techniques,
            query_composition_rules,
        ]

    async def process_result(
        self, state: ComicDramaState, final_response: str, tool_results: List[Dict]
    ) -> Dict[str, Any]:
        """
        处理 ReAct 循环的最终结果

        统计各分镜的处理情况，构建响应
        """
        logger.info("=" * 80)
        logger.info("[VIDEO_PROMPT_BUILDER] ========== 处理结果 ==========")
        logger.info(f"[VIDEO_PROMPT_BUILDER] 工具调用次数: {len(tool_results)}")

        # 统计
        analyze_count = 0
        save_count = 0
        save_success = 0
        save_failed = 0
        extend_count = 0
        new_count = 0

        for result in tool_results:
            tool_name = result.get("tool", "")
            tool_result = result.get("result", {})

            if "analyze_shot_continuity" in tool_name:
                analyze_count += 1
            elif "save_video_prompt_result" in tool_name:
                save_count += 1
                if tool_result.get("success"):
                    save_success += 1
                    mode = tool_result.get("generation_mode", "")
                    if mode == "extend":
                        extend_count += 1
                    elif mode == "new":
                        new_count += 1
                else:
                    save_failed += 1

        # 构建响应
        response_text = f"视频提示词构建完成！\n\n"
        response_text += f"统计：\n"
        response_text += f"- 连续性分析: {analyze_count} 次\n"
        response_text += f"- 提示词保存: {save_success} 成功 / {save_failed} 失败\n"
        response_text += f"- 延长模式(extend): {extend_count} 个分镜\n"
        response_text += f"- 新视频模式(new): {new_count} 个分镜\n"

        result = {
            "success": save_success > 0 and save_failed == 0,
            "response_text": response_text,
            "worker_result": {
                "worker": "video_prompt_builder",
                "summary": f"构建了 {save_success} 个分镜的视频提示词（extend: {extend_count}, new: {new_count}）",
                "success": save_success > 0,
                "completed": True,
                "response_text": response_text,
            },
        }

        logger.info(f"[VIDEO_PROMPT_BUILDER] ========== 完成处理 ==========")
        logger.info(f"[VIDEO_PROMPT_BUILDER] success: {result['success']}")
        logger.info(f"[VIDEO_PROMPT_BUILDER] save_success: {save_success}, save_failed: {save_failed}")
        logger.info(f"[VIDEO_PROMPT_BUILDER] extend: {extend_count}, new: {new_count}")
        logger.info("=" * 80)

        return result


# 便捷函数
async def video_prompt_builder_worker(state: ComicDramaState) -> Dict[str, Any]:
    """LangGraph node 函数"""
    node = VideoPromptBuilderNode()
    return await node.run(state)
