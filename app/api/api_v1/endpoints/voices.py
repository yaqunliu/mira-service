"""
Fish Audio 语音管理 API 端点
"""

from fastapi import APIRouter, Query, HTTPException
from typing import Optional
from app.schemas.voice import VoiceListResponse, VoiceItem, VoiceTag
from app.utils.fish_audio import get_fish_audio_client
from app.core.logger import logger

router = APIRouter()

# Fish Audio 封面图片 CDN URL 前缀
FISH_AUDIO_COVER_CDN_BASE = "https://public-platform.r2.fish.audio/cdn-cgi/image/width=64,format=webp/coverimage/"


def get_full_cover_url(voice_id: str) -> str:
    """根据 voice_id 生成封面图片完整 URL"""
    return f"{FISH_AUDIO_COVER_CDN_BASE}{voice_id}"


@router.get("", response_model=VoiceListResponse, summary="获取可用语音列表")
async def list_voices(
    language: str = Query(default="zh", description="语言，默认中文"),
    page_size: int = Query(default=10, ge=1, le=100, description="每页数量，默认10"),
    page_number: int = Query(default=1, ge=1, description="页码，默认1"),
    title: Optional[str] = Query(default=None, description="按标题模糊搜索"),
    tag: Optional[VoiceTag] = Query(default=None, description="按标签筛选: male(男性), female(女性), cartoon(卡通)")
):
    """
    获取 Fish Audio 可用的语音模型列表
    
    - **language**: 语言代码，默认 "zh"（中文）
    - **page_size**: 每页返回数量，默认 10，最大 100
    - **page_number**: 页码，从 1 开始
    - **title**: 按标题模糊搜索（可选）
    - **tag**: 按标签筛选，可选值：male（男性）、female（女性）、cartoon（卡通）
    """
    try:
        client = get_fish_audio_client()
        
        # 构建查询参数
        query_params = {
            "language": language,
            "page_size": page_size,
            "page_number": page_number,
        }
        
        # 添加可选参数
        if title:
            query_params["title"] = title
        if tag:
            query_params["tags"] = tag.value
        
        # 调用 Fish Audio API
        result = client.client.voices.list(**query_params)
        
        # 转换为响应格式
        items = []
        for voice in result.items:
            # 处理 samples
            samples = []
            if hasattr(voice, 'samples') and voice.samples:
                for sample in voice.samples:
                    samples.append({
                        "title": getattr(sample, 'title', ''),
                        "text": getattr(sample, 'text', ''),
                        "task_id": getattr(sample, 'task_id', None),
                        "audio": getattr(sample, 'audio', None),
                    })
            
            # 处理 author
            author = None
            if hasattr(voice, 'author') and voice.author:
                author = {
                    "id": getattr(voice.author, 'id', ''),
                    "nickname": getattr(voice.author, 'nickname', ''),
                    "avatar": getattr(voice.author, 'avatar', None),
                }
            
            items.append(VoiceItem(
                id=voice.id,
                title=voice.title,
                description=getattr(voice, 'description', None),
                cover_image=get_full_cover_url(voice.id),
                train_mode=getattr(voice, 'train_mode', None),
                state=getattr(voice, 'state', None),
                tags=getattr(voice, 'tags', []) or [],
                samples=samples,
                created_at=getattr(voice, 'created_at', None),
                updated_at=getattr(voice, 'updated_at', None),
                languages=getattr(voice, 'languages', []) or [],
                visibility=getattr(voice, 'visibility', None),
                like_count=getattr(voice, 'like_count', 0) or 0,
                mark_count=getattr(voice, 'mark_count', 0) or 0,
                shared_count=getattr(voice, 'shared_count', 0) or 0,
                task_count=getattr(voice, 'task_count', 0) or 0,
                liked=getattr(voice, 'liked', False) or False,
                marked=getattr(voice, 'marked', False) or False,
                author=author,
            ))
        
        return VoiceListResponse(
            total=result.total,
            items=items,
            page_size=page_size,
            page_number=page_number,
        )
        
    except Exception as e:
        logger.error(f"获取语音列表失败: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"获取语音列表失败: {str(e)}"
        )


@router.get("/{voice_id}", response_model=VoiceItem, summary="获取语音详情")
async def get_voice(voice_id: str):
    """
    获取指定语音模型的详细信息
    
    - **voice_id**: 语音模型 ID
    """
    try:
        client = get_fish_audio_client()
        voice = client.client.voices.get(voice_id)
        
        # 处理 samples
        samples = []
        if hasattr(voice, 'samples') and voice.samples:
            for sample in voice.samples:
                samples.append({
                    "title": getattr(sample, 'title', ''),
                    "text": getattr(sample, 'text', ''),
                    "task_id": getattr(sample, 'task_id', None),
                    "audio": getattr(sample, 'audio', None),
                })
        
        # 处理 author
        author = None
        if hasattr(voice, 'author') and voice.author:
            author = {
                "id": getattr(voice.author, 'id', ''),
                "nickname": getattr(voice.author, 'nickname', ''),
                "avatar": getattr(voice.author, 'avatar', None),
            }
        
        return VoiceItem(
            id=voice.id,
            title=voice.title,
            description=getattr(voice, 'description', None),
            cover_image=get_full_cover_url(voice.id),
            train_mode=getattr(voice, 'train_mode', None),
            state=getattr(voice, 'state', None),
            tags=getattr(voice, 'tags', []) or [],
            samples=samples,
            created_at=getattr(voice, 'created_at', None),
            updated_at=getattr(voice, 'updated_at', None),
            languages=getattr(voice, 'languages', []) or [],
            visibility=getattr(voice, 'visibility', None),
            like_count=getattr(voice, 'like_count', 0) or 0,
            mark_count=getattr(voice, 'mark_count', 0) or 0,
            shared_count=getattr(voice, 'shared_count', 0) or 0,
            task_count=getattr(voice, 'task_count', 0) or 0,
            liked=getattr(voice, 'liked', False) or False,
            marked=getattr(voice, 'marked', False) or False,
            author=author,
        )
        
    except Exception as e:
        logger.error(f"获取语音详情失败: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"获取语音详情失败: {str(e)}"
        )

