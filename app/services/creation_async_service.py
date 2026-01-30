from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import asc, desc, select, and_, func, text as sa_text
from sqlalchemy.orm import selectinload, Session
from typing import Tuple, Optional, List
import uuid
import time
import copy
from app.db.base import AsyncSessionLocal
from app.models.novel import Novel
from app.models.chapter import Chapter
from app.models.creation import Creation
from app.models.character import Character
from app.models.scene import Scene
from app.models.shot import Shot
from app.schemas.creation import CreationStatus
from app.core.logger import logger
from app.core.exceptions import NotFoundError, DatabaseError, PermissionError, AlreadyExistsError
from app.utils.us3 import US3Client
from app.core.config import settings


class CreationAsyncService:
    """创作服务类 - 纯异步版本"""
    
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
    async def update_creation_step_status(
        db: AsyncSession,
        creation_id: int,
        step_name: str,
        status: str,
        error: Optional[str] = None,
        task_id: Optional[str] = None,
        commit: bool = False
    ) -> None:
        """更新创作步骤状态（异步版本）"""
        try:
            result = await db.execute(
                select(Creation).where(
                    Creation.creation_id == creation_id
                )
            )
            creation = result.scalar_one_or_none()
            
            if not creation:
                logger.warning(f"更新步骤状态失败: 创作不存在 creation_id={creation_id}")
                return
            
            extra_data = copy.deepcopy(creation.extra_data) if creation.extra_data else {}
            if "steps" not in extra_data:
                extra_data["steps"] = {}
            
            current_time_ms = int(time.time() * 1000)
            
            if step_name not in extra_data["steps"]:
                extra_data["steps"][step_name] = {}
            
            step_data = extra_data["steps"][step_name]
            step_data["status"] = status
            step_data["updatedAt"] = current_time_ms
            
            if status != "idle":
                step_data["triggered"] = True
            
            if error is not None:
                step_data["error"] = error
            elif status in ["pending", "processing", "success"]:
                step_data.pop("error", None)
                
            if task_id:
                step_data["taskId"] = task_id
                
            creation.extra_data = extra_data
            
            await db.flush()
            if commit:
                await db.commit()
                logger.info(f"更新创作 {creation_id} 步骤 {step_name} 状态为 {status}")
            
        except Exception as e:
            await db.rollback()
            logger.error(f"更新创作步骤状态失败: {str(e)}", exc_info=True)
            raise e
    
    @staticmethod
    async def get_creation_by_id(db: AsyncSession, creation_id: int) -> Optional[Creation]:
        """根据创作ID获取创作"""
        result = await db.execute(
            select(Creation).where(Creation.creation_id == creation_id)
        )
        return result.scalar_one_or_none()
    
    @staticmethod
    async def get_creation_by_uuid(db: AsyncSession, creation_uuid: str) -> Optional[Creation]:
        """根据创作UUID获取创作"""
        result = await db.execute(
            select(Creation).where(Creation.uuid == creation_uuid)
        )
        return result.scalar_one_or_none()
    
    @staticmethod
    async def get_creations_by_user(
        db: AsyncSession,
        user_id: int,
        skip: int = 0,
        limit: int = 100
    ) -> List[Creation]:
        """获取用户的创作列表"""
        result = await db.execute(
            select(Creation).where(
                Creation.owner_id == user_id
            ).order_by(
                Creation.created_at.desc()
            ).offset(skip).limit(limit)
        )
        return result.scalars().all()
    
    @staticmethod
    async def get_creations_service(
        db: AsyncSession,
        user_id: int,
        page: int = 1,
        page_size: int = 20,
        status_filter: Optional[str] = None,
        title_filter: Optional[str] = None,
        order_by: str = "created_at",
        order: str = "desc"
    ) -> Tuple[List[Creation], int]:
        """获取创作记录列表（支持分页）- 异步版本"""
        base_query = select(Creation).where(
            Creation.owner_id == user_id,
            Creation.deleted_at.is_(None)
        )
        
        query = base_query.options(
            selectinload(Creation.novel),
            selectinload(Creation.chapter),
            selectinload(Creation.characters),
            selectinload(Creation.scenes).selectinload(Scene.shots)
        )
        
        if status_filter:
            query = query.where(Creation.status == status_filter)
        
        if title_filter:
            title_pattern = f"%{title_filter}%"
            query = query.where(Creation.title.like(title_pattern))
        
        order_column = Creation.created_at
        if order_by == "updated_at":
            order_column = Creation.updated_at
        elif order_by == "title":
            order_column = Creation.title
        
        if order.lower() == "asc":
            query = query.order_by(asc(order_column))
        else:
            query = query.order_by(desc(order_column))
        
        count_query = select(func.count()).select_from(base_query.subquery())
        count_result = await db.execute(count_query)
        total = count_result.scalar()
        
        skip = (page - 1) * page_size
        query = query.offset(skip).limit(page_size)
        
        result = await db.execute(query)
        creations = result.scalars().all()
        
        return list(creations), total
    
    @staticmethod
    async def create_creation_service(
        db: AsyncSession,
        novel_id: Optional[int],
        chapter_id: Optional[int],
        user_id: int,
        creation_id: Optional[int] = None,
        narration_mode: str = "original",
        extra_data: dict = None,
        text_content: Optional[str] = None
    ) -> int:
        """
        创建新的创作项目或继续已存在的创作 - 纯异步版本
        
        注意：此方法直接使用传入的 db 会话，不创建新会话
        """
        if creation_id is not None and not isinstance(creation_id, int):
            logger.warning(f"creation_id 必须是整数，收到: {creation_id} (类型: {type(creation_id)})")
            creation_id = None
        
        if creation_id:
            logger.info(f"继续已存在的创作: creation_id={creation_id}, user_id={user_id}")
            
            result = await db.execute(
                select(Creation).where(
                    Creation.creation_id == creation_id,
                    Creation.owner_id == user_id
                )
            )
            creation = result.scalar_one_or_none()
            
            if not creation:
                raise NotFoundError(detail="创作不存在或无权限访问")
            
            novel, chapter = None, None
            if creation.novel_id:
                result = await db.execute(
                    select(Novel).where(Novel.novel_id == creation.novel_id)
                )
                novel = result.scalar_one_or_none()
            
            if creation.chapter_id:
                result = await db.execute(
                    select(Chapter).where(Chapter.chapter_id == creation.chapter_id)
                )
                chapter = result.scalar_one_or_none()
            
            from app.tasks.creation_task import character_analysis_task
            task_id = character_analysis_task.delay(
                novel_id=creation.novel_id,
                chapter_id=creation.chapter_id,
                creation_id=creation.creation_id,
                chapter_content_url=chapter.content_url if chapter else None,
                narration_mode=narration_mode
            ).id
            
            creation.current_task_id = task_id
            await db.flush()
            await db.commit()
            logger.info(f"已更新创作记录的 current_task_id: creation_id={creation.creation_id}, task_id={task_id}")
            
            return creation.creation_id
        
        logger.info(f"创建新的视频创作项目: novel_id={novel_id}, chapter_id={chapter_id}, user_id={user_id}")
        
        if not ((novel_id and chapter_id) or text_content):
            raise ValueError("创建新创作时必须提供 novel_id+chapter_id 或 text_content")
        
        novel, chapter = None, None
        chapter_content_url = None
        
        if novel_id and chapter_id:
            result = await db.execute(
                select(Novel).where(Novel.novel_id == novel_id)
            )
            novel = result.scalar_one_or_none()
            
            if not novel:
                raise NotFoundError(detail="小说不存在")
            
            result = await db.execute(
                select(Chapter).where(Chapter.chapter_id == chapter_id)
            )
            chapter = result.scalar_one_or_none()
            
            if not chapter:
                raise NotFoundError(detail="章节不存在")
            
            if novel.owner_id != user_id:
                raise PermissionError(detail="无权访问此小说")
            
            chapter_content_url = chapter.content_url
            
            result = await db.execute(
                select(Creation).where(
                    Creation.novel_id == novel_id,
                    Creation.chapter_id == chapter_id,
                    Creation.deleted_at.is_(None)
                )
            )
            existing = result.scalar_one_or_none()
            if existing:
                logger.info(f"章节已存在创作记录，直接返回: creation_id={existing.creation_id}")
                return existing.creation_id
        
        creation_extra_data = extra_data or {}
        if narration_mode:
            creation_extra_data["narration_mode"] = narration_mode
        
        if novel and chapter:
            creation = Creation(
                uuid=str(uuid.uuid4()),
                title=chapter.title or f"创作 {chapter.chapter_number}",
                status="created",
                owner_id=user_id,
                novel_id=novel_id,
                chapter_id=chapter_id,
                extra_data=creation_extra_data,
                preview_text=chapter.preview[:500] if chapter.preview else None,
                text_content_url=chapter.content_url
            )
        else:
            preview = text_content[:500] if text_content else None
            creation = Creation(
                uuid=str(uuid.uuid4()),
                title="文案创作",
                status="created",
                owner_id=user_id,
                novel_id=0,
                chapter_id=0,
                extra_data=creation_extra_data,
                preview_text=preview,
                text_content_url=None,
                creation_type="script"
            )
        
        db.add(creation)
        await db.flush()
        
        content_url = chapter_content_url
        if not content_url and creation.text_content_url:
            content_url = creation.text_content_url
        
        from app.tasks.creation_task import character_analysis_task
        task_id = character_analysis_task.delay(
            novel_id=novel_id,
            chapter_id=chapter_id,
            creation_id=creation.creation_id,
            chapter_content_url=content_url
        ).id
        
        creation.current_task_id = task_id
        await db.flush()
        await db.commit()
        logger.info(f"创作项目创建成功: creation_id={creation.creation_id}, task_id={task_id}")
        
        return creation.creation_id
    
    @staticmethod
    async def get_creations_by_novel(
        db: AsyncSession,
        novel_id: int,
        skip: int = 0,
        limit: int = 100
    ) -> List[Creation]:
        """获取小说的创作列表"""
        result = await db.execute(
            select(Creation).where(
                Creation.novel_id == novel_id
            ).order_by(
                Creation.created_at.desc()
            ).offset(skip).limit(limit)
        )
        return result.scalars().all()
    
    @staticmethod
    async def get_creations_by_chapter(
        db: AsyncSession,
        chapter_id: int,
        skip: int = 0,
        limit: int = 100
    ) -> List[Creation]:
        """获取章节的创作列表"""
        result = await db.execute(
            select(Creation).where(
                Creation.chapter_id == chapter_id
            ).order_by(
                Creation.created_at.desc()
            ).offset(skip).limit(limit)
        )
        return result.scalars().all()
    
    @staticmethod
    async def update_creation(
        db: AsyncSession,
        creation_id: int,
        **update_data
    ) -> Optional[Creation]:
        """更新创作"""
        result = await db.execute(
            select(Creation).where(Creation.creation_id == creation_id)
        )
        creation = result.scalar_one_or_none()
        
        if not creation:
            return None
        
        for key, value in update_data.items():
            if hasattr(creation, key):
                setattr(creation, key, value)
        
        await db.commit()
        await db.refresh(creation)
        
        return creation
    
    @staticmethod
    async def delete_creation(db: AsyncSession, creation_id: int) -> bool:
        """删除创作"""
        result = await db.execute(
            select(Creation).where(Creation.creation_id == creation_id)
        )
        creation = result.scalar_one_or_none()
        
        if not creation:
            return False
        
        await db.delete(creation)
        await db.commit()
        
        return True
    
    @staticmethod
    async def get_creation_with_relations(
        db: AsyncSession,
        creation_id: int
    ) -> Optional[Creation]:
        """获取创作及其关联数据"""
        result = await db.execute(
            select(Creation).options(
                selectinload(Creation.characters),
                selectinload(Creation.scenes).selectinload(Scene.shots)
            ).where(Creation.creation_id == creation_id)
        )
        return result.scalar_one_or_none()
    
    @staticmethod
    async def count_creations_by_user(db: AsyncSession, user_id: int) -> int:
        """统计用户的创作数量"""
        result = await db.execute(
            select(Creation).where(Creation.owner_id == user_id)
        )
        return len(result.scalars().all())
    
    @staticmethod
    async def get_recent_creations(
        db: AsyncSession,
        user_id: int,
        days: int = 7,
        limit: int = 10
    ) -> List[Creation]:
        """获取最近7天的创作"""
        from datetime import datetime, timedelta
        cutoff = datetime.utcnow() - timedelta(days=days)
        
        result = await db.execute(
            select(Creation).where(
                and_(
                    Creation.owner_id == user_id,
                    Creation.created_at >= cutoff
                )
            ).order_by(
                Creation.created_at.desc()
            ).limit(limit)
        )
        return result.scalars().all()
