"""
Agent 任务执行处理器

识别用户意图并调用相应的 Celery 任务
支持通过 SSE 流式返回任务执行状态
"""

from typing import Dict, Any, List, Optional, AsyncIterator
from datetime import datetime, timezone
import uuid
import json
import asyncio
from celery.result import AsyncResult

from app.core.logger import logger
from app.core.celery_app import celery_app
from app.tasks.creation_task import character_analysis_task, scene_analysis_task, shot_analysis_task
from app.tasks.character_task import generate_character_image_task
from app.tasks.step4_scene_image_gen_task import batch_generate_scene_images_task
from app.tasks.step8_video_gen_task import generate_all_videos_task as generate_all_videos_v2_task
from app.tasks.shot_task import generate_creation_shots_task


TASK_INTENT_PROMPT = """判断用户消息的意图，只返回意图类型（不需要解释）。

意图类型：
- analyze_character: 要求分析角色、从剧本中提取角色（包含"分析角色"、"角色分析"、"提取角色"、"有哪些角色"）
- analyze_scene: 要求分析场景、从剧本中提取场景（包含"分析场景"、"场景分析"、"提取场景"、"有哪些场景"）
- analyze_shot: 要求分析分镜、从剧本中提取镜头（包含"分析分镜"、"分镜分析"、"提取分镜"、"有哪些镜头"）
- generate_character_images: 要求生成角色图片（包含"生成角色图片"、"角色图片"、"角色图"）
- generate_scene_images: 要求生成场景图片（包含"生成场景图片"、"场景图片"、"场景图"）
- generate_storyboard_images: 要求生成分镜图片（包含"生成分镜图片"、"分镜图片"、"分镜图"）
- generate_videos: 要求生成视频（包含"生成视频"、"视频生成"、"生成短视频"）
- auto_create: 全自动创作、智能创作、开始创作、接着创作、按流程创作（完整流程）
- status_query: 询问状态、进度、情况
- workflow_action: 其他工作流操作

规则：
1. "分析角色"、"角色分析"、"提取角色"、"有哪些角色" → analyze_character
2. "分析场景"、"场景分析"、"提取场景"、"有哪些场景" → analyze_scene
3. "分析分镜"、"分镜分析"、"提取镜头"、"有哪些镜头" → analyze_shot
4. "生成角色图片"、"角色图片"、"角色图" → generate_character_images
5. "生成场景图片"、"场景图片"、"场景图" → generate_scene_images
6. "生成分镜图片"、"分镜图片"、"分镜图" → generate_storyboard_images
7. "生成视频"、"视频生成" → generate_videos
8. "全自动创作"、"智能创作"、"开始创作"、"接着创作"、"按流程创作" → auto_create
9. "状态怎么样"、"进度如何"、"情况如何" → status_query
10. 其他 → workflow_action

只返回类型名称，格式：类型"""


WORKFLOW_STEPS = [
    {"step": "character_analysis", "name": "角色分析", "task_fn": "character_analysis_task"},
    {"step": "scene_analysis", "name": "场景分析", "task_fn": "scene_analysis_task"},
    {"step": "shot_analysis", "name": "分镜分析", "task_fn": "shot_analysis_task"},
    {"step": "character_images", "name": "角色图片生成", "task_fn": "character_image_task"},
    {"step": "scene_images", "name": "场景图片生成", "task_fn": "scene_image_task"},
    {"step": "storyboard_images", "name": "分镜图片生成", "task_fn": "storyboard_image_task"},
    {"step": "video_generation", "name": "视频生成", "task_fn": "video_task"},
]


class AgentTaskHandler:
    """Agent 任务执行处理器"""

    def __init__(self):
        """初始化处理器"""
        self.task_status_cache = {}
        logger.info("AgentTaskHandler 初始化完成")

    async def detect_task_intent(self, message: str) -> str:
        """使用 AI 判断任务意图"""
        try:
            from langchain_core.messages import SystemMessage, HumanMessage
            from langchain_openai import ChatOpenAI
            from app.core.config import settings
            
            llm = ChatOpenAI(
                model=settings.LLM_MODEL_NAME or "gpt-4",
                api_key=settings.OPENAI_API_KEY,
                base_url=str(settings.OPENAI_BASE_URL) if settings.OPENAI_BASE_URL else None,
                temperature=0.1,
                extra_body={"thinking": {"type": "disabled"}},
            )
            
            messages = [
                SystemMessage(content=TASK_INTENT_PROMPT),
                HumanMessage(content=f"用户消息: {message}")
            ]
            response = await llm.ainvoke(messages)
            intent = response.content.strip().lower()
            logger.info(f"任务意图识别结果: {intent}")
            return intent
        except Exception as e:
            logger.error(f"任务意图识别失败: {e}")
            return "workflow_action"

    def _get_creation(self, db, creation_uuid: str):
        """获取创作项目（同步版本）"""
        from sqlalchemy import select
        from app.models.creation import Creation
        
        stmt = select(Creation).where(Creation.uuid == creation_uuid)
        result = db.execute(stmt)
        return result.scalar_one_or_none()

    async def _get_creation_async(self, db, creation_uuid: str):
        """获取创作项目（异步版本）"""
        from sqlalchemy import select
        from app.models.creation import Creation
        
        stmt = select(Creation).where(Creation.uuid == creation_uuid)
        result = await db.execute(stmt)
        return result.scalar_one_or_none()

    async def analyze_character(self, db, creation_uuid: str) -> Dict[str, Any]:
        """执行角色分析任务"""
        try:
            creation = await self._get_creation_async(db, creation_uuid)
            if not creation:
                return {"error": "创作项目不存在"}
            
            task = character_analysis_task.delay(
                novel_id=creation.novel_id or 0,
                chapter_id=creation.chapter_id or 0,
                creation_id=creation.creation_id,
                chapter_content_url=creation.text_content_url or ""
            )
            task_id = str(task.id)
            logger.info(f"已提交角色分析任务: task_id={task_id}")
            return {"task_id": task_id, "task_type": "character_analysis", "message": "角色分析任务已提交"}
        except Exception as e:
            logger.error(f"提交角色分析任务失败: {e}")
            return {"error": f"提交任务失败: {str(e)}"}

    async def analyze_scene(self, db, creation_uuid: str) -> Dict[str, Any]:
        """执行场景分析任务"""
        try:
            creation = await self._get_creation_async(db, creation_uuid)
            if not creation:
                return {"error": "创作项目不存在"}
            
            task = scene_analysis_task.delay(
                novel_id=creation.novel_id or 0,
                chapter_id=creation.chapter_id or 0,
                creation_id=creation.creation_id,
                chapter_content_url=creation.text_content_url or ""
            )
            task_id = str(task.id)
            logger.info(f"已提交场景分析任务: task_id={task_id}")
            return {"task_id": task_id, "task_type": "scene_analysis", "message": "场景分析任务已提交"}
        except Exception as e:
            logger.error(f"提交场景分析任务失败: {e}")
            return {"error": f"提交任务失败: {str(e)}"}

    async def analyze_shot(self, db, creation_uuid: str) -> Dict[str, Any]:
        """执行分镜分析任务"""
        try:
            creation = await self._get_creation_async(db, creation_uuid)
            if not creation:
                return {"error": "创作项目不存在"}
            
            task = shot_analysis_task.delay(
                novel_id=creation.novel_id or 0,
                chapter_id=creation.chapter_id or 0,
                creation_id=creation.creation_id,
                chapter_content_url=creation.text_content_url or ""
            )
            task_id = str(task.id)
            logger.info(f"已提交分镜分析任务: task_id={task_id}")
            return {"task_id": task_id, "task_type": "shot_analysis", "message": "分镜分析任务已提交"}
        except Exception as e:
            logger.error(f"提交分镜分析任务失败: {e}")
            return {"error": f"提交任务失败: {str(e)}"}

    async def generate_character_images(self, db, creation_uuid: str) -> Dict[str, Any]:
        """执行角色图片生成任务"""
        try:
            from app.models.character import Character
            from sqlalchemy import select
            
            creation = await self._get_creation_async(db, creation_uuid)
            if not creation:
                return {"error": "创作项目不存在"}
            
            visual_style = creation.extra_data.get("visual_style", "anime") if creation.extra_data else "anime"
            
            char_stmt = select(Character).where(
                Character.creation_id == creation.creation_id,
                Character.deleted_at.is_(None)
            )
            char_result = await db.execute(char_stmt)
            characters = char_result.scalars().all()
            
            if not characters:
                return {"error": "没有角色数据，请先进行角色分析"}
            
            character_ids = [char.character_id for char in characters if not char.image_url]
            
            if not character_ids:
                return {"task_id": "already_completed", "task_type": "character_image", "message": "所有角色图片已生成，无需重复生成"}
            
            task = generate_character_image_task.delay(
                character_ids=character_ids,
                visual_style=visual_style,
                creation_uuid=creation_uuid,
                force_regenerate=True,
                model_name=None
            )
            task_id = str(task.id)
            logger.info(f"已提交角色图片生成任务: task_id={task_id}, character_ids={character_ids}")
            return {"task_id": task_id, "task_type": "character_image", "message": f"已提交 {len(character_ids)} 个角色图片生成任务"}
        except Exception as e:
            logger.error(f"提交角色图片生成任务失败: {e}")
            return {"error": f"提交任务失败: {str(e)}"}

    async def generate_scene_images(self, db, creation_uuid: str) -> Dict[str, Any]:
        """执行场景图片生成任务"""
        try:
            creation = await self._get_creation_async(db, creation_uuid)
            if not creation:
                return {"error": "创作项目不存在"}
            
            task = batch_generate_scene_images_task.delay(
                creation_id=creation.creation_id,
                visual_style=creation.extra_data.get("visual_style", "anime") if creation.extra_data else "anime"
            )
            task_id = str(task.id)
            logger.info(f"已提交场景图片生成任务: task_id={task_id}")
            return {"task_id": task_id, "task_type": "scene_image", "message": "场景图片生成任务已提交"}
        except Exception as e:
            logger.error(f"提交场景图片生成任务失败: {e}")
            return {"error": f"提交任务失败: {str(e)}"}

    async def generate_storyboard_images(self, db, creation_uuid: str) -> Dict[str, Any]:
        """执行分镜图片生成任务"""
        try:
            creation = await self._get_creation_async(db, creation_uuid)
            if not creation:
                return {"error": "创作项目不存在"}
            
            visual_style = creation.extra_data.get("visual_style", "anime") if creation.extra_data else "anime"
            
            task = generate_creation_shots_task.delay(
                creation_id=creation.creation_id,
                visual_style=visual_style,
                force_regenerate=False
            )
            task_id = str(task.id)
            logger.info(f"已提交分镜图片生成任务: task_id={task_id}")
            return {"task_id": task_id, "task_type": "storyboard_image", "message": "分镜图片生成任务已提交"}
        except Exception as e:
            logger.error(f"提交分镜图片生成任务失败: {e}")
            return {"error": f"提交任务失败: {str(e)}"}

    async def generate_videos(self, db, creation_uuid: str) -> Dict[str, Any]:
        """执行视频生成任务"""
        try:
            creation = await self._get_creation_async(db, creation_uuid)
            if not creation:
                return {"error": "创作项目不存在"}
            
            task = generate_all_videos_v2_task.delay(
                creation_id=creation.creation_id,
                generation_strategy=creation.video_generation_strategy or "ai_video"
            )
            task_id = str(task.id)
            logger.info(f"已提交视频生成任务: task_id={task_id}")
            return {"task_id": task_id, "task_type": "video", "message": "视频生成任务已提交"}
        except Exception as e:
            logger.error(f"提交视频生成任务失败: {e}")
            return {"error": f"提交任务失败: {str(e)}"}

    def get_task_status(self, task_id: str) -> Dict[str, Any]:
        """获取任务执行状态"""
        try:
            task = AsyncResult(task_id)
            
            if task.state == 'PENDING':
                return {"task_id": task_id, "status": "pending", "progress": 0, "message": "等待执行"}
            elif task.state == 'PROGRESS':
                info = task.info or {}
                return {
                    "task_id": task_id, "status": "processing",
                    "progress": info.get('percent', 0),
                    "message": info.get('status', '处理中'),
                    "current": info.get('current', 0), "total": info.get('total', 100)
                }
            elif task.state == 'SUCCESS':
                return {"task_id": task_id, "status": "completed", "progress": 100, "message": "完成"}
            elif task.state == 'FAILURE':
                return {"task_id": task_id, "status": "failed", "progress": 0, "message": str(task.info) or "失败"}
            else:
                return {"task_id": task_id, "status": task.state, "progress": 0, "message": task.state}
        except Exception as e:
            logger.error(f"获取任务状态失败: {e}")
            return {"task_id": task_id, "status": "error", "message": str(e)}

    def _make_sse(self, event: str, data: Dict[str, Any], role: str = None) -> str:
        """构建 SSE 消息"""
        if role:
            data["role"] = role
        return f"event: {event}\ndata: {json.dumps(data)}\n\n"

    async def execute_single_task(
        self, db, creation_uuid: str, intent: str
    ) -> AsyncIterator[str]:
        """执行单个任务并流式返回状态"""
        message_id = f"msg_{uuid.uuid4().hex[:12]}"
        
        task_fn_map = {
            "analyze_character": (self.analyze_character, "角色分析"),
            "analyze_scene": (self.analyze_scene, "场景分析"),
            "analyze_shot": (self.analyze_shot, "分镜分析"),
            "generate_character_images": (self.generate_character_images, "角色图片生成"),
            "generate_scene_images": (self.generate_scene_images, "场景图片生成"),
            "generate_storyboard_images": (self.generate_storyboard_images, "分镜图片生成"),
            "generate_videos": (self.generate_videos, "视频生成"),
        }
        
        if intent not in task_fn_map:
            yield self._make_sse("error", {"type": "error", "message": f"未知任务: {intent}"}, role="assistant")
            return
        
        task_fn, task_name = task_fn_map[intent]
        task_result = await task_fn(db, creation_uuid)
        
        if "error" in task_result:
            yield self._make_sse("error", {"type": "error", "message": task_result["error"]}, role="assistant")
            return
        
        task_id = task_result["task_id"]
        yield self._make_sse("message", {
            "type": "message.content", "message_id": message_id,
            "content": f"✅ {task_name}任务已提交\n任务ID: {task_id}", "timestamp": datetime.now(timezone.utc).isoformat() + "Z"
        }, role="assistant")
        
        try:
            for i in range(120):
                await asyncio.sleep(2)
                status = self.get_task_status(task_id)
                
                if status["status"] == "processing":
                    current = status.get("current", 0)
                    total = status.get("total", 100)
                    progress = int(current / total * 100) if total > 0 else 0
                    yield self._make_sse("message", {
                        "type": "message.content", "message_id": message_id,
                        "content": f"🔄 {task_name}进行中... {progress}% ({current}/{total})",
                        "timestamp": datetime.now(timezone.utc).isoformat() + "Z"
                    }, role="assistant")
                elif status["status"] == "completed":
                    yield self._make_sse("message", {
                        "type": "message.content", "message_id": message_id,
                        "content": f"✅ {task_name}已完成！", "timestamp": datetime.now(timezone.utc).isoformat() + "Z"
                    }, role="assistant")
                    break
                elif status["status"] == "failed":
                    yield self._make_sse("message", {
                        "type": "message.content", "message_id": message_id,
                        "content": f"❌ {task_name}失败: {status.get('message')}",
                        "timestamp": datetime.now(timezone.utc).isoformat() + "Z"
                    }, role="assistant")
                    break
                
                if i >= 119:
                    yield self._make_sse("message", {
                        "type": "message.content", "message_id": message_id,
                        "content": f"⏰ {task_name}超时，请稍后查看结果", "timestamp": datetime.now(timezone.utc).isoformat() + "Z"
                    })
        except asyncio.CancelledError:
            yield self._make_sse("message", {
                "type": "message.content", "message_id": message_id,
                "content": f"⚠️ {task_name}已取消", "timestamp": datetime.now(timezone.utc).isoformat() + "Z"
            })
        
        yield self._make_sse("message.end", {
            "type": "message.end", "message_id": message_id, "finish_reason": "completed"
        })

    async def execute_auto_create(self, db, creation_uuid: str) -> AsyncIterator[str]:
        """执行全自动创作流程"""
        message_id = f"msg_{uuid.uuid4().hex[:12]}"
        
        steps = [
            (self.analyze_character, "角色分析", "character_analysis"),
            (self.analyze_scene, "场景分析", "scene_analysis"),
            (self.analyze_shot, "分镜分析", "shot_analysis"),
            (self.generate_character_images, "角色图片生成", "character_image"),
            (self.generate_scene_images, "场景图片生成", "scene_image"),
            (self.generate_storyboard_images, "分镜图片生成", "storyboard_image"),
            (self.generate_videos, "视频生成", "video"),
        ]
        
        total_steps = len(steps)
        
        yield self._make_sse("message", {
            "type": "message.content", "message_id": message_id,
            "content": f"🚀 开始全自动创作流程\n共 {total_steps} 个步骤，请耐心等待...",
            "timestamp": datetime.now(timezone.utc).isoformat() + "Z"
        })
        
        for idx, (task_fn, step_name, step_key) in enumerate(steps, 1):
            yield self._make_sse("message", {
                "type": "message.content", "message_id": message_id,
                "content": f"\n📋 步骤 {idx}/{total_steps}: {step_name}...",
                "timestamp": datetime.now(timezone.utc).isoformat() + "Z"
            })
            
            task_result = task_fn(db, creation_uuid)
            
            if "error" in task_result:
                yield self._make_sse("message", {
                    "type": "message.content", "message_id": message_id,
                    "content": f"❌ {step_name}失败: {task_result['error']}",
                    "timestamp": datetime.now(timezone.utc).isoformat() + "Z"
                })
                yield self._make_sse("message.end", {
                    "type": "message.end", "message_id": message_id, "finish_reason": "error"
                })
                return
            
            task_id = task_result["task_id"]
            if "," in task_id:
                task_id = task_id.split(",")[0]
            progress_percent = int(idx / total_steps * 100)
            
            try:
                for i in range(120):
                    await asyncio.sleep(2)
                    status = self.get_task_status(task_id)
                    
                    if status["status"] == "processing":
                        current = status.get("current", 0)
                        total = status.get("total", 100)
                        step_progress = int(current / total * 100) if total > 0 else 0
                        total_progress = int((idx - 1 + step_progress / 100) / total_steps * 100)
                        yield self._make_sse("message", {
                            "type": "message.content", "message_id": message_id,
                            "content": f"🔄 {step_name} {step_progress}% (总进度 {total_progress}%)",
                            "timestamp": datetime.now(timezone.utc).isoformat() + "Z"
                        })
                    elif status["status"] == "completed":
                        yield self._make_sse("message", {
                            "type": "message.content", "message_id": message_id,
                            "content": f"✅ {step_name}完成",
                            "timestamp": datetime.now(timezone.utc).isoformat() + "Z"
                        })
                        break
                    elif status["status"] == "failed":
                        yield self._make_sse("message", {
                            "type": "message.content", "message_id": message_id,
                            "content": f"❌ {step_name}失败: {status.get('message')}",
                            "timestamp": datetime.now(timezone.utc).isoformat() + "Z"
                        })
                        yield self._make_sse("message.end", {
                            "type": "message.end", "message_id": message_id, "finish_reason": "error"
                        })
                        return
                    
                    if i >= 119:
                        yield self._make_sse("message", {
                            "type": "message.content", "message_id": message_id,
                            "content": f"⚠️ {step_name}超时，跳过此步骤",
                            "timestamp": datetime.now(timezone.utc).isoformat() + "Z"
                        })
            except asyncio.CancelledError:
                yield self._make_sse("message", {
                    "type": "message.content", "message_id": message_id,
                    "content": f"⚠️ 全自动创作已取消",
                    "timestamp": datetime.now(timezone.utc).isoformat() + "Z"
                })
                yield self._make_sse("message.end", {
                    "type": "message.end", "message_id": message_id, "finish_reason": "cancelled"
                })
                return
        
        yield self._make_sse("message", {
            "type": "message.content", "message_id": message_id,
            "content": f"\n🎉 全自动创作全部完成！\n\n您可以：\n- 查看生成的图片和视频\n- 进行后期调整",
            "timestamp": datetime.now(timezone.utc).isoformat() + "Z"
        })
        
        yield self._make_sse("message.end", {
            "type": "message.end", "message_id": message_id, "finish_reason": "completed"
        })


agent_task_handler = AgentTaskHandler()
