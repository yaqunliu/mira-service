from fastapi import APIRouter, Depends, status, UploadFile, File, Query, HTTPException
from sqlalchemy.orm import Session
from typing import Optional
from app.api.deps import get_db, get_current_user
from app.models.user import User
from app.services.novel_service import NovelService
from app.core.logger import logger
from app.core.exceptions import BaseServiceException
from app.utils.response import success_response
from app.schemas.novel import NovelUpdate
from app.schemas.chapter import ChapterUpdate

router = APIRouter()


@router.post("/upload", status_code=status.HTTP_202_ACCEPTED)
async def upload_novel(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user)
):
    """
    上传小说文件（流式上传）
    
    采用同步接收 + 异步处理的架构：
    1. 验证文件格式和大小（流式验证，避免内存溢出）
    2. 流式保存到临时目录（分块读取，降低内存占用）
    3. 创建Celery异步任务
    4. 返回任务ID（前端可通过任务ID查询进度）
    
    注意：
    - 使用流式上传，按1MB分块读取，避免大文件占用过多内存
    - 上传完成后，通过 GET /api/v1/tasks/{task_id} 查询处理进度
    """
    # 参数验证
    if not file.filename:
        logger.warning("上传文件缺少文件名")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="文件名不能为空"
        )
    
    if not file.filename.endswith('.txt'):
        logger.warning(f"不支持的文件格式: {file.filename}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="仅支持.txt格式的小说文件"
        )
    
    # 获取用户ID
    try:
        user_id = user.user_id
        logger.info(f"当前用户ID: {user_id}")
    except Exception as e:
        logger.error(f"获取用户信息失败: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="获取用户信息失败"
        )
    
    # 调用服务层处理业务逻辑
    try:
        task_id = await NovelService.upload_novel_file_service(
            db=db,
            file=file,
            user_id=user_id
        )
        
        # 转换为响应格式
        return success_response(
            data={
                "task_id": task_id,
                "status": "processing"
            },
            message="文件已接收，正在处理中"
        )
    except BaseServiceException as e:
        # 将业务异常转换为HTTP异常
        raise HTTPException(
            status_code=e.status_code,
            detail=e.detail
        )


@router.get("/", response_model=dict)
async def get_novels(
    page: int = Query(1, ge=1, description="页码，从1开始"),
    page_size: int = Query(20, ge=1, le=100, description="每页数量，最大100"),
    status: Optional[str] = Query(None, description="过滤状态：uploaded, processing, completed, failed"),
    owner_id: Optional[int] = Query(None, description="过滤所有者ID"),
    search: Optional[str] = Query(None, description="搜索关键词（标题或作者）"),
    title: Optional[str] = Query(None, description="按标题筛选（模糊匹配）"),
    order_by: str = Query("created_at", description="排序字段：created_at, updated_at, title"),
    order: str = Query("desc", description="排序方向：asc, desc"),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user)
):
    """
    获取小说列表
    
    支持功能：
    - 分页查询
    - 状态过滤（status）
    - 所有者过滤（owner_id）
    - 关键词搜索（标题或作者）
    - 按标题筛选（title）
    - 排序（按创建时间、更新时间、标题）
    
    Args:
        page: 页码，从1开始
        page_size: 每页数量，最大100
        status: 过滤状态
        owner_id: 过滤所有者ID（如果未指定，默认只返回当前用户的小说）
        search: 搜索关键词
        title: 按标题筛选（模糊匹配）
        order_by: 排序字段
        order: 排序方向（asc/desc）
        db: 数据库会话
        user: 当前用户
        
    Returns:
        包含小说列表和分页信息的字典
    """
    # 调用服务层获取数据
    try:
        novels, total = NovelService.get_novels_service(
            db=db,
            user_id=user.user_id,
            page=page,
            page_size=page_size,
            status_filter=status,
            owner_id=owner_id,
            search=search,
            title_filter=title,
            order_by=order_by,
            order=order
        )
    except BaseServiceException as e:
        # 将业务异常转换为HTTP异常
        raise HTTPException(
            status_code=e.status_code,
            detail=e.detail
        )
    
    # 转换为响应格式
    total_pages = (total + page_size - 1) // page_size
    items = []
    for novel in novels:
        # 构建 creations 列表（ID列表），按ID降序排序
        creation_ids = sorted([creation.creation_id for creation in novel.creations], reverse=True)
        
        # 构建 characters 列表（ID列表），按ID降序排序
        character_ids = sorted([character.character_id for character in novel.characters], reverse=True)
        
        items.append({
            "novel_id": novel.novel_id,
            "title": novel.title,
            "author": novel.author,
            "chapter_count": novel.chapter_count,
            "status": novel.status,
            "owner_id": novel.owner_id,
            "created_at": novel.created_at,
            "updated_at": novel.updated_at,
            "creation_ids": creation_ids,
            "character_ids": character_ids,
        })
    
    return success_response(
        data={
            "items": items,
            "total": total,
            "page": page,
            "page_size": page_size,
            "total_pages": total_pages,
            "has_next": page < total_pages,
            "has_prev": page > 1
        }
    )


@router.get("/{novel_id}")
async def get_novel(
    novel_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user)
):
    """
    根据ID获取小说详情
    
    注意：章节列表需要通过 GET /{novel_id}/chapters 接口单独获取（支持分页）
    """
    try:
        novel = NovelService.get_novel_by_id_service(db=db, novel_id=novel_id, user_id=user.user_id)
    except BaseServiceException as e:
        # 将业务异常转换为HTTP异常
        raise HTTPException(
            status_code=e.status_code,
            detail=e.detail
        )
    
    # 构建创作列表（关系查询已自动过滤已删除的），按creation_id降序排序
    creations = [
        {
            "creation_id": creation.creation_id,
            "title": creation.title,
            "status": creation.status,
            "chapter_id": creation.chapter_id,
            "video_url": creation.video_url,
            "audio_url": creation.audio_url,
            "subtitle_url": creation.subtitle_url,
            "voice_id": creation.voice_id,
            "voice_speed": creation.voice_speed,
            "current_task_id": creation.current_task_id,
            "created_at": creation.created_at,
            "updated_at": creation.updated_at,
        }
        for creation in sorted(novel.creations, key=lambda c: c.creation_id, reverse=True)
    ]
    
    # 构建角色列表，按character_id降序排序
    characters = [
        {
            "character_id": character.character_id,
            "name": character.name,
            "status": character.status,
            "basic_info": character.basic_info,
            "appearance": character.appearance,
            "body": character.body,
            "hair": character.hair,
            "clothing": character.clothing,
            "tags": character.tags,
            "image_prompt": character.image_prompt,
            "visual_style": character.visual_style,
            "image_url": character.image_url,
            "creation_id": character.creation_id,
            "created_at": character.created_at,
            "updated_at": character.updated_at,
        }
        for character in sorted(novel.characters, key=lambda c: c.character_id, reverse=True)
    ]
    
    # 将Novel对象转换为响应格式
    return success_response(
        data={
            "novel_id": novel.novel_id,
            "title": novel.title,
            "author": novel.author,
            "chapter_count": novel.chapter_count,
            "status": novel.status,
            "owner_id": novel.owner_id,
            "task_id": novel.task_id,
            "created_at": novel.created_at,
            "updated_at": novel.updated_at,
            "creations": creations,
            "characters": characters,
        },
        message="小说获取成功"
    )


@router.get("/{novel_id}/chapters/{chapter_id}")
async def get_chapter(
    novel_id: int,
    chapter_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user)
):
    """
    根据ID获取章节详情
    
    返回章节的完整信息，包括标题、内容URL、字数等
    """
    try:
        chapter = NovelService.get_chapter_by_id_service(
            db=db,
            novel_id=novel_id,
            chapter_id=chapter_id,
            user_id=user.user_id
        )
    except BaseServiceException as e:
        # 将业务异常转换为HTTP异常
        raise HTTPException(
            status_code=e.status_code,
            detail=e.detail
        )
    
    # 转换为响应格式
    return success_response(
        data={
            "chapter_id": chapter.chapter_id,
            "title": chapter.title,
            "chapter_number": chapter.chapter_number,
            "word_count": chapter.word_count,
            "preview": chapter.preview,
            "content_url": chapter.content_url,
            "novel_id": chapter.novel_id,
            "created_at": chapter.created_at,
        },
        message="章节获取成功"
    )


@router.get("/{novel_id}/chapters")
async def get_novel_chapters(
    novel_id: int,
    page: int = Query(1, ge=1, description="页码，从1开始"),
    page_size: int = Query(10, ge=1, le=100, description="每页数量，默认10，最大100"),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user)
):
    """
    获取小说章节列表（分页）
    
    支持分页查询，默认每页10个章节
    """
    try:
        chapters, total = NovelService.get_novel_chapters_service(
            db=db, 
            novel_id=novel_id, 
            user_id=user.user_id,
            page=page,
            page_size=page_size
        )
    except BaseServiceException as e:
        # 将业务异常转换为HTTP异常
        raise HTTPException(
            status_code=e.status_code,
            detail=e.detail
        )
    
    # 转换为响应格式
    total_pages = (total + page_size - 1) // page_size
    items = [
        {
            "chapter_id": chapter.chapter_id,
            "title": chapter.title,
            "chapter_number": chapter.chapter_number,
            "word_count": chapter.word_count,
            "preview": chapter.preview,
            "content_url": chapter.content_url,
            "created_at": chapter.created_at,
        }
        for chapter in chapters
    ]
    
    return success_response(
        data={
            "items": items,
            "total": total,
            "page": page,
            "page_size": page_size,
            "total_pages": total_pages,
            "has_next": page < total_pages,
            "has_prev": page > 1
        },
        message="章节列表获取成功"
    )


@router.put("/{novel_id}")
async def update_novel(
    novel_id: int,
    novel_update: NovelUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user)
):
    """
    更新小说信息
    
    支持更新字段：
    - title: 小说标题
    - author: 作者
    - status: 状态
    """
    try:
        novel = NovelService.update_novel_service(
            db=db,
            novel_id=novel_id,
            novel_update=novel_update,
            user_id=user.user_id
        )
    except BaseServiceException as e:
        # 将业务异常转换为HTTP异常
        raise HTTPException(
            status_code=e.status_code,
            detail=e.detail
        )
    
    # 转换为响应格式
    return success_response(
        data={
            "novel_id": novel.novel_id,
            "title": novel.title,
            "author": novel.author,
            "status": novel.status,
            "updated_at": novel.updated_at,
        },
        message="小说更新成功"
    )


@router.put("/{novel_id}/chapters/{chapter_id}")
async def update_chapter(
    novel_id: int,
    chapter_id: int,
    chapter_update: ChapterUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user)
):
    """
    更新章节信息
    
    支持更新字段：
    - title: 章节标题
    """
    try:
        chapter = NovelService.update_chapter_service(
            db=db,
            chapter_id=chapter_id,
            chapter_update=chapter_update,
            user_id=user.user_id
        )
        
        # 验证章节是否属于指定的小说
        if chapter.novel_id != novel_id:
            raise HTTPException(
                status_code=400,
                detail="章节不属于指定的小说"
            )
    except BaseServiceException as e:
        # 将业务异常转换为HTTP异常
        raise HTTPException(
            status_code=e.status_code,
            detail=e.detail
        )
    
    # 转换为响应格式
    return success_response(
        data={
            "chapter_id": chapter.chapter_id,
            "title": chapter.title,
            "novel_id": chapter.novel_id,
            "chapter_number": chapter.chapter_number,
        },
        message="章节更新成功"
    )


@router.delete("/{novel_id}/chapters/{chapter_id}")
async def delete_chapter(
    novel_id: int,
    chapter_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user)
):
    """
    删除章节
    
    注意：
    - 只有章节所属小说的所有者可以删除
    - 删除章节时会同时删除相关的创作（Creation）
    """
    try:
        # 先验证章节是否属于指定的小说（排除已删除的）
        from app.models.chapter import Chapter
        chapter = db.query(Chapter).filter(
            Chapter.chapter_id == chapter_id,
            Chapter.deleted_at.is_(None)
        ).first()
        if not chapter:
            raise HTTPException(
                status_code=404,
                detail="章节不存在"
            )
        if chapter.novel_id != novel_id:
            raise HTTPException(
                status_code=400,
                detail="章节不属于指定的小说"
            )
        
        # 调用服务层删除章节
        NovelService.delete_chapter_service(
            db=db,
            chapter_id=chapter_id,
            user_id=user.user_id
        )
    except HTTPException:
        raise
    except BaseServiceException as e:
        # 将业务异常转换为HTTP异常
        raise HTTPException(
            status_code=e.status_code,
            detail=e.detail
        )
    
    # 返回删除成功的响应格式
    return success_response(
        data={"chapter_id": chapter_id},
        message="章节删除成功"
    )


@router.delete("/{novel_id}")
async def delete_novel(
    novel_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user)
):
    """
    删除小说
    
    注意：当实现后，需要在API层构造删除成功的响应
    """
    try:
        NovelService.delete_novel_service(db=db, novel_id=novel_id, user_id=user.user_id)
    except BaseServiceException as e:
        # 将业务异常转换为HTTP异常
        raise HTTPException(
            status_code=e.status_code,
            detail=e.detail
        )
    # 返回删除成功的响应格式
    return success_response(
        data=None,
        message="删除成功"
    )
