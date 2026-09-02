"""
创作任务
"""
import os
import json
import tempfile
from app.core.celery_app import celery_app
from app.utils.us3 import download_file_smart
from app.utils.file_utils import read_prompt_file
from app.utils.ai_client import AIClient
from app.core.logger import logger
from app.db.base import _get_sync_session_factory
from sqlalchemy.orm import Session
from app.models.creation import Creation
from app.models.character import Character
from app.models.scene import Scene
from app.models.shot import Shot
from app.schemas.creation import CreationStatus
from app.utils.task_types import TaskType
from app.services.model_config_service import ModelConfigService
from app.utils.character_variants import (
    TYPE_ON_SCREEN,
    build_historical_library,
    parse_analysis_result,
    resolve_character_ids,
    resolve_narration_items,
    variant_key,
)

@celery_app.task(
    bind=True, 
    name="character_analysis_task",
    autoretry_for=(Exception,),
    max_retries=3,
    retry_backoff=True,
    retry_backoff_max=60,
    retry_jitter=True
)
def character_analysis_task(self, novel_id: int, chapter_id: int, creation_id: int, chapter_content_url: str):
    """
    角色分析任务（第一步）
    
    Args:
        novel_id: 小说ID（章节创作时为实际小说ID，文案创作时为0）
        chapter_id: 章节ID（章节创作时为实际章节ID，文案创作时为0）
        creation_id: 创作ID
        chapter_content_url: 文本内容URL（章节内容或文案内容）
    
    支持两种创作类型：
    - chapter: 章节创作，基于小说章节内容进行分析
    - script: 文案创作，基于上传的文本内容进行分析
    """
    db: Session = _get_sync_session_factory()()
    temp_file_path = None
    logger.info(f"开始角色分析任务: novel_id={novel_id}, chapter_id={chapter_id}, creation_id={creation_id}")
    try:
        self.update_state(
            state='PROGRESS',
            meta={
                'task_type': TaskType.CHARACTER_ANALYSIS,
                'novel_id': novel_id,
                'chapter_id': chapter_id,
                'creation_id': creation_id,
                'step': 'character_analysis'
            }
        )
        
        # 查询对应的 Creation 记录
        creation = db.query(Creation).filter(
            Creation.creation_id == creation_id
        ).with_for_update().first()
        
        if not creation:
            raise Exception(f"创作不存在: creation_id={creation_id}")
        
        # 初始化 AI Client
        extra_data = creation.extra_data or {}
        llm_model_name = extra_data.get("llm_model")
        ai_client = AIClient(llm_model_name=llm_model_name)
        logger.info(f"使用 LLM 模型: {llm_model_name if llm_model_name else '默认配置'}")

        # 更新任务状态：开始处理
        from app.services.creation_service import CreationService
        CreationService.update_creation_step_status(
            db=db,
            creation_id=creation_id,
            step_name="characterAnalysis",
            status="processing",
            task_id=self.request.id,
            commit=True
        )
        
        # 创建临时文件（使用系统临时目录，读取后立即删除）
        temp_fd, temp_file_path = tempfile.mkstemp(suffix='.txt')
        os.close(temp_fd)
        
        logger.info(f"准备下载章节内容到临时文件: {temp_file_path}")
        
        # 智能下载章节内容到临时文件（自动判断是 US3 链接还是普通 URL）
        download_result = download_file_smart(
            url_or_key=chapter_content_url,
            save_file=temp_file_path,
            bucket=None,
            timeout=60
        )
        
        if not download_result.get('success'):
            error_detail = download_result.get('message', '未知错误')
            logger.error(f"获取章节内容失败: {error_detail}")
            raise Exception(f"获取章节内容失败: {error_detail}")
        
        # 读取临时文件内容
        with open(temp_file_path, 'r', encoding='utf-8') as f:
            chapter_content = f.read()
        logger.info(f"成功读取章节内容，长度: {len(chapter_content)} 字符")
        
        # 获取历史角色库
        # 根据创作类型查询历史角色
        if creation.creation_type == "script":
            # 文案创作：查询该创作相关的角色
            existing_characters = db.query(Character).filter(
                Character.creation_id == creation_id,
                Character.deleted_at.is_(None)
            ).all()
        else:
            # 章节创作：查询同一小说的其他角色
            existing_characters = db.query(Character).filter(
                Character.novel_id == novel_id,
                Character.deleted_at.is_(None)
            ).all()

        historical_characters = build_historical_library(existing_characters)
        logger.info(f"获取到 {len(historical_characters)} 个历史角色")

        # 进行角色分析
        prompt_character_analysis = read_prompt_file("character_analysis.md")
        character_analysis_result = ai_client.gen_character_analysis(
            prompt=prompt_character_analysis,
            chapter_content=chapter_content,
            historical_characters=historical_characters if historical_characters else None,
            user_id=creation.owner_id,
            creation_id=creation_id,
            novel_id=creation.novel_id
        )

        # 解析并归一化角色列表（新格式为 characters 数组，兼容旧的中文字典格式）
        characters_data = parse_analysis_result(character_analysis_result)

        on_screen_count = sum(1 for c in characters_data if c["character_type"] == TYPE_ON_SCREEN)
        logger.info(
            f"角色分析完成，识别到 {len(characters_data)} 个角色"
            f"（出镜 {on_screen_count} 个，声音 {len(characters_data) - on_screen_count} 个）"
        )

        # 打印每个角色的详细信息，以便调试
        for char_info in characters_data:
            logger.info(
                f"【DEBUG】角色 '{char_info['name']}' "
                f"[type={char_info['character_type']}, age_group={char_info['age_group']}, "
                f"state={char_info['state']}]: "
                f"基础信息={(char_info.get('basic_info') or '')[:50]}..., "
                f"服装={(char_info.get('clothing') or '')[:100]}..."
            )

        # 保存角色信息到数据库
        # 出镜角色与声音角色统一走同一个循环，靠 character_type 区分，
        # 不再依赖 basic_info == "声音角色" 这个字符串哨兵
        character_map = {}  # variant_key -> Character obj
        created_count = 0
        reused_count = 0

        # 查重范围：文案创作限于本 creation，章节创作跨整部小说
        scope_filter = (
            Character.creation_id == creation_id
            if creation.creation_type == "script"
            else Character.novel_id == novel_id
        )

        for char_info in characters_data:
            key = variant_key(char_info["name"], char_info["age_group"], char_info["state"])

            # 变体去重键是 (name, age_group, state) 三元组，不再只看 name——
            # 同一人物的不同外观状态是独立角色条目
            existing_character = db.query(Character).filter(
                scope_filter,
                Character.name == char_info["name"],
                Character.age_group.is_(None) if char_info["age_group"] is None
                else Character.age_group == char_info["age_group"],
                Character.state.is_(None) if char_info["state"] is None
                else Character.state == char_info["state"],
                Character.deleted_at.is_(None)
            ).first()

            if existing_character:
                character_map[key] = existing_character
                reused_count += 1
                logger.info(
                    f"复用已有角色: {existing_character.variant_label} "
                    f"(character_id={existing_character.character_id})"
                )
                continue

            character = Character(
                name=char_info["name"],
                status='new',
                character_type=char_info["character_type"],
                age_group=char_info["age_group"],
                state=char_info["state"],
                voice_channel=char_info["voice_channel"],
                basic_info=char_info.get("basic_info"),
                appearance=char_info.get("appearance"),
                body=char_info.get("body"),
                hair=char_info.get("hair"),
                clothing=char_info.get("clothing"),
                tags=char_info.get("tags"),
                voice_description=char_info.get("voice_description"),
                creation_id=creation_id,
                novel_id=novel_id  # 对于文案创作，novel_id 会保持为 0
            )
            db.add(character)
            character_map[key] = character
            created_count += 1
            logger.info(f"创建新角色: {character.variant_label} [{character.character_type}]")

        # 先 flush 以确保新创建的角色有 character_id
        db.flush()
        
        # 获取原有的角色ID列表
        existing_character_ids = creation.character_ids or []
        if not isinstance(existing_character_ids, list):
            existing_character_ids = []
            
        # 收集所有角色的ID（包括新建和复用的），过滤掉 None 值
        new_character_ids = [
            char.character_id 
            for char in character_map.values() 
            if char.character_id is not None
        ]
        
        # 合并新旧角色ID，并去重（保持顺序）
        all_character_ids = list(dict.fromkeys(existing_character_ids + new_character_ids))
        
        # 更新状态为 CHARACTER_ANALYZED，并保存角色ID列表
        creation.status = CreationStatus.CHARACTER_ANALYZED
        creation.current_task_id = None
        creation.character_ids = all_character_ids
        
        # 更新任务状态：成功
        CreationService.update_creation_step_status(
            db=db,
            creation_id=creation_id,
            step_name="characterAnalysis",
            status="success",
            commit=False
        )
        
        db.commit()
        db.refresh(creation)
        logger.info(f"角色分析完成: 新建 {created_count} 个，复用 {reused_count} 个，总计 {len(character_map)} 个角色，角色ID列表: {all_character_ids}，状态已更新为 {creation.status}")
        
        return {
            "character_analysis": character_analysis_result,
            "characters_data": characters_data,
            "characters_count": len(character_map),
            "success": True,
            "task_type": TaskType.CHARACTER_ANALYSIS,
            "novel_id": novel_id,
            "chapter_id": chapter_id,
            "creation_id": creation_id,
            "result": "角色分析成功"
        }
        
    except Exception as e:
        logger.opt(exception=True).error("角色分析任务失败: {}", str(e))
        db.rollback()
        
        try:
            error_msg = str(e).lower()
        except Exception:
            error_msg = str(e) if e else "未知错误"
        
        # 判断是否为不可重试的错误
        non_retryable_keywords = [
            'invalid param', 'param_error', 'invalid_request_error',
            'model not support', 'model not found', 'max_tokens',
            'invalid max_tokens', 'bad request', 'keyerror',
            'content moderation', '内容审核'
        ]
        is_non_retryable = any(keyword in error_msg for keyword in non_retryable_keywords)
        
        retry_count = self.request.retries if hasattr(self.request, 'retries') else 0
        max_retries = 3
        
        if is_non_retryable or retry_count >= max_retries:
            try:
                creation = db.query(Creation).filter(Creation.creation_id == creation_id).first()
                if creation:
                    creation.current_task_id = None
                    creation.status = CreationStatus.FAILED
                    
                    # 更新任务状态：失败
                    from app.services.creation_service import CreationService
                    CreationService.update_creation_step_status(
                        db=db,
                        creation_id=creation_id,
                        step_name="characterAnalysis",
                        status="failed",
                        error=error_msg,
                        commit=False
                    )
                    
                    db.commit()
                    logger.info(f"已清理 current_task_id 并设置状态为 FAILED，creation_id={creation_id}")
            except Exception as cleanup_error:
                logger.opt(exception=True).error("清理 current_task_id 失败: {}", str(cleanup_error))
                try:
                    db.rollback()
                except Exception:
                    pass
            
            if is_non_retryable:
                logger.error(f"遇到不可重试的错误，直接失败: {error_msg}")
                raise
            raise
        else:
            raise self.retry(exc=e, countdown=60, max_retries=max_retries)
    finally:
        try:
            if db:
                db.close()
        except Exception:
            pass
        if temp_file_path and os.path.exists(temp_file_path):
            try:
                os.remove(temp_file_path)
                logger.info(f"已清理临时文件: {temp_file_path}")
            except Exception as e:
                logger.warning(f"删除临时文件失败: {str(e)}")


@celery_app.task(
    bind=True, 
    name="scene_analysis_task",
    autoretry_for=(Exception,),
    max_retries=3,
    retry_backoff=True,
    retry_backoff_max=60,
    retry_jitter=True
)
def scene_analysis_task(self, novel_id: int, chapter_id: int, creation_id: int, chapter_content_url: str):
    """
    场景分析任务（第二步）

    Args:
        novel_id: 小说ID
        chapter_id: 章节ID
        creation_id: 创作ID
        chapter_content_url: 文本内容URL
    """
    db: Session = _get_sync_session_factory()()
    temp_file_path = None
    logger.info(f"开始场景分析任务: novel_id={novel_id}, chapter_id={chapter_id}, creation_id={creation_id}")
    try:
        # 初始化进度
        self.update_state(
            state='PROGRESS',
            meta={
                'task_type': TaskType.SCENE_DESCRIPTION_GENERATION,
                'novel_id': novel_id,
                'chapter_id': chapter_id,
                'creation_id': creation_id,
                'current': 0,
                'total': 100,
                'percent': 0,
                'status': '开始场景分析',
                'stage': 'initializing'
            }
        )
        
        # 查询对应的 Creation 记录
        creation = db.query(Creation).filter(
            Creation.creation_id == creation_id
        ).with_for_update().first()

        if not creation:
            from app.core.exceptions import BaseServiceException
            raise BaseServiceException(message=f"创作不存在: creation_id={creation_id}")

        # 更新任务状态：开始处理
        from app.services.creation_service import CreationService
        CreationService.update_creation_step_status(
            db=db,
            creation_id=creation_id,
            step_name="sceneAnalysis",
            status="processing",
            task_id=self.request.id,
            commit=True
        )

        # 更新进度：10%
        self.update_state(
            state='PROGRESS',
            meta={
                'task_type': TaskType.SCENE_DESCRIPTION_GENERATION,
                'current': 10,
                'total': 100,
                'percent': 10,
                'status': '准备下载文本内容',
                'stage': 'downloading'
            }
        )

        # 创建临时文件
        temp_fd, temp_file_path = tempfile.mkstemp(suffix='.txt')
        os.close(temp_fd)

        # 智能下载章节内容
        download_result = download_file_smart(
            url_or_key=chapter_content_url,
            save_file=temp_file_path,
            bucket=None,
            timeout=60
        )

        if not download_result.get('success'):
            from app.core.exceptions import BaseServiceException
            error_msg = download_result.get('message', '未知错误')
            logger.error(f"下载文本内容失败: {error_msg}")
            raise BaseServiceException(message=f"获取章节内容失败: {error_msg}")

        with open(temp_file_path, 'r', encoding='utf-8') as f:
            chapter_content = f.read()

        logger.info(f"成功读取文本内容，长度: {len(chapter_content)} 字符")

        # 更新进度：30%
        self.update_state(
            state='PROGRESS',
            meta={
                'task_type': TaskType.SCENE_DESCRIPTION_GENERATION,
                'current': 30,
                'total': 100,
                'percent': 30,
                'status': '查询历史场景',
                'stage': 'loading_historical_scenes'
            }
        )
            
        # 初始化 AI Client
        extra_data = creation.extra_data or {}
        llm_model_name = extra_data.get("llm_model")
        ai_client = AIClient(llm_model_name=llm_model_name)
        logger.info(f"使用 LLM 模型: {llm_model_name if llm_model_name else '默认配置'}")

        # 更新进度：40%
        self.update_state(
            state='PROGRESS',
            meta={
                'task_type': TaskType.SCENE_DESCRIPTION_GENERATION,
                'current': 40,
                'total': 100,
                'percent': 40,
                'status': '调用AI进行场景分析',
                'stage': 'ai_analyzing'
            }
        )

        # 读取提示词
        prompt_scene = read_prompt_file("scene_decomposition.md")

        # 执行场景拆解
        scene_result = ai_client.gen_scene_decomposition(
            prompt=prompt_scene,
            chapter_content=chapter_content,
            user_id=creation.owner_id,
            creation_id=creation_id,
            novel_id=creation.novel_id
        )

        logger.info(f"AI场景分析完成")

        # 更新进度：70%
        self.update_state(
            state='PROGRESS',
            meta={
                'task_type': TaskType.SCENE_DESCRIPTION_GENERATION,
                'current': 70,
                'total': 100,
                'percent': 70,
                'status': '保存场景到数据库',
                'stage': 'saving_scenes'
            }
        )
        
        # 保存场景到数据库
        # 首先删除该创作旧的场景（如果是重试）
        # 注意：如果有分镜关联，可能会有问题。这里假设场景分析是重新开始。
        # 如果只想增量更新，逻辑会很复杂。通常是覆盖。
        existing_scenes = db.query(Scene).filter(Scene.creation_id == creation_id).all()
        if existing_scenes:
            logger.warning(f"删除旧场景 {len(existing_scenes)} 个")
            for s in existing_scenes:
                db.delete(s)
            db.flush()

        scenes_data = scene_result.get("scenes", [])
        created_scenes = []
        created_count = 0
        reused_count = 0

        # 获取该小说的历史场景（用于复用）
        historical_scenes = {}
        if novel_id > 0:  # 章节创作才查询历史场景
            existing_novel_scenes = db.query(Scene).filter(
                Scene.novel_id == novel_id,
                Scene.deleted_at.is_(None)
            ).all()

            for scene in existing_novel_scenes:
                # 构建场景特征键：标题+地点+时间
                scene_key = f"{scene.title}|{scene.location}|{scene.time_setting}"
                historical_scenes[scene_key] = scene

            logger.info(f"获取到 {len(historical_scenes)} 个历史场景")

        for scene_data in scenes_data:
            env = scene_data.get("environment", {})

            # 提取字段（LLM 可能输出 null，统一兜成空串再截断）
            title = scene_data.get("title") or f"Scene {scene_data.get('scene_number')}"
            time_setting = env.get("time_setting") or ""
            location = env.get("location") or ""
            # space_type 是枚举（indoor/outdoor），space_description 是布局描述，两者不再混用
            space_type = env.get("space_type") or ""
            space_desc = env.get("space_description") or ""
            bg_elements = env.get("background_elements") or ""
            atmosphere = env.get("atmosphere") or ""

            # 检查是否可以复用历史场景
            scene_key = f"{title}|{location}|{time_setting}"
            existing_scene = historical_scenes.get(scene_key)

            if existing_scene:
                # 复用已有场景
                created_scenes.append(existing_scene)
                reused_count += 1
                logger.info(f"复用已有场景: {title} (scene_id={existing_scene.scene_id})")
            else:
                # 创建新场景
                # 构建 extra_data 存储更多信息
                scene_extra = {
                    "space_description": space_desc,
                    "background_elements": bg_elements,
                    "environment_description": ". ".join(
                        p for p in (space_desc, bg_elements) if p
                    )  # 组合成环境描述
                }

                scene = Scene(
                    title=title[:200],
                    time_setting=time_setting[:50],
                    location=location[:200],
                    space_type=space_type[:50],
                    atmosphere=atmosphere[:100],
                    extra_data=scene_extra,
                    creation_id=creation_id,
                    novel_id=novel_id if novel_id > 0 else None,  # 设置novel_id用于场景复用
                    status="completed" # 场景解析本身完成
                )
                db.add(scene)
                created_scenes.append(scene)
                created_count += 1
                logger.info(f"创建新场景: {title}")

        # 先 flush 以确保新创建的场景有 scene_id
        db.flush()

        # 获取原有的场景ID列表
        existing_scene_ids = creation.scene_ids or []
        if not isinstance(existing_scene_ids, list):
            existing_scene_ids = []

        # 收集所有场景的ID（包括新建和复用的）
        new_scene_ids = [
            scene.scene_id
            for scene in created_scenes
            if scene.scene_id is not None
        ]

        # 合并新旧场景ID，并去重（保持顺序）
        all_scene_ids = list(dict.fromkeys(existing_scene_ids + new_scene_ids))

        # 更新创作状态
        creation.status = CreationStatus.SCENES_ANALYZED
        creation.current_task_id = None
        creation.scene_ids = all_scene_ids
        
        # 更新步骤状态
        CreationService.update_creation_step_status(
            db=db,
            creation_id=creation_id,
            step_name="sceneAnalysis",
            status="success",
            commit=False
        )
        
        db.commit()

        logger.info(f"场景分析完成: 新建 {created_count} 个，复用 {reused_count} 个，总计 {len(created_scenes)} 个场景，场景ID列表: {all_scene_ids}")

        # 更新进度：100% 完成
        self.update_state(
            state='PROGRESS',
            meta={
                'task_type': TaskType.SCENE_DESCRIPTION_GENERATION,
                'current': 100,
                'total': 100,
                'percent': 100,
                'status': '场景分析完成',
                'stage': 'completed',
                'success': True,
                'created_count': created_count,
                'reused_count': reused_count,
                'total_scenes': len(created_scenes),
                'scene_ids': all_scene_ids,
                'creation_id': creation_id
            }
        )

        return {
            "success": True,
            "task_type": TaskType.SCENE_DESCRIPTION_GENERATION,
            "scenes_count": len(created_scenes),
            "created_count": created_count,
            "reused_count": reused_count,
            "scene_ids": all_scene_ids,
            "creation_id": creation_id
        }

    except Exception as e:
        from app.core.exceptions import BaseServiceException

        # 获取错误信息
        if isinstance(e, BaseServiceException):
            error_msg = e.message
        else:
            error_msg = str(e)

        logger.error(f"场景分析任务失败: {error_msg}")
        db.rollback()

        # 更新任务状态为失败
        self.update_state(
            state='PROGRESS',
            meta={
                'task_type': TaskType.SCENE_DESCRIPTION_GENERATION,
                'current': 0,
                'total': 100,
                'percent': 0,
                'status': f'场景分析失败: {error_msg}',
                'stage': 'failed',
                'success': False,
                'error': error_msg,
                'creation_id': creation_id
            }
        )

        # 更新数据库状态
        try:
            creation = db.query(Creation).filter(Creation.creation_id == creation_id).first()
            if creation:
                creation.current_task_id = None
                creation.status = CreationStatus.FAILED

                from app.services.creation_service import CreationService
                CreationService.update_creation_step_status(
                    db=db,
                    creation_id=creation_id,
                    step_name="sceneAnalysis",
                    status="failed",
                    error=error_msg,
                    commit=False
                )
                db.commit()
        except Exception as cleanup_error:
            logger.error(f"清理失败状态时出错: {str(cleanup_error)}")

        # 使用 BaseServiceException 抛出错误
        raise BaseServiceException(message=error_msg)
        
    finally:
        if db:
            db.close()
        if temp_file_path and os.path.exists(temp_file_path):
            try:
                os.remove(temp_file_path)
            except Exception:
                pass


        if temp_file_path and os.path.exists(temp_file_path):
            try:
                os.remove(temp_file_path)
            except Exception as e:
                logger.warning(f"删除临时文件失败: {str(e)}")


@celery_app.task(
    bind=True, 
    name="shot_analysis_task",
    autoretry_for=(Exception,),
    max_retries=3,
    retry_backoff=True,
    retry_backoff_max=60,
    retry_jitter=True
)
def shot_analysis_task(self, novel_id: int, chapter_id: int, creation_id: int, chapter_content_url: str):
    """
    分镜分析任务（Step 3: 分镜拆解）
    
    Args:
        novel_id: 小说ID
        chapter_id: 章节ID
        creation_id: 创作ID
        chapter_content_url: 文本内容URL
    """
    db: Session = _get_sync_session_factory()()
    temp_file_path = None
    logger.info(f"开始分镜分析任务: novel_id={novel_id}, chapter_id={chapter_id}, creation_id={creation_id}")
    try:
        self.update_state(
            state='PROGRESS',
            meta={
                'task_type': TaskType.SCENE_SHOT_DECOMPOSITION,
                'novel_id': novel_id,
                'chapter_id': chapter_id,
                'creation_id': creation_id,
                'step': 'shot_analysis'
            }
        )
        
        # 查询对应的 Creation 记录
        creation = db.query(Creation).filter(
            Creation.creation_id == creation_id
        ).with_for_update().first()
        
        if not creation:
            raise Exception(f"创作不存在: creation_id={creation_id}")
        
        # 验证状态：必须完成场景分析
        allowed_statuses = [CreationStatus.SCENES_ANALYZED, CreationStatus.PLAYBOOK_GENERATED]
        if creation.status not in allowed_statuses:
             # 如果是从 SCENE_ANALYZED 之前的状态跳过来，需要报错
             # 除非是 CREATED -> CHARACTER_ANALYZED -> SCENES_ANALYZED -> SHOT_ANALYSIS
             # 如果当前是 CHARACTER_ANALYZED，说明跳过了场景分析，不允许
             if creation.status == CreationStatus.CHARACTER_ANALYZED:
                 raise Exception("必须先完成场景分析才能进行分镜拆解")
             # 其他状态视情况而定，这里严格一点
             if creation.status not in allowed_statuses:
                 # 允许重试
                 pass

        # 更新任务状态
        from app.services.creation_service import CreationService
        CreationService.update_creation_step_status(
            db=db,
            creation_id=creation_id,
            step_name="shotAnalysis",
            status="processing",
            task_id=self.request.id,
            commit=True
        )

        # 下载章节内容
        temp_fd, temp_file_path = tempfile.mkstemp(suffix='.txt')
        os.close(temp_fd)
        
        download_result = download_file_smart(
            url_or_key=chapter_content_url,
            save_file=temp_file_path,
            bucket=None,
            timeout=60
        )
        
        if not download_result.get('success'):
            raise Exception(f"获取章节内容失败: {download_result.get('message')}")
        
        with open(temp_file_path, 'r', encoding='utf-8') as f:
            chapter_content = f.read()

        # 准备数据：场景列表
        # 走统一入口：兼容跨章节复用的场景（其 creation_id 指向原创作）
        scenes = CreationService.get_creation_scenes(db, creation)
        if not scenes:
            raise Exception("未找到场景数据，请先进行场景分析")
            
        scenes_data = []
        scene_map = {} # title -> scene_id
        scene_id_map = {} # scene_index (1-based) -> scene
        
        for idx, scene in enumerate(scenes, 1):
            scene_extra = scene.extra_data or {}
            scene_dict = {
                "scene_number": idx, # 临时编号
                "title": scene.title,
                "environment": {
                    "time_setting": scene.time_setting,
                    "location": scene.location,
                    "space_type": scene.space_type,
                    "space_description": scene_extra.get("space_description", ""),
                    "atmosphere": scene.atmosphere,
                    "environment_description": scene_extra.get("environment_description", "")
                }
            }
            scenes_data.append(scene_dict)
            scene_map[scene.title] = scene
            scene_id_map[idx] = scene

        # 准备数据：角色特征库
        characters = db.query(Character).filter(
            Character.character_id.in_(creation.character_ids) if creation.character_ids else Character.creation_id == creation_id
        ).all()
        
        if not characters:
            raise Exception("未找到角色数据，请先进行角色分析")

        # 角色按 character_id 索引——分镜拆解的角色引用一律用 ID，不做字符串匹配
        char_by_id = {char.character_id: char for char in characters}

        # 初始化 AI Client
        extra_data = creation.extra_data or {}
        llm_model_name = extra_data.get("llm_model")
        ai_client = AIClient(llm_model_name=llm_model_name)
        logger.info(f"使用 LLM 模型: {llm_model_name if llm_model_name else '默认配置'}")

        # 执行分镜拆解
        result = ai_client.gen_shot_analysis(
            scenes_data=scenes_data,
            characters=characters,
            original_text=chapter_content,
            user_id=creation.owner_id,
            creation_id=creation_id,
            novel_id=creation.novel_id
        )
        
        shot_list = result.get("分镜列表", [])
        logger.info(f"分镜拆解完成，AI原始输出: {json.dumps(result, ensure_ascii=False)}")
        logger.info(f"分镜拆解完成，共 {len(shot_list)} 个分镜")
        
        # 保存分镜
        # 清除旧分镜 - 只删除当前 creation 的分镜，不影响其他创作
        shots_to_delete = db.query(Shot).filter(Shot.creation_id == creation_id).all()
        shot_ids_to_delete = [s.shot_id for s in shots_to_delete]
        
        if shot_ids_to_delete:
            logger.info(f"准备删除旧分镜: {len(shots_to_delete)} 个")
            # 清空关联后删除
            for shot in shots_to_delete:
                shot.characters = []
            db.flush()
            
            db.query(Shot).filter(Shot.shot_id.in_(shot_ids_to_delete)).delete(synchronize_session=False)
            db.flush()
        
        total_shots = 0
        
        # 将所有分镜收集到一个列表中
        all_shots_data = []
        for shot_data in shot_list:
            # 尝试提取数字 (e.g., "1-1" -> 101 or simple int)
            # 这里简单起见，按出现的顺序赋予一个递增的编号，因为 AI 返回的顺序通常就是时间顺序
            all_shots_data.append(shot_data)

        for shot_data in all_shots_data:
            total_shots += 1
            shot_number = total_shots
            
            # 关联场景
            scene_idx = shot_data.get("scene_number")
            scene_title = shot_data.get("scene_title")

            # LLM 可能把编号输出成字符串 "1"，统一转成 int 再查表
            try:
                scene_idx = int(scene_idx) if scene_idx is not None else None
            except (TypeError, ValueError):
                scene_idx = None

            target_scene = None
            if scene_idx is not None and scene_idx in scene_id_map:
                target_scene = scene_id_map[scene_idx]
            elif scene_title and scene_title in scene_map:
                target_scene = scene_map[scene_title]
            
            if not target_scene:
                logger.warning(f"分镜无法关联到场景: {shot_data}")
                # 兜底逻辑：关联到第一个场景
                if scenes:
                    target_scene = scenes[0]
                else:
                    continue

            # 处理台词
            # LLM 侧输出 [{"character_id": 42, "content": "..."}]，旁白用 character_id: null
            processed_narration = resolve_narration_items(
                shot_data.get("台词", []),
                char_by_id,
                shot_label=f"分镜 {shot_number}",
            )

            # 创建分镜
            shot = Shot(
                title=f"Shot {shot_number}", # 简化标题，前端会显示场景Tag
                shot_number=shot_number, # 全局递增编号 1, 2, 3...
                description=shot_data.get("画面内容", "") or shot_data.get("分镜内容", "") or shot_data.get("简要剧情", ""),
                narration=json.dumps(processed_narration, ensure_ascii=False),
                image_prompt=shot_data.get("画面提示词", "") or shot_data.get("图片提示词", ""),
                video_duration=shot_data.get("分镜时长", 5),
                scene_id=target_scene.scene_id,
                creation_id=creation_id,
                extra_data={
                    "camera_movement": shot_data.get("运镜", ""),
                    "sound_effect": shot_data.get("音效", ""),
                    "script_content": shot_data.get("剧本正文", ""),
                    "appearance_elements": shot_data.get("出镜元素", []),
                    "ai_output": shot_data,
                    "scene_title": target_scene.title # 冗余存储场景标题方便前端使用（尽管可以通过关联查）
                }
            )
            db.add(shot)
            db.flush()

            # 关联角色：一律按 character_id 查表，不做任何名字匹配
            shot_label = f"分镜 {shot_number}"
            on_screen_chars = resolve_character_ids(
                shot_data.get("on_screen_character_ids", []), char_by_id, shot_label
            )
            voice_chars = resolve_character_ids(
                shot_data.get("voice_character_ids", []), char_by_id, shot_label
            )

            # 声音角色也进 shot_characters 表——需要知道谁参与了这个分镜；
            # 生图时由 shot_task 按 character_type 过滤掉不出镜的
            for char in on_screen_chars + voice_chars:
                if char not in shot.characters:
                    shot.characters.append(char)

            if on_screen_chars or voice_chars:
                logger.info(
                    f"{shot_label} 关联角色: "
                    f"出镜={[c.variant_label for c in on_screen_chars]}, "
                    f"声音={[c.variant_label for c in voice_chars]}"
                )

        # 更新状态
        creation.status = CreationStatus.PLAYBOOK_GENERATED
        creation.current_task_id = None
        
        CreationService.update_creation_step_status(
            db=db,
            creation_id=creation_id,
            step_name="shotAnalysis",
            status="success",
            commit=True
        )
        
        db.commit()
        
        logger.info(f"分镜分析任务完成，保存 {total_shots} 个分镜")
        
        return {
            "success": True,
            "task_type": TaskType.SCENE_SHOT_DECOMPOSITION,
            "shots_count": total_shots,
            "creation_id": creation_id
        }

    except Exception as e:
        logger.opt(exception=True).error("分镜分析任务失败: {}", str(e))
        db.rollback()
        
        error_msg = str(e)
        try:
            creation = db.query(Creation).filter(Creation.creation_id == creation_id).first()
            if creation:
                creation.current_task_id = None
                creation.status = CreationStatus.FAILED
                
                from app.services.creation_service import CreationService
                CreationService.update_creation_step_status(
                    db=db,
                    creation_id=creation_id,
                    step_name="shotAnalysis",
                    status="failed",
                    error=error_msg,
                    commit=True
                )
                db.commit()
        except Exception:
            pass
        raise
        
    finally:
        if db:
            db.close()
        if temp_file_path and os.path.exists(temp_file_path):
            try:
                os.remove(temp_file_path)
            except Exception:
                pass




