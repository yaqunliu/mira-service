"""
Agent 工具模块

导出所有 Agent 可用的工具类
"""

# 基础工具
from app.agent.tools.base import BaseTool, CeleryTaskTool
from app.agent.tools.script_loader import script_loader, ScriptLoader

# 剧本分析工具
from app.agent.tools.script_tools import (
    CharacterAnalysisTool,
    SceneAnalysisTool,
    ShotAnalysisTool,
)

# 资产生成工具
from app.agent.tools.generation_tools import (
    GenerateCharacterImageTool as CharacterImageGenerationTool,
    GenerateSceneImageTool as SceneImageGenerationTool,
    GenerateStoryboardImageTool as SingleSceneImageGenerationTool,
    GenerateVideoTool,
    GenerateAudioTool,
    LLMAnalysisTool,
    GeneratePromptTool,
)

# 分镜工具
from app.agent.tools.storyboard_tools import (
    BatchShotImageGenerationTool,
    SingleShotImageGenerationTool,
)

# 音视频工具
from app.agent.tools.video_tools import (
    VideoPromptGenerationTool,
)

from app.agent.tools.video_tools import (
    SceneVideoGenerationTool,
    SingleShotVideoGenerationTool,
    VideoEditingTool,
)

# 资产管理工具
from app.agent.tools.asset_tools import (
    ReadCharacterTool,
    WriteCharacterTool,
    ReadSceneTool,
    WriteSceneTool,
    SearchAssetsTool,
    ListAssetsTool,
)

# 审核工具
from app.agent.tools.review_tools import (
    ReviewCharacterTool,
    ReviewSceneTool,
    ReviewStoryboardTool,
    ReviewVideoSegmentTool,
    BatchReviewTool,
    QualityCheckTool,
)

# 编辑工具
from app.agent.tools.editing_tools import (
    ConcatenateVideoTool,
    AddAudioTrackTool,
    ApplyTransitionTool,
    AddSubtitleTool,
    ApplyFilterTool,
    AdjustTimingTool,
    FinalRenderTool,
)

# 异步数据库工具
from app.agent.tools.async_db import AsyncDBTool

__all__ = [
    # 基础
    "BaseTool",
    "CeleryTaskTool",
    "script_loader",
    "ScriptLoader",

    # 剧本分析
    "CharacterAnalysisTool",
    "SceneAnalysisTool",
    "ShotAnalysisTool",

    # 资产生成
    "CharacterImageGenerationTool",
    "SceneImageGenerationTool",
    "SingleSceneImageGenerationTool",
    "GenerateVideoTool",
    "GenerateAudioTool",
    "LLMAnalysisTool",
    "GeneratePromptTool",

    # 分镜
    "BatchShotImageGenerationTool",
    "SingleShotImageGenerationTool",

    # 音视频
    "VideoPromptGenerationTool",
    "SceneVideoGenerationTool",
    "SingleShotVideoGenerationTool",
    "VideoEditingTool",

    # 资产管理
    "ReadCharacterTool",
    "WriteCharacterTool",
    "ReadSceneTool",
    "WriteSceneTool",
    "SearchAssetsTool",
    "ListAssetsTool",

    # 审核
    "ReviewCharacterTool",
    "ReviewSceneTool",
    "ReviewStoryboardTool",
    "ReviewVideoSegmentTool",
    "BatchReviewTool",
    "QualityCheckTool",

    # 编辑
    "ConcatenateVideoTool",
    "AddAudioTrackTool",
    "ApplyTransitionTool",
    "AddSubtitleTool",
    "ApplyFilterTool",
    "AdjustTimingTool",
    "FinalRenderTool",

    # 数据库
    "AsyncDBTool",
]
