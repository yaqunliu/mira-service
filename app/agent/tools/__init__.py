"""
Agent 工具模块

导出所有 Agent 可用的工具类

注意: 生成相关功能已迁移到 agent_generation_tools.py
"""

# 基础工具
from app.agent.tools.base import BaseTool, CeleryTaskTool

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

# 数据库查询工具
from app.agent.tools.db_tools import (
    query_characters,
    query_scenes,
    query_shots,
    query_creation_status,
    find_resources_by_identifier,
    query_failed_resources,
)

# Supervisor 工具（原子化操作、版本管理、上下文）
from app.agent.tools.regenerate_tools import (
    clear_asset,
    submit_generation,
    regenerate,
    clear_all,
    REGENERATE_TOOLS,
)
from app.agent.tools.version_tools import (
    get_version_history,
    restore_version,
    VERSION_TOOLS,
)
from app.agent.tools.context_tools import (
    get_script_context,
    get_adjacent_shots,
    get_character_scene_for_shot,
    check_constraints,
    CONTEXT_TOOLS,
)

# 资源解析工具
from app.agent.tools.resource_resolver import (
    resolve_resource_reference,
)

__all__ = [
    # 基础
    "BaseTool",
    "CeleryTaskTool",

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
    
    # 数据库查询工具
    "query_characters",
    "query_scenes",
    "query_shots",
    "query_creation_status",
    "find_resources_by_identifier",
    "query_failed_resources",
    
    # Supervisor 原子化工具
    "clear_asset",
    "submit_generation",
    "regenerate",
    "clear_all",
    "REGENERATE_TOOLS",
    
    # 版本管理
    "get_version_history",
    "restore_version",
    "VERSION_TOOLS",
    
    # 上下文工具
    "get_script_context",
    "get_adjacent_shots",
    "get_character_scene_for_shot",
    "check_constraints",
    "CONTEXT_TOOLS",
    
    # 资源解析工具
    "resolve_resource_reference",
]
