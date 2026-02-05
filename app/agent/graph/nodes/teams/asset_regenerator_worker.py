"""
Asset Regenerator Worker Node - 资产重新生成 Worker (ReAct 版本)

职责：
1. 分析用户意图（操作类型、目标资源）
2. 调用 Tools 查询资源信息
3. 调用 Tools 获取提示词模板
4. 调用 Tools 查询知识库（仅视频提示词需要）
5. 调用 Tools 生成提示词
6. 调用 Tools 保存提示词到数据库
7. 调用 Tools 触发生成任务（如需要）

基于 ReActWorkerNode 实现，支持多轮思考和工具调用。
新的细粒度工具架构，Agent 负责协调整个流程。
"""

from typing import Dict, Any, List
from datetime import datetime

from app.agent.state.schemas import ComicDramaState
from app.agent.graph.nodes.teams.react_worker_base import ReActWorkerNode
from app.core.logger import logger


class AssetRegeneratorWorkerNode(ReActWorkerNode):
    """
    资产重新生成 Worker Node (ReAct 版本)
    
    新的细粒度工具架构：
    - Agent 作为中央协调器
    - 每个步骤调用专门的工具
    - 完整的 ReAct 工作流
    
    工作流程：
    1. Thought: 分析用户意图（角色/场景/分镜？图片/提示词/视频？）
    2. Action: 调用查询工具获取资源信息
    3. Action: 调用模板工具获取提示词模板
    4. Action: 调用知识库工具获取专业知识（如需要）
    5. Thought: 构建完整提示词参数
    6. Action: 调用生成工具生成提示词
    7. Action: 调用保存工具保存到数据库
    8. Action: 调用触发工具启动生成（如需要）
    """
    
    USE_REACT = True
    
    def __init__(self):
        super().__init__(model="Qwen/Qwen-Plus", temperature=0.3)
    
    def get_system_prompt(self, state: ComicDramaState) -> str:
        """
        获取系统提示词

        根据用户消息检测目标类型，加载对应的提示词模板
        """
        user_message = state.get("user_message", "")
        creation_uuid = state.get("creation_uuid", "")
        target_type = self._detect_target_type(user_message)
        operation_type = self._detect_operation_type(user_message)
        frame_type = self._detect_frame_type(user_message) if target_type == "shot" else "both"

        from app.utils.file_utils import read_prompt_file

        # 获取系统提示词模板
        if target_type == "character":
            prompt_template = read_prompt_file("agent_regenerate_character.md")
        elif target_type == "scene":
            prompt_template = read_prompt_file("agent_regenerate_scene.md")
        else:  # shot
            prompt_template = read_prompt_file("agent_regenerate_shot.md")

        # 在提示词中注入 creation_uuid 和 frame_type
        if prompt_template:
            prompt_template = prompt_template.replace("{{CREATION_UUID}}", creation_uuid)
            prompt_template = prompt_template.replace("{{FRAME_TYPE}}", frame_type)

        # 添加新的细粒度工具使用指南
        tool_guide = self._get_tool_usage_guide(target_type, operation_type, frame_type)

        if tool_guide:
            prompt_template = (prompt_template or "") + tool_guide

        return prompt_template
    
    def _get_tool_usage_guide(self, target_type: str, operation_type: str, frame_type: str = "both") -> str:
        """获取工具使用指南"""

        # 根据操作类型确定是否强制触发生成
        is_trigger_required = operation_type in ["image", "video"]
        trigger_step_desc = "必须触发图片生成" if is_trigger_required else "可选：如果用户要求生成图片"

        base_guide = f"""

【细粒度工具使用指南】

用户操作类型: {operation_type}
检测到的帧类型: {frame_type}
你作为中央协调器，需要按顺序调用以下工具完成任务：

"""
        
        if target_type == "character":
            if operation_type == "image":
                # 用户明确要求生成图片 - 使用旧的直接提交工具
                guide = base_guide + """
### 角色图片生成流程（直接提交并等待完成）

**Step 1: 获取角色信息**
- 工具: `query_characters`
- 参数: creation_uuid
- 说明: 获取角色列表，找到匹配的角色名

**Step 2: 提交图片生成任务**
- 工具: `submit_character_image_regeneration`
- 参数:
  - character_id (从 Step 1 获取)
  - creation_uuid
  - mode="auto"
- 说明: 提交图片生成任务，返回 task_id
- 注意: 记录返回的 task_id，用于下一步查询状态

**Step 3: 查询任务状态（阻塞等待完成）**
- 工具: `query_generation_tasks_status`
- 参数:
  - task_ids: [task_id] (从 Step 2 获取的 task_id 列表)
  - target_info: [{"target_type": "character", "target_id": character_id}]
  - timeout: 1000 (最大等待1000秒)
  - poll_interval: 2.0 (每2秒查询一次)
- 说明: 轮询查询任务状态，直到任务完成或超时
- 返回: 包含所有任务的状态、结果、错误信息

**Step 4: 汇报生成结果**
- 根据 query_generation_tasks_status 的返回结果，汇报生成成功或失败
- 如果成功: 告知用户图片已生成完成
- 如果失败: 告知用户失败原因

【重要】用户说"生成图片"时：
1. 提交生成任务获取 task_id
2. 调用 query_generation_tasks_status 等待任务完成
3. 汇报最终结果给用户
"""
            elif operation_type == "prompt":
                # 生成提示词 - Node 自身生成
                guide = base_guide + """
### 角色提示词生成流程（Node 生成）

**Step 1: 获取角色信息**
- 工具: `query_single_character`
- 参数: character_id
- 说明: 获取角色的完整信息

**Step 2: 获取提示词模板**
- 工具: `get_character_prompt_template`
- 参数: template_type="regenerate"
- 说明: 获取角色提示词生成模板

**Step 3: 生成提示词（Node 自身完成）**
- 不需要调用工具！
- 基于 character_info 和 template_content，使用你的 LLM 能力生成提示词
- 参考 visual_style 确定风格

**Step 4: 保存提示词**
- 工具: `save_character_prompt`
- 参数: character_id, prompt (你生成的提示词)
- 说明: 保存到数据库

【重要】用户说"生成提示词"时：
1. 查询资源信息（工具）
2. 获取提示词模板（工具）
3. **你自己生成提示词**（使用你的 LLM，不是工具！）
4. 保存提示词（工具）
"""
            elif operation_type == "modify_prompt":
                # 修改提示词 - Node 自身生成
                guide = base_guide + """
### 角色提示词修改流程（Node 生成）

**Step 1: 获取角色信息**
- 工具: `query_single_character`
- 参数: character_id
- 说明: 获取角色的完整信息

**Step 2: 提取修改意见**
从用户消息中提取修改要求：
- "修改阿九的提示词，要求风格为日本动漫风格" → feedback="要求风格为日本动漫风格"
- "优化提示词，增加细节" → feedback="增加细节"

**Step 3: 获取提示词模板**
- 工具: `get_character_prompt_template`
- 参数: template_type="modify"
- 说明: 获取角色提示词修改模板

**Step 4: 生成提示词（Node 自身完成）**
- 不需要调用工具！
- 基于 character_info、原提示词、template_content 和 feedback
- 使用你的 LLM 能力修改提示词

**Step 5: 保存提示词**
- 工具: `save_character_prompt`
- 参数: character_id, prompt (你生成的提示词)
- 说明: 保存到数据库

【重要】用户说"修改提示词"时：
1. 查询资源信息（工具）
2. 提取修改意见
3. 获取提示词模板（工具）
4. **你自己修改提示词**（使用你的 LLM，不是工具！）
5. 保存提示词（工具）
"""
            else:
                # 默认：直接提交图片生成
                guide = base_guide + """
### 角色图片生成流程（直接提交并等待完成）

**Step 1: 获取角色信息**
- 工具: `query_characters`
- 参数: creation_uuid
- 说明: 获取角色列表，找到匹配的角色名

**Step 2: 提交图片生成任务**
- 工具: `submit_character_image_regeneration`
- 参数:
  - character_id (从 Step 1 获取)
  - creation_uuid
  - mode="auto"
- 说明: 提交图片生成任务，返回 task_id

**Step 3: 查询任务状态（阻塞等待完成）**
- 工具: `query_generation_tasks_status`
- 参数:
  - task_ids: [task_id]
  - target_info: [{"target_type": "character", "target_id": character_id}]
  - timeout: 1000
  - poll_interval: 2.0
- 说明: 轮询查询任务状态，直到任务完成或超时

**Step 4: 汇报生成结果**
- 根据查询结果，汇报生成成功或失败
"""
        elif target_type == "scene":
            if operation_type == "image":
                guide = base_guide + """
### 场景图片生成流程（直接提交并等待完成）

**Step 1: 获取场景信息**
- 工具: `query_scenes`
- 参数: creation_uuid
- 说明: 获取场景列表，找到匹配的场景名

**Step 2: 提交图片生成任务**
- 工具: `submit_scene_image_regeneration`
- 参数:
  - scene_id (从 Step 1 获取)
  - creation_uuid
- 说明: 提交图片生成任务，返回 task_id

**Step 3: 查询任务状态（阻塞等待完成）**
- 工具: `query_generation_tasks_status`
- 参数:
  - task_ids: [task_id]
  - target_info: [{"target_type": "scene", "target_id": scene_id}]
  - timeout: 1000
  - poll_interval: 2.0
- 说明: 轮询查询任务状态，直到任务完成或超时

**Step 4: 汇报生成结果**
- 根据查询结果，汇报生成成功或失败

【重要】用户说"生成图片"时：
1. 提交生成任务获取 task_id
2. 调用 query_generation_tasks_status 等待任务完成
3. 汇报最终结果给用户
"""
            elif operation_type == "prompt":
                guide = base_guide + """
### 场景提示词生成流程（Node 生成）

**Step 1: 获取场景信息**
- 工具: `query_single_scene`
- 参数: scene_id
- 说明: 获取场景的完整信息

**Step 2: 获取提示词模板**
- 工具: `get_scene_prompt_template`
- 参数: template_type="regenerate"
- 说明: 获取场景提示词生成模板

**Step 3: 生成提示词（Node 自身完成）**
- 不需要调用工具！
- 基于 scene_info 和 template_content，使用你的 LLM 能力生成提示词
- 参考 visual_style 确定风格

**Step 4: 保存提示词**
- 工具: `save_scene_prompt`
- 参数: scene_id, prompt (你生成的提示词)
- 说明: 保存到数据库
"""
            elif operation_type == "modify_prompt":
                guide = base_guide + """
### 场景提示词修改流程（Node 生成）

**Step 1: 获取场景信息**
- 工具: `query_single_scene`
- 参数: scene_id
- 说明: 获取场景的完整信息

**Step 2: 提取修改意见**
从用户消息中提取修改要求：
- "修改客厅的提示词，增加阳光" → feedback="增加阳光"
- "优化提示词，让氛围更暗" → feedback="让氛围更暗"

**Step 3: 获取提示词模板**
- 工具: `get_scene_prompt_template`
- 参数: template_type="modify"
- 说明: 获取场景提示词修改模板

**Step 4: 生成提示词（Node 自身完成）**
- 不需要调用工具！
- 基于 scene_info、原提示词、template_content 和 feedback
- 使用你的 LLM 能力修改提示词

**Step 5: 保存提示词**
- 工具: `save_scene_prompt`
- 参数: scene_id, prompt (你生成的提示词)
- 说明: 保存到数据库
"""
            else:
                guide = base_guide + """
### 场景图片生成流程（直接提交并等待完成）

**Step 1: 获取场景信息**
- 工具: `query_scenes`
- 参数: creation_uuid
- 说明: 获取场景列表，找到匹配的场景名

**Step 2: 提交图片生成任务**
- 工具: `submit_scene_image_regeneration`
- 参数:
  - scene_id (从 Step 1 获取)
  - creation_uuid
- 说明: 提交图片生成任务，返回 task_id

**Step 3: 查询任务状态（阻塞等待完成）**
- 工具: `query_generation_tasks_status`
- 参数:
  - task_ids: [task_id]
  - target_info: [{"target_type": "scene", "target_id": scene_id}]
  - timeout: 1000
  - poll_interval: 2.0
- 说明: 轮询查询任务状态，直到任务完成或超时

**Step 4: 汇报生成结果**
- 根据查询结果，汇报生成成功或失败
"""
        else:  # shot
            if operation_type == "video":
                guide = base_guide + """
### 分镜视频生成流程（直接提交并等待完成）

**Step 1: 获取分镜信息**
- 工具: `query_shots`
- 参数: creation_uuid
- 说明: 获取分镜列表，找到匹配的分镜编号

**Step 2: 提交视频生成任务**
- 工具: `submit_shot_video_regeneration`
- 参数:
  - shot_id (从 Step 1 获取)
  - creation_uuid
  - generation_mode="first_last_frame"（默认）或 "first_frame_only"
- 说明: 提交视频生成任务，返回 task_id

**Step 3: 查询任务状态（阻塞等待完成）**
- 工具: `query_generation_tasks_status`
- 参数:
  - task_ids: [task_id]
  - target_info: [{"target_type": "shot", "target_id": shot_id}]
  - timeout: 1000
  - poll_interval: 2.0
- 说明: 轮询查询任务状态，直到任务完成或超时

**Step 4: 汇报生成结果**
- 根据查询结果，汇报生成成功或失败

【重要】用户说"生成视频"时：
1. 提交生成任务获取 task_id
2. 调用 query_generation_tasks_status 等待任务完成
3. 汇报最终结果给用户
"""
            elif operation_type == "image":
                guide = base_guide + f"""
### 分镜图片生成流程（直接提交并等待完成）

**Step 1: 获取分镜信息**
- 工具: `query_shots`
- 参数: creation_uuid
- 说明: 获取分镜列表，找到匹配的分镜编号

**Step 2: 提交图片生成任务**
- 工具: `submit_shot_image_regeneration`
- 参数:
  - shot_id (从 Step 1 获取)
  - creation_uuid
  - frame_type="{frame_type}"  # 检测到的帧类型
- 说明: 提交图片生成任务，返回 task_id

**Step 3: 查询任务状态（阻塞等待完成）**
- 工具: `query_generation_tasks_status`
- 参数:
  - task_ids: [task_id]
  - target_info: [{"target_type": "shot", "target_id": shot_id}]
  - timeout: 1000
  - poll_interval: 2.0
- 说明: 轮询查询任务状态，直到任务完成或超时

**Step 4: 汇报生成结果**
- 根据查询结果，汇报生成成功或失败

【重要】用户说"生成图片"时：
1. 提交生成任务获取 task_id
2. 调用 query_generation_tasks_status 等待任务完成
3. 汇报最终结果给用户

根据用户消息自动检测 frame_type：
- "首帧"、"第一帧" → frame_type="start"
- "尾帧"、"最后一帧" → frame_type="end"
- 无明确指定 → frame_type="both"
"""
            elif operation_type == "prompt":
                guide = base_guide + f"""
### 分镜提示词生成流程（Node 生成）

**Step 1: 获取分镜信息**
- 工具: `query_single_shot`
- 参数: shot_id
- 说明: 获取分镜的完整信息，包含关联场景和上一个分镜

**Step 2: 判断提示词类型**
- 图片提示词：prompt_type="image"
- 视频提示词：prompt_type="video"

**Step 3: 获取提示词模板**
- 图片提示词：工具 `get_shot_image_prompt_template`，参数 frame_type="{frame_type}"
- 视频提示词：工具 `get_shot_video_prompt_template`

**Step 4: 查询知识库（仅视频提示词需要）**
- 工具: `query_knowledge_for_video`
- 参数:
  - shot_description: 分镜描述（从 shot_info 获取）
  - query_keywords: **你提取的关键词列表**（如 ["运镜", "特写", "手持"]，不要传整个描述！）
  - top_k: 5
- 说明: 查询运镜技巧、构图法则等专业知识
- **重要**: 自己分析分镜内容，提取 3-5 个关键词，不要直接传整个 shot_description！

**Step 5: 生成提示词（Node 自身完成）**
- 不需要调用工具！
- 基于 shot_info、scene_info、template_content 和知识库结果
- 使用你的 LLM 能力生成提示词
- 参考 visual_style 确定风格

**Step 6: 保存提示词**
- 图片提示词：工具 `save_shot_image_prompt`，参数 frame_type="{frame_type}"
- 视频提示词：工具 `save_shot_video_prompt`
- 说明: 保存到数据库

frame_type 自动检测规则：
- "首帧"、"第一帧" → frame_type="start"
- "尾帧"、"最后一帧" → frame_type="end"
- 无明确指定 → frame_type="both"
"""
            elif operation_type == "modify_prompt":
                guide = base_guide + f"""
### 分镜提示词修改流程（Node 生成）

**Step 1: 获取分镜信息**
- 工具: `query_single_shot`
- 参数: shot_id
- 说明: 获取分镜的完整信息，包含关联场景和上一个分镜

**Step 2: 判断提示词类型并提取修改意见**
- 图片提示词：prompt_type="image"
- 视频提示词：prompt_type="video"
从用户消息中提取修改要求：
- "修改分镜5的提示词，增加运镜细节" → feedback="增加运镜细节"

**Step 3: 获取提示词模板**
- 图片提示词：工具 `get_shot_image_prompt_template`，参数 frame_type="{frame_type}"
- 视频提示词：工具 `get_shot_video_prompt_template`

**Step 4: 查询知识库（仅视频提示词需要）**
- 工具: `query_knowledge_for_video`
- 参数:
  - shot_description: 分镜描述（从 shot_info 获取）
  - query_keywords: **你提取的关键词列表**（如 ["运镜", "特写", "手持"]，不要传整个描述！）
  - top_k: 5
- 说明: 查询运镜技巧、构图法则等专业知识
- **重要**: 自己分析分镜内容，提取 3-5 个关键词，不要直接传整个 shot_description！

**Step 5: 生成提示词（Node 自身完成）**
- 不需要调用工具！
- 基于 shot_info、scene_info、原提示词、template_content、feedback 和知识库结果
- 使用你的 LLM 能力修改提示词

**Step 6: 保存提示词**
- 图片提示词：工具 `save_shot_image_prompt`，参数 frame_type="{frame_type}"
- 视频提示词：工具 `save_shot_video_prompt`
- 说明: 保存到数据库

frame_type 自动检测规则：
- "首帧"、"第一帧" → frame_type="start"
- "尾帧"、"最后一帧" → frame_type="end"
- 无明确指定 → frame_type="both"
"""
            else:
                guide = base_guide + f"""
### 分镜图片生成流程（直接提交）

**Step 1: 获取分镜信息**
- 工具: `query_shots`
- 参数: creation_uuid
- 说明: 获取分镜列表，找到匹配的分镜编号

**Step 2: 提交图片生成任务**
- 工具: `submit_shot_image_regeneration`
- 参数: 
  - shot_id (从 Step 1 获取)
  - creation_uuid
  - frame_type="{frame_type}"  # 检测到的帧类型
- 说明: 提交图片生成任务

frame_type 自动检测规则：
- "首帧"、"第一帧" → frame_type="start"
- "尾帧"、"最后一帧" → frame_type="end"
- 无明确指定 → frame_type="both"
"""
        
        guide += """

【重要提示】
1. 严格按照上述步骤顺序执行
2. 每个步骤必须等待上一步完成（获取 Observation）
3. 将上一步的结果作为下一步的参数
4. 如果某一步失败，停止执行并报告错误
5. 完成后汇总所有执行结果

【输出格式】
直接调用工具，不需要额外输出。完成后返回执行摘要。
"""
        
        return guide
    
    def _detect_target_type(self, user_message: str) -> str:
        """
        检测目标类型（角色/场景/分镜）
        """
        msg_lower = user_message.lower()
        
        if any(kw in msg_lower for kw in ["角色", "人物", "演员"]):
            return "character"
        
        if any(kw in msg_lower for kw in ["场景", "背景", "环境"]):
            return "scene"
        
        return "shot"
    
    def _detect_operation_type(self, user_message: str) -> str:
        """
        检测操作类型（图片/视频/提示词/修改提示词）
        """
        msg_lower = user_message.lower()
        
        if any(kw in msg_lower for kw in ["视频", "video", "motion"]):
            return "video"
        
        # 修改提示词 - 使用 submit_*_prompt_regeneration (operation_type="modify")
        if any(kw in msg_lower for kw in ["修改提示词", "改一下提示词", "优化提示词", "调整提示词", "更新提示词"]):
            return "modify_prompt"
        
        # 生成提示词 - 使用 submit_*_prompt_regeneration (operation_type="regenerate")
        if any(kw in msg_lower for kw in ["生成提示词", "重新生成提示词", "生图提示词", "生视频提示词", "提示词"]):
            return "prompt"
        
        if any(kw in msg_lower for kw in ["图片", "图像", "image", "图", "生图"]):
            return "image"
        
        return "image"  # 默认图片生成
    
    def _detect_frame_type(self, user_message: str) -> str:
        """
        检测分镜帧类型（首帧/尾帧/全部）
        仅用于分镜图片生成
        """
        msg_lower = user_message.lower()
        
        # 只生成首帧
        if any(kw in msg_lower for kw in ["首帧", "第一帧", "开始帧", "start"]):
            return "start"
        
        # 只生成尾帧
        if any(kw in msg_lower for kw in ["尾帧", "最后一帧", "结束帧", "end"]):
            return "end"
        
        # 默认生成全部
        return "both"
    
    def get_tools(self) -> List:
        """
        获取可用工具列表
        
        根据操作类型提供不同的工具集：
        - 生成图片/视频：使用旧的直接提交工具（submit_*）
        - 生成提示词：使用新的细粒度工具链
        """
        # 获取当前状态中的用户消息
        # 注意：get_tools 在 run 方法中被调用，此时 state 还未设置
        # 我们需要通过其他方式获取 operation_type，或者在 run 中动态选择工具
        
        # 查询类工具（所有操作都需要）
        from app.agent.tools.db_tools import (
            query_characters,
            query_scenes,
            query_shots,
            query_single_character,
            query_single_scene,
            query_single_shot,
            query_creation_info,
        )
        
        # 旧的直接提交工具（用于生成图片/视频）和状态查询
        from app.agent.tools.regenerate_worker_tools import (
            submit_character_image_regeneration,
            submit_scene_image_regeneration,
            submit_shot_image_regeneration,
            submit_shot_video_regeneration,
            query_generation_tasks_status,
        )
        
        # 新的细粒度工具（用于生成提示词）
        from app.agent.tools.template_tools import (
            get_character_prompt_template,
            get_scene_prompt_template,
            get_shot_image_prompt_template,
            get_shot_video_prompt_template,
            get_visual_style_guide,
        )
        # 注意：提示词生成由 Node 自身的 LLM 完成，不需要调用外部工具
        from app.agent.tools.save_tools import (
            save_character_prompt,
            save_scene_prompt,
            save_shot_image_prompt,
            save_shot_video_prompt,
        )
        from app.agent.tools.video_knowledge_tools import (
            query_knowledge_for_video,
            query_camera_techniques,
            query_composition_rules,
        )

        return [
            # === 查询类 ===
            query_characters,
            query_scenes,
            query_shots,
            query_single_character,
            query_single_scene,
            query_single_shot,
            query_creation_info,

            # === 图片/视频生成（直接提交）===
            submit_character_image_regeneration,
            submit_scene_image_regeneration,
            submit_shot_image_regeneration,
            submit_shot_video_regeneration,

            # === 提示词模板（用于指导 Node 生成提示词）===
            get_character_prompt_template,
            get_scene_prompt_template,
            get_shot_image_prompt_template,
            get_shot_video_prompt_template,
            get_visual_style_guide,

            # === 保存提示词 ===
            save_character_prompt,
            save_scene_prompt,
            save_shot_image_prompt,
            save_shot_video_prompt,

            # === 知识库（仅视频提示词需要）===
            query_knowledge_for_video,
            query_camera_techniques,
            query_composition_rules,

            # === 任务状态查询（用于等待生成完成）===
            query_generation_tasks_status,
        ]
    
    async def process_result(self, state: ComicDramaState, final_response: str, tool_results: List[Dict]) -> Dict[str, Any]:
        """
        处理 ReAct 循环的最终结果
        
        统计各步骤执行情况，构建响应
        """
        logger.info(f"[{self.node_name}] 处理结果，工具调用次数: {len(tool_results)}")
        
        # 分类统计
        query_count = 0
        template_count = 0
        generation_count = 0
        save_count = 0
        knowledge_count = 0
        trigger_count = 0
        
        success_count = 0
        failed_count = 0
        
        for result in tool_results:
            tool_name = result.get("tool", "")
            tool_result = result.get("result", {})
            
            # 判断工具调用是否成功
            # 新工具有 success 字段，旧工具通过检查是否有 error 字段来判断
            if "success" in tool_result:
                is_success = tool_result.get("success", False)
            else:
                # 旧工具：没有 error 字段即为成功
                is_success = "error" not in tool_result
            
            if is_success:
                success_count += 1
            else:
                failed_count += 1
            
            # 分类计数
            if "query_" in tool_name:
                query_count += 1
            elif "get_" in tool_name and "template" in tool_name:
                template_count += 1
            elif "generate_" in tool_name:
                generation_count += 1
            elif "save_" in tool_name:
                save_count += 1
            elif "trigger_" in tool_name:
                trigger_count += 1
            elif "knowledge" in tool_name or "query_camera" in tool_name:
                knowledge_count += 1
        
        # 构建响应消息
        response_text = f"执行完成！\n\n"
        response_text += f"📊 执行统计：\n"
        response_text += f"- 查询操作: {query_count} 次\n"
        response_text += f"- 模板获取: {template_count} 次\n"
        if knowledge_count > 0:
            response_text += f"- 知识库查询: {knowledge_count} 次\n"
        response_text += f"- 提示词生成: {generation_count} 次\n"
        response_text += f"- 保存操作: {save_count} 次\n"
        if trigger_count > 0:
            response_text += f"- 触发生成: {trigger_count} 次\n"
        
        response_text += f"\n✅ 成功: {success_count} | ❌ 失败: {failed_count}\n"
        
        # 添加详细结果
        if tool_results:
            response_text += "\n**详细执行记录：**\n"
            for i, result in enumerate(tool_results, 1):
                tool_name = result.get("tool", "unknown")
                tool_result = result.get("result", {})
                is_success = tool_result.get("success", False)
                status = "✅" if is_success else "❌"
                
                # 提取关键信息
                detail = ""
                if "character" in tool_name and "character_id" in tool_result:
                    detail = f" (角色 {tool_result['character_id']})"
                elif "scene" in tool_name and "scene_id" in tool_result:
                    detail = f" (场景 {tool_result['scene_id']})"
                elif "shot" in tool_name and "shot_id" in tool_result:
                    detail = f" (分镜 {tool_result['shot_id']})"
                
                response_text += f"{i}. {status} {tool_name}{detail}\n"
        
        return {
            "success": success_count > 0 and failed_count == 0,
            "response_text": response_text,
            "success_count": success_count,
            "failed_count": failed_count,
            "tool_results": tool_results,
            "worker_result": {
                "worker": "asset_regenerator",
                "summary": f"执行了 {len(tool_results)} 个工具调用",
                "success": success_count > 0,
                "completed": True,
                "response_text": response_text,
            },
        }


# 便捷函数
async def regenerate_assets_worker(state: ComicDramaState) -> Dict[str, Any]:
    """LangGraph node 函数"""
    node = AssetRegeneratorWorkerNode()
    return await node.run(state)
