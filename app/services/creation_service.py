from sqlalchemy.orm import Session
from typing import Tuple
from app.models.novel import Novel
from app.models.chapter import Chapter
from app.models.creation import Creation
from app.schemas.creation import CreationStatus
from app.tasks.creation_task import process_creation_init
from app.core.logger import logger
from app.core.exceptions import NotFoundError, DatabaseError, PermissionError, AlreadyExistsError


class CreationService:
    """创作服务类"""
    
    @staticmethod
    def create_creation(
        db: Session,
        novel_id: int,
        chapter_id: int,
        user_id: int
    ) -> str:
        """
        创建新的创作项目
        
        Args:
            db: 数据库会话
            novel_id: 小说ID
            chapter_id: 章节ID
            user_id: 用户ID（已通过API层验证）
            
        Returns:
            任务ID字符串
            
        Raises:
            NotFoundError: 当小说或章节不存在时
            PermissionError: 当用户无权访问该小说时
            AlreadyExistsError: 当该章节已存在创作时
            DatabaseError: 当任务创建失败时
        """
        logger.info(f"创建新的视频创作项目: novel_id={novel_id}, chapter_id={chapter_id}, user_id={user_id}")
        
        # 验证输入参数
        novel, chapter = CreationService._validate_inputs(
            db, novel_id, chapter_id, user_id
        )
        
        # 检查是否已存在创作
        CreationService._check_existing_creation(db, novel_id, chapter_id)
        
        # 创建创作记录
        creation = CreationService._create_creation_record(
            db, novel, chapter, user_id
        )
        
        # 创建并启动 Celery 任务
        task_id = CreationService._create_and_start_task(
            creation.creation_id, novel_id, chapter_id, chapter.content_url
        )
        
        # 将 task_id 绑定到 creation 记录
        try:
            creation.current_task_id = task_id
            db.commit()
            logger.info(f"已更新创作记录的 current_task_id: creation_id={creation.creation_id}, task_id={task_id}")
        except Exception as e:
            logger.error(f"更新创作记录失败: {str(e)}", exc_info=True)
            db.rollback()
            raise DatabaseError(detail="更新创作记录失败") from e
        
        logger.info(f"创作项目创建成功: creation_id={creation.creation_id}, task_id={task_id}")
        return creation.creation_id
    
    @staticmethod
    def _validate_inputs(
        db: Session,
        novel_id: int,
        chapter_id: int,
        user_id: int
    ) -> Tuple[Novel, Chapter]:
        """
        验证输入参数的有效性
        
        Returns:
            (novel, chapter) 元组
            
        Raises:
            NotFoundError: 当小说或章节不存在时
            PermissionError: 当用户无权访问该小说时
        """
        # 验证小说是否存在
        novel = db.query(Novel).filter(Novel.novel_id == novel_id).first()
        if not novel:
            raise NotFoundError(detail="指定小说不存在")
        
        # 验证用户权限
        if novel.owner_id != user_id:
            raise PermissionError(detail="无权限访问该小说")
        
        # 验证章节是否存在
        chapter = db.query(Chapter).filter(Chapter.chapter_id == chapter_id).first()
        if not chapter:
            raise NotFoundError(detail="章节不存在")
        
        # 验证章节是否属于该小说
        if chapter.novel_id != novel_id:
            raise NotFoundError(detail="章节不属于指定小说")
        
        return novel, chapter
    
    @staticmethod
    def _check_existing_creation(db: Session, novel_id: int, chapter_id: int) -> None:
        """
        检查该章节是否已存在创作
        
        Raises:
            AlreadyExistsError: 当该章节已存在创作时
        """
        existing_creation = db.query(Creation).filter(
            Creation.novel_id == novel_id,
            Creation.chapter_id == chapter_id
        ).first()
        
        if existing_creation:
            raise AlreadyExistsError(detail="该章节已存在创作")
    
    @staticmethod
    def _create_creation_record(
        db: Session,
        novel: Novel,
        chapter: Chapter,
        user_id: int
    ) -> Creation:
        """
        创建创作记录
        
        Returns:
            创建的 Creation 对象
        """
        title = f"《{novel.title}》第{chapter.chapter_number}章"
        logger.info(f"创建创作记录: title={title}, novel_id={novel.novel_id}, chapter_id={chapter.chapter_id}")
        
        creation = Creation(
            novel_id=novel.novel_id,
            chapter_id=chapter.chapter_id,
            owner_id=user_id,
            title=title,
            status=CreationStatus.CREATED
        )
        db.add(creation)
        db.flush()  # 刷新以获取 creation_id，但不提交事务
        
        return creation
    
    @staticmethod
    def _create_and_start_task(
        creation_id: int,
        novel_id: int,
        chapter_id: int,
        chapter_content_url: str
    ) -> str:
        """
        创建并启动 Celery 任务
        
        Returns:
            任务ID字符串
            
        Raises:
            DatabaseError: 当任务创建失败时
        """
        try:
            # 创建 Celery 任务
            task = process_creation_init.delay(
                novel_id=novel_id,
                chapter_id=chapter_id,
                creation_id=creation_id,
                chapter_content_url=chapter_content_url
            )
            task_id = task.id
            logger.info(f"已创建创作初始化任务: task_id={task_id}, creation_id={creation_id}")
            
            return task_id
            
        except Exception as e:
            logger.error(f"创建创作初始化任务失败: {str(e)}", exc_info=True)
            raise DatabaseError(detail="创作初始化失败") from e
