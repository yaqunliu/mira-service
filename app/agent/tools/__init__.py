"""
Agent 工具模块

导出所有 Agent 可用的工具类

新的细粒度工具架构：
- 查询工具 (db_tools)
- 模板工具 (template_tools)
- 提示词生成工具 (prompt_generation_tools)
- 保存工具 (save_tools)
- 生成触发工具 (generation_trigger_tools)
- 知识库工具 (video_knowledge_tools)
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
    # 新增单个资源查询
    query_single_character,
    query_single_scene,
    query_single_shot,
    query_creation_info,
)

# Supervisor 原子化工具
from app.agent.tools.regenerate_worker_tools import (
    clear_asset,
    update_resource_status,
    submit_generation,
    regenerate,
    regenerate_with_poll,
    clear_all,
    query_generation_tasks_status,
    REGENERATE_WORKER_TOOLS,
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

# ==================== 新的细粒度工具架构 ====================

# 模板工具
from app.agent.tools.template_tools import (
    get_character_prompt_template,
    get_scene_prompt_template,
    get_shot_image_prompt_template,
    get_shot_video_prompt_template,
    get_visual_style_guide,
    TEMPLATE_TOOLS,
)

# 保存工具
from app.agent.tools.save_tools import (
    save_character_prompt,
    save_scene_prompt,
    save_shot_image_prompt,
    save_shot_video_prompt,
    SAVE_TOOLS,
)

# 视频知识库工具
from app.agent.tools.video_knowledge_tools import (
    query_knowledge_for_video,
    query_camera_techniques,
    query_composition_rules,
    VIDEO_KNOWLEDGE_TOOLS,
)

# 数据库保存工具（保持兼容）
from app.agent.tools.db_tools import (
    save_shot_video_prompt,
    batch_save_video_prompts,
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
    "query_single_character",
    "query_single_scene",
    "query_single_shot",
    "query_creation_info",

    # Supervisor 原子化工具
    "clear_asset",
    "update_resource_status",
    "submit_generation",
    "regenerate",
    "regenerate_with_poll",
    "clear_all",
    "query_generation_tasks_status",
    "REGENERATE_WORKER_TOOLS",

    # 批量生成工具
    "batch_submit_character_images",
    "batch_submit_scene_images",
    "batch_save_character_prompts",
    "batch_save_scene_prompts",

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

    # ==================== 新的细粒度工具 ====================

    # 模板工具
    "get_character_prompt_template",
    "get_scene_prompt_template",
    "get_shot_image_prompt_template",
    "get_shot_video_prompt_template",
    "get_visual_style_guide",
    "TEMPLATE_TOOLS",

    # 保存工具
    "save_character_prompt",
    "save_scene_prompt",
    "save_shot_image_prompt",
    "save_shot_video_prompt",
    "SAVE_TOOLS",

    # 视频知识库工具
    "query_knowledge_for_video",
    "query_camera_techniques",
    "query_composition_rules",
    "VIDEO_KNOWLEDGE_TOOLS",

    # 数据库保存工具
    "save_shot_video_prompt",
    "batch_save_video_prompts",
]
