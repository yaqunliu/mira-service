"""
创作任务
"""
import os
import json
import tempfile
from pathlib import Path
from app.core.celery_app import celery_app
from app.utils.us3 import US3Client, download_file_smart
from app.utils.file_utils import read_prompt_file
from app.utils.ai_client import AIClient
from app.core.config import settings
from app.core.logger import logger
from app.db.session import SessionLocal
from sqlalchemy.orm import Session
from app.models.creation import Creation
from app.models.character import Character
from app.models.scene import Scene
from app.models.shot import Shot
from app.schemas.creation import CreationStatus
from app.utils.task_types import TaskType
from app.services.model_config_service import ModelConfigService

@celery_app.task(bind=True, name="character_analysis_task")
def character_analysis_task(self, novel_id: int, chapter_id: int, creation_id: int, chapter_content_url: str):
    """
    角色分析任务（第一步）
    
    Args:
        novel_id: 小说ID
        chapter_id: 章节ID
        creation_id: 创作ID
        chapter_content_url: 章节内容URL
    """
    db: Session = SessionLocal()
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
        ).first()
        
        if not creation:
            raise Exception(f"创作不存在: creation_id={creation_id}")
        
        # 从 extra_data 中获取模型配置
        extra_data = creation.extra_data or {}
        llm_model_name = extra_data.get("llm_model") or settings.LLM_MODEL_NAME
        
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
        
        # 根据配置创建 AIClient（使用配置的 LLM 模型）
        ai_client = AIClient(llm_model_name=llm_model_name)
        logger.info(f"使用 LLM 模型: {llm_model_name}")
        
        # 获取历史角色库（同一小说的其他角色）
        historical_characters = {}
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
        
        characters_data = character_analysis_result.get('人物特征库', {})
        logger.info(f"角色分析完成，识别到 {len(characters_data)} 个角色")
        
        # 保存角色信息到数据库
        character_map = {}
        created_count = 0
        reused_count = 0
        
        for char_name, char_info in characters_data.items():
            # 检查该小说中是否已存在同名角色
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
                
                character = Character(
                    name=char_name,
                    status='new',
                    basic_info=char_info.get('基础信息', ''),
                    appearance=char_info.get('容貌特征', ''),
                    body=char_info.get('身材特征', ''),
                    hair=char_info.get('头发', ''),
                    clothing=char_info.get('服装', ''),
                    tags=tags_list if tags_list else None,
                    creation_id=creation_id,
                    novel_id=novel_id
                )
                db.add(character)
                character_map[char_name] = character
                created_count += 1
                logger.info(f"创建新角色: {char_name}")
        
        # 先 flush 以确保新创建的角色有 character_id
        db.flush()
        
        # 收集所有角色的ID（包括新建和复用的），过滤掉 None 值
        all_character_ids = [
            char.character_id 
            for char in character_map.values() 
            if char.character_id is not None
        ]
        
        # 更新状态为 CHARACTER_ANALYZED，并保存角色ID列表
        creation.status = CreationStatus.CHARACTER_ANALYZED
        creation.current_task_id = None
        creation.character_ids = all_character_ids  # 保存所有角色ID（包括复用的）
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


@celery_app.task(bind=True, name="playbook_generation_task")
def playbook_generation_task(self, previous_result, novel_id: int, chapter_id: int, creation_id: int, chapter_content_url: str, narration_mode: str = "original"):
    """
    分镜拆分任务（第二步）
    
    Args:
        previous_result: 前一个任务（character_analysis_task）的返回值（由 Celery link 自动传入）
        novel_id: 小说ID
        chapter_id: 章节ID
        creation_id: 创作ID
        chapter_content_url: 章节内容URL
        narration_mode: 解说词模式，可选值："original"（原文模式）或 "rewrite"（爽文模式），默认为 "original"
    """
    db: Session = SessionLocal()
    temp_file_path = None
    logger.info(f"开始分镜拆分任务: novel_id={novel_id}, chapter_id={chapter_id}, creation_id={creation_id}, narration_mode={narration_mode}")
    try:
        self.update_state(
            state='PROGRESS',
            meta={
                'task_type': TaskType.SCENE_DESCRIPTION_GENERATION,
                'novel_id': novel_id,
                'chapter_id': chapter_id,
                'creation_id': creation_id,
                'step': 'playbook_generation'
            }
        )
        
        # 查询对应的 Creation 记录
        creation = db.query(Creation).filter(
            Creation.creation_id == creation_id
        ).first()
        
        if not creation:
            raise Exception(f"创作不存在: creation_id={creation_id}")
        
        # 验证状态：必须完成角色分析（包括已生成角色图片或已拆分分镜的状态）
        allowed_statuses = [
            CreationStatus.CHARACTER_ANALYZED,
            CreationStatus.CHARACTER_GENERATED,
            CreationStatus.PLAYBOOK_GENERATED,
        ]
        if creation.status not in allowed_statuses:
            raise Exception(f"创作状态不正确，当前状态 {creation.status}。需要先完成角色分析。")
        
        # 创建临时文件
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
        
        # 获取角色数据（从数据库中读取）
        # 优先使用 character_ids 字段查询（包括复用的角色）
        # 如果角色分析任务刚完成，可能需要等待数据库提交，所以先刷新一下
        db.refresh(creation)
        
        # 重试机制：如果角色数据不存在，等待一段时间后重试（最多3次）
        import time
        characters = []
        max_retries = 3
        retry_delay = 2  # 秒
        
        for attempt in range(max_retries):
            # 优先使用 character_ids 字段查询
            if creation.character_ids and len(creation.character_ids) > 0:
                characters = db.query(Character).filter(
                    Character.character_id.in_(creation.character_ids),
                    Character.deleted_at.is_(None)
                ).all()
            else:
                # 如果没有 character_ids，使用传统方式查询（向后兼容）
                characters = db.query(Character).filter(
                    Character.creation_id == creation_id,
                    Character.deleted_at.is_(None)
                ).all()
            
            if characters:
                break
            
            if attempt < max_retries - 1:
                logger.warning(f"未找到角色数据，creation_id={creation_id}，character_ids={creation.character_ids}，等待 {retry_delay} 秒后重试 (尝试 {attempt + 1}/{max_retries})")
                time.sleep(retry_delay)
                # 重新查询创作状态
                db.refresh(creation)
            else:
                # 最后一次尝试失败，记录详细信息以便调试
                logger.error(f"未找到角色数据，creation_id={creation_id}, status={creation.status}, character_ids={creation.character_ids}")
                # 检查是否有其他创作的角色（可能是 creation_id 错误）
                all_chars = db.query(Character).filter(Character.deleted_at.is_(None)).limit(10).all()
                logger.error(f"数据库中总共有 {len(all_chars)} 个角色（前10个）")
                for char in all_chars:
                    logger.error(f"  角色: {char.name}, character_id={char.character_id}, creation_id={char.creation_id}, novel_id={char.novel_id}")
                
                # 如果状态是 CHARACTER_ANALYZED 但没有角色，说明角色分析任务可能有问题
                if creation.status == CreationStatus.CHARACTER_ANALYZED:
                    raise Exception(
                        f"创作状态为 CHARACTER_ANALYZED，但未找到角色数据，creation_id={creation_id}，character_ids={creation.character_ids}。"
                        f"可能是角色分析任务未正确保存角色数据，或数据库事务未提交。"
                    )
                else:
                    raise Exception(
                        f"未找到角色数据，creation_id={creation_id}，当前状态={creation.status}，character_ids={creation.character_ids}。"
                        f"请确保角色分析任务已完成且状态为 CHARACTER_ANALYZED。"
                    )
        
        logger.info(f"成功获取到 {len(characters)} 个角色数据（通过 character_ids={creation.character_ids}）")
        
        # 构建角色特征库
        characters_data = {}
        character_map = {}
        for char in characters:
            char_dict = {
                "基础信息": char.basic_info or "",
                "容貌特征": char.appearance or "",
                "身材特征": char.body or "",
                "头发": char.hair or "",
                "服装": char.clothing or "",
                "特征标签": char.tags if char.tags else ""
            }
            characters_data[char.name] = char_dict
            character_map[char.name] = char
        
        logger.info(f"获取到 {len(characters_data)} 个角色用于分镜拆分")
        
        # 使用创作配置的文生文模型进行分镜拆分
        extra_data = creation.extra_data or {}
        llm_model_name = extra_data.get("llm_model") or settings.LLM_MODEL_NAME
        ai_client = AIClient(llm_model_name=llm_model_name)
        logger.info(f"分镜拆分使用 LLM 模型: {llm_model_name}")
        
        # 根据模式选择不同的 prompt
        if narration_mode == "rewrite":
            prompt_playbook = read_prompt_file("playbook_rewrite.md")
        else:
            prompt_playbook = read_prompt_file("playbook_original.md")
        
        # 进行分镜拆分
        playbook = ai_client.gen_playbook_by_characters(
            prompt=prompt_playbook,
            chapter_content=chapter_content,
            characters_data=characters_data,
            user_id=creation.owner_id,
            creation_id=creation_id,
            novel_id=creation.novel_id
        )
        
        logger.info(f"分镜拆分完成，包含 {len(playbook.get('场景拆解', []))} 个场景")
        
        # 解析并保存场景和分镜信息
        scenes_data = playbook.get('场景拆解', [])
        total_shots = 0
        
        for scene_data in scenes_data:
            env_setting = scene_data.get('环境设定', {})
            
            # 创建场景记录
            scene = Scene(
                title=scene_data.get('场景标题', ''),
                duration=scene_data.get('场景时长', ''),
                time_setting=env_setting.get('时间', ''),
                location=env_setting.get('地点', ''),
                space_type=env_setting.get('空间', ''),
                atmosphere=env_setting.get('氛围', ''),
                creation_id=creation_id
            )
            db.add(scene)
            db.flush()
            
            # 创建分镜记录
            shots_data = scene_data.get('分镜列表', [])
            for shot_index, shot_data in enumerate(shots_data, start=1):
                shot_number_str = shot_data.get('分镜编号', '').split('-')[-1] if shot_data.get('分镜编号') else ''
                try:
                    shot_number = int(shot_number_str)
                except (ValueError, AttributeError):
                    shot_number = shot_index
                
                shot = Shot(
                    title=shot_data.get('分镜名称', ''),
                    shot_number=shot_number,
                    description='',
                    narration=shot_data.get('解说词', ''),
                    image_prompt=shot_data.get('完整图片提示词', ''),
                    scene_id=scene.scene_id
                )
                db.add(shot)
                db.flush()
                
                # 关联分镜和角色
                shot_characters = shot_data.get('画面人物', [])
                if shot_characters:
                    for char_name in shot_characters:
                        if char_name in character_map:
                            character = character_map[char_name]
                            shot.characters.append(character)
                            logger.debug(f"关联分镜 {shot.shot_id} 和角色 {character.character_id} ({char_name})")
                    db.flush()
                
                total_shots += 1
            
            db.flush()
        
        # 更新状态为 PLAYBOOK_GENERATED
        creation.status = CreationStatus.PLAYBOOK_GENERATED
        creation.current_task_id = None
        db.commit()
        db.refresh(creation)
        logger.info(f"成功创建 {len(scenes_data)} 个场景记录和 {total_shots} 个分镜记录，创作状态已更新: status={creation.status}")
        
        return {
            "playbook": playbook,
            "success": True,
            "task_type": TaskType.SCENE_DESCRIPTION_GENERATION,
            "novel_id": novel_id,
            "chapter_id": chapter_id,
            "creation_id": creation_id,
            "narration_mode": narration_mode,
            "scenes_count": len(scenes_data),
            "shots_count": total_shots,
            "result": "分镜拆分成功"
        }
        
    except Exception as e:
        logger.opt(exception=True).error("分镜拆分任务失败: {}", str(e))
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


# 保留原任务作为向后兼容（已废弃）
@celery_app.task(bind=True, name="process_creation_init_task")
def process_creation_init_task(self, novel_id: int, chapter_id: int, creation_id: int, chapter_content_url: str, narration_mode: str = "original"):
    """
    处理创作初始化任务（已废弃，请使用 character_analysis_task 和 playbook_generation_task）
    
    此方法保留用于向后兼容，实际会调用新的两步任务流程
    """
    logger.warning("process_creation_init_task 已废弃，将使用新的两步任务流程")
    
    try:
        # 只启动角色分析任务，不自动链接分镜拆分任务
        # 角色分析完成后，前端可以查看角色并手动触发分镜拆分
        character_analysis_task.apply_async(
            args=(novel_id, chapter_id, creation_id, chapter_content_url)
        )
        
        return {
            "message": "已启动角色分析任务（分镜拆分需手动触发）",
            "novel_id": novel_id,
            "chapter_id": chapter_id,
            "creation_id": creation_id
        }
    except Exception as e:
        # 使用 loguru 的格式化方式，避免错误消息中的字典字符串被误认为是格式化占位符
        logger.opt(exception=True).error("创作初始化任务失败: {}", str(e))
        
        try:
            error_msg = str(e).lower()
        except Exception:
            error_msg = str(e) if e else "未知错误"
        
        # 判断是否为不可重试的错误（如参数错误、模型不支持等）
        non_retryable_keywords = [
            'invalid param',
            'param_error',
            'invalid_request_error',
            'model not support',
            'model not found',
            'max_tokens',
            'invalid max_tokens',
            'bad request',
            'keyerror',
            'content moderation',
            '内容审核'
        ]
        is_non_retryable = any(keyword in error_msg for keyword in non_retryable_keywords)
        
        # 检查是否还有重试机会
        retry_count = self.request.retries if hasattr(self.request, 'retries') else 0
        max_retries = 3
        
        # 如果是不可重试的错误，或者已达到最大重试次数，需要清空 current_task_id
        if is_non_retryable or retry_count >= max_retries:
            db: Session = SessionLocal()
            try:
                # 重新查询 creation，确保能够设置 current_task_id
                creation = db.query(Creation).filter(Creation.creation_id == creation_id).first()
                if creation:
                    creation.current_task_id = None
                    db.commit()
                    logger.info(f"已清理 current_task_id，creation_id={creation_id}")
            except Exception as cleanup_error:
                logger.opt(exception=True).error("清理 current_task_id 失败: {}", str(cleanup_error))
                try:
                    db.rollback()
                except Exception:
                    pass
            finally:
                try:
                    db.close()
                except Exception:
                    pass
            
            # 如果是不可重试的错误，直接抛出，不进行重试
            if is_non_retryable:
                logger.error(f"遇到不可重试的错误，直接失败: {error_msg}")
                raise
            # 如果已达到最大重试次数，也直接抛出
            raise
        else:
            # 还有重试机会，触发重试
            raise self.retry(exc=e, countdown=60, max_retries=max_retries)