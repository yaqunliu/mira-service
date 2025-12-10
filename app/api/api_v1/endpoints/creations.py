from typing import Optional, List
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.deps import get_db, get_current_user
from app.models.user import User
from app.models.creation import Creation
from app.models.shot import Shot
from app.schemas.creation import CreationCreate, Creation as CreationSchema, CreationStatus
from app.services.creation_service import CreationService
from app.core.exceptions import BaseServiceException
from app.utils.response import success_response
from app.tasks.shot_task import generate_creation_shots_task, generate_shots_by_ids_task
from app.tasks.full_generation_task import generate_full_video_task
from app.tasks.creation_task import playbook_generation_task
from app.core.logger import logger

router = APIRouter()


@router.post("/create")
async def create_creation_service(
    creation_data: CreationCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """
    创建新的视频创作项目或继续已存在的创作

    参数说明：
    - 如果提供了 creation_id：继续已存在但未成功的创作（不需要提供 novel_id 和 chapter_id）
    - 如果没有提供 creation_id：创建新的创作（必须提供 novel_id 和 chapter_id）

    参数验证：
    - 验证 novel_id 和 chapter_id 是否有效（创建新创作时）
    - 验证用户权限
    """
    # 获取用户ID
    try:
        user_id = user.user_id
    except Exception as e:
        raise HTTPException(status_code=500, detail="获取用户信息失败")

    # 验证参数：如果提供了 creation_id，则不需要 novel_id 和 chapter_id；否则必须提供
    if creation_data.creation_id:
        if creation_data.novel_id is not None or creation_data.chapter_id is not None:
            logger.warning(
                f"提供了 creation_id={creation_data.creation_id}，但同时也提供了 "
                f"novel_id={creation_data.novel_id} 和 chapter_id={creation_data.chapter_id}，"
                f"将忽略 novel_id 和 chapter_id"
            )
    else:
        if not creation_data.novel_id or not creation_data.chapter_id:
            raise HTTPException(
                status_code=400,
                detail="创建新创作时必须提供 novel_id 和 chapter_id，或提供 creation_id 继续已存在的创作"
            )

    # 将UUID转换为ID（如果需要）
    novel_id_int = None
    chapter_id_int = None
    creation_id_int = None
    
    if creation_data.novel_id:
        # 通过UUID获取novel_id
        from app.services.novel_service import NovelService
        novel = NovelService.get_novel_by_uuid_service(db=db, novel_uuid=creation_data.novel_id, user_id=user_id)
        novel_id_int = novel.novel_id
    
    if creation_data.chapter_id:
        # 通过UUID获取chapter_id
        from app.services.novel_service import NovelService
        chapter = NovelService.get_chapter_by_uuid_service(db=db, chapter_uuid=creation_data.chapter_id, user_id=user_id)
        chapter_id_int = chapter.chapter_id
    
    if creation_data.creation_id:
        # 通过UUID获取creation_id
        creation = CreationService.get_creation_simple_by_uuid_service(db=db, creation_uuid=creation_data.creation_id)
        if creation:
            creation_id_int = creation.creation_id

    # 验证 narration_mode 参数
    narration_mode = creation_data.narration_mode or "original"
    if narration_mode not in ["original", "rewrite"]:
        raise HTTPException(
            status_code=400,
            detail="narration_mode 必须是 'original'（原文模式）或 'rewrite'（爽文模式）"
        )
    
    # 构建 extra_data（包含 narration_mode 和模型配置）
    extra_data = creation_data.extra_data or {}
    if narration_mode:
        extra_data["narration_mode"] = narration_mode
    
    # 调用服务层处理业务逻辑
    try:
        creation_id = CreationService.create_creation_service(
            db=db,
            novel_id=novel_id_int,
            chapter_id=chapter_id_int,
            user_id=user_id,
            creation_id=creation_id_int,
            narration_mode=narration_mode,
            extra_data=extra_data,
        )

        # 获取创建的创作对象，返回UUID
        creation = CreationService.get_creation_simple_service(db=db, creation_id=creation_id)
        creation_uuid = creation.uuid if creation else None
        
        # 转换为响应格式
        return success_response(
            data={"creation_id": creation_id, "uuid": creation_uuid},
            message="创作初始化成功"
        )
    except BaseServiceException as e:
        # 将业务异常转换为HTTP异常
        raise HTTPException(status_code=e.status_code, detail=e.detail)


@router.get("/")
async def get_creations_service(
    page: int = Query(1, ge=1, description="页码，从1开始"),
    page_size: int = Query(20, ge=1, le=100, description="每页数量，最大100"),
    status: Optional[str] = Query(None, description="过滤状态"),
    title: Optional[str] = Query(None, description="按标题筛选（模糊匹配）"),
    order_by: str = Query(
        "created_at", description="排序字段：created_at, updated_at, title"
    ),
    order: str = Query("desc", description="排序方向：asc, desc"),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """
    获取创作项目列表（支持分页）

    支持功能：
    - 分页查询
    - 状态过滤（status）
    - 按标题筛选（title）
    - 排序（按创建时间、更新时间、标题）

    Args:
        page: 页码，从1开始
        page_size: 每页数量，最大100
        status: 过滤状态
        title: 按标题筛选（模糊匹配）
        order_by: 排序字段
        order: 排序方向（asc/desc）
        db: 数据库会话
        user: 当前用户

    Returns:
        包含创作列表和分页信息的字典
    """
    try:
        creations, total = CreationService.get_creations_service(
            db=db,
            user_id=user.user_id,
            page=page,
            page_size=page_size,
            status_filter=status,
            title_filter=title,
            order_by=order_by,
            order=order,
        )

        # 转换为响应格式
        total_pages = (total + page_size - 1) // page_size if total > 0 else 0
        # 手动序列化，完全绕过 Pydantic 对关联字段的访问，避免触发 novel.chapters 查询
        items = []
        for creation in creations:
            novel = creation.novel
            chapter = creation.chapter
            scenes = creation.scenes or []

            creation_data = {
                "creation_id": creation.creation_id,
                "uuid": creation.uuid,
                "title": creation.title,
                "status": creation.status,
                "video_url": creation.video_url,
                "audio_url": creation.audio_url,
                "subtitle_url": creation.subtitle_url,
                "voice_id": creation.voice_id,
                "voice_speed": creation.voice_speed,
                "current_task_id": creation.current_task_id,
                "created_at": creation.created_at,
                "updated_at": creation.updated_at,
                "owner_id": creation.owner_id,
                "novel_id": creation.novel_id,
                "chapter_id": creation.chapter_id,
                "extra_data": creation.extra_data,
                "character_ids": creation.character_ids,
            }

            if novel:
                creation_data["novel"] = {
                    "novel_id": novel.novel_id,
                    "uuid": novel.uuid,
                    "title": novel.title,
                    "author": novel.author,
                    "chapter_count": novel.chapter_count,
                    "status": novel.status,
                    "owner_id": novel.owner_id,
                    "created_at": novel.created_at,
                    "updated_at": novel.updated_at,
                }
                creation_data["novel_uuid"] = novel.uuid

            if chapter:
                creation_data["chapter"] = {
                    "chapter_id": chapter.chapter_id,
                    "uuid": chapter.uuid,
                    "title": chapter.title,
                    "content_url": chapter.content_url,
                    "chapter_number": chapter.chapter_number,
                    "word_count": chapter.word_count,
                    "preview": chapter.preview,
                    "novel_id": chapter.novel_id,
                    "created_at": chapter.created_at,
                }
                creation_data["chapter_uuid"] = chapter.uuid

            if scenes:
                creation_data["scenes"] = []
                for scene in scenes:
                    shots = scene.shots or []
                    scene_data = {
                        "scene_id": scene.scene_id,
                        "uuid": scene.uuid,
                        "title": scene.title,
                        "duration": scene.duration,
                        "time_setting": scene.time_setting,
                        "location": scene.location,
                        "space_type": scene.space_type,
                        "atmosphere": scene.atmosphere,
                        "created_at": scene.created_at,
                        "updated_at": scene.updated_at,
                        "shots": [],
                    }
                    for shot in shots:
                        scene_data["shots"].append({
                            "shot_id": shot.shot_id,
                            "uuid": shot.uuid,
                            "title": shot.title,
                            "shot_number": shot.shot_number,
                            "description": shot.description,
                            "narration": shot.narration,
                            "image_prompt": shot.image_prompt,
                            "image_url": shot.image_url,
                            "audio_url": shot.audio_url,
                            "audio_duration": shot.audio_duration,
                            "scene_id": shot.scene_id,
                            "created_at": shot.created_at,
                            "updated_at": shot.updated_at,
                            "characters": [],  # 列表接口暂不返回角色，避免额外查询
                        })
                    creation_data["scenes"].append(scene_data)

            items.append(creation_data)

        return success_response(
            data={
                "items": items,
                "total": total,
                "page": page,
                "page_size": page_size,
                "total_pages": total_pages,
                "has_next": page < total_pages,
                "has_prev": page > 1,
            }
        )
    except BaseServiceException as e:
        raise HTTPException(status_code=e.status_code, detail=e.detail)


@router.get("/by-chapter/{chapter_uuid}")
async def get_creation_by_chapter(
    chapter_uuid: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """
    根据章节UUID查询该章节是否已有创作
    
    无论是否存在创作，都返回200状态码。
    如果没有创作，响应体中包含错误信息。
    """
    try:
        # 先通过UUID获取章节
        from app.services.novel_service import NovelService
        chapter = NovelService.get_chapter_by_uuid_service(db=db, chapter_uuid=chapter_uuid, user_id=user.user_id)
        creation = CreationService.get_creation_by_chapter_service(
            db=db,
            chapter_id=chapter.chapter_id,
            user_id=user.user_id
        )
        
        # 如果没有创作，返回错误格式（但HTTP状态码仍然是200）
        if creation is None:
            return {
                "error": True,
                "message": "该章节没有关联的创作",
                "status_code": 404
            }
        
        # 构建角色列表
        characters = [
            {
                "character_id": char.character_id,
                "uuid": char.uuid,
                "name": char.name,
                "status": char.status,
                "basic_info": char.basic_info,
                "appearance": char.appearance,
                "body": char.body,
                "hair": char.hair,
                "clothing": char.clothing,
                "tags": char.tags,
                "image_prompt": char.image_prompt,
                "visual_style": char.visual_style,
                "image_url": char.image_url,
                "creation_id": char.creation_id,
                "created_at": char.created_at,
                "updated_at": char.updated_at,
            }
            for char in creation.characters
        ]
        
        # 构建场景列表（简化信息，只包含基本信息）
        scenes = [
            {
                "scene_id": scene.scene_id,
                "uuid": scene.uuid,
                "title": scene.title,
                "duration": scene.duration,
                "time_setting": scene.time_setting,
                "location": scene.location,
                "space_type": scene.space_type,
                "atmosphere": scene.atmosphere,
                "created_at": scene.created_at,
                "updated_at": scene.updated_at,
            }
            for scene in creation.scenes
        ]
        
        # 构建响应数据
        response_data = {
            "creation_id": creation.creation_id,
            "uuid": creation.uuid,
            "title": creation.title,
            "status": creation.status,
            "chapter_id": creation.chapter_id,
            "novel_id": creation.novel_id,
            "owner_id": creation.owner_id,
            "voice_id": creation.voice_id,
            "voice_speed": creation.voice_speed,
            "video_url": creation.video_url,
            "audio_url": creation.audio_url,
            "subtitle_url": creation.subtitle_url,
            "created_at": creation.created_at,
            "updated_at": creation.updated_at,
            "current_task_id": creation.current_task_id,
            "characters": characters,
            "scenes": scenes,
        }
        
        return success_response(
            data=response_data,
            message="查询成功"
        )
    except BaseServiceException as e:
        raise HTTPException(status_code=e.status_code, detail=e.detail)
    except Exception as e:
        logger.error(f"查询章节创作失败: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"查询失败: {str(e)}")


@router.get("/{creation_uuid}/simple")
async def get_creation_simple(
    creation_uuid: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """
    根据UUID获取创作项目基本信息（简化版）
    
    只返回创作的基本字段，不返回关联的characters、scenes等数据，
    用于需要快速获取创作基本信息的场景，性能更优。
    """
    try:
        creation = CreationService.get_creation_simple_by_uuid_service(
            db=db,
            creation_uuid=creation_uuid
        )
        if creation is None:
            raise HTTPException(status_code=404, detail="创作项目不存在")
        if creation.owner_id != user.user_id:
            raise HTTPException(status_code=403, detail="无权限访问该创作项目")
        
        # 返回基本字段，包含 novel_uuid 和 chapter_uuid
        response_data = {
            "creation_id": creation.creation_id,
            "uuid": creation.uuid,
            "title": creation.title,
            "status": creation.status,
            "chapter_id": creation.chapter_id,
            "novel_id": creation.novel_id,
            "novel_uuid": creation.novel.uuid if creation.novel else None,
            "chapter_uuid": creation.chapter.uuid if creation.chapter else None,
            "owner_id": creation.owner_id,
            "voice_id": creation.voice_id,
            "voice_speed": creation.voice_speed,
            "video_url": creation.video_url,
            "audio_url": creation.audio_url,
            "subtitle_url": creation.subtitle_url,
            "created_at": creation.created_at,
            "updated_at": creation.updated_at,
            "current_task_id": creation.current_task_id,
        }
        
        return success_response(
            data=response_data,
            message="创作项目获取成功"
        )
    except BaseServiceException as e:
        raise HTTPException(status_code=e.status_code, detail=e.detail)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"获取创作项目基本信息失败: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"获取失败: {str(e)}")


@router.get("/{creation_uuid}")
async def get_creation(
    creation_uuid: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """根据UUID获取创作项目详情（完整版，包含所有关联数据）"""
    try:
        creation = CreationService.get_creation_by_uuid_service(db=db, creation_uuid=creation_uuid)
        if creation is None:
            raise HTTPException(status_code=404, detail="创作项目不存在")
        if creation.owner_id != user.user_id:
            raise HTTPException(status_code=403, detail="无权限访问该创作项目")
        # 将 SQLAlchemy 模型对象转换为 Pydantic schema 对象，然后转换为字典
        # 排除 chapter 和 novel.chapters，防止返回章节信息
        creation_data = CreationSchema.model_validate(creation).model_dump(
            exclude={"chapter": True, "novel": {"chapters": True}}
        )
        return success_response(
            data=creation_data,
            message="创作项目获取成功"
        )
    except BaseServiceException as e:
        raise HTTPException(status_code=e.status_code, detail=e.detail)


@router.delete("/{creation_uuid}")
async def delete_creation(
    creation_uuid: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """
    删除创作项目（软删除）
    
    Args:
        creation_uuid: 创作项目UUID
        
    Returns:
        删除结果
        
    注意：
        - 只有创建者可以删除
        - 使用软删除，设置 deleted_at 字段，不会真正删除数据
        - 已删除的创作不会在查询列表中显示
    """
    try:
        # 查询创作项目（包括已删除的，用于验证是否存在）
        creation = db.query(Creation).filter(Creation.uuid == creation_uuid).first()
        
        if not creation:
            raise HTTPException(status_code=404, detail="创作项目不存在")
        
        # 检查是否已经删除
        if creation.deleted_at is not None:
            raise HTTPException(status_code=404, detail="创作项目已被删除")
        
        # 验证权限
        if creation.owner_id != user.user_id:
            raise HTTPException(status_code=403, detail="无权限删除该创作项目")
        
        # 软删除：设置 deleted_at 字段
        now = datetime.utcnow()
        creation.deleted_at = now
        db.commit()
        
        logger.info(f"创作项目已软删除: creation_uuid={creation_uuid}, creation_id={creation.creation_id}, user_id={user.user_id}, deleted_at={now}")
        
        return success_response(
            data={"creation_uuid": creation_uuid},
            message="创作项目删除成功"
        )
        
    except HTTPException:
        raise
    except BaseServiceException as e:
        raise HTTPException(status_code=e.status_code, detail=e.detail)
    except Exception as e:
        logger.error(f"删除创作项目失败: {str(e)}", exc_info=True)
        db.rollback()
        raise HTTPException(status_code=500, detail=f"删除失败: {str(e)}")


class GenerateShotsRequest(BaseModel):
    """生成分镜图片请求体"""
    force_regenerate: bool = False  # 是否强制重新生成已有图片的分镜
    shot_ids: Optional[List[str]] = None  # 指定分镜UUID列表（为空则生成所有分镜）


class SelectVoiceRequest(BaseModel):
    """选择语音并生成音频请求体"""
    voice_id: str  # Fish Audio 语音模型ID
    voice_speed: float = 1.0  # 语速设置，范围 0-10，默认 1.0
    force_regenerate: bool = False  # 是否强制重新生成已有音频的分镜


@router.post("/{creation_uuid}/generate-shots")
async def start_generate_shots(
    creation_uuid: str,
    request: GenerateShotsRequest = GenerateShotsRequest(),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """
    启动分镜图片批量生成任务
    
    该接口会启动一个 Celery 任务来异步生成分镜图片。
    前端可以通过返回的 task_id 轮询查询任务状态。
    
    Args:
        creation_uuid: 创作项目UUID
        request: 生成请求参数
            - force_regenerate: 是否强制重新生成已有图片的分镜
            - shot_ids: 指定分镜UUID列表（为空则生成所有分镜）
    
    Returns:
        {
            "task_id": "xxx",  # 主任务ID，用于查询任务状态
            "creation_uuid": "xxx",
            "message": "分镜图片生成任务已启动"
        }
    
    任务状态查询：
        通过 GET /api/v1/tasks/{task_id} 查询任务状态
        任务状态包含子任务信息，可以查看每个分镜的生成进度
    """
    try:
        # 验证创作项目是否存在
        creation = db.query(Creation).filter(Creation.uuid == creation_uuid).first()
        if not creation:
            raise HTTPException(status_code=404, detail="创作项目不存在")
        
        # 验证权限
        if creation.owner_id != user.user_id:
            raise HTTPException(status_code=403, detail="无权限操作该创作项目")
        
        # 检查是否有正在执行的任务
        if creation.current_task_id:
            raise HTTPException(
                status_code=400, 
                detail=f"创作项目正在执行其他任务，任务ID: {creation.current_task_id}"
            )
        
        # 根据请求参数选择任务类型
        if request.shot_ids:
            # 将UUID列表转换为shot_id列表（Celery任务需要整数ID）
            shot_uuids = request.shot_ids
            shots = db.query(Shot).filter(Shot.uuid.in_(shot_uuids)).all()
            if len(shots) != len(shot_uuids):
                found_uuids = {shot.uuid for shot in shots}
                missing_uuids = set(shot_uuids) - found_uuids
                raise HTTPException(
                    status_code=404,
                    detail=f"部分分镜不存在: {list(missing_uuids)}"
                )
            shot_ids = [shot.shot_id for shot in shots]
            
            # 生成指定分镜（传递整数ID给Celery任务）
            task = generate_shots_by_ids_task.delay(
                shot_ids=shot_ids,
                creation_id=creation.creation_id
            )
            message = f"已启动 {len(shot_ids)} 个分镜图片生成任务"
        else:
            # 生成所有分镜
            task = generate_creation_shots_task.delay(
                creation_id=creation.creation_id,
                force_regenerate=request.force_regenerate
            )
            message = "分镜图片批量生成任务已启动"
        
        # 更新创作的当前任务ID
        creation.current_task_id = task.id
        db.commit()
        
        logger.info(f"创作 {creation_uuid} 分镜图片生成任务已启动: task_id={task.id}")
        
        return success_response(
            data={
                "task_id": task.id,
                "creation_uuid": creation_uuid
            },
            message=message
        )
        
    except HTTPException:
        raise
    except BaseServiceException as e:
        raise HTTPException(status_code=e.status_code, detail=e.detail)
    except Exception as e:
        logger.error(f"启动分镜图片生成任务失败: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"启动任务失败: {str(e)}")


class GeneratePlaybookRequest(BaseModel):
    narration_mode: str = "original"  # 解说词模式：original（原文模式）或 rewrite（爽文模式）


@router.post("/{creation_uuid}/generate-playbook")
async def start_generate_playbook(
    creation_uuid: str,
    request: GeneratePlaybookRequest = GeneratePlaybookRequest(),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """
    手动启动分镜拆分任务（第二步）
    
    该接口会启动一个 Celery 任务来异步生成分镜脚本。
    前端可以通过返回的 task_id 轮询查询任务状态。
    
    Args:
        creation_uuid: 创作项目UUID
        request: 生成请求参数
            - narration_mode: 解说词模式，可选值："original"（原文模式）或 "rewrite"（爽文模式），默认为 "original"
    
    Returns:
        {
            "task_id": "xxx",  # 任务ID，用于查询任务状态
            "creation_uuid": "xxx",
            "message": "分镜拆分任务已启动"
        }
    
    前置条件：
        - 创作状态必须是 CHARACTER_ANALYZED（角色已分析）
        - 不能有正在执行的任务
    
    任务状态查询：
        通过 GET /api/v1/tasks/{task_id} 查询任务状态
    """
    try:
        # 验证创作项目是否存在
        creation = db.query(Creation).filter(Creation.uuid == creation_uuid).first()
        if not creation:
            raise HTTPException(status_code=404, detail="创作项目不存在")
        
        # 验证权限
        if creation.owner_id != user.user_id:
            raise HTTPException(status_code=403, detail="无权限操作该创作项目")
        
        # 验证状态：必须完成角色分析（包括已生成角色图片或已拆分分镜的状态）
        from app.schemas.creation import CreationStatus
        allowed_statuses = [
            CreationStatus.CHARACTER_ANALYZED,
            CreationStatus.CHARACTER_GENERATED,
            CreationStatus.PLAYBOOK_GENERATED,
        ]
        if creation.status not in allowed_statuses:
            raise HTTPException(
                status_code=400,
                detail=f"创作状态不正确，当前状态 {creation.status}。需要先完成角色分析。"
            )
        
        # 检查是否有正在执行的任务
        if creation.current_task_id:
            raise HTTPException(
                status_code=400,
                detail=f"创作项目正在执行其他任务，任务ID: {creation.current_task_id}"
            )
        
        # 验证 narration_mode
        if request.narration_mode not in ["original", "rewrite"]:
            raise HTTPException(
                status_code=400,
                detail="narration_mode 必须是 'original'（原文模式）或 'rewrite'（爽文模式）"
            )
        
        # 获取章节内容URL
        from app.models.chapter import Chapter
        chapter = db.query(Chapter).filter(Chapter.chapter_id == creation.chapter_id).first()
        if not chapter or not chapter.content_url:
            raise HTTPException(status_code=404, detail="章节内容不存在")
        
        # 启动分镜拆分任务
        # 注意：当从 API 直接调用时，previous_result 参数传入 None（因为不是通过 link 调用）
        task = playbook_generation_task.delay(
            None,  # previous_result: 从 API 直接调用时传入 None
            novel_id=creation.novel_id,
            chapter_id=creation.chapter_id,
            creation_id=creation.creation_id,
            chapter_content_url=chapter.content_url,
            narration_mode=request.narration_mode
        )
        
        # 更新创作的当前任务ID
        creation.current_task_id = task.id
        db.commit()
        
        logger.info(f"创作 {creation_uuid} 分镜拆分任务已启动: task_id={task.id}, narration_mode={request.narration_mode}")
        
        return success_response(
            data={
                "task_id": task.id,
                "creation_uuid": creation_uuid
            },
            message="分镜拆分任务已启动"
        )
        
    except HTTPException:
        raise
    except BaseServiceException as e:
        raise HTTPException(status_code=e.status_code, detail=e.detail)
    except Exception as e:
        logger.error(f"启动分镜拆分任务失败: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"启动任务失败: {str(e)}")


@router.post("/{creation_uuid}/select-voice")
async def select_voice_and_generate_video(
    creation_uuid: str,
    request: SelectVoiceRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """
    选择语音并启动完整视频生成任务
    
    该接口会启动一个综合任务，自动完成：
    1. 为每个分镜生成 TTS 音频
    2. 合并所有音频
    3. 生成 SRT 字幕文件
    4. 为每个分镜图片生成带特效的视频片段
    5. 拼接视频并合并音频、字幕
    6. 生成最终视频
    
    前端只需轮询任务状态，等待最终视频生成完成即可。
    
    Args:
        creation_uuid: 创作项目UUID
        request: 请求参数
            - voice_id: Fish Audio 语音模型ID
            - force_regenerate: 是否强制重新生成
    
    Returns:
        {
            "task_id": "xxx",
            "creation_uuid": "xxx",
            "voice_id": "xxx",
            "message": "视频生成任务已启动"
        }
    
    任务状态查询：
        通过 GET /api/v1/tasks/{task_id} 查询任务状态
        
    任务进度说明：
        - stage: generating_audio - 正在生成音频
        - stage: merging_audio - 正在合并音频和字幕
        - stage: generating_video - 正在生成视频片段
        - stage: merging_video - 正在合并最终视频
        - stage: uploading - 正在上传视频
    """
    try:
        # 验证创作项目是否存在
        creation = db.query(Creation).filter(Creation.uuid == creation_uuid).first()
        if not creation:
            raise HTTPException(status_code=404, detail="创作项目不存在")
        
        # 验证权限
        if creation.owner_id != user.user_id:
            raise HTTPException(status_code=403, detail="无权限操作该创作项目")
        
        # 检查是否有正在执行的任务
        if creation.current_task_id:
            raise HTTPException(
                status_code=400, 
                detail=f"创作项目正在执行其他任务，任务ID: {creation.current_task_id}"
            )
        
        # 更新音色ID、语速和状态为"音色已选择"
        creation.voice_id = request.voice_id
        creation.voice_speed = request.voice_speed
        creation.status = CreationStatus.VOICE_SELECTED
        db.commit()
        
        # 启动完整视频生成任务
        task = generate_full_video_task.delay(
            creation_id=creation.creation_id,
            voice_id=request.voice_id,
            voice_speed=request.voice_speed,
            force_regenerate=request.force_regenerate
        )
        
        # 更新创作的当前任务ID
        creation.current_task_id = task.id
        db.commit()
        
        logger.info(f"创作 {creation_uuid} 完整视频生成任务已启动: task_id={task.id}, voice_id={request.voice_id}")
        
        return success_response(
            data={
                "task_id": task.id,
                "creation_uuid": creation_uuid,
                "voice_id": request.voice_id,
                "voice_speed": request.voice_speed
            },
            message="视频生成任务已启动"
        )
        
    except HTTPException:
        raise
    except BaseServiceException as e:
        raise HTTPException(status_code=e.status_code, detail=e.detail)
    except Exception as e:
        logger.error(f"启动视频生成任务失败: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"启动任务失败: {str(e)}")


@router.get("/{creation_uuid}/progress")
async def get_generation_progress(
    creation_uuid: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """
    获取创作项目当前任务的生成进度
    
    Args:
        creation_uuid: 创作项目UUID
        
    Returns:
        当前任务的进度信息，如果没有正在执行的任务则返回 null
    """
    from app.core.celery_app import celery_app
    
    try:
        # 验证创作项目是否存在
        creation = db.query(Creation).filter(Creation.uuid == creation_uuid).first()
        if not creation:
            raise HTTPException(status_code=404, detail="创作项目不存在")
        
        # 验证权限
        if creation.owner_id != user.user_id:
            raise HTTPException(status_code=403, detail="无权限访问该创作项目")
        
        # 检查是否有正在执行的任务
        if not creation.current_task_id:
            return success_response(
                data={
                    "creation_uuid": creation_uuid,
                    "task_id": None,
                    "status": None,
                    "progress": None,
                    "message": "当前没有正在执行的任务"
                },
                message="当前没有正在执行的任务"
            )
        
        # 查询任务状态
        task = celery_app.AsyncResult(creation.current_task_id)
        task_state = task.state
        
        response_data = {
            "creation_uuid": creation_uuid,
            "task_id": creation.current_task_id,
            "status": task_state,
        }
        
        if task_state == "PROGRESS":
            progress_info = task.info if task.info else {}
            response_data["progress"] = {
                "total": progress_info.get("total", 0),
                "completed": progress_info.get("completed", 0),
                "success_count": progress_info.get("success_count", 0),
                "failed_count": progress_info.get("failed_count", 0),
                "status": progress_info.get("status", "处理中"),
                "stage": progress_info.get("stage", "unknown"),
                "sub_tasks": progress_info.get("sub_tasks", []),
            }
            response_data["message"] = progress_info.get("status", "任务进行中")
        elif task_state == "SUCCESS":
            result = task.result if task.result else {}
            response_data["progress"] = {
                "total": result.get("total", 0),
                "completed": result.get("total", 0),
                "success_count": result.get("success_count", 0),
                "failed_count": result.get("failed_count", 0),
            }
            response_data["message"] = "任务完成"
            response_data["results"] = result.get("results", [])
        elif task_state == "FAILURE":
            response_data["message"] = "任务失败"
            response_data["error"] = str(task.info) if task.info else "未知错误"
        else:
            response_data["message"] = f"任务状态: {task_state}"
        
        return success_response(data=response_data, message=response_data.get("message", "查询成功"))
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"查询任务进度失败: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"查询任务进度失败: {str(e)}")
