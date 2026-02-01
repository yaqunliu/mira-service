"""
LangGraph State Schemas
定义 ComicDramaState 及相关子状态的 TypedDict
"""

from typing import TypedDict, Optional, List, Dict, Any, Literal
from datetime import datetime
from enum import StrEnum


# ==================== 子状态定义 ====================

class CharacterState(TypedDict, total=False):
    """角色状态"""
    character_id: Optional[int]  # 数据库 ID（已保存）
    name: str  # 角色名称
    description: str  # 角色描述
    personality: str  # 性格特征
    appearance: str  # 外貌描述
    image_prompt: Optional[str]  # 图像生成提示词
    image_url: Optional[str]  # 角色形象图 URL
    voice_id: Optional[str]  # 语音模型 ID（Fish Audio）
    voice_speed: Optional[str]  # 语速 (0.5-2.0)
    status: Literal["pending", "generating", "completed", "failed"]  # 生成状态
    error: Optional[str]  # 错误信息


class SceneState(TypedDict, total=False):
    """场景状态"""
    scene_id: Optional[int]  # 数据库 ID（已保存）
    name: str  # 场景名称
    description: str  # 场景描述
    location: str  # 地点
    time: str  # 时间（白天/夜晚/黄昏等）
    mood: str  # 氛围（欢快/悲伤/紧张等）
    image_prompt: Optional[str]  # 图像生成提示词
    image_url: Optional[str]  # 场景图 URL
    status: Literal["pending", "generating", "completed", "failed"]
    error: Optional[str]


class StoryboardState(TypedDict, total=False):
    """分镜状态"""
    shot_id: Optional[int]  # 数据库 ID（已保存）
    sequence_number: int  # 分镜序号
    character_names: List[str]  # 出场角色名称列表
    scene_name: str  # 所在场景名称
    shot_type: str  # 镜头类型（远景/特写/中景等）
    camera_movement: str  # 镜头运动（推/拉/摇/移等）
    dialogue: Optional[str]  # 对话文本
    narration: Optional[str]  # 旁白文本
    duration: float  # 时长（秒）
    image_prompt: str  # 分镜图生成提示词
    image_url: Optional[str]  # 分镜图 URL
    status: Literal["pending", "generating", "completed", "failed"]
    error: Optional[str]


class AudioSegmentState(TypedDict, total=False):
    """音频片段状态"""
    segment_id: int  # 片段序号（对应分镜序号）
    audio_type: Literal["dialogue", "narration", "music", "sfx"]  # 音频类型
    text: Optional[str]  # 文本内容（TTS 用）
    voice_id: Optional[str]  # 语音模型 ID
    audio_url: Optional[str]  # 音频文件 URL
    duration: float  # 时长（秒）
    status: Literal["pending", "generating", "completed", "failed"]
    error: Optional[str]


class VideoSegmentState(TypedDict, total=False):
    """视频片段状态"""
    segment_id: int  # 片段序号（对应分镜序号）
    image_url: str  # 源图片 URL
    video_url: Optional[str]  # 生成的视频 URL
    duration: float  # 时长（秒）
    status: Literal["pending", "generating", "completed", "failed"]
    error: Optional[str]


class CheckpointData(TypedDict, total=False):
    """检查点数据（待审核）"""
    checkpoint_type: Literal["script_analysis", "asset_finalization", "storyboard_batch", "audio_confirmation", "final_review"]
    data: Dict[str, Any]  # 待审核的数据
    message: str  # 提示信息
    suggestions: Optional[List[str]]  # 建议


class UserFeedback(TypedDict, total=False):
    """用户反馈"""
    action: Literal["approve", "reject", "modify"]  # 用户操作
    comments: Optional[str]  # 反馈意见
    modifications: Optional[Dict[str, Any]]  # 修改内容
    approved_items: Optional[List[int]]  # 部分通过的项目 ID 列表
    rejected_items: Optional[List[int]]  # 驳回的项目 ID 列表


class ProductionStage(StrEnum):
    """
    制作阶段枚举
    
    用于子图内的阶段路由，比 current_stage 更细粒度
    """
    # 初始阶段
    INIT = "init"                           # 初始状态
    SCRIPT_UPLOADED = "script_uploaded"     # 剧本已上传
    
    # 剧本分析阶段
    SCRIPT_ANALYZING = "script_analyzing"   # 剧本分析中
    SCRIPT_ANALYZED = "script_analyzed"     # 剧本分析完成，待确认
    
    # 资产生成阶段
    ASSETS_GENERATING = "assets_generating" # 资产生成中
    ASSETS_READY = "assets_ready"           # 资产待确认（检查点）

    
    # 分镜创建阶段
    STORYBOARD_GENERATING = "storyboard_generating"
    STORYBOARD_READY = "storyboard_ready"   # 分镜待确认（检查点）

    
    # 音频处理阶段
    AUDIO_PROCESSING = "audio_processing"
    AUDIO_READY = "audio_ready"             # 音频待确认（检查点）
    
    # 视频生成阶段
    VIDEO_GENERATING = "video_generating"
    VIDEO_READY = "video_ready"             # 视频待确认（检查点）
    
    # 最终阶段
    EDITING = "editing"
    COMPLETED = "completed"
    ERROR = "error"


class BoardAction(TypedDict, total=False):
    """看板联动动作 - 控制前端看板的行为"""
    type: Literal["switch_view", "highlight", "scroll", "update", "refresh"]
    target: str  # 目标元素 ID 或视图名称
    data: Optional[Dict[str, Any]]  # 附加数据


class ProductionProgress(TypedDict, total=False):
    """
    各阶段制作进度详情
    
    用于子图路由决策和进度展示
    """
    script_analysis: Dict[str, Any]  # {"status": "completed", "characters": 5, "scenes": 3}
    asset_generation: Dict[str, Any]  # {"status": "in_progress", "completed": 3, "total": 8}
    storyboard: Dict[str, Any]        # {"status": "pending", "completed": 0, "total": 24}
    audio: Dict[str, Any]
    video: Dict[str, Any]
    editing: Dict[str, Any]


# ==================== 主状态定义 ====================

class ComicDramaState(TypedDict, total=False):
    """
    漫剧创作主状态 - LangGraph 的核心状态对象

    该状态贯穿整个创作流程，由各个 Agent 节点读取和更新
    """

    # ==================== 基本信息 ====================
    creation_uuid: str  # 创作项目 UUID
    thread_id: str  # LangGraph thread_id（用于 Checkpointer）
    user_id: int  # 用户 ID

    # ==================== 对话相关（新增） ====================
    user_message: Optional[str]  # 当前用户消息
    messages: List[Dict[str, Any]]  # 对话历史（LangChain BaseMessage 格式）
    
    # 意图识别结果
    detected_intent: Optional[str]  # 具体意图: analyze_character, generate_video...
    intent_category: Optional[str]  # 意图分类: task_intent, status_query, asset_action
    intent_confidence: float  # 置信度 0.0-1.0
    intent_details: Optional[Dict[str, Any]]  # 意图详情: {"target": "character_1", "action": "regenerate"}
    
    # 用户 Action（Human Review 响应）
    user_action: Optional[str]  # approve, reject, modify
    user_action_data: Optional[Dict[str, Any]]  # action 附加数据
    pending_action: Optional[str]  # 待处理的 action
    
    # 响应文本（用于 SSE 输出）
    response_text: Optional[str]  # 节点生成的响应文本
    awaiting_clarification: bool  # 是否等待用户澄清
    board_actions: List[BoardAction]  # 看板联动指令列表

    # ==================== 输入数据 ====================
    script_text: Optional[str]  # 原始剧本文本（用户上传或输入）
    script_url: Optional[str]  # 剧本文件 URL（US3）

    # ==================== 创作阶段 ====================
    current_stage: Literal[
        "init",  # 初始化
        "script_analysis",  # 剧本解析
        "asset_generation",  # 资产生成（角色+场景）
        "storyboard_creation",  # 分镜创建
        "audio_processing",  # 音频处理
        "video_generation",  # 视频生成
        "editing",  # 剪辑合成
        "completed",  # 完成
        "error",  # 错误
    ]
    
    # 子图阶段（更细粒度）
    production_stage: ProductionStage  # 细粒度制作阶段
    production_progress: ProductionProgress  # 各阶段详细进度

    # ==================== 剧本分析结果 ====================
    script_summary: Optional[str]  # 剧本摘要
    script_theme: Optional[str]  # 主题
    script_style: Optional[str]  # 风格（悬疑/喜剧/动作等）

    # ==================== 资产数据 ====================
    characters: List[CharacterState]  # 角色列表
    scenes: List[SceneState]  # 场景列表
    props: List[Dict[str, Any]]  # 道具列表（暂时简化为字典）

    # ==================== 分镜数据 ====================
    storyboards: List[StoryboardState]  # 分镜列表
    total_duration: Optional[float]  # 总时长（秒）

    # ==================== 音频数据 ====================
    audio_segments: List[AudioSegmentState]  # 音频片段列表
    final_audio_url: Optional[str]  # 最终合成音频 URL
    subtitle_url: Optional[str]  # 字幕文件 URL（SRT）

    # ==================== 视频数据 ====================
    video_segments: List[VideoSegmentState]  # 视频片段列表
    final_video_url: Optional[str]  # 最终合成视频 URL

    # ==================== 检查点控制 ====================
    checkpoint_data: Optional[CheckpointData]  # 当前检查点数据
    user_feedback: Optional[UserFeedback]  # 用户反馈
    pending_approval: bool  # 是否等待审核

    # ==================== 工具调用记录 ====================
    tool_calls: List[Dict[str, Any]]  # 工具调用历史
    retry_count: Dict[str, int]  # 重试计数器（按工具名称）

    # ==================== 错误处理 ====================
    errors: List[Dict[str, Any]]  # 错误记录
    error_message: Optional[str]  # 当前错误信息

    # ==================== 配置信息 ====================
    config: Dict[str, Any]  # 配置选项（模型选择、生成策略等）

    # ==================== 元数据 ====================
    created_at: Optional[str]  # 创建时间（ISO 格式）
    updated_at: Optional[str]  # 更新时间（ISO 格式）
    extra_data: Optional[Dict[str, Any]]  # 扩展数据


# ==================== 辅助类型 ====================

class StateUpdateResult(TypedDict):
    """状态更新结果"""
    success: bool
    message: str
    updated_fields: List[str]
    errors: Optional[List[str]]
