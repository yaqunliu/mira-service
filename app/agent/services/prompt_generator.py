"""
Agent 提示词生成服务

将提示词生成逻辑从 Celery 任务中抽离到 Agent 层
支持查询知识库、获取上下文、调用 LLM 生成高质量提示词
"""

from typing import Dict, Any, List, Optional
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sqlalchemy.orm import selectinload
from sqlalchemy.orm.attributes import flag_modified

from app.core.logger import logger
from app.core.config import settings
from app.agent.knowledge.base import (
    get_style_knowledge,
    get_storyboard_knowledge,
    get_prompt_knowledge
)


class AgentPromptGenerator:
    """Agent 提示词生成服务"""

    def __init__(self):
        self.style_kb = None
        self.storyboard_kb = None
        self.prompt_kb = None

    def _get_knowledge_bases(self):
        """延迟初始化知识库"""
        if self.style_kb is None:
            self.style_kb = get_style_knowledge()
        if self.storyboard_kb is None:
            self.storyboard_kb = get_storyboard_knowledge()
        if self.prompt_kb is None:
            self.prompt_kb = get_prompt_knowledge()

    async def generate_shot_image_prompt(
        self,
        db: AsyncSession,
        shot_id: int,
        visual_style: str = "anime",
        force_regenerate: bool = False
    ) -> Dict[str, Any]:
        """
        生成分镜图片提示词

        Args:
            db: 数据库会话
            shot_id: 分镜ID
            visual_style: 视觉风格
            force_regenerate: 是否强制重新生成

        Returns:
            生成结果，包含 image_prompt
        """
        from app.models.shot import Shot
        from app.models.scene import Scene

        try:
            self._get_knowledge_bases()

            # 获取分镜信息
            stmt = select(Shot).options(
                selectinload(Shot.scene),
                selectinload(Shot.characters)
            ).where(Shot.shot_id == shot_id)
            result = await db.execute(stmt)
            shot = result.scalar_one_or_none()

            if not shot:
                return {"success": False, "error": f"分镜不存在: {shot_id}"}

            # 检查是否已有提示词
            if shot.image_prompt and not force_regenerate:
                return {
                    "success": True,
                    "shot_id": shot_id,
                    "image_prompt": shot.image_prompt,
                    "cached": True
                }

            # 获取场景上下文
            scene = shot.scene
            scene_context = ""
            if scene:
                scene_context = f"场景: {scene.title}, 地点: {scene.location}, 时间: {scene.time_setting}, 氛围: {scene.atmosphere}"

            # 获取角色上下文
            character_context = ""
            if shot.characters:
                char_descs = [f"{c.name}: {c.appearance_desc or ''}" for c in shot.characters[:3]]
                character_context = "角色: " + "; ".join(char_descs)

            # 查询知识库获取分镜技巧
            storyboard_tips = await self.storyboard_kb.query(
                f"分镜 {shot.description[:50] if shot.description else ''}",
                k=2
            )
            tips_text = "\n".join([t["content"][:200] for t in storyboard_tips])

            # 获取风格提示词
            style_prompt = self.style_kb.get_style_prompt(visual_style)

            # 调用 LLM 生成提示词
            from langchain_core.messages import HumanMessage
            from langchain_openai import ChatOpenAI

            llm = ChatOpenAI(
                model=settings.LLM_MODEL_NAME or "gpt-4",
                api_key=settings.OPENAI_API_KEY,
                base_url=str(settings.OPENAI_BASE_URL) if settings.OPENAI_BASE_URL else None,
                temperature=0.7,
                extra_body={"thinking": {"type": "disabled"}},
            )

            prompt = f"""你是一个专业的AI图片生成提示词工程师。请根据以下信息生成一个高质量的图片生成提示词。

分镜描述: {shot.description or '无'}
旁白: {shot.narration or '无'}
{scene_context}
{character_context}

分镜技巧参考:
{tips_text}

视觉风格: {visual_style}
风格关键词: {style_prompt}

要求:
1. 使用英文输出提示词
2. 包含镜头类型、构图、光线、氛围描述
3. 融入角色特征和场景元素
4. 添加风格关键词
5. 提示词长度控制在100-200词

只输出提示词，不要其他内容。"""

            response = await llm.ainvoke([HumanMessage(content=prompt)])
            image_prompt = response.content.strip()

            # 保存到数据库
            shot.image_prompt = image_prompt
            await db.commit()

            logger.info(f"已生成分镜 {shot_id} 的图片提示词")

            return {
                "success": True,
                "shot_id": shot_id,
                "image_prompt": image_prompt,
                "cached": False
            }

        except Exception as e:
            logger.error(f"生成分镜图片提示词失败: {e}")
            return {"success": False, "error": str(e)}

    async def generate_shot_video_prompt(
        self,
        db: AsyncSession,
        shot_id: int,
        force_regenerate: bool = False
    ) -> Dict[str, Any]:
        """生成分镜视频提示词"""
        from app.models.shot import Shot

        try:
            self._get_knowledge_bases()

            stmt = select(Shot).where(Shot.shot_id == shot_id)
            result = await db.execute(stmt)
            shot = result.scalar_one_or_none()

            if not shot:
                return {"success": False, "error": f"分镜不存在: {shot_id}"}

            # 检查是否已有视频提示词
            extra_data = shot.extra_data or {}
            if extra_data.get("video_prompt") and not force_regenerate:
                return {
                    "success": True,
                    "shot_id": shot_id,
                    "video_prompt": extra_data["video_prompt"],
                    "cached": True
                }

            # 查询知识库获取视频运动技巧
            video_tips = await self.storyboard_kb.query("视频运动 camera movement", k=2)
            tips_text = "\n".join([t["content"][:200] for t in video_tips])

            from langchain_core.messages import HumanMessage
            from langchain_openai import ChatOpenAI

            llm = ChatOpenAI(
                model=settings.LLM_MODEL_NAME or "gpt-4",
                api_key=settings.OPENAI_API_KEY,
                base_url=str(settings.OPENAI_BASE_URL) if settings.OPENAI_BASE_URL else None,
                temperature=0.7,
                extra_body={"thinking": {"type": "disabled"}},
            )

            prompt = f"""你是一个专业的AI视频生成提示词工程师。请根据以下信息生成一个视频运动提示词。

分镜描述: {shot.description or '无'}
旁白: {shot.narration or '无'}
图片提示词: {shot.image_prompt or '无'}

视频技巧参考:
{tips_text}

要求:
1. 使用英文输出
2. 描述镜头运动（pan, zoom, tilt, dolly等）
3. 描述画面中元素的运动
4. 保持与图片提示词风格一致
5. 提示词简洁，30-50词

只输出视频提示词，不要其他内容。"""

            response = await llm.ainvoke([HumanMessage(content=prompt)])
            video_prompt = response.content.strip()

            # 保存到数据库
            if shot.extra_data is None:
                shot.extra_data = {}
            shot.extra_data["video_prompt"] = video_prompt
            flag_modified(shot, "extra_data")
            await db.commit()

            logger.info(f"已生成分镜 {shot_id} 的视频提示词")

            return {
                "success": True,
                "shot_id": shot_id,
                "video_prompt": video_prompt,
                "cached": False
            }

        except Exception as e:
            logger.error(f"生成分镜视频提示词失败: {e}")
            return {"success": False, "error": str(e)}

    async def generate_scene_image_prompt(
        self,
        db: AsyncSession,
        scene_id: int,
        visual_style: str = "anime",
        force_regenerate: bool = False
    ) -> Dict[str, Any]:
        """生成场景图片提示词"""
        from app.models.scene import Scene

        try:
            self._get_knowledge_bases()

            stmt = select(Scene).where(Scene.scene_id == scene_id)
            result = await db.execute(stmt)
            scene = result.scalar_one_or_none()

            if not scene:
                return {"success": False, "error": f"场景不存在: {scene_id}"}

            # 检查是否已有提示词
            extra_data = scene.extra_data or {}
            if extra_data.get("image_prompt") and not force_regenerate:
                return {
                    "success": True,
                    "scene_id": scene_id,
                    "image_prompt": extra_data["image_prompt"],
                    "cached": True
                }

            # 查询知识库
            scene_tips = await self.prompt_kb.query("场景图片提示词", k=2)
            tips_text = "\n".join([t["content"][:200] for t in scene_tips])

            style_prompt = self.style_kb.get_style_prompt(visual_style)

            from langchain_core.messages import HumanMessage
            from langchain_openai import ChatOpenAI

            llm = ChatOpenAI(
                model=settings.LLM_MODEL_NAME or "gpt-4",
                api_key=settings.OPENAI_API_KEY,
                base_url=str(settings.OPENAI_BASE_URL) if settings.OPENAI_BASE_URL else None,
                temperature=0.7,
                extra_body={"thinking": {"type": "disabled"}},
            )

            prompt = f"""你是一个专业的AI图片生成提示词工程师。请根据以下场景信息生成一个高质量的场景图片提示词。

场景标题: {scene.title}
地点: {scene.location or '未指定'}
时间: {scene.time_setting or '未指定'}
空间类型: {scene.space_type or '未指定'}
氛围: {scene.atmosphere or '未指定'}

提示词技巧参考:
{tips_text}

视觉风格: {visual_style}
风格关键词: {style_prompt}

要求:
1. 使用英文输出
2. 描述场景的空间感和层次感
3. 包含光线、天气、氛围描述
4. 融入建筑或自然元素细节
5. 添加风格关键词
6. 提示词长度100-150词

只输出提示词，不要其他内容。"""

            response = await llm.ainvoke([HumanMessage(content=prompt)])
            image_prompt = response.content.strip()

            # 保存到数据库
            if scene.extra_data is None:
                scene.extra_data = {}
            scene.extra_data["image_prompt"] = image_prompt
            flag_modified(scene, "extra_data")
            await db.commit()

            logger.info(f"已生成场景 {scene_id} 的图片提示词")

            return {
                "success": True,
                "scene_id": scene_id,
                "image_prompt": image_prompt,
                "cached": False
            }

        except Exception as e:
            logger.error(f"生成场景图片提示词失败: {e}")
            return {"success": False, "error": str(e)}

    async def generate_character_image_prompt(
        self,
        db: AsyncSession,
        character_id: int,
        visual_style: str = "anime",
        force_regenerate: bool = False
    ) -> Dict[str, Any]:
        """生成角色图片提示词"""
        from app.models.character import Character

        try:
            self._get_knowledge_bases()

            stmt = select(Character).where(Character.character_id == character_id)
            result = await db.execute(stmt)
            character = result.scalar_one_or_none()

            if not character:
                return {"success": False, "error": f"角色不存在: {character_id}"}

            # 检查是否已有提示词
            extra_data = character.extra_data or {}
            if extra_data.get("image_prompt") and not force_regenerate:
                return {
                    "success": True,
                    "character_id": character_id,
                    "image_prompt": extra_data["image_prompt"],
                    "cached": True
                }

            # 查询知识库
            char_tips = await self.prompt_kb.query("角色图片提示词", k=2)
            tips_text = "\n".join([t["content"][:200] for t in char_tips])

            style_prompt = self.style_kb.get_style_prompt(visual_style)

            from langchain_core.messages import HumanMessage
            from langchain_openai import ChatOpenAI

            llm = ChatOpenAI(
                model=settings.LLM_MODEL_NAME or "gpt-4",
                api_key=settings.OPENAI_API_KEY,
                base_url=str(settings.OPENAI_BASE_URL) if settings.OPENAI_BASE_URL else None,
                temperature=0.7,
                extra_body={"thinking": {"type": "disabled"}},
            )

            prompt = f"""你是一个专业的AI图片生成提示词工程师。请根据以下角色信息生成一个高质量的角色立绘提示词。

角色名称: {character.name}
角色类型: {character.role_type or '未指定'}
年龄: {character.age or '未指定'}
性别: {character.gender or '未指定'}
外貌描述: {character.appearance_desc or '无'}
性格特点: {character.personality or '无'}
服装描述: {character.costume_desc or '无'}

提示词技巧参考:
{tips_text}

视觉风格: {visual_style}
风格关键词: {style_prompt}

要求:
1. 使用英文输出
2. 生成半身或全身立绘的提示词
3. 包含面部特征、表情、姿态描述
4. 详细描述服装和配饰
5. 添加光线和背景描述
6. 融入风格关键词
7. 提示词长度100-150词

只输出提示词，不要其他内容。"""

            response = await llm.ainvoke([HumanMessage(content=prompt)])
            image_prompt = response.content.strip()

            # 保存到数据库
            if character.extra_data is None:
                character.extra_data = {}
            character.extra_data["image_prompt"] = image_prompt
            flag_modified(character, "extra_data")
            await db.commit()

            logger.info(f"已生成角色 {character_id} 的图片提示词")

            return {
                "success": True,
                "character_id": character_id,
                "image_prompt": image_prompt,
                "cached": False
            }

        except Exception as e:
            logger.error(f"生成角色图片提示词失败: {e}")
            return {"success": False, "error": str(e)}

    async def generate_all_prompts_for_creation(
        self,
        db: AsyncSession,
        creation_id: int,
        prompt_types: List[str] = None,
        visual_style: str = "anime",
        force_regenerate: bool = False
    ) -> Dict[str, Any]:
        """
        为创作批量生成所有提示词

        Args:
            db: 数据库会话
            creation_id: 创作ID
            prompt_types: 要生成的提示词类型列表 ['character', 'scene', 'shot_image', 'shot_video']
            visual_style: 视觉风格
            force_regenerate: 是否强制重新生成

        Returns:
            生成结果
        """
        from app.models.creation import Creation
        from app.models.character import Character
        from app.models.scene import Scene
        from app.models.shot import Shot

        if prompt_types is None:
            prompt_types = ['character', 'scene', 'shot_image']

        results = {
            "creation_id": creation_id,
            "characters": [],
            "scenes": [],
            "shots": [],
            "errors": []
        }

        try:
            # 获取创作信息
            stmt = select(Creation).where(Creation.creation_id == creation_id)
            result = await db.execute(stmt)
            creation = result.scalar_one_or_none()

            if not creation:
                return {"success": False, "error": "创作不存在"}

            # 获取风格设置
            extra_data = creation.extra_data or {}
            visual_style = extra_data.get("visual_style", visual_style)

            # 生成角色提示词
            if 'character' in prompt_types:
                char_stmt = select(Character).where(
                    Character.creation_id == creation_id,
                    Character.deleted_at.is_(None)
                )
                char_result = await db.execute(char_stmt)
                characters = char_result.scalars().all()

                for char in characters:
                    try:
                        result = await self.generate_character_image_prompt(
                            db, char.character_id, visual_style, force_regenerate
                        )
                        results["characters"].append(result)
                    except Exception as e:
                        results["errors"].append(f"角色 {char.name}: {str(e)}")

            # 生成场景提示词
            if 'scene' in prompt_types:
                scene_stmt = select(Scene).where(
                    Scene.creation_id == creation_id,
                    Scene.deleted_at.is_(None)
                )
                scene_result = await db.execute(scene_stmt)
                scenes = scene_result.scalars().all()

                for scene in scenes:
                    try:
                        result = await self.generate_scene_image_prompt(
                            db, scene.scene_id, visual_style, force_regenerate
                        )
                        results["scenes"].append(result)
                    except Exception as e:
                        results["errors"].append(f"场景 {scene.title}: {str(e)}")

            # 生成分镜图片提示词
            if 'shot_image' in prompt_types:
                shot_stmt = select(Shot).where(Shot.creation_id == creation_id)
                shot_result = await db.execute(shot_stmt)
                shots = shot_result.scalars().all()

                for shot in shots:
                    try:
                        result = await self.generate_shot_image_prompt(
                            db, shot.shot_id, visual_style, force_regenerate
                        )
                        results["shots"].append(result)
                    except Exception as e:
                        results["errors"].append(f"分镜 {shot.shot_number}: {str(e)}")

            # 生成分镜视频提示词
            if 'shot_video' in prompt_types:
                shot_stmt = select(Shot).where(Shot.creation_id == creation_id)
                shot_result = await db.execute(shot_stmt)
                shots = shot_result.scalars().all()

                for shot in shots:
                    try:
                        result = await self.generate_shot_video_prompt(
                            db, shot.shot_id, force_regenerate
                        )
                        if "video_prompt" not in results:
                            results["video_prompts"] = []
                        results["video_prompts"].append(result)
                    except Exception as e:
                        results["errors"].append(f"分镜视频 {shot.shot_number}: {str(e)}")

            results["success"] = True
            return results

        except Exception as e:
            logger.error(f"批量生成提示词失败: {e}")
            return {"success": False, "error": str(e)}


# 全局实例
_prompt_generator = None


def get_prompt_generator() ->   PromptGenerator:
    """获取提示词生成器实例"""
    global _prompt_generator
    if _prompt_generator is None:
        _prompt_generator = AgentPromptGenerator()
    return _prompt_generator
