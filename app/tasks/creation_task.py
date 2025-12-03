"""
创作任务
"""
import os
import json
import tempfile
from pathlib import Path
from app.core.celery_app import celery_app
from app.utils.us3 import US3Client
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

@celery_app.task(bind=True, name="process_creation_init_task")
def process_creation_init_task(self, novel_id: int, chapter_id: int, creation_id: int, chapter_content_url: str):
    """处理创作初始化任务"""
    db: Session = SessionLocal()
    temp_file_path = None
    logger.info(f"开始处理创作初始化任务: novel_id={novel_id}, chapter_id={chapter_id}, creation_id={creation_id}")
    try:
        ##X## Debug 模式下抛出测试异常 - 测试创作初始化错误
        # if settings.DEBUG:
        #     raise Exception("测试创作初始化错误")
        
        self.update_state(
            state='PROGRESS',
            meta={
                'task_type': TaskType.CREATION_INIT,
                'novel_id': novel_id,
                'chapter_id': chapter_id,
                'creation_id': creation_id
            }
        )
        
        # 创建临时文件（使用系统临时目录，读取后立即删除）
        temp_fd, temp_file_path = tempfile.mkstemp(suffix='.txt')
        os.close(temp_fd)  # 关闭文件描述符，但保留文件路径
        
        logger.info(f"准备下载章节内容到临时文件: {temp_file_path}")
        
        # 从us3下载章节内容到临时文件
        us3_client = US3Client()
        download_result = us3_client.download_file(
            bucket=None, 
            put_key=chapter_content_url, 
            save_file=temp_file_path
        )
        
        if not download_result['success']:
            error_detail = download_result.get('message', '未知错误')
            logger.error(f"获取章节内容失败: {error_detail}")
            raise Exception(f"获取章节内容失败: {error_detail}")
        
        # 读取临时文件内容
        with open(temp_file_path, 'r', encoding='utf-8') as f:
            chapter_content = f.read()
        logger.info(f"成功读取章节内容，长度: {len(chapter_content)} 字符")

        # 查询对应的 Creation 记录以获取用户信息
        creation = db.query(Creation).filter(
            Creation.creation_id == creation_id
        ).first()
        
        if not creation:
            raise Exception(f"创作不存在: creation_id={creation_id}")
        
        # TODO: 生成剧本 - 临时简化开发，直接返回 demo.json 数据
        # 正式环境应使用以下代码：
        ai_client = AIClient()
        prompt_playbook = read_prompt_file("playbook.md")
        playbook = ai_client.gen_playbook_by_chapter(
            prompt=prompt_playbook, 
            chapter_content=chapter_content,
            user_id=creation.owner_id,
            creation_id=creation_id,
            novel_id=creation.novel_id
        )
        
        # 临时方案：直接读取 demo.json 文件
        # app_dir = Path(__file__).parent.parent.parent
        # demo_file = app_dir / "ai_res" / "demo.json"
        # logger.info(f"使用演示数据: {demo_file}")
        
        # if not demo_file.exists():
        #     raise FileNotFoundError(f"演示数据文件不存在: {demo_file}")
        
        # with open(demo_file, 'r', encoding='utf-8') as f:
        #     playbook = json.load(f)
        
        logger.info(f"成功加载演示数据，包含 {len(playbook.get('场景拆解', []))} 个场景")
        logger.info(f"找到创作记录: creation_id={creation_id}")
        
        # 解析并保存角色信息
        character_map = {}  # 用于存储角色名到 Character 对象的映射
        characters_data = playbook.get('人物特征库', {})
        created_count = 0
        reused_count = 0
        
        for char_name, char_info in characters_data.items():
            # 检查该小说中是否已存在同名角色
            existing_character = db.query(Character).filter(
                Character.novel_id == novel_id,
                Character.name == char_name
            ).first()
            
            if existing_character:
                # 如果已存在，使用已有角色
                character_map[char_name] = existing_character
                reused_count += 1
                logger.info(f"复用已有角色: {char_name} (character_id={existing_character.character_id})")
            else:
                # 如果不存在，创建新角色
                # 解析特征标签（可能是字符串或列表）
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
                    tags=tags_list if tags_list else None,  # 直接存储列表，SQLAlchemy 会自动序列化
                    creation_id=creation_id,
                    novel_id=novel_id
                )
                db.add(character)
                character_map[char_name] = character
                created_count += 1
                logger.info(f"创建新角色: {char_name}")
        
        db.flush()  # 刷新以获取 character_id，但不提交事务
        logger.info(f"角色处理完成: 新建 {created_count} 个，复用 {reused_count} 个，总计 {len(character_map)} 个角色")
        
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
            db.flush()  # 获取 scene_id
            
            # 创建分镜记录
            shots_data = scene_data.get('分镜列表', [])
            for shot_index, shot_data in enumerate(shots_data, start=1):
                # 尝试从分镜编号中提取序号（如 "1-1-1" -> 1），失败则使用场景内序号
                shot_number_str = shot_data.get('分镜编号', '').split('-')[-1] if shot_data.get('分镜编号') else ''
                try:
                    shot_number = int(shot_number_str)
                except (ValueError, AttributeError):
                    shot_number = shot_index  # 使用场景内的序号
                
                shot = Shot(
                    title=shot_data.get('分镜名称', ''),
                    shot_number=shot_number,
                    description='',  # 分镜描述暂时为空
                    narration=shot_data.get('解说词', ''),
                    image_prompt=shot_data.get('完整图片提示词', ''),
                    scene_id=scene.scene_id
                )
                db.add(shot)
                db.flush()  # 获取 shot_id
                
                # 关联分镜和角色（多对多关系）
                shot_characters = shot_data.get('画面人物', [])
                if shot_characters:
                    for char_name in shot_characters:
                        if char_name in character_map:
                            character = character_map[char_name]
                            shot.characters.append(character)
                            logger.debug(f"关联分镜 {shot.shot_id} 和角色 {character.character_id} ({char_name})")
                    # 关联后立即 flush，确保多对多关系被保存到关联表
                    db.flush()
                
                total_shots += 1
            
            # 在场景循环结束后 flush，确保关联关系被保存
            db.flush()
        
        # 修改creation的状态为playbook_generated，current_task_id为空
        creation.status = CreationStatus.PLAYBOOK_GENERATED
        creation.current_task_id = None
        db.commit()
        db.refresh(creation)  # 刷新对象以确保数据同步
        logger.info(f"成功创建 {len(scenes_data)} 个场景记录和 {total_shots} 个分镜记录，创作状态已更新: status={creation.status}, current_task_id={creation.current_task_id}")
        
        return {
            "playbook": playbook,
            "success": True,
            "task_type": TaskType.CREATION_INIT,
            "novel_id": novel_id,
            "chapter_id": chapter_id,
            "creation_id": creation_id,
            "characters_count": len(character_map),
            "scenes_count": len(scenes_data),
            "shots_count": total_shots,
            "result": "创作初始化成功"
        }

    except Exception as e:
        # 使用 loguru 的格式化方式，避免错误消息中的字典字符串被误认为是格式化占位符
        logger.opt(exception=True).error("创作初始化任务失败: {}", str(e))
        db.rollback()  # 确保回滚事务
        
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
            
            # 如果是不可重试的错误，直接抛出，不进行重试
            if is_non_retryable:
                logger.error(f"遇到不可重试的错误，直接失败: {error_msg}")
                raise
            # 如果已达到最大重试次数，也直接抛出
            raise
        else:
            # 还有重试机会，触发重试（临时文件会在 finally 中清理，重试时会重新下载）
            raise self.retry(exc=e, countdown=60, max_retries=max_retries)
    finally:
        # 确保数据库连接已关闭
        try:
            if db:
                db.close()
        except Exception:
            pass
        # 清理临时文件（重试时会重新下载，所以可以安全清理）
        if temp_file_path and os.path.exists(temp_file_path):
            try:
                os.remove(temp_file_path)
                logger.info(f"已清理临时文件: {temp_file_path}")
            except Exception as e:
                logger.warning(f"删除临时文件失败: {str(e)}")