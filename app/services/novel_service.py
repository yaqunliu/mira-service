import os
import time
from typing import List, Optional, Dict, Any, Tuple
from sqlalchemy.orm import Session, selectinload
from sqlalchemy import desc, asc
from fastapi import UploadFile
from app.models.novel import Novel
from app.models.chapter import Chapter
from app.tasks.novel_tasks import process_novel_upload_task
from app.core.logger import logger
from app.core.exceptions import (
    FileSizeExceededError,
    FileEmptyError,
    DatabaseError,
    NotFoundError,
    PermissionError
)
from app.schemas.novel import NovelUpdate
from app.schemas.chapter import ChapterUpdate

# 文件大小限制：50MB
MAX_NOVEL_FILE_SIZE = 50 * 1024 * 1024


class NovelService:
    """小说服务类"""
    
    @staticmethod
    async def upload_novel_file_service(
        db: Session,
        file: UploadFile,
        user_id: int
    ) -> str:
        """
        上传小说文件（流式上传）
        
        采用同步接收 + 异步处理的架构：
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
            
        Raises:
            HTTPException: 当文件处理出错时
        """
        logger.info(f"处理上传小说文件: filename={file.filename}, user_id={user_id}")
        
        temp_dir = os.path.join("/tmp", "novels", str(user_id))
        os.makedirs(temp_dir, exist_ok=True)
        
        # 生成临时文件名：{timestamp}_{filename}
        timestamp = int(time.time())
        safe_filename = file.filename.replace(" ", "_").replace("/", "_")
        temp_filename = f"{timestamp}_{safe_filename}"
        temp_file_path = os.path.join(temp_dir, temp_filename)
        
        # 2. 流式保存文件到临时目录，同时验证文件大小
        file_size = 0
        chunk_size = 1024 * 1024  # 1MB chunks for streaming
        
        try:
            with open(temp_file_path, "wb") as buffer:
                while True:
                    chunk = await file.read(chunk_size)
                    if not chunk:
                        break
                    
                    file_size += len(chunk)
                    
                    # 检查文件大小限制
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
        
        # 3. 任务投递
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
            # 如果任务创建失败，清理临时文件
            if os.path.exists(temp_file_path):
                os.remove(temp_file_path)
            logger.error(f"上传小说任务失败: {str(e)}")
            raise DatabaseError(detail="上传小说任务失败")
    
    @staticmethod
    def get_novels_service(
        db: Session,
        user_id: int,
        page: int = 1,
        page_size: int = 20,
        status_filter: Optional[str] = None,
        owner_id: Optional[int] = None,
        search: Optional[str] = None,
        order_by: str = "created_at",
        order: str = "desc"
    ) -> Tuple[List[Novel], int]:
        """
        获取小说列表
        
        支持功能：
        - 分页查询
        - 状态过滤（status）
        - 所有者过滤（owner_id）
        - 关键词搜索（标题或作者）
        - 排序（按创建时间、更新时间、标题）
        
        Args:
            db: 数据库会话
            user_id: 当前用户ID（已通过API层验证）
            page: 页码，从1开始
            page_size: 每页数量，最大100
            status_filter: 过滤状态
            owner_id: 过滤所有者ID（如果未指定，默认只返回当前用户的小说）
            search: 搜索关键词
            order_by: 排序字段
            order: 排序方向（asc/desc）
            
        Returns:
            (小说列表, 总数) 元组
        """
        try:
            # 构建查询
            query = db.query(Novel)
            
            # 默认只返回当前用户的小说（除非指定了 owner_id）
            if owner_id is None:
                query = query.filter(Novel.owner_id == user_id)
            else:
                # 如果指定了 owner_id，检查权限（只有管理员可以查看其他用户的小说）
                # 这里简化处理，如果用户指定了 owner_id，允许查询（实际项目中可能需要权限检查）
                query = query.filter(Novel.owner_id == owner_id)
            
            # 状态过滤
            if status_filter:
                query = query.filter(Novel.status == status_filter)
            
            # 关键词搜索（标题或作者）
            if search:
                search_pattern = f"%{search}%"
                query = query.filter(
                    (Novel.title.like(search_pattern)) | 
                    (Novel.author.like(search_pattern))
                )
            
            # 排序
            order_column = None
            if order_by == "created_at":
                order_column = Novel.created_at
            elif order_by == "updated_at":
                order_column = Novel.updated_at
            elif order_by == "title":
                order_column = Novel.title
            else:
                order_column = Novel.created_at  # 默认按创建时间
            
            if order.lower() == "asc":
                query = query.order_by(asc(order_column))
            else:
                query = query.order_by(desc(order_column))
            
            # 计算总数
            total = query.count()
            
            # 分页（使用 selectinload 预加载关联数据，避免 N+1 查询问题）
            skip = (page - 1) * page_size
            novels = query.options(
                selectinload(Novel.creations),
                selectinload(Novel.characters),
                selectinload(Novel.chapters)
            ).offset(skip).limit(page_size).all()
            
            logger.info(f"查询小说列表: 用户={user_id}, 页码={page}, 每页={page_size}, 总数={total}, 返回={len(novels)}")
            
            return novels, total
            
        except Exception as e:
            logger.error(f"查询小说列表失败: {str(e)}", exc_info=True)
            raise DatabaseError(detail=f"查询小说列表失败: {str(e)}")
    
    @staticmethod
    def get_novel_by_id_service(
        db: Session,
        novel_id: int,
        user_id: int
    ) -> Novel:
        """
        根据ID获取小说详情
        
        Args:
            db: 数据库会话
            novel_id: 小说ID
            user_id: 当前用户ID（已通过API层验证）
            
        Returns:
            小说对象（包含章节信息）
            
        Raises:
            NotFoundError: 当小说不存在时
            PermissionError: 当用户无权限时
        """
        logger.info(f"获取小说详情: novel_id={novel_id}, user_id={user_id}")
        
        # 查询小说（使用 selectinload 预加载关联数据，避免 N+1 查询问题）
        novel = db.query(Novel).options(
            selectinload(Novel.chapters),
            selectinload(Novel.creations),
            selectinload(Novel.characters)
        ).filter(Novel.novel_id == novel_id).first()
        
        if not novel:
            raise NotFoundError(detail="小说不存在")
        
        # 验证权限
        if novel.owner_id != user_id:
            raise PermissionError(detail="无权限访问该小说")
        
        logger.info(
            f"成功获取小说详情: novel_id={novel_id}, title={novel.title}, "
            f"chapters_count={len(novel.chapters)}, "
            f"creations_count={len(novel.creations)}, "
            f"characters_count={len(novel.characters)}"
        )
        return novel
    
    @staticmethod
    def get_novel_chapters_service(
        db: Session,
        novel_id: int,
        user_id: int
    ) -> List[Chapter]:
        """
        获取小说章节列表
        
        Args:
            db: 数据库会话
            novel_id: 小说ID
            user_id: 当前用户ID（已通过API层验证）
            
        Returns:
            章节对象列表
            
        Raises:
            HTTPException: 当小说不存在或用户无权限时
        """
        # TODO: 实现获取章节列表逻辑
        from app.core.exceptions import BaseServiceException
        raise BaseServiceException("功能尚未实现", status_code=501)
    
    @staticmethod
    def delete_novel_service(
        db: Session,
        novel_id: int,
        user_id: int
    ) -> None:
        """
        删除小说
        
        Args:
            db: 数据库会话
            novel_id: 小说ID
            user_id: 当前用户ID（已通过API层验证）
            
        Returns:
            None
            
        Raises:
            NotFoundError: 当小说不存在时
            PermissionError: 当用户无权限时
            DatabaseError: 当删除失败时
        """
        from app.core.exceptions import NotFoundError, PermissionError, DatabaseError
        
        logger.info(f"删除小说: novel_id={novel_id}, user_id={user_id}")
        
        # 查询小说
        novel = db.query(Novel).filter(Novel.novel_id == novel_id).first()
        
        if not novel:
            raise NotFoundError(detail="小说不存在")
        
        # 验证权限
        if novel.owner_id != user_id:
            raise PermissionError(detail="无权限删除该小说")
        
        try:
            # 删除小说（级联删除相关的 chapters）
            # chapters 关系已设置 cascade="all, delete-orphan"，会自动删除
            db.delete(novel)
            db.commit()
            
            logger.info(f"小说已删除: novel_id={novel_id}, user_id={user_id}")
        except Exception as e:
            logger.error(f"删除小说失败: {str(e)}", exc_info=True)
            db.rollback()
            raise DatabaseError(detail=f"删除小说失败: {str(e)}") from e
    
    @staticmethod
    def update_novel_service(
        db: Session,
        novel_id: int,
        novel_update: NovelUpdate,
        user_id: int
    ) -> Novel:
        """
        更新小说信息
        
        Args:
            db: 数据库会话
            novel_id: 小说ID
            novel_update: 更新数据
            user_id: 当前用户ID（已通过API层验证）
            
        Returns:
            更新后的小说对象
            
        Raises:
            NotFoundError: 当小说不存在时
            PermissionError: 当用户无权限时
            DatabaseError: 当更新失败时
        """
        logger.info(f"更新小说: novel_id={novel_id}, user_id={user_id}, update_data={novel_update.model_dump(exclude_unset=True)}")
        
        # 查询小说
        novel = db.query(Novel).filter(Novel.novel_id == novel_id).first()
        
        if not novel:
            raise NotFoundError(detail="小说不存在")
        
        # 验证权限
        if novel.owner_id != user_id:
            raise PermissionError(detail="无权限修改该小说")
        
        try:
            # 更新小说属性（只更新提供的字段）
            update_data = novel_update.model_dump(exclude_unset=True)
            for field, value in update_data.items():
                setattr(novel, field, value)
            
            db.commit()
            db.refresh(novel)
            
            logger.info(f"小说已更新: novel_id={novel_id}, user_id={user_id}")
            return novel
        except Exception as e:
            logger.error(f"更新小说失败: {str(e)}", exc_info=True)
            db.rollback()
            raise DatabaseError(detail=f"更新小说失败: {str(e)}") from e
    
    @staticmethod
    def update_chapter_service(
        db: Session,
        chapter_id: int,
        chapter_update: ChapterUpdate,
        user_id: int
    ) -> Chapter:
        """
        更新章节信息
        
        Args:
            db: 数据库会话
            chapter_id: 章节ID
            chapter_update: 更新数据
            user_id: 当前用户ID（已通过API层验证）
            
        Returns:
            更新后的章节对象
            
        Raises:
            NotFoundError: 当章节不存在时
            PermissionError: 当用户无权限时
            DatabaseError: 当更新失败时
        """
        logger.info(f"更新章节: chapter_id={chapter_id}, user_id={user_id}, update_data={chapter_update.model_dump(exclude_unset=True)}")
        
        # 查询章节（同时加载关联的小说以验证权限）
        chapter = db.query(Chapter).filter(Chapter.chapter_id == chapter_id).first()
        
        if not chapter:
            raise NotFoundError(detail="章节不存在")
        
        # 查询小说以验证权限
        novel = db.query(Novel).filter(Novel.novel_id == chapter.novel_id).first()
        if not novel:
            raise NotFoundError(detail="章节所属的小说不存在")
        
        # 验证权限
        if novel.owner_id != user_id:
            raise PermissionError(detail="无权限修改该章节")
        
        try:
            # 更新章节属性（只更新提供的字段）
            update_data = chapter_update.model_dump(exclude_unset=True)
            for field, value in update_data.items():
                setattr(chapter, field, value)
            
            db.commit()
            db.refresh(chapter)
            
            logger.info(f"章节已更新: chapter_id={chapter_id}, user_id={user_id}")
            return chapter
        except Exception as e:
            logger.error(f"更新章节失败: {str(e)}", exc_info=True)
            db.rollback()
            raise DatabaseError(detail=f"更新章节失败: {str(e)}") from e

