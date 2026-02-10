# 创作团队 Nodes
"""
创作团队各角色的 LLM 节点

Supervisor Agent 模式:
- supervisor: 决策中心，单次 LLM 决策，调度 Workers

Workers:
- script_analyst: 剧本分析师 - 分析剧本提取角色和场景
- character_scene_generator: 角色场景生成器 - 生成角色和场景的提示词+图片
- storyboard_director: 分镜导演 - 创建分镜脚本
- shot_generator: 分镜图片生成器 - 生成分镜首尾帧图片
- audio_engineer: 音频工程师 - 生成配音
- video_editor: 视频编辑师 - 生成视频片段
- asset_regenerator: 资产重新生成器 - 重新生成图片/提示词/视频

ReAct 支持：
- react_worker_base: ReAct Worker 基类
"""

from app.agent.graph.nodes.teams.supervisor import supervisor_node, route_from_supervisor
from app.agent.graph.nodes.teams.react_worker_base import ReActWorkerNode
from app.agent.graph.nodes.teams.script_analyst import ScriptAnalystNode
from app.agent.graph.nodes.teams.storyboard_director import StoryboardDirectorNode
from app.agent.graph.nodes.teams.audio_engineer import AudioEngineerNode
from app.agent.graph.nodes.teams.video_editor import VideoEditorNode
from app.agent.graph.nodes.teams.asset_regenerator_worker import (
    AssetRegeneratorWorkerNode,
    regenerate_assets_worker,
)
# 角色场景生成 Worker
from app.agent.graph.nodes.teams.character_scene_generation_worker import (
    CharacterSceneGenerationWorkerNode,
    generate_character_scene_worker,
)
# 新增：分镜图片生成 Worker
from app.agent.graph.nodes.teams.shot_generation_worker import (
    ShotGenerationWorkerNode,
    generate_shot_worker,
)
# 新增：视频提示词构建 Worker
from app.agent.graph.nodes.teams.video_prompt_builder import (
    VideoPromptBuilderNode,
    video_prompt_builder_worker,
)

__all__ = [
    # Supervisor
    "supervisor_node",
    "route_from_supervisor",
    # Workers
    "ReActWorkerNode",
    "ScriptAnalystNode",
    "StoryboardDirectorNode",
    "AudioEngineerNode",
    "VideoEditorNode",
    # Asset Regenerator
    "AssetRegeneratorWorkerNode",
    "regenerate_assets_worker",
    # Character & Scene Generation
    "CharacterSceneGenerationWorkerNode",
    "generate_character_scene_worker",
    # Shot Generation (新版)
    "ShotGenerationWorkerNode",
    "generate_shot_worker",
    # Video Prompt Builder
    "VideoPromptBuilderNode",
    "video_prompt_builder_worker",
]

