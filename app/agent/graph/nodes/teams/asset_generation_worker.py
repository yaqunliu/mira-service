"""
Asset Generation Worker Node - 资产生成 Worker (ReAct 版本)

职责：
1. 分析用户意图（单个/全部，角色/场景/分镜，提示词/图片/视频）
2. 调用 Tools 查询资源信息
3. 调用 Tools 获取提示词模板
4. 调用 Tools 查询知识库（仅视频提示词需要）
5. Node 自身生成提示词
6. 调用 Tools 保存提示词到数据库
7. 调用 Tools 提交生成任务
8. 调用 Tools 查询任务状态，等待完成

支持：
- 单个生成：单个角色/场景/分镜的提示词、图片、视频
- 全部生成：批量生成所有角色/场景/分镜的提示词、图片、视频

基于 ReActWorkerNode 实现，支持多轮思考和工具调用。
"""

from typing import Dict, Any, List, Optional
from datetime import datetime

from app.agent.state.schemas import ComicDramaState, ProductionStage
from app.agent.graph.nodes.teams.react_worker_base import ReActWorkerNode
from app.core.logger import logger


class AssetGenerationWorkerNode(ReActWorkerNode):
    """
    资产生成 Worker Node (ReAct 版本)

    新的细粒度工具架构：
    - Agent 作为中央协调器
    - 每个步骤调用专门的工具
    - 完整的 ReAct 工作流
    - 支持单个生成和全部生成

    工作流程：
    1. Thought: 分析用户意图（单个/全部？角色/场景/分镜？提示词/图片/视频？）
    2. Action: 调用查询工具获取资源信息
    3. Action: 调用模板工具获取提示词模板
    4. Action: 调用知识库工具获取专业知识（如需要）
    5. Thought: Node 自身生成提示词
    6. Action: 调用保存工具保存到数据库
    7. Action: 调用提交工具启动生成（如需要）
    8. Action: 调用状态查询工具等待完成
    9. Thought: 汇报生成结果
    """

    USE_REACT = True

    def __init__(self):
        super().__init__(model="Qwen/Qwen-Plus", temperature=0.3)

    def _get_supervisor_params(self, state: ComicDramaState) -> Optional[Dict[str, Any]]:
        """
        从 Supervisor 传递的参数中获取意图信息

        支持两种参数格式：
        1. 简单模式（向后兼容）：
           {
             "target_type": "character/scene/shot/shot_video/all",
             "operation_type": "generate_image/generate_prompt/generate_video",
             "scope": "all/single",
             "frame_type": "both/start/end"
           }

        2. 任务数组模式（推荐）：
           {
             "user_intent": "用户意图总结",
             "tasks": [
               {
                 "target": "character/scene/shot/shot_video",
                 "actions": ["prompt", "image"],
                 "scope": "all/single",
                 "frame_type": "both/start/end"
               }
             ]
           }
        """
        task_params = state.get("task_params", {})
        if task_params:
            logger.info(f"[AssetGeneration] 从 Supervisor 获取参数: {task_params}")
            return task_params
        return None

    def _parse_tasks_from_params(self, supervisor_params: Dict[str, Any]) -> List[Dict[str, Any]]:
        """
        从参数中解析任务列表

        支持简单模式和任务数组模式
        """
        # 任务数组模式（优先）
        if "tasks" in supervisor_params and isinstance(supervisor_params["tasks"], list):
            tasks = supervisor_params["tasks"]
            logger.info(f"[AssetGeneration] 使用任务数组模式，任务数: {len(tasks)}")
            return tasks

        # 简单模式（向后兼容）
        target_type = supervisor_params.get("target_type", "all")
        operation_type = supervisor_params.get("operation_type", "generate_image")
        scope = supervisor_params.get("scope", "all")
        frame_type = supervisor_params.get("frame_type", "both")

        # 将 operation_type 转换为 actions
        action_map = {
            "generate_image": ["image"],
            "generate_prompt": ["prompt"],
            "generate_video": ["video"],
        }
        actions = action_map.get(operation_type, ["image"])

        # 处理 "all" 类型
        if target_type == "all":
            tasks = [
                {"target": "character", "actions": actions, "scope": scope, "frame_type": frame_type},
                {"target": "scene", "actions": actions, "scope": scope, "frame_type": frame_type},
            ]
        else:
            tasks = [
                {"target": target_type, "actions": actions, "scope": scope, "frame_type": frame_type}
            ]

        logger.info(f"[AssetGeneration] 使用简单模式，任务数: {len(tasks)}")
        return tasks

    def _get_visual_style_for_creation(self, creation_uuid: str) -> str:
        """
        获取创作的视觉风格描述

        Args:
            creation_uuid: 创作 UUID

        Returns:
            风格描述字符串
        """
        from app.agent.config import get_visual_style_description
        from app.db.session import get_sync_session
        from app.models.creation import Creation

        try:
            # 使用同步数据库查询
            with get_sync_session() as db:
                creation = db.query(Creation).filter(Creation.uuid == creation_uuid).first()
                if creation and creation.extra_data:
                    visual_style_key = creation.extra_data.get("visual_style", "anime")
                    return get_visual_style_description(visual_style_key)
        except Exception as e:
            logger.warning(f"[AssetGeneration] 获取风格失败: {e}")

        # 默认返回 anime 风格
        return get_visual_style_description("anime")

    def _build_prompt_from_tasks(self, tasks: List[Dict[str, Any]], creation_uuid: str, user_intent: str = "") -> str:
        """
        根据任务列表构建系统提示词

        Args:
            tasks: 任务列表
            creation_uuid: 创作 UUID
            user_intent: 用户意图总结
        """
        from app.utils.file_utils import read_prompt_file

        # 获取视觉风格
        visual_style = self._get_visual_style_for_creation(creation_uuid)
        logger.info(f"[AssetGeneration] 使用视觉风格: {visual_style[:50]}...")

        # 添加用户意图（如果有）
        prompt_parts = []
        if user_intent:
            prompt_parts.append(f"# 用户意图\n\n{user_intent}\n")

        task_descriptions = []

        for i, task in enumerate(tasks):
            target = task.get("target", "character")
            actions = task.get("actions", ["image"])
            scope = task.get("scope", "all")
            frame_type = task.get("frame_type", "both")

            target_name = {
                "character": "角色",
                "scene": "场景",
                "shot": "分镜图片",
                "shot_video": "分镜视频",
            }.get(target, target)

            action_descriptions = {
                "prompt": "提示词",
                "image": "图片",
                "video": "视频",
            }
            action_str = " + ".join([action_descriptions.get(a, a) for a in actions])

            task_descriptions.append(f"{i+1}. {target_name}：{action_str}")

            # 获取对应模板
            if target == "character":
                template = read_prompt_file("agent_generate_character.md")
            elif target == "scene":
                template = read_prompt_file("agent_generate_scene.md")
            else:
                template = read_prompt_file("agent_generate_shot.md")

            if template:
                template = template.replace("{{CREATION_UUID}}", creation_uuid)
                template = template.replace("{{SCOPE}}", scope)
                template = template.replace("{{VISUAL_STYLE}}", visual_style)
                if "frame_type" in task:
                    template = template.replace("{{FRAME_TYPE}}", frame_type)
                prompt_parts.append(f"\n## 任务 {i+1}：{target_name}（{action_str}）\n{template}")

        # 构建主提示词
        if len(tasks) == 1:
            main_prompt = f"# 资产生成任务\n\n你需要完成以下任务："
        else:
            main_prompt = f"# 多任务资产生成\n\n你需要按顺序完成以下 {len(tasks)} 个任务："

        main_prompt += "\n" + "\n".join(task_descriptions)

        # 检查是否有连续生成需求（prompt + image）
        has_continuous_generation = False
        for task in tasks:
            actions = task.get("actions", [])
            if "prompt" in actions and "image" in actions:
                has_continuous_generation = True
                break
        
        if has_continuous_generation:
            main_prompt += "\n\n## ⚠️ 连续生成模式（关键！）\n"
            main_prompt += "检测到需要同时生成提示词和图片，你必须：\n"
            main_prompt += "1. **首先完成所有提示词的生成和保存**（使用 batch_save_shot_image_prompts）\n"
            main_prompt += "2. **然后立即继续生成所有图片**（使用 batch_submit_shot_images）\n"
            main_prompt += "3. **不要中途停止或返回**，必须连续完成两个步骤！\n"
            main_prompt += "4. 最后汇报完整的生成结果（提示词生成情况 + 图片生成情况）"
        elif len(tasks) > 1:
            main_prompt += "\n\n## 执行顺序（重要）\n必须按顺序执行：先完成所有提示词生成，再进行所有图片/视频生成。"

        main_prompt += "\n".join(prompt_parts)

        return main_prompt

    def get_system_prompt(self, state: ComicDramaState) -> str:
        """
        获取系统提示词

        意图解析优先级：
        1. Supervisor 传递的任务数组（task_params.tasks + user_intent）—— 最灵活
        2. Supervisor 传递的简单参数（task_params）—— 向后兼容
        3. LLM 解析用户消息 —— 更灵活
        4. 关键词匹配 —— 兜底
        """
        user_message = state.get("user_message", "")
        creation_uuid = state.get("creation_uuid", "")

        # 获取 user_intent
        supervisor_params = self._get_supervisor_params(state)
        user_intent = ""
        if supervisor_params and isinstance(supervisor_params, dict):
            user_intent = supervisor_params.get("user_intent", "")

        # 1. 优先使用 Supervisor 传递的参数
        if supervisor_params:
            # 检查是否是任务数组模式
            if "tasks" in supervisor_params and isinstance(supervisor_params["tasks"], list):
                tasks = self._parse_tasks_from_params(supervisor_params)
                prompt_template = self._build_prompt_from_tasks(tasks, creation_uuid, user_intent)
                logger.info(f"[AssetGeneration] 使用任务数组模式，user_intent: {user_intent}")
                return prompt_template
            else:
                # 简单模式
                target_type = supervisor_params.get("target_type", "all")
                operation_type = supervisor_params.get("operation_type", "generate_image")
                scope = supervisor_params.get("scope", "all")
                frame_type = supervisor_params.get("frame_type", "both")
                logger.info(f"[AssetGeneration] 使用简单模式: target={target_type}, op={operation_type}, scope={scope}")

                # 构建简单模式提示词
                prompt_template = self._build_simple_prompt(target_type, operation_type, scope, frame_type, creation_uuid, user_intent)
                return prompt_template

        # 兜底：使用 LLM 解析或关键词匹配
        logger.warning(f"[AssetGeneration] 未获取到 Supervisor 参数，使用关键词匹配")
        
        return self._build_fallback_prompt(user_message, creation_uuid)

    def _build_simple_prompt(self, target_type: str, operation_type: str, scope: str, frame_type: str, creation_uuid: str, user_intent: str = "") -> str:
        """构建简单模式的提示词（向后兼容）"""
        from app.utils.file_utils import read_prompt_file

        # 获取视觉风格
        visual_style = self._get_visual_style_for_creation(creation_uuid)
        logger.info(f"[AssetGeneration] 使用视觉风格: {visual_style[:50]}...")

        # 添加用户意图（如果有）
        intent_prefix = ""
        if user_intent:
            intent_prefix = f"# 用户意图\n\n{user_intent}\n\n"

        # 获取系统提示词模板
        if target_type == "all":
            character_prompt = read_prompt_file("agent_generate_character.md")
            scene_prompt = read_prompt_file("agent_generate_scene.md")
            prompt_template = f"""# 完整资产生成模式

{intent_prefix}你需要完成以下任务（按顺序执行）：

## 第一阶段：生成全部角色提示词和图片

{character_prompt}

## 第二阶段：生成全部场景提示词和图片

{scene_prompt}

## 执行顺序（重要）

1. **先生成全部角色提示词**（跳过已有提示词的角色）
2. **再生成全部角色图片**（跳过已有图片的角色，必须先有提示词）
3. **然后生成全部场景提示词**（跳过已有提示词的场景）
4. **最后生成全部场景图片**（跳过已有图片的场景，必须先有提示词）

## 完成标准

当所有角色的提示词和图片、所有场景的提示词和图片都生成完成后，任务才算完成。
"""
        elif target_type == "character":
            character_prompt = read_prompt_file("agent_generate_character.md")
            prompt_template = f"# 角色生成任务\n\n{intent_prefix}{character_prompt}" if intent_prefix else character_prompt
        elif target_type == "scene":
            scene_prompt = read_prompt_file("agent_generate_scene.md")
            prompt_template = f"# 场景生成任务\n\n{intent_prefix}{scene_prompt}" if intent_prefix else scene_prompt
        elif target_type in ["shot", "shot_video"]:
            shot_prompt = read_prompt_file("agent_generate_shot.md")
            prompt_template = f"# 分镜生成任务\n\n{intent_prefix}{shot_prompt}" if intent_prefix else shot_prompt
        else:
            logger.warning(f"[AssetGeneration] 未知的 target_type: {target_type}，使用默认 shot 模板")
            shot_prompt = read_prompt_file("agent_generate_shot.md")
            prompt_template = f"# 分镜生成任务\n\n{intent_prefix}{shot_prompt}" if intent_prefix else shot_prompt

        # 在提示词中注入变量
        if prompt_template:
            prompt_template = prompt_template.replace("{{CREATION_UUID}}", creation_uuid)
            prompt_template = prompt_template.replace("{{FRAME_TYPE}}", frame_type)
            prompt_template = prompt_template.replace("{{SCOPE}}", scope)
            prompt_template = prompt_template.replace("{{VISUAL_STYLE}}", visual_style)

        # 添加细粒度工具使用指南（非 all 模式）
        if target_type != "all":
            tool_guide = self._get_tool_usage_guide(target_type, operation_type, scope, frame_type)
            if tool_guide:
                prompt_template = (prompt_template or "") + tool_guide

        return prompt_template

    def _build_fallback_prompt(self, user_message: str, creation_uuid: str) -> str:
        """兜底的关键词匹配提示词"""
        target_type = self._detect_target_type(user_message)
        operation_type = self._detect_operation_type(user_message)
        scope = self._detect_scope(user_message)
        frame_type = self._detect_frame_type(user_message) if target_type in ["shot", "shot_video"] else "both"

        logger.info(f"[AssetGeneration] 兜底模式: target={target_type}, op={operation_type}, scope={scope}")

        return self._build_simple_prompt(target_type, operation_type, scope, frame_type, creation_uuid)

    def _detect_target_type(self, user_message: str) -> str:
        """
        检测目标类型（角色/场景/分镜/全部）

        返回: "character" | "scene" | "shot" | "all"
        """
        msg_lower = user_message.lower()

        # 完整创作模式（没有明确指定类型时，表示角色+场景都要处理）
        auto_creation_patterns = [
            "开始创作", "开始生成", "开始执行", "开始任务", "自动创作",
            "自动执行", "自动开始", "执行创作", "执行任务",
        ]
        for pattern in auto_creation_patterns:
            if pattern in msg_lower:
                return "all"  # 表示角色和场景都要处理

        # 分镜关键词
        shot_keywords = ["分镜", "shot", "镜头"]
        for kw in shot_keywords:
            if kw in msg_lower:
                return "shot"

        # 场景关键词
        scene_keywords = ["场景", "scene", "背景", "地点"]
        for kw in scene_keywords:
            if kw in msg_lower:
                return "scene"

        # 角色关键词
        character_keywords = ["角色", "character", "人物", "演员"]
        for kw in character_keywords:
            if kw in msg_lower:
                return "character"

        # 默认返回 all（完整创作模式）
        return "all"

    def _detect_operation_type(self, user_message: str) -> str:
        """
        检测操作类型（提示词/图片/视频）

        返回: "generate_prompt" | "generate_image" | "generate_video"
        """
        msg_lower = user_message.lower()

        # 视频生成
        video_keywords = ["视频", "video", "生视频", "生成视频", "动态视频"]
        for kw in video_keywords:
            if kw in msg_lower:
                return "generate_video"

        # 图片生成
        image_keywords = ["图片", "image", "生图", "生成图片", "图像", "照片"]
        for kw in image_keywords:
            if kw in msg_lower:
                return "generate_image"

        # 提示词生成关键词（明确要生成提示词）
        prompt_keywords = ["提示词", "prompt", "生成提示词", "创建提示词"]
        for kw in prompt_keywords:
            if kw in msg_lower:
                return "generate_prompt"

        # 默认生成图片（创作流程中的默认行为）
        # 如果用户说"开始创作"、"生成角色"等，没有明确指定类型，默认生成图片
        return "generate_image"

    def _detect_scope(self, user_message: str) -> str:
        """
        检测范围（单个还是全部）

        返回: "single" | "all"
        """
        msg_lower = user_message.lower()

        # 全部关键词
        all_keywords = ["全部", "所有", "批量", "一起", "统统", "all"]
        for kw in all_keywords:
            if kw in msg_lower:
                return "all"

        # 默认全部的场景（创作流程中的默认行为）
        # 如果用户说"生成角色图片"、"为角色生图"等，没有指定具体角色名，默认为全部
        default_all_patterns = [
            "为角色", "为场景", "为分镜",
            "生成角色", "生成场景", "生成分镜",
            "角色图片", "场景图片", "分镜图片",
            "开始生成", "开始创作",
        ]
        for pattern in default_all_patterns:
            if pattern in msg_lower:
                # 检查是否包含具体角色/场景/分镜名（简单判断：是否包含数字或特定名字）
                # 如果没有具体名字，认为是全部
                return "all"

        # 默认单个
        return "single"

    def _detect_frame_type(self, user_message: str) -> str:
        """
        检测分镜帧类型（首帧/尾帧/全部）

        返回: "start" | "end" | "both"
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

    # ==================== 资源存在性检测方法 ====================

    def _check_character_prompt_exists(self, character: Dict) -> bool:
        """检查角色是否已有图片提示词"""
        return bool(character.get("image_prompt"))

    def _check_character_image_exists(self, character: Dict) -> bool:
        """检查角色是否已有图片"""
        return bool(character.get("image_url"))

    def _check_scene_prompt_exists(self, scene: Dict) -> bool:
        """检查场景是否已有图片提示词"""
        # 从 extra_data 中获取
        extra_data = scene.get("extra_data", {}) or {}
        return bool(extra_data.get("image_prompt"))

    def _check_scene_image_exists(self, scene: Dict) -> bool:
        """检查场景是否已有图片"""
        return bool(scene.get("image_url"))

    def _check_shot_image_prompt_exists(self, shot: Dict, frame_type: str = "both") -> bool:
        """检查分镜是否已有图片提示词"""
        extra_data = shot.get("extra_data", {}) or {}

        if frame_type == "start":
            return bool(shot.get("image_prompt") or extra_data.get("start_frame_image_prompt"))
        elif frame_type == "end":
            return bool(extra_data.get("end_frame_image_prompt"))
        else:  # both
            has_start = bool(shot.get("image_prompt") or extra_data.get("start_frame_image_prompt"))
            has_end = bool(extra_data.get("end_frame_image_prompt"))
            return has_start and has_end

    def _check_shot_image_exists(self, shot: Dict) -> bool:
        """检查分镜是否已有图片"""
        return bool(shot.get("image_url"))

    def _check_shot_video_prompt_exists(self, shot: Dict) -> bool:
        """检查分镜是否已有视频提示词"""
        extra_data = shot.get("extra_data", {}) or {}
        return bool(extra_data.get("video_prompt"))

    def _check_shot_video_exists(self, shot: Dict) -> bool:
        """检查分镜是否已有视频"""
        return bool(shot.get("video_url"))

    def _get_tool_usage_guide(self, target_type: str, operation_type: str, scope: str, frame_type: str = "both") -> str:
        """获取工具使用指南"""

        base_guide = f"""

【细粒度工具使用指南】

用户操作类型: {operation_type}
检测到的范围: {scope}
检测到的帧类型: {frame_type}
你作为中央协调器，需要按顺序调用以下工具完成任务：

"""

        if target_type == "character":
            return self._get_character_tool_guide(operation_type, scope)
        elif target_type == "scene":
            return self._get_scene_tool_guide(operation_type, scope)
        else:  # shot
            return self._get_shot_tool_guide(operation_type, scope, frame_type)

    def _get_character_tool_guide(self, operation_type: str, scope: str) -> str:
        """获取角色工具使用指南"""
        base_guide = ""

        if operation_type == "generate_prompt":
            if scope == "all":
                base_guide = """
### 全部角色提示词生成流程

**Step 1: 获取所有角色信息并检测已存在的提示词**
- 工具: `query_characters`
- 参数: creation_uuid
- 说明: 获取所有角色列表
- **检测**: 检查每个角色的 `image_prompt` 字段
  - 已有提示词的角色 → 跳过，记录到 skipped 列表
  - 没有提示词的角色 → 进入下一步生成

**Step 2: 遍历需要生成提示词的角色**
对于每个没有提示词的角色:
- 调用 `get_character_prompt_template` 获取模板
- **Node 自身生成提示词**（使用你的 LLM，不是工具！）
- 调用 `save_character_prompt` 保存提示词

**Step 3: 汇总结果**
- 统计成功生成的角色数量
- 统计已存在提示词的角色数量（跳过）
- 汇报生成结果："生成了 X 个角色的提示词，跳过了 Y 个（已有提示词）"
"""
            else:  # single
                base_guide = """
### 单个角色提示词生成流程

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
"""

        elif operation_type == "generate_image":
            if scope == "all":
                base_guide = """
### 全部角色图片生成流程（重要：先生成提示词，再生成图片，跳过已存在的）

**【重要】全部生成时必须先有提示词！**
- 如果角色还没有提示词，必须先调用 "生成全部角色提示词" 流程
- **不支持同时生成提示词+图片**，必须分两步走

**Step 1: 检查提示词状态和图片存在性**
- 工具: `query_characters`
- 参数: creation_uuid
- 说明: 获取所有角色列表，检查每个角色：
  - `image_prompt` 字段：是否有提示词
  - `image_url` 字段：是否已有图片
- **分类处理**：
  - 已有图片的角色 → 跳过，记录到 "skipped_image_exists"
  - 没有提示词的角色 → 记录到 "missing_prompt"
  - 有提示词但没有图片的角色 → 进入下一步生成

**Step 2: 处理缺少提示词的角色**
- 如果有角色没有提示词:
  - **停止图片生成**
  - 告知用户："部分角色还没有提示词，需要先生成提示词"
  - 建议用户先执行："生成全部角色提示词"

**Step 3: 批量提交图片生成任务（仅针对有提示词且无图片的角色）**
- 对于每个有提示词但没有图片的角色:
  - 调用 `submit_character_image_regeneration`
  - 参数: character_id, creation_uuid
  - 记录返回的 task_id

**Step 4: 查询任务状态（阻塞等待完成）**
- 工具: `query_generation_tasks_status`
- 参数:
  - task_ids: [task_id1, task_id2, ...]（所有任务的 task_id 列表）
  - target_info: [{"target_type": "character", "target_id": id1}, ...]
  - timeout: 1000
  - poll_interval: 2.0
- 说明: 轮询查询所有任务状态，直到全部完成或超时

**Step 5: 汇报生成结果**
- 统计成功生成的图片数量
- 统计已有图片的角色数量（跳过）
- 统计缺少提示词的角色数量
- 告知用户："角色图片生成完成：生成了 X 个，跳过了 Y 个（已有图片），Z 个缺少提示词。请查看并确认"
- **重要**：图片生成完成后，必须等待用户确认，不要自动进入下一阶段
"""
            else:  # single
                base_guide = """
### 单个角色图片生成流程

**Step 1: 获取角色信息**
- 工具: `query_single_character`
- 参数: character_id
- 说明: 获取角色的完整信息

**Step 2: 检查并生成提示词（如需要）**
- 如果角色没有提示词:
  - 调用 `get_character_prompt_template` 获取模板
  - **Node 自身生成提示词**
  - 调用 `save_character_prompt` 保存

**Step 3: 提交图片生成任务**
- 工具: `submit_character_image_regeneration`
- 参数: character_id, creation_uuid
- 说明: 提交图片生成任务，返回 task_id

**Step 4: 查询任务状态（阻塞等待完成）**
- 工具: `query_generation_tasks_status`
- 参数:
  - task_ids: [task_id]
  - target_info: [{"target_type": "character", "target_id": character_id}]
  - timeout: 1000
  - poll_interval: 2.0
- 说明: 轮询查询任务状态，直到完成或超时

**Step 5: 汇报生成结果**
- 根据查询结果告知用户成功或失败
"""

        return base_guide

    def _get_scene_tool_guide(self, operation_type: str, scope: str) -> str:
        """获取场景工具使用指南"""
        base_guide = ""

        if operation_type == "generate_prompt":
            if scope == "all":
                base_guide = """
### 全部场景提示词生成流程

**Step 1: 获取所有场景信息并检测已存在的提示词**
- 工具: `query_scenes`
- 参数: creation_uuid
- 说明: 获取所有场景列表
- **检测**: 检查每个场景的 `extra_data.image_prompt` 字段
  - 已有提示词的场景 → 跳过，记录到 skipped 列表
  - 没有提示词的场景 → 进入下一步生成

**Step 2: 遍历需要生成提示词的场景**
对于每个没有提示词的场景:
- 调用 `get_scene_prompt_template` 获取模板
- **Node 自身生成提示词**（使用你的 LLM，不是工具！）
- 调用 `save_scene_prompt` 保存提示词

**Step 3: 汇总结果**
- 统计成功生成的场景数量
- 统计已存在提示词的场景数量（跳过）
- 汇报生成结果："生成了 X 个场景的提示词，跳过了 Y 个（已有提示词）"
"""
            else:  # single
                base_guide = """
### 单个场景提示词生成流程

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

        elif operation_type == "generate_image":
            if scope == "all":
                base_guide = """
### 全部场景图片生成流程（重要：先生成提示词，再生成图片，跳过已存在的）

**【重要】全部生成时必须先有提示词！**
- 如果场景还没有提示词，必须先调用 "生成全部场景提示词" 流程
- **不支持同时生成提示词+图片**，必须分两步走

**Step 1: 检查提示词状态和图片存在性**
- 工具: `query_scenes`
- 参数: creation_uuid
- 说明: 获取所有场景列表，检查每个场景：
  - `extra_data.image_prompt`：是否有提示词
  - `image_url` 字段：是否已有图片
- **分类处理**：
  - 已有图片的场景 → 跳过，记录到 "skipped_image_exists"
  - 没有提示词的场景 → 记录到 "missing_prompt"
  - 有提示词但没有图片的场景 → 进入下一步生成

**Step 2: 处理缺少提示词的场景**
- 如果有场景没有提示词:
  - **停止图片生成**
  - 告知用户："部分场景还没有提示词，需要先生成提示词"
  - 建议用户先执行："生成全部场景提示词"

**Step 3: 批量提交图片生成任务（仅针对有提示词且无图片的场景）**
- 对于每个有提示词但没有图片的场景:
  - 调用 `submit_scene_image_regeneration`
  - 参数: scene_id, creation_uuid
  - 记录返回的 task_id

**Step 4: 查询任务状态（阻塞等待完成）**
- 工具: `query_generation_tasks_status`
- 参数:
  - task_ids: [task_id1, task_id2, ...]（所有任务的 task_id 列表）
  - target_info: [{"target_type": "scene", "target_id": id1}, ...]
  - timeout: 1000
  - poll_interval: 2.0
- 说明: 轮询查询所有任务状态，直到全部完成或超时

**Step 5: 汇报生成结果**
- 统计成功生成的图片数量
- 统计已有图片的场景数量（跳过）
- 统计缺少提示词的场景数量
- 告知用户："场景图片生成完成：生成了 X 个，跳过了 Y 个（已有图片），Z 个缺少提示词。请查看并确认"
- **重要**：图片生成完成后，必须等待用户确认，不要自动进入下一阶段
"""
            else:  # single
                base_guide = """
### 单个场景图片生成流程

**Step 1: 获取场景信息**
- 工具: `query_single_scene`
- 参数: scene_id
- 说明: 获取场景的完整信息

**Step 2: 检查并生成提示词（如需要）**
- 如果场景没有提示词:
  - 调用 `get_scene_prompt_template` 获取模板
  - **Node 自身生成提示词**
  - 调用 `save_scene_prompt` 保存

**Step 3: 提交图片生成任务**
- 工具: `submit_scene_image_regeneration`
- 参数: scene_id, creation_uuid
- 说明: 提交图片生成任务，返回 task_id

**Step 4: 查询任务状态（阻塞等待完成）**
- 工具: `query_generation_tasks_status`
- 参数:
  - task_ids: [task_id]
  - target_info: [{"target_type": "scene", "target_id": scene_id}]
  - timeout: 1000
  - poll_interval: 2.0
- 说明: 轮询查询任务状态，直到完成或超时

**Step 5: 汇报生成结果**
- 根据查询结果告知用户成功或失败
"""

        return base_guide

    def _get_shot_tool_guide(self, operation_type: str, scope: str, frame_type: str) -> str:
        """获取分镜工具使用指南"""
        base_guide = ""

        if operation_type == "generate_prompt":
            if scope == "all":
                base_guide = f"""
### 全部分镜提示词生成流程

**Step 1: 获取所有分镜信息并检测已存在的提示词**
- 工具: `query_shots`
- 参数: creation_uuid
- 说明: 获取所有分镜列表
- **检测图片提示词**: 检查每个分镜的 `image_prompt` 和 `extra_data.start_frame_image_prompt`
  - 已有提示词的分镜 → 跳过，记录到 skipped 列表
  - 没有提示词的分镜 → 进入下一步生成
- **检测视频提示词**: 检查每个分镜的 `extra_data.video_prompt`
  - 已有视频提示词的分镜 → 跳过，记录到 skipped 列表
  - 没有视频提示词的分镜 → 进入下一步生成

**Step 2: 遍历需要生成提示词的分镜**
对于每个没有提示词的分镜:
- 调用 `query_single_shot` 获取分镜详情（包含场景信息）
- 判断提示词类型:
  - 图片提示词: 调用 `get_shot_image_prompt_template`，参数 frame_type="{frame_type}"
  - 视频提示词: 调用 `get_shot_video_prompt_template`
- **Node 自身生成提示词**（使用你的 LLM，不是工具！）
- 调用 `save_shot_image_prompt` 或 `save_shot_video_prompt` 保存

**Step 3: 汇总结果**
- 统计成功生成的分镜数量
- 统计已存在提示词的分镜数量（跳过）
- 汇报生成结果："生成了 X 个分镜的提示词，跳过了 Y 个（已有提示词）"

frame_type 自动检测规则：
- "首帧"、"第一帧" → frame_type="start"
- "尾帧"、"最后一帧" → frame_type="end"
- 无明确指定 → frame_type="both"
"""
            else:  # single
                base_guide = f"""
### 单个分镜提示词生成流程

**Step 1: 获取分镜信息**
- 工具: `query_single_shot`
- 参数: shot_id
- 说明: 获取分镜的完整信息，包含关联场景和上一个分镜

**Step 2: 判断提示词类型**
- 图片提示词: prompt_type="image"
- 视频提示词: prompt_type="video"

**Step 3: 获取提示词模板**
- 图片提示词: 工具 `get_shot_image_prompt_template`，参数 frame_type="{frame_type}"
- 视频提示词: 工具 `get_shot_video_prompt_template`

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
- 图片提示词: 工具 `save_shot_image_prompt`，参数 frame_type="{frame_type}"
- 视频提示词: 工具 `save_shot_video_prompt`
- 说明: 保存到数据库

frame_type 自动检测规则：
- "首帧"、"第一帧" → frame_type="start"
- "尾帧"、"最后一帧" → frame_type="end"
- 无明确指定 → frame_type="both"
"""

        elif operation_type == "generate_image":
            if scope == "all":
                base_guide = f"""
### 全部分镜图片生成流程（重要：先生成提示词，再生成图片，跳过已存在的）

**【重要】全部生成时必须先有提示词！**
- 如果分镜还没有图片提示词，必须先调用 "生成全部分镜提示词" 流程
- **不支持同时生成提示词+图片**，必须分两步走

**Step 1: 检查提示词状态和图片存在性**
- 工具: `query_shots`
- 参数: creation_uuid
- 说明: 获取所有分镜列表，检查每个分镜：
  - `image_prompt` / `extra_data.start_frame_image_prompt`：是否有提示词
  - `image_url` 字段：是否已有图片
- **分类处理**：
  - 已有图片的分镜 → 跳过，记录到 "skipped_image_exists"
  - 没有提示词的分镜 → 记录到 "missing_prompt"
  - 有提示词但没有图片的分镜 → 进入下一步生成

**Step 2: 处理缺少提示词的分镜**
- 如果有分镜没有图片提示词:
  - **停止图片生成**
  - 告知用户："部分分镜还没有图片提示词，需要先生成提示词"
  - 建议用户先执行："生成全部分镜提示词"

**Step 3: 批量提交图片生成任务（仅针对有提示词且无图片的分镜）**
- 对于每个有提示词但没有图片的分镜:
  - 调用 `submit_shot_image_regeneration`
  - 参数: shot_id, creation_uuid, frame_type="{frame_type}"
  - 记录返回的 task_id

**Step 4: 查询任务状态（阻塞等待完成）**
- 工具: `query_generation_tasks_status`
- 参数:
  - task_ids: [task_id1, task_id2, ...]（所有任务的 task_id 列表）
  - target_info: [{{"target_type": "shot", "target_id": id1}}, ...]
  - timeout: 1000
  - poll_interval: 2.0
- 说明: 轮询查询所有任务状态，直到全部完成或超时

**Step 5: 汇报生成结果**
- 统计成功生成的图片数量
- 统计已有图片的分镜数量（跳过）
- 统计缺少提示词的分镜数量
- 告知用户："分镜图片生成完成：生成了 X 个，跳过了 Y 个（已有图片），Z 个缺少提示词。请查看并确认"
- **重要**：图片生成完成后，必须等待用户确认，不要自动进入下一阶段

frame_type 自动检测规则：
- "首帧"、"第一帧" → frame_type="start"
- "尾帧"、"最后一帧" → frame_type="end"
- 无明确指定 → frame_type="both"
"""
            else:  # single
                base_guide = f"""
### 单个分镜图片生成流程

**Step 1: 获取分镜信息**
- 工具: `query_single_shot`
- 参数: shot_id
- 说明: 获取分镜的完整信息

**Step 2: 检查并生成提示词（如需要）**
- 如果分镜没有图片提示词:
  - 调用 `get_shot_image_prompt_template` 获取模板
  - **Node 自身生成提示词**
  - 调用 `save_shot_image_prompt` 保存

**Step 3: 提交图片生成任务**
- 工具: `submit_shot_image_regeneration`
- 参数: shot_id, creation_uuid, frame_type="{frame_type}"
- 说明: 提交图片生成任务，返回 task_id

**Step 4: 查询任务状态（阻塞等待完成）**
- 工具: `query_generation_tasks_status`
- 参数:
  - task_ids: [task_id]
  - target_info: [{{"target_type": "shot", "target_id": shot_id}}]
  - timeout: 1000
  - poll_interval: 2.0
- 说明: 轮询查询任务状态，直到完成或超时

**Step 5: 汇报生成结果**
- 根据查询结果告知用户成功或失败

frame_type 自动检测规则：
- "首帧"、"第一帧" → frame_type="start"
- "尾帧"、"最后一帧" → frame_type="end"
- 无明确指定 → frame_type="both"
"""

        elif operation_type == "generate_video":
            if scope == "all":
                base_guide = """
### 全部分镜视频生成流程（重要：不支持全部生成视频）

**【重要】不支持 "生成全部分镜视频" 操作！**

原因：
1. 视频生成需要先有视频提示词和首帧图片
2. 全部生成视频会导致大量任务同时执行，资源消耗过大
3. 视频生成应该在分镜图片确认后，逐个或分批进行

**正确的工作流程**：
1. 先生成全部角色/场景提示词
2. 再生成全部角色/场景图片
3. 用户确认图片后，生成分镜提示词
4. 用户确认分镜提示词后，生成分镜图片
5. 用户确认分镜图片后，**逐个或分批**生成分镜视频

**如果用户要求生成全部分镜视频**：
- 告知用户："不支持一次性生成全部分镜视频"
- 建议："请逐个生成分镜视频，或确认分镜图片后再生成视频"
- 引导用户先确认分镜图片是否已生成完成
"""
            else:  # single
                base_guide = """
### 单个分镜视频生成流程（检测视频是否已存在）

**Step 1: 获取分镜信息并检测视频存在性**
- 工具: `query_single_shot`
- 参数: shot_id
- 说明: 获取分镜的完整信息
- **检测视频是否存在**: 检查 `video_url` 字段
  - 如果 `video_url` 已存在 → **跳过生成**，告知用户"该分镜视频已存在"
  - 如果 `video_status` 为 "generating" → 告知用户"视频生成中，请稍后查询"
  - 如果没有视频 → 继续下一步

**Step 2: 检查并生成视频提示词（如需要）**
- 如果分镜没有视频提示词:
  - 调用 `get_shot_video_prompt_template` 获取模板
  - 调用 `query_knowledge_for_video` 查询运镜知识（提取关键词查询）
  - **Node 自身生成视频提示词**
  - 调用 `save_shot_video_prompt` 保存

**Step 3: 检查首帧图片（如需要）**
- 如果分镜没有首帧图片:
  - 调用 `submit_shot_image_regeneration` 生成首帧
  - 调用 `query_generation_tasks_status` 等待首帧完成

**Step 4: 提交视频生成任务**
- 工具: `submit_shot_video_regeneration`
- 参数: shot_id, creation_uuid, generation_mode="first_last_frame"（或 "first_frame_only"）
- 说明: 提交视频生成任务，返回 task_id

**Step 5: 查询任务状态（阻塞等待完成）**
- 工具: `query_generation_tasks_status`
- 参数:
  - task_ids: [task_id]
  - target_info: [{"target_type": "shot", "target_id": shot_id}]
  - timeout: 1000
  - poll_interval: 2.0
- 说明: 轮询查询任务状态，直到完成或超时

**Step 6: 汇报生成结果**
- 如果视频已存在 → 告知用户"视频已存在，无需重新生成"
- 如果生成成功 → 告知用户"视频生成成功"
- 如果生成失败 → 告知用户失败原因
"""

        return base_guide

    def get_tools(self) -> List:
        """
        获取可用工具列表 - 精简版

        只保留 agent_generate_shot 提示词中提及的必要工具：
        1. query_all_shots - 一次性返回所有分镜、角色、场景信息
        2. get_prompt_template - 统一提示词模板接口
        3. batch_save_*_prompts - 批量保存提示词
        4. query_knowledge_for_video - 知识库查询
        5. query_generation_tasks_status - 批量查询任务状态
        6. batch_submit_* - 批量提交生成任务
        """
        # 1. 统一批量查询工具 - 返回所有角色、场景、分镜信息
        from app.agent.tools.regenerate_worker_tools import (
            query_all_shots,
            query_generation_tasks_status,
        )

        # 2. 统一提示词模板工具
        from app.agent.tools.template_tools import (
            get_prompt_template,
        )

        # 3. 批量保存提示词工具
        from app.agent.tools.regenerate_worker_tools import (
            batch_save_character_prompts,
            batch_save_scene_prompts,
            batch_save_shot_image_prompts,
            batch_save_shot_video_prompts,
        )

        # 4. 知识库工具（仅视频提示词需要）
        from app.agent.tools.video_knowledge_tools import (
            query_knowledge_for_video,
        )

        # 5. 批量提交生成任务工具
        from app.agent.tools.regenerate_worker_tools import (
            batch_submit_character_images,
            batch_submit_scene_images,
            batch_submit_shot_images,
            batch_submit_shot_videos,
        )

        return [
            # === 1. 查询类 ===
            query_all_shots,
            query_generation_tasks_status,

            # === 2. 提示词模板 ===
            get_prompt_template,

            # === 3. 批量保存提示词 ===
            batch_save_character_prompts,
            batch_save_scene_prompts,
            batch_save_shot_image_prompts,
            batch_save_shot_video_prompts,

            # === 4. 知识库 ===
            query_knowledge_for_video,

            # === 5. 批量提交生成任务 ===
            batch_submit_character_images,
            batch_submit_scene_images,
            batch_submit_shot_images,
            batch_submit_shot_videos,
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
        save_count = 0
        submit_count = 0
        status_query_count = 0
        knowledge_count = 0

        success_count = 0
        failed_count = 0

        for result in tool_results:
            tool_name = result.get("tool", "")
            tool_result = result.get("result", {})

            if "query" in tool_name and "status" not in tool_name:
                query_count += 1
            elif "template" in tool_name:
                template_count += 1
            elif "save" in tool_name:
                save_count += 1
            elif "submit" in tool_name:
                submit_count += 1
            elif "status" in tool_name:
                status_query_count += 1
            elif "knowledge" in tool_name:
                knowledge_count += 1

            if tool_result.get("success"):
                success_count += 1
            else:
                failed_count += 1

        # 构建状态更新
        production_progress = dict(state.get("production_progress", {}))

        # 检测操作类型和范围
        user_message = state.get("user_message", "")
        operation_type = self._detect_operation_type(user_message)
        scope = self._detect_scope(user_message)

        # 根据操作类型更新进度
        if operation_type == "generate_prompt":
            production_progress["prompt_generation"] = {
                "status": "completed",
                "query_count": query_count,
                "template_count": template_count,
                "save_count": save_count,
            }
        elif operation_type == "generate_image":
            production_progress["image_generation"] = {
                "status": "completed",
                "submit_count": submit_count,
                "status_query_count": status_query_count,
            }
        elif operation_type == "generate_video":
            production_progress["video_generation"] = {
                "status": "completed",
                "submit_count": submit_count,
                "status_query_count": status_query_count,
            }

        # 根据任务类型确定新的 production_stage
        new_production_stage = None
        task_params = state.get("task_params", {})
        tasks = task_params.get("tasks", [])
        
        # 分析任务类型
        has_character_or_scene = False
        has_shot = False
        has_shot_video = False
        
        for task in tasks:
            target = task.get("target", "")
            if target in ["character", "scene"]:
                has_character_or_scene = True
            elif target == "shot":
                has_shot = True
            elif target == "shot_video":
                has_shot_video = True
        
        # 根据任务类型设置 production_stage
        if has_shot_video:
            # 视频生成完成
            new_production_stage = ProductionStage.COMPLETED
            logger.info(f"[{self.node_name}] 视频生成完成，设置 production_stage=COMPLETED")
        elif has_shot:
            # 分镜图片生成完成，进入 VIDEO_READY 阶段
            new_production_stage = ProductionStage.VIDEO_READY
            logger.info(f"[{self.node_name}] 分镜图片生成完成，设置 production_stage=VIDEO_READY")
        elif has_character_or_scene:
            # 角色/场景生成完成，进入 ASSETS_READY 阶段
            new_production_stage = ProductionStage.ASSETS_READY
            logger.info(f"[{self.node_name}] 角色/场景生成完成，设置 production_stage=ASSETS_READY")
        
        logger.info(f"[{self.node_name}] 结果统计: 成功={success_count}, 失败={failed_count}")

        result = {
            "response_text": final_response,
            "production_progress": production_progress,
            "tool_usage_summary": {
                "query_count": query_count,
                "template_count": template_count,
                "save_count": save_count,
                "submit_count": submit_count,
                "status_query_count": status_query_count,
                "knowledge_count": knowledge_count,
                "success_count": success_count,
                "failed_count": failed_count,
            }
        }
        
        # 如果有新的 production_stage，添加到结果中
        if new_production_stage:
            result["production_stage"] = new_production_stage
        
        return result


# 便捷函数，用于直接调用
async def generate_assets_worker(state: ComicDramaState) -> Dict[str, Any]:
    """
    资产生成 Worker 便捷函数

    用于在 Graph 中直接调用
    """
    node = AssetGenerationWorkerNode()
    return await node.run(state)
