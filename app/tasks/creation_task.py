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
from app.utils.llm import LLMClient
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

@celery_app.task(bind=True, name="process_creation_init")
def process_creation_init(self, novel_id: int, chapter_id: int, creation_id: int, chapter_content_url: str):
    """处理创作初始化任务"""
    db: Session = SessionLocal()
    temp_file_path = None
    try:
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

        # TODO: 生成剧本 - 临时简化开发，直接返回 demo.json 数据
        # 正式环境应使用以下代码：
        # llm_client = LLMClient()
        # prompt_playbook = read_prompt_file("playbook.md")
        # playbook = llm_client.gen_playbook_by_chapter(
        #     prompt=prompt_playbook, 
        #     chapter_content=chapter_content
        # )
        
        # 临时方案：直接读取 demo.json 文件
        app_dir = Path(__file__).parent.parent.parent
        demo_file = app_dir / "ai_res" / "demo.json"
        logger.info(f"使用演示数据: {demo_file}")
        
        if not demo_file.exists():
            raise FileNotFoundError(f"演示数据文件不存在: {demo_file}")
        
        with open(demo_file, 'r', encoding='utf-8') as f:
            playbook = json.load(f)
        
        logger.info(f"成功加载演示数据，包含 {len(playbook.get('场景拆解', []))} 个场景")
        
        # 查询对应的 Creation 记录
        creation = db.query(Creation).filter(
            Creation.creation_id == creation_id
        ).first()
        
        if not creation:
            raise Exception(f"未找到对应的创作记录: creation_id={creation_id}")
        
        creation_id = creation.creation_id
        logger.info(f"找到创作记录: creation_id={creation_id}")
        
        # 解析并保存角色信息
        character_map = {}  # 用于存储角色名到 Character 对象的映射
        characters_data = playbook.get('人物特征库', {})
        for char_name, char_info in characters_data.items():
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
                tags=json.dumps(tags_list, ensure_ascii=False) if tags_list else None,
                creation_id=creation_id,
                novel_id=novel_id
            )
            db.add(character)
            character_map[char_name] = character
        
        db.flush()  # 刷新以获取 character_id，但不提交事务
        logger.info(f"成功创建 {len(character_map)} 个角色记录")
        
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
                
                # 关联分镜和角色
                shot_characters = shot_data.get('画面人物', [])
                for char_name in shot_characters:
                    if char_name in character_map:
                        shot.characters.append(character_map[char_name])
                
                total_shots += 1
            
            db.flush()
        
        # 修改creation的状态为playbook_generated，current_task_id为空
        creation.status = CreationStatus.PLAYBOOK_GENERATED
        creation.current_task_id = None
        db.commit()
        logger.info(f"成功创建 {len(scenes_data)} 个场景记录和 {total_shots} 个分镜记录")
        
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
        logger.error(f"创作初始化任务失败: {str(e)}")
        raise self.retry(exc=e, countdown=60, max_retries=3)
    finally:
        # 清理临时文件（finally 块确保无论成功还是异常都会执行清理）
        if temp_file_path and os.path.exists(temp_file_path):
            try:
                os.remove(temp_file_path)
                logger.info(f"已清理临时文件: {temp_file_path}")
            except Exception as e:
                logger.warning(f"删除临时文件失败: {str(e)}")
        db.close()