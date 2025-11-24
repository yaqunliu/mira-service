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
    def get_creations_service(
        db: Session,
        user_id: int,
        page: int = 1,
        page_size: int = 20,
        status_filter: Optional[str] = None,
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
            order_by: 排序字段（created_at, updated_at, title）
            order: 排序方向（asc, desc）
            
        Returns:
            (创作记录列表, 总数) 元组
        """
        # 构建查询
        query = db.query(Creation).filter(Creation.owner_id == user_id)
        
        # 状态过滤
        if status_filter:
            query = query.filter(Creation.status == status_filter)
        
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
        # 先加载 Creation 及其直接关联的数据
        creation = db.query(Creation).options(
            selectinload(Creation.characters),
            selectinload(Creation.scenes).selectinload(Scene.shots),
            selectinload(Creation.novel),
            selectinload(Creation.chapter)
            # selectinload(Creation.owner)
        ).filter(Creation.creation_id == creation_id).first()
        
        if not creation:
            return None
        
        # 单独加载所有 shots 的 characters（多对多关系）
        # 收集所有 shot_id
        shot_ids = [shot.shot_id for scene in creation.scenes for shot in scene.shots]
        
        # 如果有 shots，则单独查询并加载它们的 characters
        if shot_ids:
            # 查询所有相关的 shots 并加载它们的 characters
            shots_with_chars = db.query(Shot).filter(Shot.shot_id.in_(shot_ids)).options(
                selectinload(Shot.characters)
            ).all()
            
            # 打印每个 shot 及其关联的 characters 信息
            logger.info(f"加载了 {len(shots_with_chars)} 个 shots 的 characters")
            for shot in shots_with_chars:
                char_info = [
                    f"character_id={char.character_id}, name={char.name}"
                    for char in shot.characters
                ]
                logger.info(
                    f"Shot ID={shot.shot_id}, title={shot.title}, "
                    f"characters_count={len(shot.characters)}, "
                    f"characters=[{', '.join(char_info)}]"
                )
            
            # 创建一个 shot_id 到 characters 列表的映射
            shot_characters_map = {
                shot.shot_id: list(shot.characters)  # 复制列表，避免引用问题
                for shot in shots_with_chars
            }
            logger.info(f"创建了 shot_characters_map，包含 {len(shot_characters_map)} 个 shots: {list(shot_characters_map.keys())}")
            
            # 将已加载的 characters 关联到 creation 中的 shot 对象
            logger.info(f"开始关联 characters 到 creation 中的 shots，scenes 数量: {len(creation.scenes)}")
            for scene_idx, scene in enumerate(creation.scenes):
                logger.info(f"处理 Scene {scene_idx + 1} (scene_id={scene.scene_id})，包含 {len(scene.shots)} 个 shots")
                for shot_idx, shot in enumerate(scene.shots):
                    logger.info(f"  处理 Shot {shot_idx + 1} (shot_id={shot.shot_id}, title={shot.title})")
                    if shot.shot_id in shot_characters_map:
                        # 获取该 shot 的 characters 列表
                        characters_list = shot_characters_map[shot.shot_id]
                        # 清空现有的 characters（如果有）
                        shot.characters.clear()
                        # 添加新的 characters（确保在同一个 session 中）
                        for char in characters_list:
                            # 确保 character 对象在当前 session 中
                            char_in_session = db.merge(char)
                            shot.characters.append(char_in_session)
                        
                        logger.info(
                            f"  ✓ 已关联 Shot ID={shot.shot_id}，characters 数量: {len(shot.characters)}"
                        )
                        # 验证：打印每个 character 的信息
                        for char in shot.characters:
                            logger.info(f"    - Character ID={char.character_id}, name={char.name}")
                    else:
                        logger.warning(
                            f"  ✗ Shot ID={shot.shot_id} 不在 shot_characters_map 中，无法关联 characters"
                        )
                
                # 在 scene 级别验证
                logger.info(f"  Scene {scene_idx + 1} 处理完成，验证所有 shots 的 characters:")
                for shot in scene.shots:
                    logger.info(
                        f"    Shot ID={shot.shot_id}: {len(shot.characters)} 个 characters"
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
