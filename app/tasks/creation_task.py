"""
创作任务
"""
from app.core.celery_app import celery_app
from app.utils.us3 import US3Client
from app.core.config import settings
from app.core.logger import logger
from app.db.session import SessionLocal
from sqlalchemy.orm import Session
from app.models.creation import Creation
from app.utils.task_types import TaskType


@celery_app.task(bind=True, name="process_creation_init")
def process_creation_init(self, novel_id: int, chapter_id: int, chapter_content_url: str):
    """处理创作初始化任务"""
    db: Session = SessionLocal()
    try:
        self.update_state(
            state='PROGRESS',
            meta={
                'task_type': TaskType.CREATION_INIT,
                'novel_id': novel_id,
                'chapter_id': chapter_id
            }
        )
        # 从us3获取章节内容
        us3_client = US3Client()
        download_result = us3_client.download_file(bucket=None, put_key=chapter_content_url, save_file=None)
        if not download_result['success']:
            raise Exception("获取章节内容失败")
        chapter_content = download_result['response']
        return {
            "success": True,
            "task_type": TaskType.CREATION_INIT,
            "novel_id": novel_id,
            "chapter_id": chapter_id,
            "data": chapter_content,
            "result": "创作初始化成功"
        }

    except Exception as e:
        logger.error(f"创作初始化任务失败: {str(e)}")
        raise self.retry(exc=e, countdown=60, max_retries=3)