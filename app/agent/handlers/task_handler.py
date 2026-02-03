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
from app.agent.services.prompt_generator import get_prompt_generator


TASK_INTENT_PROMPT = """判断用户消息的意图，只返回意图类型（不需要解释）。

意图类型：
- analyze_character: 要求分析角色、从剧本中提取角色（包含"分析角色"、"角色分析"、"提取角色"、"有哪些角色"）
- analyze_scene: 要求分析场景、从剧本中提取场景（包含"分析场景"、"场景分析"、"提取场景"、"有哪些场景"）
- analyze_shot: 要求分析分镜、从剧本中提取镜头（包含"分析分镜"、"分镜分析"、"提取分镜"、"有哪些镜头"）
- generate_character_images: 要求生成角色图片（包含"生成角色图片"、"角色图片"、"角色图"）
- generate_scene_images: 要求生成场景图片（包含"生成场景图片"、"场景图片"、"场景图"）
- generate_storyboard_images: 要求生成分镜图片（包含"生成分镜图片"、"分镜图片"、"分镜图"）
- generate_videos: 要求生成视频（包含"生成视频"、"视频生成"、"生成短视频"）
- generate_prompt_only: 只生成提示词不生成图片（包含"生成提示词"、"只要提示词"、"先生成prompt"、"不要图片只要提示词"）
- modify_prompt: 修改提示词（包含"修改提示词"、"改一下提示词"、"编辑prompt"、"更新提示词"）
- modify_settings: 修改创作设置（包含"设置分辨率"、"改成竖屏"、"改成横屏"、"16:9"、"9:16"、"修改风格"、"设置风格"）
- collect_info: 采集创作信息或回答设置相关问题（用户提供分辨率、风格等设置信息）
- auto_create: 全自动创作、智能创作、开始创作、接着创作、按流程创作（完整流程）
- status_query: 询问状态、进度、情况
- unknown: 无法识别的意图、闲聊、无关问题

规则：
1. "分析角色"、"角色分析"、"提取角色"、"有哪些角色" → analyze_character
2. "分析场景"、"场景分析"、"提取场景"、"有哪些场景" → analyze_scene
3. "分析分镜"、"分镜分析"、"提取镜头"、"有哪些镜头" → analyze_shot
4. "生成角色图片"、"角色图片"、"角色图" → generate_character_images
5. "生成场景图片"、"场景图片"、"场景图" → generate_scene_images
6. "生成分镜图片"、"分镜图片"、"分镜图" → generate_storyboard_images
7. "生成视频"、"视频生成" → generate_videos
8. "生成提示词"、"只要提示词"、"先生成prompt" → generate_prompt_only
9. "修改提示词"、"改一下提示词"、"编辑prompt" → modify_prompt
10. "设置分辨率"、"改成竖屏"、"改成横屏"、"16:9"、"9:16"、"修改风格" → modify_settings
11. 用户回答分辨率、风格等设置问题时 → collect_info
12. "全自动创作"、"智能创作"、"开始创作"、"接着创作"、"按流程创作" → auto_create
13. "状态怎么样"、"进度如何"、"情况如何" → status_query
14. 其他无法识别的意图 → unknown

只返回类型名称，格式：类型"""


INTENT_REFINE_PROMPT = """你是一个意图细化分析Agent。用户已经表达了一个大致的意图，现在需要你分析用户具体想要做什么。

用户的大致意图: {intent_type}
用户的原始消息: {user_message}

{chat_history}

{context_info}

请分析用户的具体需求，返回JSON格式：
{{
    "action": "具体操作类型",
    "target": "操作对象",
    "target_ids": [目标ID列表，如果有的话],
    "target_numbers": [目标编号列表，如果有的话],
    "scope": "all" 或 "specific" 或 "first" 或 "last",
    "force_regenerate": true 或 false,
    "resource_type": "image" 或 "video" 或 "both",
    "frame_type": "start" 或 "end" 或 "both",
    "description": "对用户意图的简短描述"
}}

操作类型说明：
- 对于 generate_storyboard_images（分镜图片生成）:
  - action: "generate_shot_image"
  - scope: "all"（全部）, "specific"（指定编号）, "first"（第一个）, "last"（最后一个）
  - target_numbers: 用户提到的分镜编号列表，如 [1, 2, 3]
  - resource_type: "image"
  - frame_type: "start"（首帧）, "end"（尾帧）, "both"（首尾帧）

- 对于 generate_scene_images（场景图片生成）:
  - action: "generate_scene_image"
  - scope: "all", "specific", "first", "last"
  - target_numbers: 用户提到的场景编号列表
  - resource_type: "image"

- 对于 generate_character_images（角色图片生成）:
  - action: "generate_character_image"
  - scope: "all", "specific"
  - target: 角色名称（如果用户指定了的话）
  - resource_type: "image"

- 对于 generate_videos（视频生成）:
  - action: "generate_video"
  - scope: "all", "specific"
  - target_numbers: 用户提到的分镜编号列表
  - resource_type: "video"
  - frame_type: "start"（只用首帧生成视频）, "both"（用首尾帧生成视频）
  - 注意：视频生成时，frame_type 决定使用哪些帧作为输入

- 对于 regenerate（重新生成）:
  - target: "shot" 或 "character" 或 "scene"
  - resource_type: "image" 或 "video"
  - frame_type: "start"（仅首帧）, "end"（仅尾帧）, "both"（首尾帧）

frame_type 识别规则（重要！必须严格遵守）：
- 用户说"首帧"、"开始帧"、"第一帧"、"首帧图片" -> "start"
- 用户说"尾帧"、"结束帧"、"最后一帧"、"尾帧图片" -> "end"
- 用户说"分镜图"、"图片"、"重新生成图片"（未明确指定首尾）-> "both"

关键判断逻辑：
1. 只要用户明确提到"尾帧"或"结束帧"，frame_type 必须是 "end"
2. 只要用户明确提到"首帧"或"开始帧"，frame_type 必须是 "start"
3. 用户说"重新生成...尾帧" -> frame_type="end"
4. 用户说"重新生成...首帧" -> frame_type="start"
5. 用户只说"重新生成图片"没指定首尾 -> frame_type="both"

示例：
用户说"给第一个分镜生成图片" -> {{"action": "generate_shot_image", "target": "shot", "target_ids": [], "target_numbers": [1], "scope": "first", "force_regenerate": false, "resource_type": "image", "frame_type": "both", "description": "为第1个分镜生成图片"}}
用户说"重新生成所有分镜图片" -> {{"action": "generate_shot_image", "target": "shot", "target_ids": [], "target_numbers": [], "scope": "all", "force_regenerate": true, "resource_type": "image", "frame_type": "both", "description": "重新生成所有分镜图片"}}
用户说"生成第2和第3个分镜的图片" -> {{"action": "generate_shot_image", "target": "shot", "target_ids": [], "target_numbers": [2, 3], "scope": "specific", "force_regenerate": false, "resource_type": "image", "frame_type": "both", "description": "为第2、3个分镜生成图片"}}
用户说"给分镜5生成尾帧" -> {{"action": "generate_shot_image", "target": "shot", "target_ids": [], "target_numbers": [5], "scope": "specific", "force_regenerate": false, "resource_type": "image", "frame_type": "end", "description": "为分镜5生成尾帧"}}
用户说"重新生成分镜3和5的尾帧图片" -> {{"action": "generate_shot_image", "target": "shot", "target_ids": [], "target_numbers": [3, 5], "scope": "specific", "force_regenerate": true, "resource_type": "image", "frame_type": "end", "description": "重新生成分镜3和5的尾帧"}}
用户说"给我的分镜1和分镜3重新生成一下尾帧图片" -> {{"action": "generate_shot_image", "target": "shot", "target_ids": [], "target_numbers": [1, 3], "scope": "specific", "force_regenerate": true, "resource_type": "image", "frame_type": "end", "description": "重新生成分镜1和3的尾帧"}}
用户说"重新生成首帧" -> {{"action": "generate_shot_image", "target": "shot", "target_ids": [], "target_numbers": [], "scope": "all", "force_regenerate": true, "resource_type": "image", "frame_type": "start", "description": "重新生成所有分镜的首帧"}}
用户说"给分镜1生成视频" -> {{"action": "generate_video", "target": "shot", "target_ids": [], "target_numbers": [1], "scope": "specific", "force_regenerate": false, "resource_type": "video", "frame_type": "both", "description": "为分镜1生成视频（使用首尾帧）"}}
用户说"用首帧给分镜2生成视频" -> {{"action": "generate_video", "target": "shot", "target_ids": [], "target_numbers": [2], "scope": "specific", "force_regenerate": false, "resource_type": "video", "frame_type": "start", "description": "为分镜2生成视频（只用首帧）"}}

只返回JSON，不要其他内容。"""


CLARIFY_PROMPT = """你是一个友好的短剧创作助手。请根据用户的消息和对话历史，给出合适的回复。

{chat_history}

用户当前消息: {user_message}

你可以帮助用户完成以下任务：
1. 分析角色 - 从剧本中提取和分析角色信息
2. 分析场景 - 从剧本中提取和分析场景信息
3. 分析分镜 - 从剧本中提取镜头和分镜信息
4. 生成角色图片 - 为角色生成形象图片
5. 生成场景图片 - 为场景生成背景图片
6. 生成分镜图片 - 为分镜生成插画
7. 生成视频 - 生成短视频
8. 全自动创作 - 一键完成整个创作流程
9. 查询进度 - 查看当前创作进度和状态

回复规则：
- 如果用户在询问之前的对话内容（如"你刚才在干啥"、"你说了什么"），请根据对话历史回答
- 如果用户在闲聊或问候，友好地回应并简单介绍你能做什么
- 如果用户的问题不明确，引导他们选择上述功能之一
- 回复要简洁友好（2-4句话）"""


SETTINGS_COLLECT_PROMPT = """你是一个短剧创作助手，正在帮助用户设置创作参数。

当前创作设置：
{current_settings}

用户消息：{user_message}

{chat_history}

请分析用户的消息，提取或确认创作设置信息，返回JSON格式：
{{
    "action": "update_settings" 或 "ask_for_info",
    "settings": {{
        "aspect_ratio": "16:9" 或 "9:16"（如果用户提到了分辨率/横竖屏）,
        "visual_style": "风格名称"（如果用户提到了风格：realism/anime/watercolor/cyberpunk/ukiyoe）,
        "其他设置键": "值"
    }},
    "missing_info": ["缺少的信息列表"],
    "response": "给用户的回复内容"
}}

风格选项说明：
- realism: 写实摄影风格
- anime: 日漫风格
- watercolor: 水彩画风格
- cyberpunk: 赛博朋克风格
- ukiyoe: 浮世绘风格

分辨率选项：
- 16:9: 横屏（适合电脑/电视）
- 9:16: 竖屏（适合手机/短视频）

如果用户说"横屏"、"电脑"、"电视"，设置为 16:9
如果用户说"竖屏"、"手机"、"抖音"、"短视频"，设置为 9:16

只返回JSON，不要其他内容。"""


MODIFY_PROMPT_PROMPT = """你是一个短剧创作助手，用户想要修改或查看提示词。

用户消息：{user_message}

{chat_history}

{context_info}

请分析用户的需求，返回JSON格式：
{{
    "action": "view_prompt" 或 "modify_prompt" 或 "generate_prompt",
    "target_type": "shot" 或 "scene" 或 "character",
    "target_numbers": [目标编号列表],
    "target_name": "目标名称（如果是角色）",
    "new_prompt": "新的提示词内容（如果是修改操作）",
    "modification": "修改描述（如添加什么元素、改变什么风格）",
    "description": "对操作的简短描述"
}}

示例：
- "看看第一个分镜的提示词" -> {{"action": "view_prompt", "target_type": "shot", "target_numbers": [1], ...}}
- "把第2个分镜的提示词改成xxx" -> {{"action": "modify_prompt", "target_type": "shot", "target_numbers": [2], "new_prompt": "xxx", ...}}
- "给第3个分镜生成提示词" -> {{"action": "generate_prompt", "target_type": "shot", "target_numbers": [3], ...}}

只返回JSON，不要其他内容。"""


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
        self.prompt_generator = None  # 延迟初始化
        logger.info("AgentTaskHandler 初始化完成")

    def _get_prompt_generator(self):
        """获取提示词生成器（延迟初始化）"""
        if self.prompt_generator is None:
            self.prompt_generator = get_prompt_generator()
        return self.prompt_generator

    async def detect_task_intent(self, message: str, chat_history: list = None) -> str:
        """使用 AI 判断任务意图

        Args:
            message: 用户当前消息
            chat_history: 聊天历史列表，格式为 [{"role": "user/assistant", "content": "..."}]
        """
        try:
            from langchain_core.messages import SystemMessage, HumanMessage, AIMessage
            from langchain_openai import ChatOpenAI
            from app.core.config import settings

            llm = ChatOpenAI(
                model=settings.LLM_MODEL_NAME or "gpt-4",
                api_key=settings.OPENAI_API_KEY,
                base_url=str(settings.OPENAI_BASE_URL) if settings.OPENAI_BASE_URL else None,
                temperature=0.1,
                extra_body={"thinking": {"type": "disabled"}},
            )

            # 构建包含上下文的消息列表
            messages = [SystemMessage(content=TASK_INTENT_PROMPT)]

            # 添加聊天历史作为上下文（最近5轮对话）
            if chat_history:
                recent_history = chat_history[-10:]  # 最多取最近10条消息（5轮对话）
                context_text = "以下是之前的对话历史：\n"
                for msg in recent_history:
                    role = "用户" if msg.get("role") == "user" else "助手"
                    content = msg.get("content", "")[:200]  # 截断过长的内容
                    context_text += f"{role}: {content}\n"
                context_text += f"\n当前用户消息: {message}"
                messages.append(HumanMessage(content=context_text))
            else:
                messages.append(HumanMessage(content=f"用户消息: {message}"))

            response = await llm.ainvoke(messages)
            intent = response.content.strip().lower()
            logger.info(f"任务意图识别结果: {intent}")
            return intent
        except Exception as e:
            logger.error(f"任务意图识别失败: {e}")
            return "unknown"

    async def refine_task_intent(
        self,
        intent_type: str,
        user_message: str,
        chat_history: list = None,
        context_info: str = ""
    ) -> Dict[str, Any]:
        """细化用户意图，分析具体要操作什么

        Args:
            intent_type: 粗粒度意图类型
            user_message: 用户原始消息
            chat_history: 聊天历史
            context_info: 上下文信息（如可用的分镜列表、角色列表等）

        Returns:
            细化后的意图详情
        """
        try:
            from langchain_core.messages import HumanMessage
            from langchain_openai import ChatOpenAI
            from app.core.config import settings

            llm = ChatOpenAI(
                model=settings.LLM_MODEL_NAME or "gpt-4",
                api_key=settings.OPENAI_API_KEY,
                base_url=str(settings.OPENAI_BASE_URL) if settings.OPENAI_BASE_URL else None,
                temperature=0.1,
                extra_body={"thinking": {"type": "disabled"}},
            )

            # 构建聊天历史文本
            chat_history_text = ""
            if chat_history:
                chat_history_text = "对话历史：\n"
                for msg in chat_history[-6:]:
                    role = "用户" if msg.get("role") == "user" else "助手"
                    content = msg.get("content", "")[:200]
                    chat_history_text += f"{role}: {content}\n"

            prompt = INTENT_REFINE_PROMPT.format(
                intent_type=intent_type,
                user_message=user_message,
                chat_history=chat_history_text,
                context_info=context_info
            )

            response = await llm.ainvoke([HumanMessage(content=prompt)])
            result_text = response.content.strip()

            # 解析JSON
            import re
            json_match = re.search(r'\{[\s\S]*\}', result_text)
            if json_match:
                refined_intent = json.loads(json_match.group())
                logger.info(f"意图细化结果: {refined_intent}")
                logger.info(f"[TaskHandler] 提取 frame_type: {refined_intent.get('frame_type', 'both')}, "
                           f"resource_type: {refined_intent.get('resource_type', 'image')}, "
                           f"target_numbers: {refined_intent.get('target_numbers', [])}")
                return refined_intent
            else:
                logger.warning(f"无法解析意图细化结果: {result_text}")
                return {
                    "action": intent_type,
                    "target": "all",
                    "target_ids": [],
                    "target_numbers": [],
                    "scope": "all",
                    "force_regenerate": False,
                    "description": "执行默认操作"
                }
        except Exception as e:
            logger.error(f"意图细化失败: {e}")
            return {
                "action": intent_type,
                "target": "all",
                "target_ids": [],
                "target_numbers": [],
                "scope": "all",
                "force_regenerate": False,
                "description": "执行默认操作"
            }

    async def get_context_for_intent(self, db, creation_uuid: str, intent_type: str) -> str:
        """获取意图相关的上下文信息"""
        try:
            from app.models.creation import Creation
            from app.models.shot import Shot
            from app.models.scene import Scene
            from app.models.character import Character
            from sqlalchemy import select

            creation = await self._get_creation_async(db, creation_uuid)
            if not creation:
                return ""

            context_parts = []

            if intent_type in ["generate_storyboard_images", "generate_videos"]:
                # 获取分镜列表
                stmt = select(Shot).where(Shot.creation_id == creation.creation_id).order_by(Shot.shot_number)
                result = await db.execute(stmt)
                shots = result.scalars().all()
                if shots:
                    shot_list = [f"分镜{s.shot_number}: {s.title or s.description[:30] if s.description else '无描述'}（{'有图' if s.image_url else '无图'}）" for s in shots]
                    context_parts.append(f"当前有 {len(shots)} 个分镜:\n" + "\n".join(shot_list[:20]))

            elif intent_type == "generate_scene_images":
                # 获取场景列表
                stmt = select(Scene).where(Scene.creation_id == creation.creation_id).order_by(Scene.scene_id)
                result = await db.execute(stmt)
                scenes = result.scalars().all()
                if scenes:
                    scene_list = [f"场景{i+1}: {s.title}（{'有图' if s.image_url else '无图'}）" for i, s in enumerate(scenes)]
                    context_parts.append(f"当前有 {len(scenes)} 个场景:\n" + "\n".join(scene_list[:20]))

            elif intent_type == "generate_character_images":
                # 获取角色列表
                stmt = select(Character).where(Character.creation_id == creation.creation_id)
                result = await db.execute(stmt)
                characters = result.scalars().all()
                if characters:
                    char_list = [f"{c.name}（{'有图' if c.image_url else '无图'}）" for c in characters]
                    context_parts.append(f"当前有 {len(characters)} 个角色:\n" + "\n".join(char_list[:20]))

            return "\n".join(context_parts) if context_parts else ""
        except Exception as e:
            logger.error(f"获取上下文信息失败: {e}")
            return ""

    async def generate_clarify_response(self, user_message: str, chat_history: list = None) -> AsyncIterator[str]:
        """当无法识别用户意图时，生成智能回复

        Args:
            user_message: 用户当前消息
            chat_history: 聊天历史列表，格式为 [{"role": "user/assistant", "content": "..."}]
        """
        message_id = f"msg_{uuid.uuid4().hex[:12]}"

        try:
            from langchain_core.messages import SystemMessage, HumanMessage
            from langchain_openai import ChatOpenAI
            from app.core.config import settings

            llm = ChatOpenAI(
                model=settings.LLM_MODEL_NAME or "gpt-4",
                api_key=settings.OPENAI_API_KEY,
                base_url=str(settings.OPENAI_BASE_URL) if settings.OPENAI_BASE_URL else None,
                temperature=0.7,
                streaming=True,
                extra_body={"thinking": {"type": "disabled"}},
            )

            # 构建聊天历史文本
            chat_history_text = ""
            if chat_history:
                chat_history_text = "以下是之前的对话历史：\n"
                for msg in chat_history[-10:]:  # 最近10条
                    role = "用户" if msg.get("role") == "user" else "助手"
                    content = msg.get("content", "")[:300]  # 截断过长内容
                    chat_history_text += f"{role}: {content}\n"

            prompt = CLARIFY_PROMPT.format(
                user_message=user_message,
                chat_history=chat_history_text
            )
            messages = [HumanMessage(content=prompt)]

            yield self._make_sse("message.start", {
                "type": "message.start",
                "message_id": message_id,
                "timestamp": datetime.now(timezone.utc).isoformat() + "Z"
            }, role="assistant")

            full_content = ""
            async for chunk in llm.astream(messages):
                if chunk.content:
                    full_content += chunk.content
                    yield self._make_sse("message", {
                        "type": "message.content",
                        "message_id": message_id,
                        "content": full_content,
                        "delta": chunk.content,
                        "timestamp": datetime.now(timezone.utc).isoformat() + "Z"
                    }, role="assistant")

            yield self._make_sse("message.end", {
                "type": "message.end",
                "message_id": message_id,
                "finish_reason": "completed"
            })

            logger.info(f"已生成引导性回复: {full_content[:100]}...")

        except Exception as e:
            logger.error(f"生成引导性回复失败: {e}")
            fallback_message = "抱歉，我没有理解您的意思。我可以帮您：分析角色、分析场景、分析分镜、生成图片、生成视频，或者进行全自动创作。请告诉我您想做什么？"
            yield self._make_sse("message", {
                "type": "message.content",
                "message_id": message_id,
                "content": fallback_message,
                "timestamp": datetime.now(timezone.utc).isoformat() + "Z"
            }, role="assistant")
            yield self._make_sse("message.end", {
                "type": "message.end",
                "message_id": message_id,
                "finish_reason": "completed"
            })

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
            from app.models.chapter import Chapter
            from sqlalchemy import select

            creation = await self._get_creation_async(db, creation_uuid)
            if not creation:
                return {"error": "创作项目不存在"}

            # 从 Chapter 表获取 content_url
            if not creation.chapter_id:
                return {"error": "创作项目未关联章节，请先选择章节"}

            stmt = select(Chapter).where(Chapter.chapter_id == creation.chapter_id)
            result = await db.execute(stmt)
            chapter = result.scalar_one_or_none()

            if not chapter:
                return {"error": "关联的章节不存在"}

            chapter_content_url = chapter.content_url or ""
            if not chapter_content_url:
                return {"error": "章节缺少内容URL，请先上传剧本内容"}

            # 检查是否是完整的 URL
            if not chapter_content_url.startswith(("http://", "https://")):
                # 可能是 US3 key，尝试拼接完整 URL
                from app.utils.us3 import US3Client
                us3_client = US3Client()
                chapter_content_url = us3_client.get_file_url(chapter_content_url)
                logger.info(f"将 US3 key 转换为完整 URL: {chapter_content_url}")

            task = shot_analysis_task.delay(
                novel_id=creation.novel_id or 0,
                chapter_id=creation.chapter_id or 0,
                creation_id=creation.creation_id,
                chapter_content_url=chapter_content_url
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
                creation_id=creation.creation_id
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
            
            task = generate_creation_shots_task.delay(
                creation_id=creation.creation_id,
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

    async def execute_refined_task(
        self,
        db,
        creation_uuid: str,
        intent_type: str,
        refined_intent: Dict[str, Any]
    ) -> AsyncIterator[str]:
        """根据细化后的意图执行具体任务

        Args:
            db: 数据库会话
            creation_uuid: 创作UUID
            intent_type: 粗粒度意图类型
            refined_intent: 细化后的意图详情
        """
        message_id = f"msg_{uuid.uuid4().hex[:12]}"
        scope = refined_intent.get("scope", "all")
        target_numbers = refined_intent.get("target_numbers", [])
        force_regenerate = refined_intent.get("force_regenerate", False)
        description = refined_intent.get("description", "")

        yield self._make_sse("message.start", {
            "type": "message.start",
            "message_id": message_id,
        }, role="assistant")

        try:
            creation = await self._get_creation_async(db, creation_uuid)
            if not creation:
                yield self._make_sse("message", {
                    "type": "message.content",
                    "message_id": message_id,
                    "content": "创作项目不存在",
                    "delta": "创作项目不存在",
                }, role="assistant")
                yield self._make_sse("message.end", {"type": "message.end", "message_id": message_id, "finish_reason": "error"})
                return

            # 获取视觉风格
            visual_style = "anime"
            if creation.extra_data:
                visual_style = creation.extra_data.get("visual_style", "anime")

            # 处理 generate_prompt_only 意图 - 只生成提示词不生成图片
            if intent_type == "generate_prompt_only":
                result = await self._execute_prompt_generation_only(
                    db, creation, scope, target_numbers, visual_style, force_regenerate
                )
                response_msg = result.get("message", "提示词生成完成")
                yield self._make_sse("message", {
                    "type": "message.content",
                    "message_id": message_id,
                    "content": response_msg,
                    "delta": response_msg,
                }, role="assistant")
                yield self._make_sse("message.end", {
                    "type": "message.end",
                    "message_id": message_id,
                    "finish_reason": "completed"
                })
                return

            # 根据意图类型和细化结果执行不同的任务
            if intent_type == "generate_storyboard_images":
                # 先生成提示词，再生成图片
                prompt_result = await self._generate_prompts_before_task(
                    db, creation, "shot_image", scope, target_numbers, visual_style, force_regenerate
                )
                if prompt_result.get("generated_count", 0) > 0:
                    yield self._make_sse("message", {
                        "type": "message.content",
                        "message_id": message_id,
                        "content": f"已为 {prompt_result['generated_count']} 个分镜生成提示词，正在提交图片生成任务...\n",
                        "delta": f"已为 {prompt_result['generated_count']} 个分镜生成提示词，正在提交图片生成任务...\n",
                    }, role="assistant")
                result = await self._execute_storyboard_image_task(
                    db, creation, scope, target_numbers, force_regenerate
                )
            elif intent_type == "generate_scene_images":
                # 先生成提示词，再生成图片
                prompt_result = await self._generate_prompts_before_task(
                    db, creation, "scene_image", scope, target_numbers, visual_style, force_regenerate
                )
                if prompt_result.get("generated_count", 0) > 0:
                    yield self._make_sse("message", {
                        "type": "message.content",
                        "message_id": message_id,
                        "content": f"已为 {prompt_result['generated_count']} 个场景生成提示词，正在提交图片生成任务...\n",
                        "delta": f"已为 {prompt_result['generated_count']} 个场景生成提示词，正在提交图片生成任务...\n",
                    }, role="assistant")
                result = await self._execute_scene_image_task(
                    db, creation, scope, target_numbers, force_regenerate
                )
            elif intent_type == "generate_character_images":
                # 先生成提示词，再生成图片
                target_name = refined_intent.get("target", "")
                prompt_result = await self._generate_prompts_before_task(
                    db, creation, "character_image", scope, [], visual_style, force_regenerate
                )
                if prompt_result.get("generated_count", 0) > 0:
                    yield self._make_sse("message", {
                        "type": "message.content",
                        "message_id": message_id,
                        "content": f"已为 {prompt_result['generated_count']} 个角色生成提示词，正在提交图片生成任务...\n",
                        "delta": f"已为 {prompt_result['generated_count']} 个角色生成提示词，正在提交图片生成任务...\n",
                    }, role="assistant")
                result = await self._execute_character_image_task(
                    db, creation, scope, target_name, force_regenerate
                )
            elif intent_type == "generate_videos":
                # 先生成视频提示词，再生成视频
                prompt_result = await self._generate_prompts_before_task(
                    db, creation, "shot_video", scope, target_numbers, visual_style, force_regenerate
                )
                if prompt_result.get("generated_count", 0) > 0:
                    yield self._make_sse("message", {
                        "type": "message.content",
                        "message_id": message_id,
                        "content": f"已为 {prompt_result['generated_count']} 个分镜生成视频提示词，正在提交视频生成任务...\n",
                        "delta": f"已为 {prompt_result['generated_count']} 个分镜生成视频提示词，正在提交视频生成任务...\n",
                    }, role="assistant")
                result = await self._execute_video_task(
                    db, creation, scope, target_numbers, force_regenerate
                )
            else:
                # 其他意图使用原有的 execute_single_task 逻辑
                result = await self._execute_task_by_intent(db, creation_uuid, intent_type)

            # 生成响应消息
            if "error" in result:
                response_msg = f"任务执行失败：{result['error']}"
            else:
                task_id = result.get("task_id", "")
                task_type = result.get("task_type", "")
                message = result.get("message", "任务已提交")
                response_msg = f"{description or message}"
                if task_id and task_id != "already_completed":
                    response_msg += f"\n\n任务ID: {task_id}"

            yield self._make_sse("message", {
                "type": "message.content",
                "message_id": message_id,
                "content": response_msg,
                "delta": response_msg,
            }, role="assistant")

            yield self._make_sse("message.end", {
                "type": "message.end",
                "message_id": message_id,
                "finish_reason": "completed"
            })

        except Exception as e:
            logger.error(f"执行细化任务失败: {e}")
            yield self._make_sse("message", {
                "type": "message.content",
                "message_id": message_id,
                "content": f"执行任务时发生错误：{str(e)}",
                "delta": f"执行任务时发生错误：{str(e)}",
            }, role="assistant")
            yield self._make_sse("message.end", {"type": "message.end", "message_id": message_id, "finish_reason": "error"})

    async def _generate_prompts_before_task(
        self,
        db,
        creation,
        prompt_type: str,
        scope: str,
        target_numbers: List[int],
        visual_style: str,
        force_regenerate: bool
    ) -> Dict[str, Any]:
        """在执行图片/视频生成任务前，先通过 Agent 生成提示词

        Args:
            db: 数据库会话
            creation: 创作对象
            prompt_type: 提示词类型 (shot_image, shot_video, scene_image, character_image)
            scope: 范围 (all, first, last, specific)
            target_numbers: 目标编号列表
            visual_style: 视觉风格
            force_regenerate: 是否强制重新生成
        """
        try:
            prompt_generator = self._get_prompt_generator()
            generated_count = 0

            if prompt_type == "shot_image":
                from app.models.shot import Shot
                from sqlalchemy import select

                stmt = select(Shot).where(Shot.creation_id == creation.creation_id).order_by(Shot.shot_number)
                result = await db.execute(stmt)
                shots = result.scalars().all()

                shots_to_process = self._filter_items_by_scope(shots, scope, target_numbers, "shot_number")

                for shot in shots_to_process:
                    if force_regenerate or not shot.image_prompt:
                        gen_result = await prompt_generator.generate_shot_image_prompt(
                            db, shot.shot_id, visual_style, force_regenerate
                        )
                        if gen_result.get("success"):
                            generated_count += 1

            elif prompt_type == "shot_video":
                from app.models.shot import Shot
                from sqlalchemy import select

                stmt = select(Shot).where(Shot.creation_id == creation.creation_id).order_by(Shot.shot_number)
                result = await db.execute(stmt)
                shots = result.scalars().all()

                shots_to_process = self._filter_items_by_scope(shots, scope, target_numbers, "shot_number")

                for shot in shots_to_process:
                    extra_data = shot.extra_data or {}
                    if force_regenerate or not extra_data.get("video_prompt"):
                        gen_result = await prompt_generator.generate_shot_video_prompt(
                            db, shot.shot_id, force_regenerate
                        )
                        if gen_result.get("success"):
                            generated_count += 1

            elif prompt_type == "scene_image":
                from app.models.scene import Scene
                from sqlalchemy import select

                stmt = select(Scene).where(Scene.creation_id == creation.creation_id).order_by(Scene.scene_id)
                result = await db.execute(stmt)
                scenes = result.scalars().all()

                scenes_to_process = self._filter_items_by_scope(scenes, scope, target_numbers, None, use_index=True)

                for scene in scenes_to_process:
                    extra_data = scene.extra_data or {}
                    if force_regenerate or not extra_data.get("image_prompt"):
                        gen_result = await prompt_generator.generate_scene_image_prompt(
                            db, scene.scene_id, visual_style, force_regenerate
                        )
                        if gen_result.get("success"):
                            generated_count += 1

            elif prompt_type == "character_image":
                from app.models.character import Character
                from sqlalchemy import select

                stmt = select(Character).where(
                    Character.creation_id == creation.creation_id,
                    Character.deleted_at.is_(None)
                )
                result = await db.execute(stmt)
                characters = result.scalars().all()

                for char in characters:
                    extra_data = char.extra_data or {}
                    if force_regenerate or not extra_data.get("image_prompt"):
                        gen_result = await prompt_generator.generate_character_image_prompt(
                            db, char.character_id, visual_style, force_regenerate
                        )
                        if gen_result.get("success"):
                            generated_count += 1

            logger.info(f"提示词预生成完成: type={prompt_type}, generated={generated_count}")
            return {"success": True, "generated_count": generated_count}

        except Exception as e:
            logger.error(f"提示词预生成失败: {e}")
            return {"success": False, "error": str(e), "generated_count": 0}

    def _filter_items_by_scope(
        self,
        items: list,
        scope: str,
        target_numbers: List[int],
        number_attr: str = None,
        use_index: bool = False
    ) -> list:
        """根据 scope 筛选要处理的项目"""
        if not items:
            return []

        if scope == "all":
            return items
        elif scope == "first":
            return [items[0]]
        elif scope == "last":
            return [items[-1]]
        elif scope == "specific" and target_numbers:
            result = []
            for num in target_numbers:
                if use_index:
                    # 使用索引（从1开始）
                    if 0 < num <= len(items):
                        result.append(items[num - 1])
                else:
                    # 使用属性值
                    for item in items:
                        if getattr(item, number_attr, None) == num:
                            result.append(item)
                            break
            return result
        return items

    async def _execute_prompt_generation_only(
        self,
        db,
        creation,
        scope: str,
        target_numbers: List[int],
        visual_style: str,
        force_regenerate: bool
    ) -> Dict[str, Any]:
        """只生成提示词，不生成��片/视频

        用于 generate_prompt_only 意图
        """
        try:
            prompt_generator = self._get_prompt_generator()

            # 批量生成所有类型的提示词
            prompt_types = ['character', 'scene', 'shot_image']
            result = await prompt_generator.generate_all_prompts_for_creation(
                db,
                creation.creation_id,
                prompt_types=prompt_types,
                visual_style=visual_style,
                force_regenerate=force_regenerate
            )

            if result.get("success"):
                char_count = len([r for r in result.get("characters", []) if r.get("success")])
                scene_count = len([r for r in result.get("scenes", []) if r.get("success")])
                shot_count = len([r for r in result.get("shots", []) if r.get("success")])

                message = f"提示词生成完成！\n\n"
                message += f"- 角色提示词: {char_count} 个\n"
                message += f"- 场景提示词: {scene_count} 个\n"
                message += f"- 分镜提示词: {shot_count} 个\n"

                if result.get("errors"):
                    message += f"\n⚠️ 有 {len(result['errors'])} 个错误"

                return {"success": True, "message": message}
            else:
                return {"success": False, "message": f"提示词生成失败: {result.get('error', '未知错误')}"}

        except Exception as e:
            logger.error(f"执行提示词生成失败: {e}")
            return {"success": False, "message": f"生成提示词时发生错误: {str(e)}"}

    async def _execute_storyboard_image_task(
        self,
        db,
        creation,
        scope: str,
        target_numbers: List[int],
        force_regenerate: bool
    ) -> Dict[str, Any]:
        """执行分镜图片生成任务"""
        from app.models.shot import Shot
        from sqlalchemy import select
        from app.tasks.shot_task import generate_single_shot_image_task

        try:
            # 获取分镜列表
            stmt = select(Shot).where(Shot.creation_id == creation.creation_id).order_by(Shot.shot_number)
            result = await db.execute(stmt)
            shots = result.scalars().all()

            if not shots:
                return {"error": "没有分镜数据，请先进行分镜分析"}

            # 根据 scope 筛选要生成的分镜
            shots_to_generate = []
            if scope == "all":
                shots_to_generate = [s for s in shots if force_regenerate or not s.image_url]
            elif scope == "first":
                shots_to_generate = [shots[0]] if shots else []
            elif scope == "last":
                shots_to_generate = [shots[-1]] if shots else []
            elif scope == "specific" and target_numbers:
                for num in target_numbers:
                    for s in shots:
                        if s.shot_number == num:
                            shots_to_generate.append(s)
                            break

            if not shots_to_generate:
                return {"task_id": "already_completed", "task_type": "storyboard_image", "message": "指定的分镜图片已生成，无需重复生成"}

            # 提交任务
            shot_ids = [s.shot_id for s in shots_to_generate]

            if len(shot_ids) == 1:
                # 单个分镜，直接调用单个任务
                task = generate_single_shot_image_task.delay(
                    shot_id=shot_ids[0],
                    creation_id=creation.creation_id
                )
            else:
                # 多个分镜，使用批量任务
                task = generate_creation_shots_task.delay(
                    creation_id=creation.creation_id,
                    force_regenerate=force_regenerate,
                    shot_ids=shot_ids
                )

            task_id = str(task.id)
            shot_desc = "、".join([f"分镜{s.shot_number}" for s in shots_to_generate[:5]])
            if len(shots_to_generate) > 5:
                shot_desc += f"等{len(shots_to_generate)}个分镜"

            logger.info(f"已提交分镜图片生成任务: task_id={task_id}, shots={shot_ids}")
            return {
                "task_id": task_id,
                "task_type": "storyboard_image",
                "message": f"正在为{shot_desc}生成图片..."
            }
        except Exception as e:
            logger.error(f"执行分镜图片任务失败: {e}")
            return {"error": str(e)}

    async def _execute_scene_image_task(
        self,
        db,
        creation,
        scope: str,
        target_numbers: List[int],
        force_regenerate: bool
    ) -> Dict[str, Any]:
        """执行场景图片生成任务"""
        from app.models.scene import Scene
        from sqlalchemy import select
        from app.tasks.step4_scene_image_gen_task import generate_single_scene_image_task

        try:
            stmt = select(Scene).where(Scene.creation_id == creation.creation_id).order_by(Scene.scene_id)
            result = await db.execute(stmt)
            scenes = result.scalars().all()

            if not scenes:
                return {"error": "没有场景数据，请先进行场景分析"}

            scenes_to_generate = []
            if scope == "all":
                scenes_to_generate = [s for s in scenes if force_regenerate or not s.image_url]
            elif scope == "first":
                scenes_to_generate = [scenes[0]] if scenes else []
            elif scope == "last":
                scenes_to_generate = [scenes[-1]] if scenes else []
            elif scope == "specific" and target_numbers:
                for i, num in enumerate(target_numbers):
                    if 0 < num <= len(scenes):
                        scenes_to_generate.append(scenes[num - 1])

            if not scenes_to_generate:
                return {"task_id": "already_completed", "task_type": "scene_image", "message": "指定的场景图片已生成"}

            if len(scenes_to_generate) == 1:
                task = generate_single_scene_image_task.delay(
                    scene_id=scenes_to_generate[0].scene_id,
                    creation_id=creation.creation_id
                )
            else:
                task = batch_generate_scene_images_task.delay(
                    creation_id=creation.creation_id
                )

            task_id = str(task.id)
            scene_desc = "、".join([s.title for s in scenes_to_generate[:3]])
            logger.info(f"已提交场景图片生成任务: task_id={task_id}")
            return {
                "task_id": task_id,
                "task_type": "scene_image",
                "message": f"正在为{scene_desc}生成图片..."
            }
        except Exception as e:
            logger.error(f"执行场景图片任务失败: {e}")
            return {"error": str(e)}

    async def _execute_character_image_task(
        self,
        db,
        creation,
        scope: str,
        target_name: str,
        force_regenerate: bool
    ) -> Dict[str, Any]:
        """执行角色图片生成任务"""
        from app.models.character import Character
        from sqlalchemy import select

        try:
            stmt = select(Character).where(
                Character.creation_id == creation.creation_id,
                Character.deleted_at.is_(None)
            )
            result = await db.execute(stmt)
            characters = result.scalars().all()

            if not characters:
                return {"error": "没有角色数据，请先进行角色分析"}

            chars_to_generate = []
            if scope == "all":
                chars_to_generate = [c for c in characters if force_regenerate or not c.image_url]
            elif scope == "specific" and target_name:
                for c in characters:
                    if target_name.lower() in c.name.lower():
                        chars_to_generate.append(c)

            if not chars_to_generate:
                return {"task_id": "already_completed", "task_type": "character_image", "message": "指定的角色图片已生成"}

            visual_style = creation.extra_data.get("visual_style", "anime") if creation.extra_data else "anime"
            character_ids = [c.character_id for c in chars_to_generate]

            task = generate_character_image_task.delay(
                character_ids=character_ids,
                visual_style=visual_style,
                creation_uuid=creation.uuid,
                creation_id=creation.creation_id
            )

            task_id = str(task.id)
            char_names = "、".join([c.name for c in chars_to_generate[:3]])
            logger.info(f"已提交角色图片生成任务: task_id={task_id}")
            return {
                "task_id": task_id,
                "task_type": "character_image",
                "message": f"正在为{char_names}生成图片..."
            }
        except Exception as e:
            logger.error(f"执行角色图片任务失败: {e}")
            return {"error": str(e)}

    async def _execute_video_task(
        self,
        db,
        creation,
        scope: str,
        target_numbers: List[int],
        force_regenerate: bool
    ) -> Dict[str, Any]:
        """执行视频生成任务"""
        try:
            # 目前视频生成只支持全部生成
            task = generate_all_videos_v2_task.delay(
                creation_id=creation.creation_id,
                user_id=creation.owner_id
            )
            task_id = str(task.id)
            logger.info(f"已提交视频生成任务: task_id={task_id}")
            return {"task_id": task_id, "task_type": "video", "message": "正在生成视频..."}
        except Exception as e:
            logger.error(f"执行视频生成任务失败: {e}")
            return {"error": str(e)}

    async def _execute_task_by_intent(self, db, creation_uuid: str, intent_type: str) -> Dict[str, Any]:
        """根据意图类型执行对应任务（兼容旧逻辑）"""
        task_map = {
            "analyze_character": self.analyze_character,
            "analyze_scene": self.analyze_scene,
            "analyze_shot": self.analyze_shot,
            "auto_create": self.auto_create,
        }

        if intent_type in task_map:
            return await task_map[intent_type](db, creation_uuid)
        else:
            return {"error": f"不支持的任务类型: {intent_type}"}

    async def handle_settings_modification(
        self,
        db,
        creation_uuid: str,
        user_message: str,
        chat_history: list = None
    ) -> AsyncIterator[str]:
        """处理创作设置修改"""
        message_id = f"msg_{uuid.uuid4().hex[:12]}"

        try:
            from langchain_core.messages import HumanMessage
            from langchain_openai import ChatOpenAI
            from app.core.config import settings
            from app.models.creation import Creation
            from sqlalchemy import select
            from sqlalchemy.orm.attributes import flag_modified

            creation = await self._get_creation_async(db, creation_uuid)
            if not creation:
                yield self._make_sse("message", {
                    "type": "message.content",
                    "message_id": message_id,
                    "content": "创作项目不存在",
                    "delta": "创作项目不存在",
                }, role="assistant")
                return

            # 获取当前设置
            extra_data = creation.extra_data or {}
            current_settings = {
                "aspect_ratio": extra_data.get("aspect_ratio", "16:9"),
                "visual_style": extra_data.get("visual_style", "anime"),
            }

            llm = ChatOpenAI(
                model=settings.LLM_MODEL_NAME or "gpt-4",
                api_key=settings.OPENAI_API_KEY,
                base_url=str(settings.OPENAI_BASE_URL) if settings.OPENAI_BASE_URL else None,
                temperature=0.1,
                extra_body={"thinking": {"type": "disabled"}},
            )

            chat_history_text = ""
            if chat_history:
                chat_history_text = "对话历史：\n"
                for msg in chat_history[-6:]:
                    role = "用户" if msg.get("role") == "user" else "助手"
                    content = msg.get("content", "")[:200]
                    chat_history_text += f"{role}: {content}\n"

            prompt = SETTINGS_COLLECT_PROMPT.format(
                current_settings=json.dumps(current_settings, ensure_ascii=False),
                user_message=user_message,
                chat_history=chat_history_text
            )

            response = await llm.ainvoke([HumanMessage(content=prompt)])
            result_text = response.content.strip()

            import re
            json_match = re.search(r'\{[\s\S]*\}', result_text)
            if json_match:
                result = json.loads(json_match.group())
            else:
                result = {"action": "ask_for_info", "response": "请告诉我您想要设置的内容，比如分辨率（横屏16:9或竖屏9:16）或风格（写实、日漫、水彩等）。"}

            yield self._make_sse("message.start", {
                "type": "message.start",
                "message_id": message_id,
            }, role="assistant")

            if result.get("action") == "update_settings":
                # 更新设置
                new_settings = result.get("settings", {})
                for key, value in new_settings.items():
                    if value:
                        extra_data[key] = value

                creation.extra_data = extra_data
                flag_modified(creation, "extra_data")
                await db.commit()

                response_msg = result.get("response", f"好的，已更新设置：{json.dumps(new_settings, ensure_ascii=False)}")
            else:
                response_msg = result.get("response", "请告诉我您想要的设置。")

            yield self._make_sse("message", {
                "type": "message.content",
                "message_id": message_id,
                "content": response_msg,
                "delta": response_msg,
            }, role="assistant")

            yield self._make_sse("message.end", {
                "type": "message.end",
                "message_id": message_id,
                "finish_reason": "completed"
            })

        except Exception as e:
            logger.error(f"处理设置修改失败: {e}")
            yield self._make_sse("message", {
                "type": "message.content",
                "message_id": message_id,
                "content": f"处理设置时发生错误：{str(e)}",
                "delta": f"处理设置时发生错误：{str(e)}",
            }, role="assistant")

    async def handle_prompt_operation(
        self,
        db,
        creation_uuid: str,
        user_message: str,
        chat_history: list = None,
        operation_type: str = "modify"
    ) -> AsyncIterator[str]:
        """处理提示词操作（查看、修改、生成）"""
        message_id = f"msg_{uuid.uuid4().hex[:12]}"

        try:
            from langchain_core.messages import HumanMessage
            from langchain_openai import ChatOpenAI
            from app.core.config import settings
            from app.models.shot import Shot
            from app.models.scene import Scene
            from sqlalchemy import select
            from sqlalchemy.orm.attributes import flag_modified

            creation = await self._get_creation_async(db, creation_uuid)
            if not creation:
                yield self._make_sse("message", {
                    "type": "message.content",
                    "message_id": message_id,
                    "content": "创作项目不存在",
                    "delta": "创作项目不存在",
                }, role="assistant")
                return

            # 获取上下文信息
            context_info = await self.get_context_for_intent(db, creation_uuid, "generate_storyboard_images")

            llm = ChatOpenAI(
                model=settings.LLM_MODEL_NAME or "gpt-4",
                api_key=settings.OPENAI_API_KEY,
                base_url=str(settings.OPENAI_BASE_URL) if settings.OPENAI_BASE_URL else None,
                temperature=0.1,
                extra_body={"thinking": {"type": "disabled"}},
            )

            chat_history_text = ""
            if chat_history:
                chat_history_text = "对话历史：\n"
                for msg in chat_history[-6:]:
                    role = "用户" if msg.get("role") == "user" else "助手"
                    content = msg.get("content", "")[:200]
                    chat_history_text += f"{role}: {content}\n"

            prompt = MODIFY_PROMPT_PROMPT.format(
                user_message=user_message,
                chat_history=chat_history_text,
                context_info=context_info
            )

            response = await llm.ainvoke([HumanMessage(content=prompt)])
            result_text = response.content.strip()

            import re
            json_match = re.search(r'\{[\s\S]*\}', result_text)
            if json_match:
                result = json.loads(json_match.group())
            else:
                result = {"action": "view_prompt", "target_type": "shot", "target_numbers": [1]}

            yield self._make_sse("message.start", {
                "type": "message.start",
                "message_id": message_id,
            }, role="assistant")

            action = result.get("action", "view_prompt")
            target_type = result.get("target_type", "shot")
            target_numbers = result.get("target_numbers", [])

            response_msg = ""

            if target_type == "shot":
                stmt = select(Shot).where(Shot.creation_id == creation.creation_id).order_by(Shot.shot_number)
                db_result = await db.execute(stmt)
                shots = db_result.scalars().all()

                if action == "view_prompt":
                    # 查看提示词
                    for num in target_numbers:
                        for shot in shots:
                            if shot.shot_number == num:
                                prompt_text = shot.image_prompt or "（尚未生成提示词）"
                                response_msg += f"分镜{num}的提示词：\n{prompt_text}\n\n"
                                break
                    if not response_msg:
                        response_msg = "未找到指定的分镜"

                elif action == "modify_prompt":
                    # 修改提示词
                    new_prompt = result.get("new_prompt", "")
                    modified_count = 0
                    for num in target_numbers:
                        for shot in shots:
                            if shot.shot_number == num:
                                shot.image_prompt = new_prompt
                                modified_count += 1
                                break
                    if modified_count > 0:
                        await db.commit()
                        response_msg = f"已修改{modified_count}个分镜的提示词"
                    else:
                        response_msg = "未找到指定的分镜"

                elif action == "generate_prompt":
                    # 只生成提示词，不生成图片
                    from app.utils.ai_client import AIClient
                    from app.utils.file_utils import read_prompt_file

                    ai_client = AIClient()
                    generated_count = 0

                    for num in target_numbers:
                        for shot in shots:
                            if shot.shot_number == num:
                                # 生成提示词
                                prompt_template = read_prompt_file("shot_image.md")
                                scene = shot.scene
                                visual_style = creation.extra_data.get("visual_style", "anime") if creation.extra_data else "anime"

                                messages = [{
                                    "role": "user",
                                    "content": f"{prompt_template}\n\n分镜描述：{shot.description}\n旁白：{shot.narration or '无'}\n视觉风格：{visual_style}"
                                }]

                                try:
                                    resp = ai_client.chat_completion(messages=messages)
                                    shot.image_prompt = resp.get("content", "").strip()
                                    generated_count += 1
                                except Exception as e:
                                    logger.error(f"生成分镜{num}提示词失败: {e}")

                    if generated_count > 0:
                        await db.commit()
                        response_msg = f"已为{generated_count}个分镜生成提示词"

                        # 显示生成的提示词
                        for num in target_numbers:
                            for shot in shots:
                                if shot.shot_number == num and shot.image_prompt:
                                    response_msg += f"\n\n分镜{num}的提示词：\n{shot.image_prompt[:200]}..."
                                    break
                    else:
                        response_msg = "未能生成提示词"

            elif target_type == "scene":
                stmt = select(Scene).where(Scene.creation_id == creation.creation_id).order_by(Scene.scene_id)
                db_result = await db.execute(stmt)
                scenes = db_result.scalars().all()

                if action == "view_prompt":
                    for i, num in enumerate(target_numbers):
                        if 0 < num <= len(scenes):
                            scene = scenes[num - 1]
                            prompt_text = scene.extra_data.get("image_prompt", "（尚未生成提示词）") if scene.extra_data else "（尚未生成提示词）"
                            response_msg += f"场景{num}（{scene.title}）的提示词：\n{prompt_text}\n\n"
                    if not response_msg:
                        response_msg = "未找到指定的场景"

                elif action == "modify_prompt":
                    new_prompt = result.get("new_prompt", "")
                    modified_count = 0
                    for num in target_numbers:
                        if 0 < num <= len(scenes):
                            scene = scenes[num - 1]
                            if scene.extra_data is None:
                                scene.extra_data = {}
                            scene.extra_data["image_prompt"] = new_prompt
                            flag_modified(scene, "extra_data")
                            modified_count += 1
                    if modified_count > 0:
                        await db.commit()
                        response_msg = f"已修改{modified_count}个场景的提示词"
                    else:
                        response_msg = "未找到指定的场景"

            if not response_msg:
                response_msg = result.get("description", "操作完成")

            yield self._make_sse("message", {
                "type": "message.content",
                "message_id": message_id,
                "content": response_msg,
                "delta": response_msg,
            }, role="assistant")

            yield self._make_sse("message.end", {
                "type": "message.end",
                "message_id": message_id,
                "finish_reason": "completed"
            })

        except Exception as e:
            logger.error(f"处理提示词操作失败: {e}")
            yield self._make_sse("message", {
                "type": "message.content",
                "message_id": message_id,
                "content": f"处理提示词时发生错误：{str(e)}",
                "delta": f"处理提示词时发生错误：{str(e)}",
            }, role="assistant")

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
