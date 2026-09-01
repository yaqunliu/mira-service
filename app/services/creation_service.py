from sqlalchemy.orm import Session, selectinload
from sqlalchemy import asc, desc
from typing import Tuple, Optional, List
from app.models.novel import Novel
from app.models.chapter import Chapter
from app.models.creation import Creation
from app.models.character import Character
from app.models.scene import Scene
from app.models.shot import Shot
from app.schemas.creation import CreationStatus
from app.tasks.creation_task import character_analysis_task
from app.core.logger import logger
from app.core.exceptions import NotFoundError, DatabaseError, PermissionError, AlreadyExistsError
from app.utils.us3 import US3Client
from app.utils.local_storage import get_storage_client
from app.core.config import settings
import uuid
import time


class CreationService:
    """创作服务类"""
    
    # 定义所有创作步骤名称
    STEPS = [
        "characterAnalysis",
        "characterImageGeneration",
        "sceneAnalysis",
        "shotAnalysis",
        "sceneImageGeneration",
        "shotImageGeneration",
        "videoGeneration"
    ]
    
    @staticmethod
    def update_creation_step_status(
        db: Session,
        creation_id: int,
        step_name: str,
        status: str,
        error: Optional[str] = None,
        task_id: Optional[str] = None,
        commit: bool = True
    ) -> None:
        """
        更新创作步骤状态（使用行锁防止并发冲突）
        
        Args:
            db: 数据库会话
            creation_id: 创作ID
            step_name: 步骤名称（如 characterAnalysis, sceneAnalysis 等）
            status: 状态（pending, processing, success, failed）
            error: 错误信息（可选）
            task_id: Celery任务ID（可选）
            commit: 是否立即提交事务（默认True，在任务内部调用建议设为False）
        """
        try:
            # 使用 with_for_update 获取行锁，确保并发安全
            creation = db.query(Creation).filter(
                Creation.creation_id == creation_id
            ).with_for_update().first()
            
            if not creation:
                logger.warning(f"更新步骤状态失败: 创作不存在 creation_id={creation_id}")
                return
            
            # 深度复制 extra_data 以确保 SQLAlchemy 检测到变更
            import copy
            from sqlalchemy.orm.attributes import flag_modified
            
            extra_data = copy.deepcopy(creation.extra_data) if creation.extra_data else {}
            if "steps" not in extra_data:
                extra_data["steps"] = {}
            
            current_time_ms = int(time.time() * 1000)
            
            # 初始化或更新步骤信息
            if step_name not in extra_data["steps"]:
                extra_data["steps"][step_name] = {}
            
            step_data = extra_data["steps"][step_name]
            step_data["status"] = status
            step_data["updatedAt"] = current_time_ms
            
            # 如果状态不是 idle，则标记为已触发
            if status != "idle":
                step_data["triggered"] = True
            
            if error is not None:
                step_data["error"] = error
            elif status in ["pending", "processing", "success"]:
                # 如果状态不是 failed，清除之前的错误
                step_data.pop("error", None)
                
            if task_id:
                step_data["taskId"] = task_id
                
            # 重新赋值并标记修改，确保触发 ORM 更新
            creation.extra_data = extra_data
            flag_modified(creation, "extra_data")
            
            if commit:
                db.commit()
                logger.info(f"更新创作 {creation_id} 步骤 {step_name} 状态为 {status} (已提交)")
            else:
                db.flush()
                logger.info(f"更新创作 {creation_id} 步骤 {step_name} 状态为 {status} (已刷新)")
            
        except Exception as e:
            logger.error(f"更新创作步骤状态失败: {str(e)}", exc_info=True)
            # 不在子方法中执行 rollback，让调用方决定是否回滚整个事务
            raise e

    @staticmethod
    def create_creation_service(
        db: Session,
        novel_id: Optional[int],
        chapter_id: Optional[int],
        user_id: int,
        creation_id: Optional[int] = None,
        narration_mode: str = "original",
        extra_data: dict = None,
        text_content: Optional[str] = None
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
                creation.creation_id, creation.novel_id, creation.chapter_id, chapter.content_url, narration_mode
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
        logger.info(f"创建新的视频创作项目: novel_id={novel_id}, chapter_id={chapter_id}, text_content={text_content[:50]}... (truncated), user_id={user_id}")
        
        # 验证输入参数 - 必须提供 novel_id+chapter_id 或 text_content
        if not ((novel_id and chapter_id) or text_content):
            raise ValueError("创建新创作时必须提供 novel_id+chapter_id 或 text_content")
        
        novel, chapter = None, None
        chapter_content_url = None
        
        if novel_id and chapter_id:
            # 通过小说章节创建
            novel, chapter = CreationService._validate_inputs(
                db, novel_id, chapter_id, user_id
            )
            chapter_content_url = chapter.content_url
            
            # 检查是否已存在创作
            CreationService._check_existing_creation(db, novel_id, chapter_id)
        
        # 构建 extra_data（如果提供了 narration_mode，添加到 extra_data 中）
        creation_extra_data = extra_data or {}
        if narration_mode:
            creation_extra_data["narration_mode"] = narration_mode
        
        # 创建创作记录
        if novel and chapter:
            creation = CreationService._create_creation_record(
                db, novel, chapter, user_id, creation_extra_data
            )
        else:
            # 通过文本内容创建
            creation = CreationService._create_text_creation_record(
                db, user_id, text_content, creation_extra_data
            )
        
        # 确定内容URL
        content_url = chapter_content_url
        if not content_url and creation.text_content_url:
            content_url = creation.text_content_url
        
        # 创建并启动 Celery 任务
        task_id = CreationService._create_and_start_task(
            creation.creation_id, novel_id, chapter_id, content_url, narration_mode
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

        # 预加载必要的关联，避免 N+1，同时不加载 novel.chapters
        query = query.options(
            selectinload(Creation.novel),
            selectinload(Creation.chapter),
            selectinload(Creation.characters),
            selectinload(Creation.scenes)
            .selectinload(Scene.shots)
            # .selectinload(Shot.characters),
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
        # 使用 selectinload 加载关联数据
        creation = db.query(Creation).options(
            selectinload(Creation.scenes).selectinload(Scene.shots).selectinload(Shot.characters),
            selectinload(Creation.novel),
            selectinload(Creation.chapter)
        ).filter(
            Creation.creation_id == creation_id,
            Creation.deleted_at.is_(None)
        ).first()
        
        if not creation:
            return None
        
        # 根据 character_ids 字段查询角色（包括复用的角色）
        if creation.character_ids and len(creation.character_ids) > 0:
            characters = db.query(Character).filter(
                Character.character_id.in_(creation.character_ids),
                Character.deleted_at.is_(None)
            ).all()
            # 手动设置角色关系（因为不是通过 creation_id 关联的）
            creation.characters = characters
        else:
            # 如果没有 character_ids，使用传统方式查询（向后兼容）
            characters = db.query(Character).filter(
                Character.creation_id == creation_id,
                Character.deleted_at.is_(None)
            ).all()
            creation.characters = characters
            
        # 根据 scene_ids 字段查询场景（包括复用的场景）
        if creation.scene_ids and len(creation.scene_ids) > 0:
            scenes = db.query(Scene).options(
                selectinload(Scene.shots).selectinload(Shot.characters)
            ).filter(
                Scene.scene_id.in_(creation.scene_ids),
                Scene.deleted_at.is_(None)
            ).order_by(Scene.scene_id).all()
            # 手动设置场景关系
            creation.scenes = scenes
        
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
        # 使用 selectinload 加载关联数据
        creation = db.query(Creation).options(
            selectinload(Creation.scenes).selectinload(Scene.shots).selectinload(Shot.characters),
            selectinload(Creation.novel),
            selectinload(Creation.chapter)
        ).filter(
            Creation.uuid == creation_uuid,
            Creation.deleted_at.is_(None)
        ).first()
        
        if not creation:
            return None
        
        # 根据 character_ids 字段查询角色（包括复用的角色）
        if creation.character_ids and len(creation.character_ids) > 0:
            characters = db.query(Character).filter(
                Character.character_id.in_(creation.character_ids),
                Character.deleted_at.is_(None)
            ).all()
            # 手动设置角色关系（因为不是通过 creation_id 关联的）
            creation.characters = characters
        else:
            # 如果没有 character_ids，使用传统方式查询（向后兼容）
            characters = db.query(Character).filter(
                Character.creation_id == creation.creation_id,
                Character.deleted_at.is_(None)
            ).all()
            creation.characters = characters
            
        # 根据 scene_ids 字段查询场景（包括复用的场景）
        if creation.scene_ids and len(creation.scene_ids) > 0:
            scenes = db.query(Scene).options(
                selectinload(Scene.shots).selectinload(Shot.characters)
            ).filter(
                Scene.scene_id.in_(creation.scene_ids),
                Scene.deleted_at.is_(None)
            ).order_by(Scene.scene_id).all()
            # 手动设置场景关系
            creation.scenes = scenes
        
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
        根据UUID获取创作记录（仅基本字段，但加载 novel 和 chapter 关系以获取 UUID）
        
        Args:
            db: 数据库会话
            creation_uuid: 创作UUID
            
        Returns:
            创作记录对象（包含基本字段和 novel、chapter 关系）
        """
        # 查询创作的基本字段，并加载 novel 和 chapter 关系以获取 UUID（排除已删除的）
        creation = db.query(Creation).options(
            selectinload(Creation.novel),
            selectinload(Creation.chapter)
        ).filter(
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
    def update_creation_service(
        db: Session,
        creation_uuid: str,
        user_id: int,
        update_data: dict
    ) -> Creation:
        """
        更新创作项目
        
        Args:
            db: 数据库会话
            creation_uuid: 创作UUID
            user_id: 用户ID
            update_data: 更新数据字典
            
        Returns:
            更新后的 Creation 对象
            
        Raises:
            NotFoundError: 当创作不存在时
            PermissionError: 当用户无权修改该创作时
        """
        creation = db.query(Creation).filter(
            Creation.uuid == creation_uuid,
            Creation.deleted_at.is_(None)
        ).first()
        
        if not creation:
            raise NotFoundError(detail="创作项目不存在")
            
        if creation.owner_id != user_id:
            raise PermissionError(detail="无权限修改该创作项目")
            
        # 更新字段
        for field, value in update_data.items():
            if hasattr(creation, field) and value is not None:
                setattr(creation, field, value)
                
        try:
            db.commit()
            db.refresh(creation)
            return creation
        except Exception as e:
            logger.error(f"更新创作项目失败: {str(e)}", exc_info=True)
            db.rollback()
            raise DatabaseError(detail=f"更新失败: {str(e)}")

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
    def _init_steps_metadata(extra_data: dict = None) -> dict:
        """初始化步骤元数据"""
        data = extra_data or {}
        if "steps" not in data:
            data["steps"] = {}
        
        current_time_ms = int(time.time() * 1000)
        for step in CreationService.STEPS:
            if step not in data["steps"]:
                data["steps"][step] = {
                    "status": "idle",
                    "triggered": False,
                    "updatedAt": current_time_ms
                }
        return data

    @staticmethod
    def _create_creation_record(
        db: Session,
        novel: Novel,
        chapter: Chapter,
        user_id: int,
        extra_data: dict = None
    ) -> Creation:
        """
        创建创作记录

        Args:
            db: 数据库会话
            novel: 小说对象
            chapter: 章节对象
            user_id: 用户ID
            extra_data: 扩展数据（创作配置）

        Returns:
            创建的 Creation 对象
        """
        title = f"{novel.title} {chapter.title}"
        logger.info(f"创建创作记录: title={title}, novel_id={novel.novel_id}, chapter_id={chapter.chapter_id}")
        
        # 初始化步骤元数据
        creation_extra_data = CreationService._init_steps_metadata(extra_data)
        
        # 创建章节创作记录
        creation = Creation(
            novel_id=novel.novel_id,
            chapter_id=chapter.chapter_id,
            owner_id=user_id,
            title=title,
            status=CreationStatus.CREATED,
            creation_type="chapter",  # 章节创作类型
            preview_text=chapter.content[:500] if chapter.content else None,  # 章节内容预览
            text_content_url=chapter.content_url,  # 章节内容URL
            extra_data=creation_extra_data
        )
        db.add(creation)
        db.flush()  # 刷新以获取 creation_id，但不提交事务
        
        return creation
    
    @staticmethod
    def _create_text_creation_record(
        db: Session,
        user_id: int,
        text_content: str,
        extra_data: dict = None
    ) -> Creation:
        """
        通过文本内容创建创作记录
        
        Args:
            db: 数据库会话
            user_id: 用户ID
            text_content: 直接上传的文本内容
            extra_data: 扩展数据（创作配置）
        
        Returns:
            创建的 Creation 对象
        """
        # 从文本内容中提取标题（前20个字符）
        title_prefix = text_content[:20].replace('\n', ' ').strip()
        title = f"文本创作 - {title_prefix}..."
        logger.info(f"通过文本内容创建创作记录: title={title}, user_id={user_id}")
        
        # 将文本内容上传到US3（US3 未配置时自动降级到本地存储）
        us3_client = get_storage_client()
        put_key = f"texts/{uuid.uuid4()}.txt"
        upload_result = us3_client.upload_file_stream(
            file_stream=text_content.encode('utf-8'),
            put_key=put_key,
            content_type='text/plain'
        )

        if not upload_result.get('success'):
            raise DatabaseError(detail=f"文本内容上传失败: {upload_result.get('message')}")

        # 由客户端生成访问地址：本地存储没有 bucket/DOWNLOAD_SUFFIX 的概念，
        # 手工拼 US3 域名会得到一个访问不到的地址。
        text_content_url = us3_client.get_file_url(put_key)
        
        # 初始化步骤元数据
        creation_extra_data = CreationService._init_steps_metadata(extra_data)
        
        creation = Creation(
            novel_id=0,  # 设置默认值0
            chapter_id=0,  # 设置默认值0
            owner_id=user_id,
            title=title,
            status=CreationStatus.CREATED,
            creation_type="script",  # 文案创作类型
            preview_text=text_content[:500] if text_content else None,  # 文本内容预览
            text_content_url=text_content_url,  # 文本内容US3 URL
            extra_data=creation_extra_data
        )
        db.add(creation)
        db.flush()  # 刷新以获取 creation_id，但不提交事务
        
        return creation
    
    @staticmethod
    def _create_and_start_task(
        creation_id: int,
        novel_id: int,
        chapter_id: int,
        chapter_content_url: str,
        narration_mode: str = "original"
    ) -> str:
        """
        创建并启动 Celery 任务（只启动角色分析任务，分镜拆分由前端手动触发）
        
        Args:
            creation_id: 创作ID
            novel_id: 小说ID
            chapter_id: 章节ID
            chapter_content_url: 章节内容URL
            narration_mode: 解说词模式，可选值："original"（原文模式）或 "rewrite"（爽文模式），默认为 "original"
                          注意：此参数在当前方法中不再使用，保留用于向后兼容
        
        Returns:
            任务ID字符串（角色分析任务的ID）
            
        Raises:
            DatabaseError: 当任务创建失败时
        """
        try:
            # 只启动角色分析任务，不自动链接分镜拆分任务
            # 角色分析完成后，前端可以查看角色，然后手动触发分镜拆分
            logger.info(f"准备创建角色分析任务: novel_id={novel_id}, chapter_id={chapter_id}, creation_id={creation_id}")
            
            task = character_analysis_task.apply_async(
                args=(novel_id, chapter_id, creation_id, chapter_content_url),
                countdown=0  # 立即执行
            )
            task_id = task.id
            logger.info(f"已创建角色分析任务: task_id={task_id}, creation_id={creation_id}, task_state={task.state}")
            logger.info(f"角色分析完成后，前端可以查看角色并手动触发分镜拆分任务")
            
            # 验证任务是否成功发送到队列
            if not task_id:
                raise ValueError("任务ID为空，任务可能未成功发送")
            
            return task_id
            
        except Exception as e:
            logger.error(f"创建角色分析任务失败: {str(e)}", exc_info=True)
            raise DatabaseError(detail=f"创作初始化失败: {str(e)}") from e
