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


class BoardActionType(StrEnum):
    """
    Board 交互类型 - 用于人工介入
    """
    APPROVE_REJECT = "approve_reject"     # 同意/拒绝
    TEXT_INPUT = "text_input"             # 文本输入
    SELECT_OPTIONS = "select_options"     # 多选项选择


class BoardAction(TypedDict, total=False):
    """
    看板联动动作 - 控制前端看板的行为和人工交互
    
    用途：
    1. 视图控制：switch_view, highlight, scroll, update, refresh
    2. 人工介入：approve_reject, text_input, select_options
    """
    type: str  # BoardActionType 或视图控制类型
    target: Optional[str]  # 目标元素 ID 或视图名称
    message: Optional[str]  # 提示信息（人工介入时）
    options: Optional[List[Dict[str, Any]]]  # 选项列表 [{id, text}]
    input_placeholder: Optional[str]  # 输入框占位符
    data: Optional[Dict[str, Any]]  # 附加数据



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

    # ==================== 知识库上下文 ====================
    shot_knowledge_context: Dict[int, str]  # 分镜知识上下文 {shot_id: knowledge_context}
    character_knowledge_context: Dict[int, str]  # 角色知识上下文
    scene_knowledge_context: Dict[int, str]  # 场景知识上下文

    # ==================== 输入数据 ====================
    script_text: Optional[str]  # 原始剧本文本（用户上传或输入）
    script_url: Optional[str]  # 剧本文件 URL（US3）

    # ==================== 创作阶段 ====================
    # 子图阶段
    production_stage: ProductionStage  # 制作阶段
    
    # Supervisor 调度相关
    production_cache: Dict[str, Any]  # 生产状态缓存（避免重复 DB 查询）
    next_worker: Optional[str]  # Supervisor 调度的下一个 Worker
    needs_input: bool  # LLM 决策是否需要等待用户输入
    worker_result: Optional[Dict[str, Any]]  # Worker 执行结果（用于 Supervisor 决策）
    task_params: Optional[Dict[str, Any]]  # 任务参数（用于 Worker 执行）

    # ==================== 剧本分析结果 ====================
    script_summary: Optional[str]  # 剧本摘要
    script_theme: Optional[str]  # 主题
    script_style: Optional[str]  # 风格（悬疑/喜剧/动作等）

    # ==================== 资产数据 ====================
    characters: List[CharacterState]  # 角色列表
    scenes: List[SceneState]  # 场景列表
    # ==================== 错误处理 ====================
    errors: List[Dict[str, Any]]  # 错误记录
    error_message: Optional[str]  # 当前错误信息

    # ==================== 配置信息 ====================
    config: Dict[str, Any]  # 配置选项（模型选择、生成策略等）

    # ==================== 元数据 ====================
    created_at: Optional[str]  # 创建时间（ISO 格式）
    updated_at: Optional[str]  # 更新时间（ISO 格式）
    extra_data: Optional[Dict[str, Any]]  # 扩展数据


