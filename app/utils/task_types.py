"""
任务类型定义
用于标识和管理不同类型的 Celery 任务
"""
from enum import Enum


class TaskType(str, Enum):
    """任务类型枚举"""
    # 小说相关任务
    NOVEL_UPLOAD = "novel_upload"  # 小说上传处理
    
    # AI 生成任务
    CREATION_INIT = "creation_init"  # 创作初始化
    CHARACTER_ANALYSIS = "character_analysis"  # 角色分析
    CHARACTER_IMAGE_GENERATION = "character_image_generation"  # 角色图片生成
    SCENE_DESCRIPTION_GENERATION = "scene_description_generation"  # 场景描述生成
    SHOT_IMAGE_GENERATION = "shot_image_generation"  # 分镜图片生成
    AUDIO_GENERATION = "audio_generation"  # 音频生成
    VIDEO_SYNTHESIS = "video_synthesis"  # 视频合成
    
    # 批量任务
    BATCH_CHARACTER_IMAGE_GENERATION = "batch_character_image_generation"  # 批量角色图片生成
    BATCH_SHOT_IMAGE_GENERATION = "batch_shot_image_generation"  # 批量分镜图片生成
    BATCH_AUDIO_GENERATION = "batch_audio_generation"  # 批量音频生成（含字幕）
    BATCH_VIDEO_GENERATION = "batch_video_generation"  # 批量视频生成
    VIDEO_MERGE = "video_merge"  # 视频合并（视频+音频+字幕）


class TaskStage(str, Enum):
    """任务处理阶段（通用）"""
    # 通用阶段
    INITIALIZING = "initializing"  # 初始化
    PROCESSING = "processing"  # 处理中
    COMPLETING = "completing"  # 完成中
    COMPLETED = "completed"  # 已完成
    FAILED = "failed"  # 失败
    
    # 小说上传特定阶段
    PARSING = "parsing"  # 解析中
    PARSING_COMPLETE = "parsing_complete"  # 解析完成
    CREATING_NOVEL = "creating_novel"  # 创建小说记录
    UPLOADING_CHAPTERS = "uploading_chapters"  # 上传章节
    
    # AI 生成任务阶段
    GENERATING = "generating"  # 生成中
    UPLOADING_RESULT = "uploading_result"  # 上传结果中


def get_task_type_from_name(task_name: str) -> TaskType:
    """
    从 Celery 任务名称推断任务类型
    
    Args:
        task_name: Celery 任务名称（如 "process_novel_upload_task"）
        
    Returns:
        任务类型枚举
    """
    task_name_lower = task_name.lower()
    
    if "novel_upload" in task_name_lower or "novel" in task_name_lower:
        return TaskType.NOVEL_UPLOAD
    elif "creation_init" in task_name_lower:
        return TaskType.CREATION_INIT
    elif "character_image" in task_name_lower:
        return TaskType.CHARACTER_IMAGE_GENERATION
    elif "scene_description" in task_name_lower:
        return TaskType.SCENE_DESCRIPTION_GENERATION
    elif "creation_shots" in task_name_lower or "batch_shot" in task_name_lower:
        return TaskType.BATCH_SHOT_IMAGE_GENERATION
    elif "shot_image" in task_name_lower or "single_shot" in task_name_lower:
        return TaskType.SHOT_IMAGE_GENERATION
    elif "audio" in task_name_lower:
        return TaskType.AUDIO_GENERATION
    elif "video" in task_name_lower or "synthesis" in task_name_lower:
        return TaskType.VIDEO_SYNTHESIS
    else:
        # 默认返回未知类型（可以扩展）
        return TaskType.NOVEL_UPLOAD  # 临时默认值

