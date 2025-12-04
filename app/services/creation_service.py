from sqlalchemy.orm import Session, selectinload, Load
from sqlalchemy import asc, desc
from typing import Tuple, Optional, List
from app.models.novel import Novel
from app.models.chapter import Chapter
from app.models.creation import Creation
from app.models.scene import Scene
from app.models.shot import Shot
from app.schemas.creation import CreationStatus
from app.tasks.creation_task import process_creation_init_task
from app.core.logger import logger
from app.core.exceptions import NotFoundError, DatabaseError, PermissionError, AlreadyExistsError


class CreationService:
    """创作服务类"""
    
    @staticmethod
    def create_creation_service(
        db: Session,
        novel_id: Optional[int],
        chapter_id: Optional[int],
        user_id: int,
        creation_id: Optional[int] = None
    ) -> int:
        """
        创建新的创作项目或继续已存在的创作
        
        Args:
            db: 数据库会话
            novel_id: 小说ID（如果提供了 creation_id，则可以为 None）
            chapter_id: 章节ID（如果提供了 creation_id，则可以为 None）
            user_id: 用户ID（已通过API层验证）
            creation_id: 可选的创作ID，用于继续已存在但未成功的创作
            
        Returns:
            创作ID
            
        Raises:
            NotFoundError: 当小说或章节不存在时，或创作不存在时
            PermissionError: 当用户无权访问该小说或创作时
            AlreadyExistsError: 当该章节已存在创作时（仅在创建新创作时）
            DatabaseError: 当任务创建失败时
        """
        # 如果提供了 creation_id，则继续已存在的创作
        if creation_id:
            logger.info(f"继续已存在的创作: creation_id={creation_id}, user_id={user_id}")
            creation = CreationService._validate_and_get_existing_creation(
                db, creation_id, user_id
            )
            
            # 验证输入参数（从已有创作中获取）
            novel, chapter = CreationService._validate_inputs(
                db, creation.novel_id, creation.chapter_id, user_id
            )
            
            # 创建并启动 Celery 任务
            task_id = CreationService._create_and_start_task(
                creation.creation_id, creation.novel_id, creation.chapter_id, chapter.content_url
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
            
            logger.info(f"创作项目继续成功: creation_id={creation.creation_id}, task_id={task_id}")
            return creation.creation_id
        
        # 如果没有提供 creation_id，则创建新的创作
        logger.info(f"创建新的视频创作项目: novel_id={novel_id}, chapter_id={chapter_id}, user_id={user_id}")
        
        # 验证输入参数
        if not novel_id or not chapter_id:
            raise ValueError("创建新创作时必须提供 novel_id 和 chapter_id")
        
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
    def get_creations_service(
        db: Session,
        user_id: int,
        page: int = 1,
        page_size: int = 20,
        status_filter: Optional[str] = None,
        title_filter: Optional[str] = None,
        order_by: str = "created_at",
        order: str = "desc"
    ) -> Tuple[List[Creation], int]:
        """
        获取创作记录列表（支持分页）
        
        Args:
            db: 数据库会话
            user_id: 用户ID
            page: 页码，从1开始
            page_size: 每页数量，最大100
            status_filter: 状态过滤（可选）
            title_filter: 按标题筛选（模糊匹配，可选）
            order_by: 排序字段（created_at, updated_at, title）
            order: 排序方向（asc, desc）
            
        Returns:
            (创作记录列表, 总数) 元组
        """
        # 构建查询（排除已删除的）
        query = db.query(Creation).filter(
            Creation.owner_id == user_id,
            Creation.deleted_at.is_(None)
        )
        
        # 状态过滤
        if status_filter:
            query = query.filter(Creation.status == status_filter)
        
        # 按标题筛选
        if title_filter:
            title_pattern = f"%{title_filter}%"
            query = query.filter(Creation.title.like(title_pattern))
        
        # 排序
        order_column = None
        if order_by == "created_at":
            order_column = Creation.created_at
        elif order_by == "updated_at":
            order_column = Creation.updated_at
        elif order_by == "title":
            order_column = Creation.title
        else:
            order_column = Creation.created_at  # 默认按创建时间
        
        if order.lower() == "asc":
            query = query.order_by(asc(order_column))
        else:
            query = query.order_by(desc(order_column))
        
        # 计算总数
        total = query.count()
        
        # 分页
        skip = (page - 1) * page_size
        creations = query.offset(skip).limit(page_size).all()
        
        return creations, total

    @staticmethod
    def get_creation_service(db: Session, creation_id: Optional[int] = None) -> Optional[Creation]:
        """
        获取创作记录（包含关联数据）
        
        Args:
            db: 数据库会话
            creation_id: 创作ID
            
        Returns:
            创作记录对象（包含预加载的关联数据）
        """
        # 使用 selectinload 一次性加载所有关联数据，包括嵌套的关联
        # 注意：scenes 和 shots 的排序已在模型 relationship 中通过 order_by 设置
        creation = db.query(Creation).options(
            selectinload(Creation.characters),
            selectinload(Creation.scenes).selectinload(Scene.shots).selectinload(Shot.characters),
            selectinload(Creation.novel),
            selectinload(Creation.chapter)
        ).filter(
            Creation.creation_id == creation_id,
            Creation.deleted_at.is_(None)
        ).first()
        
        return creation
    
    @staticmethod
    def get_creation_by_uuid_service(db: Session, creation_uuid: str) -> Optional[Creation]:
        """
        根据UUID获取创作记录（包含关联数据）
        
        Args:
            db: 数据库会话
            creation_uuid: 创作UUID
            
        Returns:
            创作记录对象（包含预加载的关联数据）
        """
        # 使用 selectinload 一次性加载所有关联数据，包括嵌套的关联
        creation = db.query(Creation).options(
            selectinload(Creation.characters),
            selectinload(Creation.scenes).selectinload(Scene.shots).selectinload(Shot.characters),
            selectinload(Creation.novel),
            selectinload(Creation.chapter)
        ).filter(
            Creation.uuid == creation_uuid,
            Creation.deleted_at.is_(None)
        ).first()
        
        return creation

    @staticmethod
    def get_creation_simple_service(
        db: Session,
        creation_id: int
    ) -> Optional[Creation]:
        """
        获取创作记录（仅基本字段，不加载关联数据）
        
        这是一个轻量级方法，只返回创作的基本信息，不加载关联的characters、scenes等数据，
        用于需要快速获取创作基本信息的场景。
        
        Args:
            db: 数据库会话
            creation_id: 创作ID
            
        Returns:
            创作记录对象（仅包含基本字段，不包含关联数据）
        """
        # 只查询创作的基本字段，不加载任何关联数据（排除已删除的）
        creation = db.query(Creation).filter(
            Creation.creation_id == creation_id,
            Creation.deleted_at.is_(None)
        ).first()
        
        return creation
    
    @staticmethod
    def get_creation_simple_by_uuid_service(
        db: Session,
        creation_uuid: str
    ) -> Optional[Creation]:
        """
        根据UUID获取创作记录（仅基本字段，不加载关联数据）
        
        Args:
            db: 数据库会话
            creation_uuid: 创作UUID
            
        Returns:
            创作记录对象（仅包含基本字段，不包含关联数据）
        """
        # 只查询创作的基本字段，不加载任何关联数据（排除已删除的）
        creation = db.query(Creation).filter(
            Creation.uuid == creation_uuid,
            Creation.deleted_at.is_(None)
        ).first()
        
        return creation

    @staticmethod
    def get_creation_by_chapter_service(
        db: Session,
        chapter_id: int,
        user_id: int
    ) -> Optional[Creation]:
        """
        根据章节ID获取创作记录
        
        Args:
            db: 数据库会话
            chapter_id: 章节ID
            user_id: 用户ID（已通过API层验证）
            
        Returns:
            创作记录对象（如果存在），否则返回None
            
        Raises:
            NotFoundError: 当章节不存在时
            PermissionError: 当用户无权访问该章节所属的小说时
        """
        logger.info(f"根据章节ID查询创作: chapter_id={chapter_id}, user_id={user_id}")
        
        # 先查询章节，验证章节是否存在和权限（排除已删除的）
        chapter = db.query(Chapter).filter(
            Chapter.chapter_id == chapter_id,
            Chapter.deleted_at.is_(None)
        ).first()
        if not chapter:
            raise NotFoundError(detail="章节不存在")
        
        # 查询章节所属的小说，验证权限
        novel = db.query(Novel).filter(Novel.novel_id == chapter.novel_id).first()
        if not novel:
            raise NotFoundError(detail="章节所属的小说不存在")
        
        # 验证用户权限
        if novel.owner_id != user_id:
            raise PermissionError(detail="无权限访问该章节")
        
        # 查询该章节的创作（排除已删除的）
        creation = db.query(Creation).options(
            selectinload(Creation.characters),
            selectinload(Creation.scenes)
        ).filter(
            Creation.chapter_id == chapter_id,
            Creation.deleted_at.is_(None)
        ).first()
        
        if not creation:
            logger.info(f"章节 {chapter_id} 没有关联的创作")
            return None
        
        logger.info(
            f"找到创作: creation_id={creation.creation_id}, "
            f"characters_count={len(creation.characters)}, "
            f"scenes_count={len(creation.scenes)}"
        )
        return creation

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
        
        # 验证章节是否存在（排除已删除的）
        chapter = db.query(Chapter).filter(
            Chapter.chapter_id == chapter_id,
            Chapter.deleted_at.is_(None)
        ).first()
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
            Creation.chapter_id == chapter_id,
            Creation.deleted_at.is_(None)
        ).first()
        
        if existing_creation:
            raise AlreadyExistsError(detail="该章节已存在创作")
    
    @staticmethod
    def _validate_and_get_existing_creation(
        db: Session,
        creation_id: int,
        user_id: int
    ) -> Creation:
        """
        验证并获取已存在的创作
        
        Args:
            db: 数据库会话
            creation_id: 创作ID
            user_id: 用户ID
            
        Returns:
            Creation 对象
            
        Raises:
            NotFoundError: 当创作不存在时
            PermissionError: 当用户无权访问该创作时
            DatabaseError: 当创作状态不允许继续时，或已有正在执行的任务时
        """
        creation = db.query(Creation).filter(
            Creation.creation_id == creation_id,
            Creation.deleted_at.is_(None)
        ).first()
        
        if not creation:
            raise NotFoundError(detail="创作不存在")
        
        # 验证用户权限
        if creation.owner_id != user_id:
            raise PermissionError(detail="无权限访问该创作")
        
        # 检查是否有正在执行的任务
        if creation.current_task_id:
            raise DatabaseError(
                detail=f"创作正在执行其他任务，任务ID: {creation.current_task_id}"
            )
        
        # 检查创作状态是否允许继续
        # 允许继续的状态：CREATED（已创建但未成功）、FAILED（失败）
        allowed_statuses = [CreationStatus.CREATED, CreationStatus.FAILED]
        if creation.status not in allowed_statuses:
            raise DatabaseError(
                detail=f"创作状态为 {creation.status}，不允许继续。只有状态为 CREATED 或 FAILED 的创作可以继续。"
            )
        
        logger.info(
            f"验证通过，可以继续创作: creation_id={creation_id}, "
            f"status={creation.status}, novel_id={creation.novel_id}, "
            f"chapter_id={creation.chapter_id}"
        )
        
        return creation
    
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
            logger.info(f"准备创建创作初始化任务: novel_id={novel_id}, chapter_id={chapter_id}, creation_id={creation_id}")
            
            # 使用 apply_async 可以更好地控制任务发送
            task = process_creation_init_task.apply_async(
                args=(novel_id, chapter_id, creation_id, chapter_content_url),
                countdown=0  # 立即执行
            )
            task_id = task.id
            logger.info(f"已创建创作初始化任务: task_id={task_id}, creation_id={creation_id}, task_state={task.state}")
            
            # 验证任务是否成功发送到队列
            if not task_id:
                raise ValueError("任务ID为空，任务可能未成功发送")
            
            return task_id
            
        except Exception as e:
            logger.error(f"创建创作初始化任务失败: {str(e)}", exc_info=True)
            raise DatabaseError(detail=f"创作初始化失败: {str(e)}") from e
