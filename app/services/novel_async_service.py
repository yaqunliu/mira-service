import uuid
import os
import time
from typing import List, Optional, Dict, Any, Tuple
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import desc, asc, select, func, and_, or_
from sqlalchemy.orm import selectinload
from fastapi import UploadFile
from app.models.novel import Novel
from app.models.chapter import Chapter
from app.core.logger import logger
from app.core.exceptions import NotFoundError, PermissionError, FileSizeExceededError, FileEmptyError, DatabaseError
from app.models.user import User
from app.tasks.novel_tasks import process_novel_upload_task
from app.utils.upload_helper import upload_helper
from app.schemas.novel import NovelUpdate, NovelCreate
from app.schemas.chapter import ChapterUpdate, ChapterCreate

MAX_NOVEL_FILE_SIZE = 50 * 1024 * 1024


class NovelAsyncService:
    """小说服务类 - 异步版本"""
    
    @staticmethod
    async def upload_novel_file_service(
        db: AsyncSession,
        file: UploadFile,
        user_id: int
    ) -> str:
        """
        上传小说文件（流式上传）
        
        采用异步处理架构：
        1. 流式保存到临时目录（分块读取，降低内存占用）
        2. 验证文件大小（流式验证，避免内存溢出）
        3. 创建Celery异步任务
        4. 返回任务ID（前端可通过任务ID查询进度）
        
        Args:
            db: 数据库会话
            file: 上传的文件（已通过API层验证）
            user_id: 用户ID（已通过API层验证）
            
        Returns:
            任务ID字符串
        """
        logger.info(f"处理上传小说文件: filename={file.filename}, user_id={user_id}")
        
        temp_dir = os.path.join("/tmp", "novels", str(user_id))
        os.makedirs(temp_dir, exist_ok=True)
        
        timestamp = int(time.time())
        safe_filename = file.filename.replace(" ", "_").replace("/", "_")
        temp_filename = f"{timestamp}_{safe_filename}"
        temp_file_path = os.path.join(temp_dir, temp_filename)
        
        file_size = 0
        chunk_size = 1024 * 1024
        
        try:
            with open(temp_file_path, "wb") as buffer:
                while True:
                    chunk = await file.read(chunk_size)
                    if not chunk:
                        break
                    
                    file_size += len(chunk)
                    
                    if file_size > MAX_NOVEL_FILE_SIZE:
                        buffer.close()
                        if os.path.exists(temp_file_path):
                            os.remove(temp_file_path)
                        raise FileSizeExceededError(
                            detail=f"文件大小超过限制（最大{MAX_NOVEL_FILE_SIZE // (1024*1024)}MB）"
                        )
                    
                    buffer.write(chunk)
            
            if file_size == 0:
                if os.path.exists(temp_file_path):
                    os.remove(temp_file_path)
                raise FileEmptyError()
            
            logger.info(f"文件已保存到临时目录: {temp_file_path}, 大小: {file_size / (1024*1024):.2f}MB")
        except (FileSizeExceededError, FileEmptyError):
            raise
        except Exception as e:
            logger.error(f"保存临时文件失败: {str(e)}")
            raise DatabaseError(detail="保存文件失败")
        
        try:
            task = process_novel_upload_task.delay(
                user_id=user_id,
                temp_file_path=temp_file_path,
                original_filename=file.filename
            )
            task_id = task.id
            logger.info(f"已创建Celery任务: task_id={task_id}, file={file.filename}")
            
            return task_id
        except Exception as e:
            if os.path.exists(temp_file_path):
                os.remove(temp_file_path)
            logger.error(f"上传小说任务失败: {str(e)}")
            raise
    
    @staticmethod
    async def get_novels_service(
        db: AsyncSession,
        user_id: int,
        page: int = 1,
        page_size: int = 20,
        status_filter: Optional[str] = None,
        owner_id: Optional[int] = None,
        search: Optional[str] = None,
        title_filter: Optional[str] = None,
        type_filter: Optional[str] = None,
        order_by: str = "created_at",
        order: str = "desc"
    ) -> Tuple[List[Novel], int]:
        """
        获取小说列表（支持分页）- 异步版本
        
        Args:
            db: 数据库会话
            user_id: 当前用户ID
            page: 页码，从1开始
            page_size: 每页数量，最大100
            status_filter: 状态过滤（可选）
            owner_id: 所有者ID过滤（可选）
            search: 搜索关键词（可选）
            title_filter: 按标题筛选（模糊匹配，可选）
            type_filter: 按类型筛选（可选）
            order_by: 排序字段（created_at, updated_at, title）
            order: 排序方向（asc, desc）
            
        Returns:
            (小说列表, 总数) 元组
            """
        effective_user_id = owner_id if owner_id is not None else user_id
        
        base_query = select(Novel).where(
            Novel.owner_id == effective_user_id
        )
        
        query = base_query.options(
            selectinload(Novel.characters),
            selectinload(Novel.creations)
        )
        
        if status_filter:
            query = query.where(Novel.status == status_filter)
        
        if type_filter:
            query = query.where(Novel.type == type_filter)
        
        if search:
            search_pattern = f"%{search}%"
            query = query.where(
                or_(
                    Novel.title.like(search_pattern),
                    Novel.author.like(search_pattern),
                    Novel.description.like(search_pattern)
                )
            )
        
        if title_filter:
            title_pattern = f"%{title_filter}%"
            query = query.where(Novel.title.like(title_pattern))
        
        order_column = Novel.created_at
        if order_by == "updated_at":
            order_column = Novel.updated_at
        elif order_by == "title":
            order_column = Novel.title
        
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
        novels = result.scalars().all()
        
        return list(novels), total
    
    @staticmethod
    async def get_novel_by_uuid(
        db: AsyncSession,
        novel_uuid: str,
        user_id: int
    ) -> Optional[Novel]:
        """
        根据 UUID 获取小说
        """
        result = await db.execute(
            select(Novel).where(Novel.uuid == novel_uuid).options(
                selectinload(Novel.characters),
                selectinload(Novel.creations)
            )
        )
        novel = result.scalar_one_or_none()
        
        if not novel:
            return None
        
        if novel.owner_id != user_id:
            return None
        
        return novel
    
    get_novel_by_uuid_service = get_novel_by_uuid
    
    @staticmethod
    async def get_novel_by_id(
        db: AsyncSession,
        novel_id: int
    ) -> Optional[Novel]:
        """
        根据 ID 获取小说
        """
        result = await db.execute(
            select(Novel).where(Novel.novel_id == novel_id)
        )
        return result.scalar_one_or_none()
    
    @staticmethod
    async def get_user_novels(
        db: AsyncSession,
        user_id: int,
        skip: int = 0,
        limit: int = 100
    ) -> List[Novel]:
        """
        获取用户的小说列表
        """
        result = await db.execute(
            select(Novel).where(
                Novel.owner_id == user_id
            ).order_by(
                Novel.created_at.desc()
            ).offset(skip).limit(limit)
        )
        return result.scalars().all()
    
    @staticmethod
    async def count_user_novels(db: AsyncSession, user_id: int) -> int:
        """
        统计用户的小说数量
        """
        result = await db.execute(
            select(Novel).where(Novel.owner_id == user_id)
        )
        return len(result.scalars().all())
    
    @staticmethod
    async def create_novel(
        db: AsyncSession,
        title: str,
        user_id: int,
        description: Optional[str] = None
    ) -> Novel:
        """
        创建小说
        """
        novel = Novel(
            uuid=str(uuid.uuid4()),
            title=title,
            description=description,
            owner_id=user_id
        )
        db.add(novel)
        await db.commit()
        await db.refresh(novel)
        return novel
    
    @staticmethod
    async def update_novel(
        db: AsyncSession,
        novel_id: int,
        **update_data
    ) -> Optional[Novel]:
        """
        更新小说
        """
        result = await db.execute(
            select(Novel).where(Novel.novel_id == novel_id)
        )
        novel = result.scalar_one_or_none()
        
        if not novel:
            return None
        
        for key, value in update_data.items():
            if hasattr(novel, key):
                setattr(novel, key, value)
        
        await db.commit()
        await db.refresh(novel)
        return novel
    
    @staticmethod
    async def delete_novel(db: AsyncSession, novel_id: int) -> bool:
        """
        删除小说
        """
        result = await db.execute(
            select(Novel).where(Novel.novel_id == novel_id)
        )
        novel = result.scalar_one_or_none()
        
        if not novel:
            return False
        
        await db.delete(novel)
        await db.commit()
        return True
    
    create_project_service = create_novel
    update_novel_service = update_novel
    delete_novel_service = delete_novel


class ChapterAsyncService:
    """章节服务类 - 异步版本"""
    
    @staticmethod
    async def get_chapter_by_uuid(
        db: AsyncSession,
        chapter_uuid: str,
        user_id: int
    ) -> Optional[Chapter]:
        """
        根据 UUID 获取章节
        """
        result = await db.execute(
            select(Chapter).where(Chapter.uuid == chapter_uuid)
        )
        chapter = result.scalar_one_or_none()
        
        if not chapter:
            return None
        
        result = await db.execute(
            select(Novel).where(Novel.novel_id == chapter.novel_id)
        )
        novel = result.scalar_one_or_none()
        
        if not novel or novel.owner_id != user_id:
            return None
        
        return chapter
    
    get_chapter_by_uuid_service = get_chapter_by_uuid
    
    @staticmethod
    async def get_chapter_by_id(
        db: AsyncSession,
        chapter_id: int
    ) -> Optional[Chapter]:
        """
        根据 ID 获取章节
        """
        result = await db.execute(
            select(Chapter).where(Chapter.chapter_id == chapter_id)
        )
        return result.scalar_one_or_none()
    
    @staticmethod
    async def get_chapters_by_novel(
        db: AsyncSession,
        novel_id: int,
        skip: int = 0,
        limit: int = 100
    ) -> List[Chapter]:
        """
        获取小说的章节列表
        """
        result = await db.execute(
            select(Chapter).where(
                Chapter.novel_id == novel_id
            ).order_by(
                Chapter.order.asc()
            ).offset(skip).limit(limit)
        )
        return result.scalars().all()
    
    @staticmethod
    async def get_novel_chapters_service(
        db: AsyncSession,
        novel_id: int,
        user_id: int,
        page: int = 1,
        page_size: int = 20
    ) -> Tuple[List[Chapter], int]:
        """
        获取小说章节列表（支持分页）
        
        Args:
            db: 数据库会话
            novel_id: 小说ID
            user_id: 当前用户ID（用于验证权限）
            page: 页码，从1开始
            page_size: 每页数量
            
        Returns:
            (章节列表, 总数) 元组
        """
        result = await db.execute(
            select(Novel).where(Novel.novel_id == novel_id)
        )
        novel = result.scalar_one_or_none()
        
        if not novel or novel.owner_id != user_id:
            return [], 0
        
        base_query = select(Chapter).where(
            Chapter.novel_id == novel_id
        ).options(selectinload(Chapter.creation))
        
        query = base_query.order_by(Chapter.chapter_number.asc())
        
        count_query = select(func.count()).select_from(base_query.subquery())
        count_result = await db.execute(count_query)
        total = count_result.scalar()
        
        skip = (page - 1) * page_size
        query = query.offset(skip).limit(page_size)
        
        result = await db.execute(query)
        chapters = result.scalars().all()
        
        return list(chapters), total
    
    @staticmethod
    async def count_chapters(db: AsyncSession, novel_id: int) -> int:
        """
        统计章节数量
        """
        result = await db.execute(
            select(Chapter).where(Chapter.novel_id == novel_id)
        )
        return len(result.scalars().all())
    
    @staticmethod
    async def create_chapter(
        db: AsyncSession,
        novel_id: int,
        title: str,
        order: int,
        content: Optional[str] = None
    ) -> Chapter:
        """
        创建章节
        """
        chapter = Chapter(
            uuid=str(uuid.uuid4()),
            novel_id=novel_id,
            title=title,
            order=order,
            content=content
        )
        db.add(chapter)
        await db.commit()
        await db.refresh(chapter)
        return chapter
    
    @staticmethod
    async def update_chapter(
        db: AsyncSession,
        chapter_id: int,
        **update_data
    ) -> Optional[Chapter]:
        """
        更新章节
        """
        result = await db.execute(
            select(Chapter).where(Chapter.chapter_id == chapter_id)
        )
        chapter = result.scalar_one_or_none()
        
        if not chapter:
            return None
        
        for key, value in update_data.items():
            if hasattr(chapter, key):
                setattr(chapter, key, value)
        
        await db.commit()
        await db.refresh(chapter)
        return chapter
    
    @staticmethod
    async def delete_chapter(db: AsyncSession, chapter_id: int) -> bool:
        """
        删除章节
        """
        result = await db.execute(
            select(Chapter).where(Chapter.chapter_id == chapter_id)
        )
        chapter = result.scalar_one_or_none()
        
        if not chapter:
            return False
        
        await db.delete(chapter)
        await db.commit()
        return True
    
    create_chapter_service = create_chapter
    update_chapter_service = update_chapter
    delete_chapter_service = delete_chapter


NovelAsyncService.get_chapter_by_uuid_service = ChapterAsyncService.get_chapter_by_uuid_service
NovelAsyncService.get_novel_chapters_service = ChapterAsyncService.get_novel_chapters_service
NovelAsyncService.create_chapter_service = ChapterAsyncService.create_chapter
NovelAsyncService.update_chapter_service = ChapterAsyncService.update_chapter
NovelAsyncService.delete_chapter_service = ChapterAsyncService.delete_chapter
