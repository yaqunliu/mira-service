"""
LangGraph State Utility Functions
提供状态序列化、验证、更新等辅助函数
"""

from typing import Dict, Any, List, Optional
from datetime import datetime
import json
from .schemas import (
    ComicDramaState,
    CharacterState,
    SceneState,
    StoryboardState,
    AudioSegmentState,
    VideoSegmentState,
    CheckpointData,
    UserFeedback,
    StateUpdateResult,
)


# ==================== 状态序列化 ====================

def serialize_state(state: ComicDramaState) -> Dict[str, Any]:
    """
    将 ComicDramaState 序列化为 JSON-serializable 字典
    用于存储到数据库（JSONB）或通过 API 传输
    """
    serialized = {}

    for key, value in state.items():
        if value is None:
            serialized[key] = None
        elif isinstance(value, (str, int, float, bool)):
            serialized[key] = value
        elif isinstance(value, list):
            serialized[key] = value
        elif isinstance(value, dict):
            serialized[key] = value
        else:
            # 其他类型尝试转换为字符串
            serialized[key] = str(value)

    return serialized


def deserialize_state(data: Dict[str, Any]) -> ComicDramaState:
    """
    从 JSON 字典反序列化为 ComicDramaState
    用于从数据库读取或 API 接收
    """
    # TypedDict 不需要实例化，直接返回字典即可
    # LangGraph 会自动处理类型验证
    return data  # type: ignore


# ==================== 状态验证 ====================

def validate_state(state: ComicDramaState) -> StateUpdateResult:
    """
    验证 ComicDramaState 的完整性和一致性

    Returns:
        StateUpdateResult: 验证结果
    """
    errors = []
    updated_fields = []

    # 1. 基本字段验证
    if not state.get("creation_uuid"):
        errors.append("Missing required field: creation_uuid")
    if not state.get("thread_id"):
        errors.append("Missing required field: thread_id")
    if not state.get("user_id"):
        errors.append("Missing required field: user_id")

    # 2. 当前阶段验证
    valid_stages = [
        "init", "script_analysis", "asset_generation",
        "storyboard_creation", "audio_processing", "video_generation",
        "editing", "completed", "error"
    ]
    current_stage = state.get("current_stage")
    if current_stage and current_stage not in valid_stages:
        errors.append(f"Invalid current_stage: {current_stage}")

    # 3. 输入数据验证
    if current_stage != "init":
        if not state.get("script_text") and not state.get("script_url"):
            errors.append("Either script_text or script_url is required after init stage")

    # 4. 资产数据验证
    if current_stage in ["asset_generation", "storyboard_creation", "audio_processing",
                         "video_generation", "editing", "completed"]:
        characters = state.get("characters", [])
        scenes = state.get("scenes", [])

        if not characters:
            errors.append(f"Characters are required in {current_stage} stage")
        if not scenes:
            errors.append(f"Scenes are required in {current_stage} stage")

        # 验证角色状态
        for idx, char in enumerate(characters):
            if not char.get("name"):
                errors.append(f"Character {idx}: name is required")
            if char.get("status") not in ["pending", "generating", "completed", "failed"]:
                errors.append(f"Character {idx}: invalid status")

        # 验证场景状态
        for idx, scene in enumerate(scenes):
            if not scene.get("name"):
                errors.append(f"Scene {idx}: name is required")
            if scene.get("status") not in ["pending", "generating", "completed", "failed"]:
                errors.append(f"Scene {idx}: invalid status")

    # 5. 分镜数据验证
    if current_stage in ["storyboard_creation", "audio_processing",
                         "video_generation", "editing", "completed"]:
        storyboards = state.get("storyboards", [])

        if not storyboards:
            errors.append(f"Storyboards are required in {current_stage} stage")

        # 验证分镜顺序
        sequence_numbers = [sb.get("sequence_number") for sb in storyboards]
        if len(sequence_numbers) != len(set(sequence_numbers)):
            errors.append("Duplicate sequence_numbers in storyboards")

    # 6. 音频数据验证
    if current_stage in ["audio_processing", "video_generation", "editing", "completed"]:
        audio_segments = state.get("audio_segments", [])

        if not audio_segments:
            errors.append(f"Audio segments are required in {current_stage} stage")

    # 7. 视频数据验证
    if current_stage in ["video_generation", "editing", "completed"]:
        video_segments = state.get("video_segments", [])

        if not video_segments:
            errors.append(f"Video segments are required in {current_stage} stage")

    # 8. 检查点验证
    if state.get("pending_approval"):
        if not state.get("checkpoint_data"):
            errors.append("checkpoint_data is required when pending_approval is True")

    return {
        "success": len(errors) == 0,
        "message": "State validation passed" if len(errors) == 0 else "State validation failed",
        "updated_fields": updated_fields,
        "errors": errors if errors else None
    }


# ==================== 状态更新辅助函数 ====================

def update_character_status(
    state: ComicDramaState,
    character_name: str,
    status: str,
    **kwargs
) -> StateUpdateResult:
    """
    更新指定角色的状态

    Args:
        state: 当前状态
        character_name: 角色名称
        status: 新状态（pending/generating/completed/failed）
        **kwargs: 其他要更新的字段（如 image_url, error 等）
    """
    characters = state.get("characters", [])
    updated = False

    for char in characters:
        if char.get("name") == character_name:
            char["status"] = status  # type: ignore
            for key, value in kwargs.items():
                char[key] = value  # type: ignore
            updated = True
            break

    if not updated:
        return {
            "success": False,
            "message": f"Character '{character_name}' not found",
            "updated_fields": [],
            "errors": [f"Character '{character_name}' not found"]
        }

    state["updated_at"] = datetime.utcnow().isoformat()

    return {
        "success": True,
        "message": f"Character '{character_name}' status updated to '{status}'",
        "updated_fields": ["characters", "updated_at"],
        "errors": None
    }


def update_scene_status(
    state: ComicDramaState,
    scene_name: str,
    status: str,
    **kwargs
) -> StateUpdateResult:
    """
    更新指定场景的状态

    Args:
        state: 当前状态
        scene_name: 场景名称
        status: 新状态（pending/generating/completed/failed）
        **kwargs: 其他要更新的字段（如 image_url, error 等）
    """
    scenes = state.get("scenes", [])
    updated = False

    for scene in scenes:
        if scene.get("name") == scene_name:
            scene["status"] = status  # type: ignore
            for key, value in kwargs.items():
                scene[key] = value  # type: ignore
            updated = True
            break

    if not updated:
        return {
            "success": False,
            "message": f"Scene '{scene_name}' not found",
            "updated_fields": [],
            "errors": [f"Scene '{scene_name}' not found"]
        }

    state["updated_at"] = datetime.utcnow().isoformat()

    return {
        "success": True,
        "message": f"Scene '{scene_name}' status updated to '{status}'",
        "updated_fields": ["scenes", "updated_at"],
        "errors": None
    }


def update_storyboard_status(
    state: ComicDramaState,
    sequence_number: int,
    status: str,
    **kwargs
) -> StateUpdateResult:
    """
    更新指定分镜的状态

    Args:
        state: 当前状态
        sequence_number: 分镜序号
        status: 新状态（pending/generating/completed/failed）
        **kwargs: 其他要更新的字段（如 image_url, error 等）
    """
    storyboards = state.get("storyboards", [])
    updated = False

    for sb in storyboards:
        if sb.get("sequence_number") == sequence_number:
            sb["status"] = status  # type: ignore
            for key, value in kwargs.items():
                sb[key] = value  # type: ignore
            updated = True
            break

    if not updated:
        return {
            "success": False,
            "message": f"Storyboard {sequence_number} not found",
            "updated_fields": [],
            "errors": [f"Storyboard {sequence_number} not found"]
        }

    state["updated_at"] = datetime.utcnow().isoformat()

    return {
        "success": True,
        "message": f"Storyboard {sequence_number} status updated to '{status}'",
        "updated_fields": ["storyboards", "updated_at"],
        "errors": None
    }


def add_error(state: ComicDramaState, error: Dict[str, Any]) -> None:
    """
    向状态中添加错误记录

    Args:
        state: 当前状态
        error: 错误信息字典，应包含 timestamp, stage, message, details 等字段
    """
    errors = state.get("errors", [])

    # 添加时间戳
    if "timestamp" not in error:
        error["timestamp"] = datetime.utcnow().isoformat()

    errors.append(error)
    state["errors"] = errors
    state["updated_at"] = datetime.utcnow().isoformat()


def increment_retry_count(state: ComicDramaState, tool_name: str) -> int:
    """
    增加指定工具的重试计数

    Args:
        state: 当前状态
        tool_name: 工具名称

    Returns:
        int: 更新后的重试次数
    """
    retry_count = state.get("retry_count", {})
    current_count = retry_count.get(tool_name, 0)
    new_count = current_count + 1

    retry_count[tool_name] = new_count
    state["retry_count"] = retry_count
    state["updated_at"] = datetime.utcnow().isoformat()

    return new_count


def reset_retry_count(state: ComicDramaState, tool_name: str) -> None:
    """
    重置指定工具的重试计数

    Args:
        state: 当前状态
        tool_name: 工具名称
    """
    retry_count = state.get("retry_count", {})

    if tool_name in retry_count:
        retry_count[tool_name] = 0
        state["retry_count"] = retry_count
        state["updated_at"] = datetime.utcnow().isoformat()


def set_checkpoint(
    state: ComicDramaState,
    checkpoint_type: str,
    data: Dict[str, Any],
    message: str,
    suggestions: Optional[List[str]] = None
) -> None:
    """
    设置检查点，等待用户审核

    Args:
        state: 当前状态
        checkpoint_type: 检查点类型（script_analysis/asset_finalization/storyboard_batch/final_review）
        data: 待审核的数据
        message: 提示信息
        suggestions: 可选的建议列表
    """
    checkpoint_data: CheckpointData = {
        "checkpoint_type": checkpoint_type,  # type: ignore
        "data": data,
        "message": message,
        "suggestions": suggestions
    }

    state["checkpoint_data"] = checkpoint_data
    state["pending_approval"] = True
    state["updated_at"] = datetime.utcnow().isoformat()


def apply_user_feedback(
    state: ComicDramaState,
    action: str,
    comments: Optional[str] = None,
    modifications: Optional[Dict[str, Any]] = None,
    approved_items: Optional[List[int]] = None,
    rejected_items: Optional[List[int]] = None
) -> StateUpdateResult:
    """
    应用用户反馈到状态中

    Args:
        state: 当前状态
        action: 用户操作（approve/reject/modify）
        comments: 反馈意见
        modifications: 修改内容
        approved_items: 部分通过的项目 ID 列表
        rejected_items: 驳回的项目 ID 列表
    """
    user_feedback: UserFeedback = {
        "action": action,  # type: ignore
        "comments": comments,
        "modifications": modifications,
        "approved_items": approved_items,
        "rejected_items": rejected_items
    }

    state["user_feedback"] = user_feedback
    state["pending_approval"] = False
    state["updated_at"] = datetime.utcnow().isoformat()

    # 清除检查点数据（已处理）
    state["checkpoint_data"] = None

    return {
        "success": True,
        "message": f"User feedback applied: {action}",
        "updated_fields": ["user_feedback", "pending_approval", "checkpoint_data", "updated_at"],
        "errors": None
    }


def clear_checkpoint(state: ComicDramaState) -> None:
    """
    清除检查点状态

    Args:
        state: 当前状态
    """
    state["checkpoint_data"] = None
    state["user_feedback"] = None
    state["pending_approval"] = False
    state["updated_at"] = datetime.utcnow().isoformat()


# ==================== 状态查询辅助函数 ====================

def get_character_by_name(state: ComicDramaState, name: str) -> Optional[CharacterState]:
    """
    根据名称获取角色

    Args:
        state: 当前状态
        name: 角色名称

    Returns:
        CharacterState or None
    """
    characters = state.get("characters", [])

    for char in characters:
        if char.get("name") == name:
            return char

    return None


def get_scene_by_name(state: ComicDramaState, name: str) -> Optional[SceneState]:
    """
    根据名称获取场景

    Args:
        state: 当前状态
        name: 场景名称

    Returns:
        SceneState or None
    """
    scenes = state.get("scenes", [])

    for scene in scenes:
        if scene.get("name") == name:
            return scene

    return None


def get_storyboard_by_sequence(state: ComicDramaState, sequence_number: int) -> Optional[StoryboardState]:
    """
    根据序号获取分镜

    Args:
        state: 当前状态
        sequence_number: 分镜序号

    Returns:
        StoryboardState or None
    """
    storyboards = state.get("storyboards", [])

    for sb in storyboards:
        if sb.get("sequence_number") == sequence_number:
            return sb

    return None


def get_pending_items(state: ComicDramaState, item_type: str) -> List[Any]:
    """
    获取指定类型中状态为 pending 的项目

    Args:
        state: 当前状态
        item_type: 项目类型（characters/scenes/storyboards/audio_segments/video_segments）

    Returns:
        List of pending items
    """
    items = state.get(item_type, [])  # type: ignore

    return [item for item in items if item.get("status") == "pending"]


def get_failed_items(state: ComicDramaState, item_type: str) -> List[Any]:
    """
    获取指定类型中状态为 failed 的项目

    Args:
        state: 当前状态
        item_type: 项目类型（characters/scenes/storyboards/audio_segments/video_segments）

    Returns:
        List of failed items
    """
    items = state.get(item_type, [])  # type: ignore

    return [item for item in items if item.get("status") == "failed"]


def get_completed_items(state: ComicDramaState, item_type: str) -> List[Any]:
    """
    获取指定类型中状态为 completed 的项目

    Args:
        state: 当前状态
        item_type: 项目类型（characters/scenes/storyboards/audio_segments/video_segments）

    Returns:
        List of completed items
    """
    items = state.get(item_type, [])  # type: ignore

    return [item for item in items if item.get("status") == "completed"]


def is_stage_completed(state: ComicDramaState, stage: str) -> bool:
    """
    检查指定阶段是否已完成

    Args:
        state: 当前状态
        stage: 阶段名称

    Returns:
        bool: 是否完成
    """
    current_stage = state.get("current_stage", "init")

    stage_order = [
        "init",
        "script_analysis",
        "asset_generation",
        "storyboard_creation",
        "audio_processing",
        "video_generation",
        "editing",
        "completed"
    ]

    if stage not in stage_order or current_stage not in stage_order:
        return False

    return stage_order.index(current_stage) > stage_order.index(stage)
