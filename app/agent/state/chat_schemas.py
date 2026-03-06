"""
Chat 类型创作的 State 定义

完全独立于 ComicDramaState，用于智能创作模式（单词视频等）
"""

from typing import Dict, Any, List, Optional, TypedDict
from enum import StrEnum


class ChatStage(StrEnum):
    """Chat 创作阶段"""
    INIT = "init"                    # 初始化
    CONFIGURING = "configuring"      # 配置中（收集参数）
    GENERATING = "generating"        # 生成中
    COMPLETED = "completed"          # 完成
    FAILED = "failed"                # 失败


class VocabConfig(TypedDict, total=False):
    """单词视频配置"""
    words: List[str]                 # 单词列表
    difficulty: str                  # 难度: easy/medium/hard
    repetitions: int                 # 重复次数
    sentence_level: str              # 句子级别


class ChatState(TypedDict, total=False):
    """
    Chat 类型创作的 State
    
    与 ComicDramaState 完全独立，不包含角色/场景/分镜等动漫相关字段
    """
    # 基础信息
    creation_uuid: str
    thread_id: str
    user_id: int
    
    # 视频创作类型（用户选择后锁定，不可更改）
    video_type: Optional[str]  # vocab_video / gaoxiao_video / story_video
    
    # 对话相关
    user_message: Optional[str]
    messages: List[Dict[str, Any]]
    
    # 意图识别
    detected_intent: Optional[str]
    intent_category: Optional[str]
    intent_confidence: float
    intent_details: Dict[str, Any]
    
    # 创作阶段
    chat_stage: ChatStage
    
    # 创作配置（根据类型不同）
    vocab_config: VocabConfig  # vocab_video 类型使用
    gaoxiao_config: Dict[str, Any]  # gaoxiao_video 类型使用
    story_config: Dict[str, Any]  # story_video 类型使用
    
    # 输出
    response_text: Optional[str]
    final_video_url: Optional[str]
    
    # 看板动作（触发前端卡片显示）
    board_actions: List[Dict[str, Any]]
    
    # 错误处理
    errors: List[str]
    
    # 时间戳
    updated_at: Optional[str]
    
    # 路由控制
    should_generate: bool  # 是否需要生成视频
    next_node: Optional[str]  # 下一个节点：vocab_worker / gaoxiao_worker / story_worker
