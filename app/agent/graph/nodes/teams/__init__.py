# 创作团队 Nodes
"""
创作团队各角色的 LLM 节点

Supervisor Agent 模式:
- supervisor: 决策中心，单次 LLM 决策，调度 Workers

Workers:
- script_analyst: 剧本分析师 - 分析剧本提取角色和场景
- asset_director: 资产总监 - 生成角色/场景图片
- storyboard_director: 分镜导演 - 生成分镜脚本
- audio_engineer: 音频工程师 - 生成配音
- video_editor: 视频编辑师 - 生成视频片段

ReAct 支持：
- react_worker_base: ReAct Worker 基类
"""

from app.agent.graph.nodes.teams.supervisor import supervisor_node, route_from_supervisor
from app.agent.graph.nodes.teams.react_worker_base import ReActWorkerNode
from app.agent.graph.nodes.teams.script_analyst import ScriptAnalystNode
from app.agent.graph.nodes.teams.asset_director import AssetDirectorNode
from app.agent.graph.nodes.teams.storyboard_director import StoryboardDirectorNode
from app.agent.graph.nodes.teams.audio_engineer import AudioEngineerNode
from app.agent.graph.nodes.teams.video_editor import VideoEditorNode, FinalEditorNode

__all__ = [
    # Supervisor
    "supervisor_node",
    "route_from_supervisor",
    # Workers
    "ReActWorkerNode",
    "ScriptAnalystNode",
    "AssetDirectorNode", 
    "StoryboardDirectorNode",
    "AudioEngineerNode",
    "VideoEditorNode",
    "FinalEditorNode",
]

