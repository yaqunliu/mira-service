"""
视频编辑师 Node - Video Editor

负责为分镜生成视频片段。
1. 使用 LLM 批量生成视频提示词和选择生成模式
2. 调用 tool 保存提示词
3. 调用 tool 创建视频生成任务
4. 轮询等待完成
"""

import asyncio
import json
from pathlib import Path
from typing import Dict, Any, List

from langchain_core.messages import HumanMessage
from langchain_openai import ChatOpenAI

from app.agent.state.schemas import ComicDramaState, ProductionStage
from app.core.config import settings
from app.core.logger import logger


class VideoEditorNode:
    """
    视频编辑师 Node
    
    职责：
    1. 查询分镜进度（断点恢复）
    2. 使用 LLM 批量生成视频提示词和模式选择
    3. 调用 tool 创建视频生成任务
    4. 轮询等待任务完成
    """
    
    # LLM 提示词模板名称
    PROMPT_TEMPLATE_NAME = "agent_video_prompt_gen"
    
    # 轮询配置
    POLL_INTERVAL = 5  # 秒
    MAX_POLL_TIME = 3600  # 最大轮询时间（1小时）
    HEARTBEAT_INTERVAL = 30  # 心跳间隔（秒）
    
    def __init__(self):
        """初始化 LLM"""
        self.llm = ChatOpenAI(
            model="Qwen/Qwen-Plus",  # 与图片提示词生成一致
            api_key=settings.OPENAI_API_KEY,
            base_url=settings.OPENAI_BASE_URL,
            temperature=0.3,
            timeout=120,
            max_retries=2,
        )
    
    async def _check_progress(self, creation_uuid: str) -> Dict[str, Any]:
        """
        检查视频生成进度（支持断点恢复）
        
        Returns:
            {
                "total_shots": int,
                "with_video_prompt": int,
                "with_video": int,
                "needs_prompt": [shot_data...],
                "needs_video": [shot_data...],
                "all_shots": [shot_data...],
            }
        """
        from app.agent.tools.db_tools import query_shots
        
        result = await query_shots.ainvoke({
            "creation_uuid": creation_uuid,
            "include_details": True,
        })
        
        if result.get("error"):
            raise Exception(f"查询分镜失败: {result.get('error')}")
        
        shots = result.get("shots", [])
        
        needs_prompt = []
        needs_video = []
        with_video_prompt = 0
        with_video = 0
        
        for shot in shots:
            extra_data = shot.get("extra_data", {}) or {}
            video_prompt = extra_data.get("video_prompt")
            video_url = shot.get("video_url")
            
            # 准备 shot 数据
            shot_data = {
                "shot_id": shot.get("shot_id"),
                "description": shot.get("description", ""),
                "image_prompt": shot.get("image_prompt", ""),
                "end_frame_prompt": extra_data.get("end_frame_prompt", ""),
                "narration": shot.get("narration", []),
                "duration": shot.get("video_duration", 5),
                "has_start_image": bool(shot.get("image_url")),
                "has_end_image": bool(extra_data.get("end_frame_image_url")),
                "characters": shot.get("characters", []),
            }
            
            if video_url:
                with_video += 1
            elif video_prompt:
                with_video_prompt += 1
                needs_video.append(shot_data)
            else:
                needs_prompt.append(shot_data)
        
        return {
            "total_shots": len(shots),
            "with_video_prompt": with_video_prompt,
            "with_video": with_video,
            "needs_prompt": needs_prompt,
            "needs_video": needs_video,
            "all_shots": shots,
        }
    
    def _load_template(self, template_name: str) -> str:
        """加载 prompt 模板文件"""
        # 计算 prompt 目录路径
        current_file = Path(__file__)
        project_root = current_file.parent.parent.parent.parent.parent  # 从 nodes/teams 往上5层到项目根目录
        prompt_dir = project_root / "prompt"
        
        template_path = prompt_dir / f"{template_name}.md"
        if not template_path.exists():
            raise FileNotFoundError(f"模板文件不存在: {template_path}")
        
        return template_path.read_text(encoding="utf-8")
    
    async def _generate_video_prompts(self, shots: List[Dict]) -> List[Dict]:
        """
        使用 LLM 批量生成视频提示词
        
        Args:
            shots: 需要生成提示词的分镜列表
            
        Returns:
            [{shot_id, video_prompt, generation_mode, mode_reason}, ...]
        """
        if not shots:
            return []
        
        logger.info(f"[VideoEditor] 开始生成 {len(shots)} 个分镜的视频提示词")
        
        # 加载提示词模板
        try:
            template = self._load_template(self.PROMPT_TEMPLATE_NAME)
        except Exception as e:
            logger.error(f"[VideoEditor] 加载模板失败: {e}")
            raise Exception(f"加载视频提示词模板失败: {e}")
        
        # 准备输入数据
        shots_data = json.dumps(shots, ensure_ascii=False, indent=2)
        prompt = template.replace("{{SHOTS_DATA}}", shots_data)
        
        # 使用 langchain 调用 LLM（与其他 node 保持一致）
        logger.info("[VideoEditor] 调用 LLM 生成视频提示词 (stream 模式)...")
        content_chunks = []
        async for chunk in self.llm.astream([HumanMessage(content=prompt)]):
            chunk_text = chunk.content
            if chunk_text:
                content_chunks.append(chunk_text)
        
        response_content = "".join(content_chunks).strip()
        
        if not response_content:
            raise Exception("LLM 返回了空的响应")
        
        # 解析 JSON
        prompts = self._parse_prompts_response(response_content)
        
        logger.info(f"[VideoEditor] 成功生成 {len(prompts)} 个视频提示词")
        
        return prompts
    
    def _parse_prompts_response(self, response_content: str) -> List[Dict]:
        """解析 LLM 返回的 JSON 响应"""
        # 尝试提取 JSON 块
        json_content = response_content
        
        if "```json" in response_content:
            start = response_content.find("```json") + 7
            end = response_content.find("```", start)
            if end > start:
                json_content = response_content[start:end].strip()
        elif "```" in response_content:
            start = response_content.find("```") + 3
            end = response_content.find("```", start)
            if end > start:
                json_content = response_content[start:end].strip()
        
        try:
            prompts = json.loads(json_content)
            if not isinstance(prompts, list):
                raise ValueError("期望返回 JSON 数组")
            return prompts
        except json.JSONDecodeError as e:
            logger.error(f"[VideoEditor] JSON 解析失败: {e}")
            logger.error(f"[VideoEditor] 原始响应: {response_content[:500]}")
            raise Exception(f"JSON 解析失败: {e}")
    
    async def _poll_task_completion(
        self, 
        group_id: str, 
        shot_task_ids: Dict[int, str],
        state: ComicDramaState,
    ) -> Dict[str, Any]:
        """
        轮询等待任务完成
        
        Args:
            group_id: Celery group ID
            shot_task_ids: {shot_id: task_id, ...}
            state: 当前状态
            
        Returns:
            最终状态
        """
        from app.agent.tools.agent_generation_tools import check_task_group_status
        
        start_time = asyncio.get_event_loop().time()
        last_heartbeat = start_time
        
        while True:
            current_time = asyncio.get_event_loop().time()
            elapsed = current_time - start_time
            
            # 超时检查
            if elapsed > self.MAX_POLL_TIME:
                logger.warning(f"[VideoEditor] 轮询超时: elapsed={elapsed}s")
                return {
                    "success": False,
                    "error": "视频生成超时",
                    "elapsed": elapsed,
                }
            
            # 查询任务状态
            status = await check_task_group_status.ainvoke({
                "group_id": group_id,
                "shot_task_ids": shot_task_ids,
            })
            
            all_done = status.get("all_done", False)
            completed = status.get("completed", 0)
            failed = status.get("failed", 0)
            pending = status.get("pending", 0)
            total = status.get("total", 0)
            
            logger.info(f"[VideoEditor] 轮询状态: completed={completed}/{total}, failed={failed}, pending={pending}")
            
            if all_done:
                return {
                    "success": failed == 0,
                    "completed": completed,
                    "failed": failed,
                    "total": total,
                    "elapsed": elapsed,
                    "failed_shots": status.get("failed_shots"),
                }
            
            # 心跳日志
            if current_time - last_heartbeat > self.HEARTBEAT_INTERVAL:
                logger.info(f"[VideoEditor] 心跳: 已等待 {int(elapsed)}s, 完成 {completed}/{total}")
                last_heartbeat = current_time
            
            # 等待后继续轮询
            await asyncio.sleep(self.POLL_INTERVAL)
    
    async def run(self, state: ComicDramaState) -> Dict[str, Any]:
        """
        执行视频生成流程
        
        完整流程：
        1. 检查进度（断点恢复）
        2. 生成视频提示词（如果需要）
        3. 创建视频生成任务
        4. 轮询等待完成
        5. 返回结果
        """
        creation_uuid = state.get("creation_uuid")
        
        try:
            logger.info(f"[VideoEditor] 开始执行: creation_uuid={creation_uuid}")
            
            # Step 1: 检查进度
            progress = await self._check_progress(creation_uuid)
            
            total_shots = progress["total_shots"]
            with_video = progress["with_video"]
            needs_prompt = progress["needs_prompt"]
            needs_video = progress["needs_video"]
            
            logger.info(f"[VideoEditor] 进度: total={total_shots}, with_video={with_video}, "
                       f"needs_prompt={len(needs_prompt)}, needs_video={len(needs_video)}")
            
            # 如果所有视频都已生成
            if with_video == total_shots:
                response_text = "✅ 所有分镜视频已生成完成！请预览确认。"
                return {
                    "response_text": response_text,
                    "production_stage": ProductionStage.VIDEO_READY,
                    "worker_result": {"worker": "video_editor", "completed": True, "response_text": response_text},
                    "board_actions": [
                        {"type": "switch_view", "target": "preview"},
                    ],
                }
            
            # Step 2: 生成视频提示词（如果有需要的）
            from app.agent.tools.db_tools import save_video_prompts
            
            if needs_prompt:
                prompts = await self._generate_video_prompts(needs_prompt)
                
                # 保存提示词
                save_result = await save_video_prompts.ainvoke({
                    "creation_uuid": creation_uuid,
                    "prompts": prompts,
                })
                
                if not save_result.get("success"):
                    raise Exception(f"保存视频提示词失败: {save_result.get('error')}")
                
                logger.info(f"[VideoEditor] 保存了 {save_result.get('saved_count')} 个视频提示词")
                
                # 需要生成视频的分镜 = 刚生成提示词的 + 之前已有提示词但没视频的
                needs_video.extend([{"shot_id": p["shot_id"]} for p in prompts])
            
            # Step 3: 创建视频生成任务
            if not needs_video and not needs_prompt:
                # 所有都已完成
                response_text = "✅ 所有分镜视频已生成完成！"
                return {
                    "response_text": response_text,
                    "production_stage": ProductionStage.VIDEO_READY,
                    "worker_result": {"worker": "video_editor", "completed": True, "response_text": response_text},
                }
            
            from app.agent.tools.agent_generation_tools import generate_shot_videos
            
            task_result = await generate_shot_videos.ainvoke({
                "creation_uuid": creation_uuid,
            })
            
            if not task_result.get("success"):
                raise Exception(f"创建视频生成任务失败: {task_result.get('error')}")
            
            group_id = task_result.get("group_id")
            shot_task_ids = task_result.get("shot_task_ids", {})
            shot_count = task_result.get("shot_count", 0)
            
            if shot_count == 0:
                response_text = "✅ 所有分镜视频已生成完成！"
                return {
                    "response_text": response_text,
                    "production_stage": ProductionStage.VIDEO_READY,
                    "worker_result": {"worker": "video_editor", "completed": True, "response_text": response_text},
                }
            
            logger.info(f"[VideoEditor] 已创建 {shot_count} 个视频生成任务, group_id={group_id}")
            
            # Step 4: 轮询等待完成
            poll_result = await self._poll_task_completion(group_id, shot_task_ids, state)
            
            # Step 5: 返回结果
            if poll_result.get("success"):
                response_text = f"""✅ 视频生成完成！

🎬 **共生成 {poll_result.get('completed')} 个分镜视频**
⏱️ 耗时 {int(poll_result.get('elapsed', 0))} 秒

请预览确认视频效果。"""
                return {
                    "response_text": response_text,
                    "production_stage": ProductionStage.VIDEO_READY,
                    "worker_result": {"worker": "video_editor", "completed": True, "response_text": response_text},
                    "board_actions": [
                        {"type": "switch_view", "target": "preview"},
                        {"type": "refresh"},
                    ],
                }
            else:
                failed_count = poll_result.get("failed", 0)
                completed = poll_result.get("completed", 0)
                failed_shots = poll_result.get("failed_shots", [])
                
                error_msg = "部分视频生成失败"
                if failed_shots:
                    error_msg += "：\n" + "\n".join([
                        f"- 分镜 {s['shot_id']}: {s.get('error', '未知错误')}" 
                        for s in failed_shots[:3]
                    ])
                
                return {
                    "response_text": f"""⚠️ 视频生成部分完成

✅ 成功: {completed} 个
❌ 失败: {failed_count} 个

{error_msg}

您可以稍后重试失败的分镜。""",
                    "production_stage": ProductionStage.VIDEO_GENERATING,
                    "errors": [{"message": error_msg}],
                }
            
        except Exception as e:
            logger.error(f"[VideoEditor] 执行失败: {e}")
            return {
                "response_text": f"视频生成过程中出现错误：{str(e)}",
                "production_stage": ProductionStage.STORYBOARD_READY,
                "errors": [{"message": str(e)}],
            }


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


# 便捷函数
async def generate_video(state: ComicDramaState) -> Dict[str, Any]:
    """LangGraph node 函数"""
    node = VideoEditorNode()
    return await node.run(state)


async def finalize_editing(state: ComicDramaState) -> Dict[str, Any]:
    """LangGraph node 函数"""
    node = FinalEditorNode()
    return await node.run(state)
