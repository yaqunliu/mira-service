"""
Chat Supervisor Tools - 对话监督 Agent 的工具集
"""
from typing import Dict, Any, List, Optional

from langchain_core.tools import tool

from app.core.logger import logger


@tool
async def ask_video_type() -> Dict[str, Any]:
    """
    显示视频类型选择器，让用户选择要创作的视频类型。
    
    当用户还没有选择视频类型时调用此工具。
    
    Returns:
        包含选择选项的响应
    """
    logger.info("[ChatSupervisor] 显示视频类型选择")
    
    return {
        "response_text": "请选择你想创作的视频类型：",
        "board_actions": [
            {
                "type": "select_options",
                "message": "请选择创作类型：",
                "options": [
                    {"id": "vocab_video", "label": "📚 英文单词视频", "value": "我要创作英文单词视频"},
                    {"id": "gaoxiao_video", "label": "😄 搞笑短视频", "value": "我要创作搞笑视频"},
                    {"id": "story_video", "label": "📖 故事动画视频", "value": "我要创作故事视频"},
                ]
            }
        ]
    }


@tool
def set_video_type(video_type: str) -> Dict[str, Any]:
    """
    设置视频类型。
    
    当用户选择了视频类型后调用此工具保存类型。
    
    Args:
        video_type: 视频类型 (vocab_video/gaoxiao_video/story_video)
    
    Returns:
        保存结果
    """
    logger.info(f"[ChatSupervisor] 设置视频类型: {video_type}")
    
    return {
        "response_text": f"已选择视频类型：{video_type}",
        "video_type": video_type,
    }


@tool
async def ask_vocab_config() -> Dict[str, Any]:
    """
    显示单词视频配置卡片，让用户填写参数。
    
    当用户选择了单词视频但没有提供完整参数时调用此工具。
    
    Returns:
        包含配置卡片的响应
    """
    logger.info("[ChatSupervisor] 显示单词视频配置卡片")
    
    return {
        "response_text": "请填写单词视频的参数：",
        "board_actions": [
            {
                "type": "show_config_card",
                "card_type": "vocab_config",
                "title": "🎬 配置单词视频参数",
                "description": "请填写以下参数，都有默认值可以直接确认",
                "fields": [
                    {"name": "words", "label": "📝 单词列表", "type": "tags", "placeholder": "输入英文单词（1-5个）", "required": True, "default": [], "max": 5},
                    {"name": "sentence_level", "label": "📚 句子难度", "type": "select", "options": [{"value": "kindergarten", "label": "🍼 幼儿园"}, {"value": "primary", "label": "📖 小学"}, {"value": "middle", "label": "🎓 中学"}], "default": "primary"},
                    {"name": "word_repeat_count", "label": "🔁 单词重复", "type": "select", "options": [{"value": 1, "label": "1次"}, {"value": 2, "label": "2次"}], "default": 2},
                    {"name": "translation_repeat_count", "label": "🔁 翻译重复", "type": "select", "options": [{"value": 1, "label": "1次"}, {"value": 2, "label": "2次"}], "default": 1},
                    {"name": "voice_gender", "label": "🎙️ 配音性别", "type": "select", "options": [{"value": "female", "label": "👩 女声"}, {"value": "male", "label": "👨 男声"}, {"value": "random", "label": "🎲 随机"}], "default": "random"},
                ],
                "submit_text": "✨ 确认并开始创作"
            }
        ]
    }


@tool
async def save_vocab_params(
    words: List[str],
    sentence_level: str = "primary",
    word_repeat_count: int = 2,
    translation_repeat_count: int = 1,
    voice_gender: str = "random",
    user_id: int = 1,
    creation_uuid: str = ""
) -> Dict[str, Any]:
    """
    保存单词视频的参数。
    
    当用户提供了单词或配置信息时，调用此工具保存参数。
    注意：此工具只保存参数，不显示确认卡片。确认卡片由 ask_confirm_generation 工具单独显示。
    
    Args:
        words: 单词列表，最多5个
        sentence_level: 句子难度 (kindergarten/primary/middle)
        word_repeat_count: 单词重复次数 (1或2)
        translation_repeat_count: 翻译重复次数 (1或2)
        voice_gender: 配音性别 (female/male/random)
        user_id: 用户ID
        creation_uuid: 创作UUID
    
    Returns:
        保存结果和当前参数状态
    """
    logger.info(f"[ChatSupervisor] 保存参数: words={words}, creation_uuid={creation_uuid}")
    
    # 保存到 Creation 表
    if creation_uuid:
        from sqlalchemy import select
        from app.db.base import _get_async_session_factory
        from app.models.creation import Creation
        
        db = _get_async_session_factory()()
        try:
            result = await db.execute(
                select(Creation).where(Creation.uuid == creation_uuid)
            )
            creation = result.scalar_one_or_none()
            
            if creation:
                extra = creation.extra_data or {}
                extra["vocab_config"] = {
                    "words": words,
                    "sentence_level": sentence_level,
                    "word_repeat_count": word_repeat_count,
                    "translation_repeat_count": translation_repeat_count,
                    "voice_gender": voice_gender,
                    "user_id": user_id,
                }
                creation.extra_data = extra
                await db.commit()
                logger.info(f"[ChatSupervisor] 参数已保存到 Creation: {creation_uuid}")
        except Exception as e:
            logger.error(f"[ChatSupervisor] 保存参数失败: {e}", exc_info=True)
        finally:
            await db.close()
    
    is_complete = len(words) > 0
    
    response_text = f"✅ 已保存参数：{', '.join(words)}"
    
    if is_complete:
        response_text += "\n\n参数已配置完成！请点击下方按钮确认生成视频。"
    
    return {
        "response_text": response_text,
        "board_actions": [],  # 不在这里添加确认卡片，由 ask_confirm_generation 单独处理
        "params": {
            "words": words,
            "sentence_level": sentence_level,
            "word_repeat_count": word_repeat_count,
            "translation_repeat_count": translation_repeat_count,
            "voice_gender": voice_gender,
            "user_id": user_id,
            "creation_uuid": creation_uuid,
        },
        "is_complete": is_complete
    }


@tool
def ask_confirm_generation(
    words: List[str],
    sentence_level: str = "primary",
    word_repeat_count: int = 2,
    translation_repeat_count: int = 1,
    voice_gender: str = "random",
) -> Dict[str, Any]:
    """
    显示确认生成视频的按钮，让用户确认是否开始生成。
    
    当参数已经齐全时，调用此工具询问用户是否开始生成视频。
    
    Args:
        words: 单词列表
        sentence_level: 句子难度
        word_repeat_count: 单词重复次数
        translation_repeat_count: 翻译重复次数
        voice_gender: 配音性别
    
    Returns:
        包含确认按钮的响应
    """
    logger.info(f"[ChatSupervisor] 询问确认生成: words={words}")
    
    return {
        "response_text": f"参数已齐全！单词：{', '.join(words)}。确认开始生成视频？",
        "board_actions": [
            {
                "type": "confirm_generation",
                "message": "参数已齐全，确认生成视频？",
                "params": {
                    "words": words,
                    "sentence_level": sentence_level,
                    "word_repeat_count": word_repeat_count,
                    "translation_repeat_count": translation_repeat_count,
                    "voice_gender": voice_gender,
                }
            }
        ]
    }


@tool
async def query_creation_status(creation_id: str = "") -> Dict[str, Any]:
    """
    查询视频创作状态。
    
    Args:
        creation_id: 创作ID（可选）
    
    Returns:
        创作状态
    """
    logger.info(f"[ChatSupervisor] 查询状态: creation_id={creation_id}")
    
    from sqlalchemy import select
    from app.db.base import _get_async_session_factory
    from app.models.creation import Creation
    
    db = _get_async_session_factory()()
    try:
        creation = None
        if creation_id:
            result = await db.execute(
                select(Creation).where(Creation.uuid == creation_id)
            )
            creation = result.scalar_one_or_none()
        
        if not creation:
            return {
                "response_text": "当前没有正在生成的视频",
                "status": "idle"
            }
        
        status = creation.status or "unknown"
        extra = creation.extra_data or {}
        progress = extra.get("progress", 0)
        current_step = extra.get("current_step", "未知")
        video_url = extra.get("video_url") or creation.video_url
        
        status_text = {
            "pending": "等待中",
            "processing": "处理中",
            "generating": "生成中",
            "exporting": "导出中",
            "completed": "已完成",
            "failed": "失败",
        }.get(status, status)
        
        response = f"📊 视频生成状态：\n"
        response += f"- 状态：{status_text}\n"
        response += f"- 进度：{progress}%\n"
        response += f"- 当前步骤：{current_step}\n"
        
        if video_url:
            response += f"- 视频地址：{video_url}\n"
        
        return {
            "response_text": response,
            "status": status,
            "progress": progress,
            "current_step": current_step,
            "video_url": video_url,
            "task_id": str(creation.uuid) if creation.uuid else None,
            "creation_id": creation.creation_id,
        }
    finally:
        await db.close()


@tool
async def reset_and_restart_video(creation_id: str = "") -> Dict[str, Any]:
    """
    重置视频生成状态并重新开始生成。
    
    当用户询问"视频是不是生成失败了"或"重新生成"时调用此工具。
    此工具会将状态重置为 pending，然后开始重新生成。
    
    Args:
        creation_id: 创作UUID
    
    Returns:
        重置和重新开始的结果
    """
    logger.info(f"[ChatSupervisor] 重置并重新开始: creation_id={creation_id}")
    
    from sqlalchemy import select, update
    from app.db.base import _get_async_session_factory
    from app.models.creation import Creation
    
    db = _get_async_session_factory()()
    try:
        result = await db.execute(
            select(Creation).where(Creation.uuid == creation_id)
        )
        creation = result.scalar_one_or_none()
        
        if not creation:
            return {
                "response_text": f"未找到创作项目：{creation_id}",
                "reset_success": False,
            }
        
        # 重置状态为 pending
        creation.status = "pending"
        extra = creation.extra_data or {}
        extra["progress"] = 0
        extra["current_step"] = "等待重新生成"
        extra["video_url"] = None  # 清除旧的视频URL
        creation.extra_data = extra
        
        await db.commit()
        
        logger.info(f"[ChatSupervisor] 已重置状态: {creation_id}, 新状态=pending")
        
        return {
            "response_text": "视频状态已重置，现在开始重新生成！",
            "reset_success": True,
            "needs_restart": True,  # 标记需要重新调度到 Worker
        }
    finally:
        await db.close()


def get_chat_supervisor_tools() -> List:
    """获取所有 Chat Supervisor 工具"""
    return [
        ask_video_type,
        set_video_type,
        ask_vocab_config,
        save_vocab_params,
        ask_confirm_generation,
        query_creation_status,
        reset_and_restart_video,
    ]
