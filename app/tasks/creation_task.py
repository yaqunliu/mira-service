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
        historical_characters = {}
        
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
        
        for char in existing_characters:
            # 构建角色特征字典
            char_dict = {
                "基础信息": char.basic_info or "",
                "容貌特征": char.appearance or "",
                "身材特征": char.body or "",
                "头发": char.hair or "",
                "服装": char.clothing or "",
                "特征标签": char.tags if char.tags else ""
            }
            historical_characters[char.name] = char_dict
        
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
        
        # 获取出镜角色数据
        characters_data = character_analysis_result.get('人物特征库', {}).get('出镜角色', {})
        if not characters_data:
             # 兼容旧格式（如果没有区分出镜角色和声音角色）
             characters_data = character_analysis_result.get('人物特征库', {})
             # 如果包含"出镜角色"键但为空，或者包含"声音角色"键，说明是新格式但没有出镜角色
             if '出镜角色' in character_analysis_result.get('人物特征库', {}) or '声音角色' in character_analysis_result.get('人物特征库', {}):
                  if not isinstance(characters_data, dict) or ('出镜角色' not in characters_data and '声音角色' not in characters_data):
                       # 只有当它是纯角色字典时才使用，否则认为是空
                       pass
                  else:
                       characters_data = {}

        logger.info(f"角色分析完成，识别到 {len(characters_data)} 个出镜角色")
        logger.info(f"【DEBUG】角色列表: {list(characters_data.keys())}")

        # 打印每个角色的详细信息，以便调试
        for char_name, char_info in characters_data.items():
            logger.info(f"【DEBUG】角色 '{char_name}': 基础信息={char_info.get('基础信息', '')[:50]}..., 服装={char_info.get('服装', '')[:100]}...")
        
        # 保存角色信息到数据库
        character_map = {}
        created_count = 0
        reused_count = 0
        
        for char_name, char_info in characters_data.items():
            # 根据创作类型检查是否存在同名角色
            if creation.creation_type == "script":
                # 文案创作：检查该创作下是否已存在同名角色
                existing_character = db.query(Character).filter(
                    Character.creation_id == creation_id,
                    Character.name == char_name,
                    Character.deleted_at.is_(None)
                ).first()
            else:
                # 章节创作：检查该小说中是否已存在同名角色
                existing_character = db.query(Character).filter(
                    Character.novel_id == novel_id,
                    Character.name == char_name,
                    Character.deleted_at.is_(None)
                ).first()
            
            if existing_character:
                character_map[char_name] = existing_character
                reused_count += 1
                logger.info(f"复用已有角色: {char_name} (character_id={existing_character.character_id})")
            else:
                # 解析特征标签
                tags = char_info.get('特征标签', '')
                if isinstance(tags, str):
                    tags_list = [tag.strip() for tag in tags.split('、') if tag.strip()]
                else:
                    tags_list = tags if isinstance(tags, list) else []
                
                # 根据创作类型设置角色属性
                character = Character(
                    name=char_name,
                    status='new',
                    basic_info=char_info.get('基础信息', ''),
                    appearance=char_info.get('容貌特征', ''),
                    body=char_info.get('身材特征', ''),
                    hair=char_info.get('头发', ''),
                    clothing=char_info.get('服装', ''),
                    tags=tags_list if tags_list else None,
                    voice_description=char_info.get('音色描述', ''),  # 新增字段
                    creation_id=creation_id,
                    novel_id=novel_id  # 对于文案创作，novel_id 会保持为 0
                )
                db.add(character)
                character_map[char_name] = character
                created_count += 1
                logger.info(f"创建新角色: {char_name}")
        
        # 处理声音角色
        voice_characters_data = character_analysis_result.get('人物特征库', {}).get('声音角色', {})
        if voice_characters_data:
             for char_name, char_info in voice_characters_data.items():
                if char_name in character_map:
                    continue # 如果已经存在（可能是出镜角色同时也是声音角色），跳过
                
                # 检查是否存在
                if creation.creation_type == "script":
                    existing_character = db.query(Character).filter(
                        Character.creation_id == creation_id,
                        Character.name == char_name,
                        Character.deleted_at.is_(None)
                    ).first()
                else:
                    existing_character = db.query(Character).filter(
                        Character.novel_id == novel_id,
                        Character.name == char_name,
                        Character.deleted_at.is_(None)
                    ).first()
                
                if existing_character:
                     character_map[char_name] = existing_character
                     reused_count += 1
                     logger.info(f"复用已有声音角色: {char_name}")
                else:
                     character = Character(
                        name=char_name,
                        status='new',
                        basic_info="声音角色", # 标记为声音角色
                        voice_description=char_info.get('音色描述', ''),
                        creation_id=creation_id,
                        novel_id=novel_id
                     )
                     db.add(character)
                     character_map[char_name] = character
                     created_count += 1
                     logger.info(f"创建新声音角色: {char_name}")

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

        scenes_data = scene_result.get("场景列表", [])
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
            env = scene_data.get("环境设定", {})

            # 提取字段
            title = scene_data.get("场景标题", "") or f"场景 {scene_data.get('场景编号')}"
            time_setting = env.get("时间", "")
            location = env.get("地点", "")
            space_desc = env.get("空间描述") or env.get("空间", "")
            bg_elements = env.get("背景元素", "")
            atmosphere = env.get("氛围", "")

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
                    "environment_description": f"{space_desc}。{bg_elements}" # 组合成环境描述
                }

                # 截断 space_type 以适应 String(50)
                space_type_short = space_desc[:50] if space_desc else ""

                scene = Scene(
                    title=title,
                    time_setting=time_setting,
                    location=location,
                    space_type=space_type_short,
                    atmosphere=atmosphere,
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
        scenes = db.query(Scene).filter(Scene.creation_id == creation_id).order_by(Scene.scene_id).all()
        if not scenes:
            raise Exception("未找到场景数据，请先进行场景分析")
            
        scenes_data = []
        scene_map = {} # title -> scene_id
        scene_id_map = {} # scene_index (1-based) -> scene
        
        for idx, scene in enumerate(scenes, 1):
            scene_dict = {
                "场景编号": idx, # 临时编号
                "场景标题": scene.title,
                "环境设定": {
                    "时间": scene.time_setting,
                    "地点": scene.location,
                    "空间": scene.space_type,
                    "氛围": scene.atmosphere,
                    "环境描述": scene.extra_data.get("environment_description", "") if scene.extra_data else ""
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
            
        characters_data = {
            "出镜角色": {},
            "声音角色": {}
        }
        character_map = {} # name -> Character obj
        
        for char in characters:
            character_map[char.name] = char
            char_info = {
                "基础信息": char.basic_info or "",
                "容貌特征": char.appearance or "",
                "身材特征": char.body or "",
                "头发": char.hair or "",
                "服装": char.clothing or "",
                "特征标签": char.tags if char.tags else "",
                "音色描述": char.voice_description or ""
            }
            
            # 根据 basic_info 判断是否为声音角色 (约定俗成)
            if char.basic_info == "声音角色":
                characters_data["声音角色"][char.name] = char_info
            else:
                characters_data["出镜角色"][char.name] = char_info

        # 初始化 AI Client
        extra_data = creation.extra_data or {}
        llm_model_name = extra_data.get("llm_model")
        ai_client = AIClient(llm_model_name=llm_model_name)
        logger.info(f"使用 LLM 模型: {llm_model_name if llm_model_name else '默认配置'}")

        # 执行分镜拆解
        result = ai_client.gen_shot_analysis(
            scenes_data=scenes_data,
            characters_data=characters_data,
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
            scene_idx = shot_data.get("场景编号")
            scene_title = shot_data.get("场景标题")
            
            target_scene = None
            if scene_idx and isinstance(scene_idx, int) and scene_idx in scene_id_map:
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
            raw_narration = shot_data.get("台词", [])
            if isinstance(raw_narration, list):
                # 已经是列表，直接保存
                processed_narration = raw_narration
            elif isinstance(raw_narration, str) and raw_narration.strip():
                # 是字符串，转换为默认旁白格式
                processed_narration = [{"角色": "旁白", "内容": raw_narration}]
            else:
                processed_narration = []

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
            
            # 关联角色
            char_names = shot_data.get("人物", []) or shot_data.get("出镜角色", []) # 兼容字段
            if char_names:
                for name in char_names:
                    # 尝试精确匹配
                    if name in character_map:
                        shot.characters.append(character_map[name])
                        logger.info(f"分镜 {shot_number} 关联角色: {name}")
                    else:
                        # 尝试模糊匹配（如果 AI 输出的名字包含额外描述，或者数据库名字包含额外描述）
                        # 例如：AI输出 "陶未"，DB中有 "陶未-青年"
                        matched = False
                        for db_char_name, char_obj in character_map.items():
                            if name in db_char_name or db_char_name in name:
                                shot.characters.append(char_obj)
                                logger.info(f"分镜 {shot_number} 模糊关联角色: {name} -> {db_char_name}")
                                matched = True
                                break
                        if not matched:
                            logger.warning(f"分镜 {shot_number} 未找到角色: {name} (可用角色: {list(character_map.keys())})")
            
            # 关联声音角色（如果需要）
            voice_char_names = shot_data.get("声音角色", [])
            if voice_char_names:
                 for name in voice_char_names:
                    if name in character_map:
                        # 声音角色也关联到 shot_characters 表吗？是的，通常都需要知道谁参与了这个分镜
                        # 但如果是为了生成图片，可能只关心出镜角色。
                        # 这里我们先关联上，后续使用时可以根据角色属性过滤
                        if character_map[name] not in shot.characters:
                            shot.characters.append(character_map[name])
                            logger.info(f"分镜 {shot_number} 关联声音角色: {name}")
            
            
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




