"""
Agent 状态查询处理器（AI驱动版）

提供自然语言查询创作状态的能力，支持从数据库获取实时数据并使用AI生成响应
支持流式输出
"""

from typing import Dict, Any, List, Optional, AsyncIterator
from datetime import datetime
import uuid
import json
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from langchain_core.messages import SystemMessage, HumanMessage
from langchain_openai import ChatOpenAI
from app.models.character import Character
from app.models.scene import Scene
from app.models.shot import Shot
from app.models.creation import Creation
from app.models.agent_session import AgentSession, ProductionStage
from app.core.logger import logger
from app.core.config import settings
import re


SIMPLE_SYSTEM_PROMPT = """你是漫画短剧助手，回答要简洁直接。

回复规则：
1. 用最少的字告诉用户核心结果
2. 数据列表最多5项，超出用"等"省略
3. 不要冗长的建议和鼓励
4. 用emoji增加可读性即可
5. 中文回复

格式：
- 开头：一句话说清状态
- 数据：简短列表
- 结尾：下一步建议（可选，一句话）"""

INTENT_DETECTION_PROMPT = """判断用户消息的意图，只返回意图类型（不需要解释）。

意图类型：
- status_query: 纯询问状态/进度/情况（问"怎么样"、"如何"、"多少"但没有动作词）
- character_query: 纯询问角色数量/列表（问"有多少人物"、"角色列表"）
- scene_query: 纯询问场景数量/列表（问"有多少场景"、"场景列表"）
- character_image_query: 纯询问角色图片生成状态（问"角色图片"、"角色图像"、"角色头像"）
- scene_image_query: 纯询问场景图片生成状态（问"场景图片"、"场景图像"）
- storyboard_image_query: 纯询问分镜图片生成状态（问"分镜图片"、"分镜图像"、"镜头图片"）
- video_query: 纯询问视频生成状态（问"视频"、"影片"）
- workflow_action: 要求执行某个操作/任务（有任何动作词）

关键判断规则：
1. "生成图片"、"生成角色"、"开始分析"、"继续"、"下一步"、"帮我"、"为我的...生成" → workflow_action
2. "状态怎么样"、"进度如何"、"进行到哪了"、"有多少"、"情况如何" → status_query（纯询问）
3. "角色图片"、"角色图像"、"角色头像" → character_image_query
4. "场景图片"、"场景图像" → scene_image_query
5. "分镜图片"、"分镜图像"、"镜头图片" → storyboard_image_query
6. "视频"、"影片" → video_query
7. 如果用户想要AI去做某件事（生成、创建、分析、开始）→ workflow_action

例子：
- "当前创作状态怎么样？" → status_query
- "有多少人物？" → character_query
- "角色图片生成了吗？" → character_image_query
- "场景图片有多少张？" → scene_image_query
- "分镜图片生成进度如何？" → storyboard_image_query
- "视频生成完了吗？" → video_query
- "开始为我的所有角色生成图片吧" → workflow_action（因为有"开始"和"生成"）
- "帮我生成角色图片" → workflow_action
- "继续进行下一步" → workflow_action

只返回类型名称，格式：类型"""


class AIStatusQueryHandler:
    """AI驱动的状态查询处理器"""

    def __init__(self):
        """初始化处理器"""
        self.llm = ChatOpenAI(
            model=settings.LLM_MODEL_NAME or "gpt-4",
            api_key=settings.OPENAI_API_KEY,
            base_url=str(settings.OPENAI_BASE_URL) if settings.OPENAI_BASE_URL else None,
            temperature=0.3,
            extra_body={"thinking": {"type": "disabled"}},
        )
        logger.info("AIStatusQueryHandler 初始化完成")

    async def detect_intent_ai(self, message: str) -> str:
        """使用AI判断用户意图"""
        try:
            messages = [
                SystemMessage(content=INTENT_DETECTION_PROMPT),
                HumanMessage(content=f"用户消息: {message}")
            ]
            response = await self.llm.ainvoke(messages)
            raw_content = response.content
            intent = raw_content.strip().lower()
            logger.info(f"AI意图识别原始响应: '{raw_content}', 解析结果: '{intent}'")
            return intent
        except Exception as e:
            logger.error(f"AI意图识别失败: {e}")
            return "workflow_action"

    def detect_query_type(self, message: str) -> List[str]:
        """检测消息中的查询类型（正则备用方法）"""
        detected = []
        message_lower = message.lower()

        query_patterns = {
            "character_count": [
                r"有多少.*人物", r"角色.*多少", r"人物.*数量",
                r"有几个.*角色", r"人物.*列表", r"角色.*列表",
                r"人物.*名称", r"角色.*名称",
            ],
            "scene_count": [
                r"有多少.*场景", r"场景.*多少", r"场景.*数量",
                r"有几个.*场景", r"场景.*列表",
            ],
            "image_status": [
                r"图片.*生成", r"图像.*状态", r"生成.*图片",
                r"图片.*数量", r"有多少.*图片", r"角色.*图片",
                r"场景.*图片", r"生成了.*图片",
            ],
            "stage_status": [
                r"当前.*阶段", r"制作.*进度", r"创作.*状态",
                r"现在.*哪步", r"进行.*哪步", r"状态.*如何",
                r"进行.*如何", r"进度.*如何",
            ],
            "overall_status": [
                r"总体.*状态", r"整体.*情况", r"创作.*概况",
                r"项目.*状态", r"summary", r"概况", r"状态",
                r"现在.*情况", r"现在.*进度", r"项目.*进度",
            ],
            "storyboard_count": [
                r"分镜.*多少", r"镜头.*多少", r"有多少.*分镜",
                r"shot.*多少", r"分镜.*列表",
            ],
        }

        for query_type, patterns in query_patterns.items():
            for pattern in patterns:
                if re.search(pattern, message_lower):
                    detected.append(query_type)
                    break

        return detected if detected else ["overall_status"]

    async def get_realtime_data(
        self,
        db: AsyncSession,
        creation_uuid: str
    ) -> Dict[str, Any]:
        """从数据库获取实时数据"""
        try:
            creation_stmt = select(Creation).where(Creation.uuid == creation_uuid)
            creation_result = await db.execute(creation_stmt)
            creation = creation_result.scalar_one_or_none()

            if not creation:
                return {"error": "创作项目不存在"}

            creation_id = creation.creation_id

            character_stmt = select(Character).where(
                Character.creation_id == creation_id,
                Character.deleted_at.is_(None)
            )
            character_result = await db.execute(character_stmt)
            characters = character_result.scalars().all()

            scene_stmt = select(Scene).where(
                Scene.creation_id == creation_id,
                Scene.deleted_at.is_(None)
            )
            scene_result = await db.execute(scene_stmt)
            scenes = scene_result.scalars().all()

            shot_stmt = select(Shot).where(
                Shot.scene_id.in_([s.scene_id for s in scenes]) if scenes else select(Shot).where(False)
            )
            shot_result = await db.execute(shot_stmt)
            shots = shot_result.scalars().all()

            session_stmt = select(AgentSession).where(
                AgentSession.creation_uuid == creation_uuid,
                AgentSession.deleted_at.is_(None)
            ).order_by(AgentSession.created_at.desc())
            session_result = await db.execute(session_stmt)
            session = session_result.scalar_one_or_none()

            return {
                "creation": creation,
                "characters": characters,
                "scenes": scenes,
                "shots": shots,
                "session": session,
                "current_stage": session.current_stage.value if session and session.current_stage else "init",
                "workflow_mode": creation.workflow_mode
            }
        except Exception as e:
            logger.error(f"获取实时数据失败: {e}")
            return {"error": str(e)}

    def _format_data_for_ai(self, data: Dict[str, Any], query_type: str) -> str:
        """将数据格式化为AI可读的文本"""
        lines = []

        creation = data.get("creation")
        characters = data.get("characters", [])
        scenes = data.get("scenes", [])
        shots = data.get("shots", [])
        current_stage = data.get("current_stage", "init")
        workflow_mode = data.get("workflow_mode", "traditional")

        stage_names = {
            "init": "初始化", "script_analysis": "剧本分析",
            "asset_generation": "资产生成", "storyboard_creation": "分镜创建",
            "audio_processing": "音频处理", "video_generation": "视频生成",
            "editing": "后期剪辑", "completed": "已完成", "error": "错误",
        }

        character_with_images = sum(1 for c in characters if getattr(c, 'image_url', None))
        scene_with_images = sum(1 for s in scenes if getattr(s, 'image_url', None))
        shot_with_images = sum(1 for s in shots if getattr(s, 'image_url', None))
        shots_with_videos = sum(1 for s in shots if getattr(s, 'video_status', None) == 'completed')

        if query_type in ["character_image_status", "character_images"]:
            lines.append(f"🎭 角色图片生成状态")
            lines.append(f"总角色数: {len(characters)}")
            lines.append(f"已生成图片: {character_with_images}")
            lines.append(f"待生成: {len(characters) - character_with_images}")
            if characters:
                lines.append("")
                lines.append("=== 角色图片详情 ===")
                for i, char in enumerate(characters, 1):
                    name = getattr(char, 'name', f'角色{i}') or f'角色{i}'
                    image_status = "✅ 已生成" if getattr(char, 'image_url', None) else "⏳ 待生成"
                    lines.append(f"{i}. {name} - {image_status}")
            return "\n".join(lines)

        if query_type in ["scene_image_status", "scene_images"]:
            lines.append(f"🏠 场景图片生成状态")
            lines.append(f"总场景数: {len(scenes)}")
            lines.append(f"已生成图片: {scene_with_images}")
            lines.append(f"待生成: {len(scenes) - scene_with_images}")
            if scenes:
                lines.append("")
                lines.append("=== 场景图片详情 ===")
                for i, scene in enumerate(scenes, 1):
                    name = getattr(scene, 'title', f'场景{i}') or f'场景{i}'
                    image_status = "✅ 已生成" if getattr(scene, 'image_url', None) else "⏳ 待生成"
                    lines.append(f"{i}. {name} - {image_status}")
            return "\n".join(lines)

        if query_type in ["storyboard_image_status", "storyboard_images"]:
            lines.append(f"🎬 分镜图片生成状态")
            lines.append(f"总分镜数: {len(shots)}")
            lines.append(f"已生成图片: {shot_with_images}")
            lines.append(f"待生成: {len(shots) - shot_with_images}")
            if shots:
                lines.append("")
                lines.append("=== 分镜图片详情 ===")
                for i, shot in enumerate(shots, 1):
                    title = getattr(shot, 'title', f'分镜{i}') or f'分镜{i}'
                    image_status = "✅ 已生成" if getattr(shot, 'image_url', None) else "⏳ 待生成"
                    lines.append(f"{i}. {title} - {image_status}")
            return "\n".join(lines)

        if query_type in ["video_status", "videos"]:
            lines.append(f"🎥 视频生成状态")
            lines.append(f"总分镜数: {len(shots)}")
            lines.append(f"已生成视频: {shots_with_videos}")
            lines.append(f"待生成: {len(shots) - shots_with_videos}")
            if shots:
                lines.append("")
                lines.append("=== 视频详情 ===")
                for i, shot in enumerate(shots, 1):
                    title = getattr(shot, 'title', f'分镜{i}') or f'分镜{i}'
                    video_status = getattr(shot, 'video_status', '') or ''
                    if video_status == 'completed':
                        status_text = "✅ 已完成"
                    elif video_status == 'processing':
                        status_text = "🔄 生成中"
                    elif video_status == 'failed':
                        status_text = "❌ 失败"
                    else:
                        status_text = "⏳ 待生成"
                    lines.append(f"{i}. {title} - {status_text}")
            return "\n".join(lines)

        lines.append(f"项目名称: {getattr(creation, 'title', '未命名项目')}")
        lines.append(f"创作模式: {workflow_mode}")
        lines.append(f"当前阶段: {stage_names.get(current_stage, current_stage)}")
        lines.append("")
        lines.append("=== 角色列表 ===")
        if characters:
            for i, char in enumerate(characters, 1):
                name = getattr(char, 'name', f'角色{i}') or f'角色{i}'
                gender = getattr(char, 'gender', '') or ''
                age = getattr(char, 'age_group', '') or ''
                has_image = bool(getattr(char, 'image_url', None))
                desc = getattr(char, 'description', '') or ''
                lines.append(f"{i}. {name} | 性别: {gender} | 年龄: {age} | 图片: {'有' if has_image else '无'} | 描述: {desc[:30] if desc else '无'}")
        else:
            lines.append("暂无角色数据")

        lines.append("")
        lines.append("=== 场景列表 ===")
        if scenes:
            for i, scene in enumerate(scenes, 1):
                name = getattr(scene, 'title', f'场景{i}') or f'场景{i}'
                location = getattr(scene, 'location', '') or ''
                time_setting = getattr(scene, 'time_setting', '') or ''
                has_image = bool(getattr(scene, 'image_url', None))
                desc = getattr(scene, 'description', '') or ''
                lines.append(f"{i}. {name} | 地点: {location} | 时间: {time_setting} | 图片: {'有' if has_image else '无'} | 描述: {desc[:30] if desc else '无'}")
        else:
            lines.append("暂无场景数据")

        lines.append("")
        lines.append("=== 分镜列表 ===")
        if shots:
            for i, shot in enumerate(shots, 1):
                title = getattr(shot, 'title', f'分镜{i}') or f'分镜{i}'
                desc = getattr(shot, 'description', '') or ''
                has_image = bool(getattr(shot, 'image_url', None))
                video_status = getattr(shot, 'video_status', '') or ''
                lines.append(f"{i}. {title} | 图片: {'有' if has_image else '无'} | 视频状态: {video_status or '未生成'} | 描述: {desc[:30] if desc else '无'}")
        else:
            lines.append("暂无分镜数据")

        lines.append("")
        lines.append("=== 资产统计 ===")
        lines.append(f"• 角色: {len(characters)} 个 (已生成图片: {character_with_images})")
        lines.append(f"• 场景: {len(scenes)} 个 (已生成图片: {scene_with_images})")
        lines.append(f"• 分镜: {len(shots)} 个 (已生成图片: {shot_with_images}, 已生成视频: {shots_with_videos})")

        return "\n".join(lines)

    async def generate_ai_response(
        self,
        db: AsyncSession,
        creation_uuid: str,
        user_message: str,
        query_types: List[str]
    ) -> AsyncIterator[str]:
        """使用AI生成状态响应（流式SSE输出）"""
        message_id = f"msg_{uuid.uuid4().hex[:12]}"
        try:
            data = await self.get_realtime_data(db, creation_uuid)

            if "error" in data:
                error_content = f"❌ 获取数据失败: {data['error']}"
                error_data = {
                    'type': 'message.content',
                    'message_id': message_id,
                    'role': 'assistant',
                    'content': error_content,
                    'delta': error_content,
                    'timestamp': datetime.utcnow().isoformat() + 'Z'
                }
                yield f"event: message\ndata: {json.dumps(error_data)}\n\n"
                end_data = {
                    'type': 'message.end',
                    'message_id': message_id,
                    'finish_reason': 'error'
                }
                yield f"event: message.end\ndata: {json.dumps(end_data)}\n\n"
                return

            formatted_data = self._format_data_for_ai(data, query_types[0] if query_types else "overall")

            query_type_str = ", ".join(query_types) if query_types else "整体状态"
            human_prompt = f"""用户问题: {user_message}

查询类型: {query_type_str}

项目数据:
{formatted_data}

请简洁回答。"""

            messages = [
                SystemMessage(content=SIMPLE_SYSTEM_PROMPT),
                HumanMessage(content=human_prompt)
            ]

            logger.info("开始流式调用AI")
            content_buffer = ""
            async for chunk in self.llm.astream(messages):
                if chunk.content:
                    content_buffer += chunk.content
                    chunk_data = {
                        'type': 'message.content',
                        'message_id': message_id,
                        'role': 'assistant',
                        'content': content_buffer,
                        'delta': chunk.content,
                        'timestamp': datetime.utcnow().isoformat() + 'Z'
                    }
                    yield f"event: message\ndata: {json.dumps(chunk_data)}\n\n"
            
            logger.info("流式调用完成")
            end_data = {
                'type': 'message.end',
                'message_id': message_id,
                'finish_reason': 'completed'
            }
            yield f"event: message.end\ndata: {json.dumps(end_data)}\n\n"

        except Exception as e:
            logger.error(f"AI流式生成失败: {e}", exc_info=True)
            error_content = f"❌ 处理查询时出错: {str(e)}"
            error_data = {
                'type': 'message.content',
                'message_id': message_id,
                'content': error_content,
                'delta': error_content,
                'timestamp': datetime.utcnow().isoformat() + 'Z'
            }
            yield f"event: message\ndata: {json.dumps(error_data)}\n\n"
            end_data = {
                'type': 'message.end',
                'message_id': message_id,
                'finish_reason': 'error'
            }
            yield f"event: message.end\ndata: {json.dumps(end_data)}\n\n"

    def _generate_fallback_response(self, data: Dict[str, Any], query_types: List[str]) -> str:
        """生成备用响应（当AI调用失败时）"""
        characters = data.get("characters", [])
        scenes = data.get("scenes", [])
        shots = data.get("shots", [])
        current_stage = data.get("current_stage", "init")

        stage_names = {
            "init": "初始化", "script_analysis": "剧本分析",
            "asset_generation": "资产生成", "storyboard_creation": "分镜创建",
            "audio_processing": "音频处理", "video_generation": "视频生成",
            "editing": "后期剪辑", "completed": "已完成", "error": "错误",
        }

        lines = ["📊 **创作状态总览**", ""]
        lines.append(f"🎯 **当前阶段**: {stage_names.get(current_stage, current_stage)}")
        lines.append("")
        lines.append("📋 **资产统计**")
        lines.append("---")
        lines.append(f"  • 角色: {len(characters)} 个")
        lines.append(f"  • 场景: {len(scenes)} 个")
        lines.append(f"  • 分镜: {len(shots)} 个")
        lines.append("---")
        lines.append("✅ **状态**: 正常")

        return "\n".join(lines)


ai_status_query_handler = AIStatusQueryHandler()
