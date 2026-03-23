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
    
    【重要】只在用户完全没有表达类型意向时调用此工具！
    如果用户消息中已经表达了类型选择，应该直接调用 set_video_type 保存类型：
    - 用户说"开始英文单词视频创作" → 直接调用 set_video_type("vocab_video")
    - 用户说"我要创作搞笑视频" → 直接调用 set_video_type("gaoxiao_video")
    - 用户说"我想做故事动画" → 直接调用 set_video_type("story_video")
    - 用户说"单词视频"、"英文单词" → 直接调用 set_video_type("vocab_video")
    
    只有当用户完全没有提到任何类型时才调用此工具：
    - 用户说"开始创作"、"我要创作视频" → 调用 ask_video_type 显示选择器
    
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
    
    【重要】当用户消息中表达了类型选择时，必须调用此工具保存类型！
    不要先显示选择器再让用户选，直接保存用户已经表达的类型：
    - 用户说"开始英文单词视频创作" → 调用 set_video_type("vocab_video")
    - 用户说"我要创作搞笑视频" → 调用 set_video_type("gaoxiao_video")
    - 用户说"我想做故事动画" → 调用 set_video_type("story_video")
    - 用户说"单词视频"、"英文单词" → 调用 set_video_type("vocab_video")
    
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
    
    【重要】此工具用于收集用户输入，不是用于保存参数！
    - 调用此工具后，必须等待用户在卡片中填写并提交
    - 用户提交后，系统会再次调用 Agent，此时才能调用 save_vocab_params 保存参数
    - 绝对不要在调用此工具后立即调用 save_vocab_params
    
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
    
    【重要】此工具只能用于保存用户实际填写/提供的参数！
    - 必须等待用户在配置卡片中填写并提交参数后才能调用
    - 绝对禁止自己编造/猜测单词列表或其他参数
    - 如果用户还没有填写参数，应该调用 ask_vocab_config 显示配置卡片让用户填写
    
    调用时机：
    - 用户在配置卡片中填写/修改参数后提交时
    - 用户明确提供了单词列表（如"我要学 apple, banana"）时
    
    注意：此工具只保存参数，不显示确认卡片。确认卡片由 ask_confirm_generation 工具单独显示。
    
    Args:
        words: 单词列表，最多5个（必须是用户实际提供的）
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
async def get_shot_by_word(word: str, creation_uuid: str = "") -> Dict[str, Any]:
    """
    根据单词查询特定分镜的详细信息。
    
    用于回答用户关于特定单词分镜的问题，如：
    - "noodles 分镜处理的结果是什么？"
    - "apple 这个单词的图片生成了吗？"
    - "查看 banana 分镜的状态"
    - "food 的图片链接是什么？"
    
    返回信息包括：
    - 分镜ID、类型（单词展示/句子场景）
    - 图片URL、视频URL
    - 图片提示词、视频提示词
    - 翻译、句子等
    
    Args:
        word: 要查询的单词（英文）
        creation_uuid: 创作UUID（可选，用于定位具体的创作项目）
    
    Returns:
        分镜详细信息
    """
    from sqlalchemy import select
    from app.db.base import _get_async_session_factory
    from app.models.creation import Creation
    from app.models.shot import Shot
    
    logger.info(f"[ChatSupervisor] 查询单词分镜: word={word}, creation_uuid={creation_uuid}")
    
    db = _get_async_session_factory()()
    try:
        # 先查找 creation
        creation = None
        if creation_uuid:
            result = await db.execute(
                select(Creation).where(Creation.uuid == creation_uuid)
            )
            creation = result.scalar_one_or_none()
        
        if not creation:
            return {
                "found": False,
                "word": word,
                "message": f"未找到创作项目",
            }
        
        # 查询所有分镜
        result = await db.execute(
            select(Shot).where(Shot.creation_id == creation.creation_id)
        )
        shots = result.scalars().all()
        
        # 查找匹配的分镜
        matching_shots = []
        word_lower = word.lower().strip()
        
        for s in shots:
            extra = s.extra_data or {}
            shot_word = extra.get("word", "").lower().strip()
            
            # 匹配单词（支持部分匹配）
            if shot_word == word_lower or word_lower in shot_word or shot_word in word_lower:
                matching_shots.append({
                    "shot_id": s.shot_id,
                    "shot_type": extra.get("shot_type", ""),
                    "word": extra.get("word", ""),
                    "translation": extra.get("translation", ""),
                    "sentence": extra.get("sentence", ""),
                    "status": s.status,
                    "image_url": s.image_url,
                    "video_url": s.video_url,
                    "image_prompt": s.image_prompt,
                    "video_prompt": extra.get("video_prompt", ""),
                    "has_image": bool(s.image_url),
                    "has_video": bool(s.video_url),
                })
        
        if not matching_shots:
            # 如果没有精确匹配，返回所有分镜让用户查看
            all_words = list(set([s.extra_data.get("word", "") for s in shots if s.extra_data]))
            return {
                "found": False,
                "word": word,
                "message": f"未找到单词 '{word}' 的分镜",
                "available_words": all_words,
                "suggestion": f"可用的单词有: {', '.join(all_words)}" if all_words else "暂无分镜数据"
            }
        
        # 按 shot_type 排序（word_display 在前，sentence_scene 在后）
        matching_shots.sort(key=lambda x: 0 if x["shot_type"] == "word_display" else 1)
        
        logger.info(f"[ChatSupervisor] 找到 {len(matching_shots)} 个分镜 for word={word}")
        
        # 构建详细的响应文本
        response_parts = [f"📝 **{word}** 分镜详情：\n"]
        
        for i, shot in enumerate(matching_shots, 1):
            shot_type_name = "单词展示" if shot["shot_type"] == "word_display" else "句子场景"
            response_parts.append(f"\n**分镜{i}（{shot_type_name}）**")
            response_parts.append(f"- 分镜ID: {shot['shot_id']}")
            response_parts.append(f"- 状态: {shot['status']}")
            
            if shot["translation"]:
                response_parts.append(f"- 翻译: {shot['translation']}")
            if shot["sentence"]:
                response_parts.append(f"- 句子: {shot['sentence']}")
            
            response_parts.append(f"- 图片: {'✅ 已生成' if shot['has_image'] else '❌ 未生成'}")
            if shot["image_url"]:
                response_parts.append(f"  - 图片链接: {shot['image_url']}")
            
            response_parts.append(f"- 视频: {'✅ 已生成' if shot['has_video'] else '❌ 未生成'}")
            if shot["video_url"]:
                response_parts.append(f"  - 视频链接: {shot['video_url']}")
            
            if shot["image_prompt"]:
                response_parts.append(f"- 图片提示词: {shot['image_prompt'][:100]}...")
            if shot["video_prompt"]:
                response_parts.append(f"- 视频提示词: {shot['video_prompt'][:100]}...")
        
        return {
            "found": True,
            "word": word,
            "shots": matching_shots,
            "response_text": "\n".join(response_parts),
            "summary": {
                "total_shots": len(matching_shots),
                "has_all_images": all(s["has_image"] for s in matching_shots),
                "has_all_videos": all(s["has_video"] for s in matching_shots),
                "status": "completed" if all(s["has_video"] for s in matching_shots) else "in_progress"
            }
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
        get_shot_by_word,
    ]
