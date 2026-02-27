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

from typing import Dict, Any, List, Optional
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

    def _get_supervisor_params(self, state: ComicDramaState) -> Optional[Dict[str, Any]]:
        """
        从 Supervisor 传递的参数中获取意图信息

        支持两种参数格式：
        1. 简单模式：
           {
             "target_type": "character/scene/shot/shot_video",
             "target_id": int,
             "operation_type": "generate_image/generate_prompt/generate_video/modify_prompt",
             "frame_type": "both/start/end"
           }

        2. 任务模式（支持多个操作）：
           {
             "user_intent": "用户意图总结",
             "tasks": [
               {
                 "target": "character/scene/shot/shot_video",
                 "target_id": int,
                 "actions": ["prompt"],
                 "frame_type": "both/start/end"
               }
             ]
           }
        """
        task_params = state.get("task_params", "")
        if task_params:
            logger.info(f"[AssetRegenerator] 从 Supervisor 获取参数: {task_params}")
            return task_params
        return None

    def _parse_tasks_from_params(self, supervisor_params: Dict[str, Any]) -> List[Dict[str, Any]]:
        """
        从参数中解析任务列表
        """
        # 任务模式
        if "tasks" in supervisor_params and isinstance(supervisor_params["tasks"], list):
            tasks = supervisor_params["tasks"]
            logger.info(f"[AssetRegenerator] 使用任务模式，任务数: {len(tasks)}")
            return tasks

        # 简单模式
        target_type = supervisor_params.get("target_type", "shot")
        target_id = supervisor_params.get("target_id")
        operation_type = supervisor_params.get("operation_type", "generate_image")
        frame_type = supervisor_params.get("frame_type", "both")

        # 将 operation_type 转换为 action
        action_map = {
            "generate_image": "regenerate",
            "generate_prompt": "regenerate",
            "generate_video": "regenerate",
            "modify_prompt": "modify_prompt",
        }
        action = action_map.get(operation_type, "regenerate")

        task = {
            "target": target_type,
            "target_id": target_id,
            "action": action,
            "frame_type": frame_type,
        }

        logger.info(f"[AssetRegenerator] 使用简单模式，单任务")
        return [task]

    def get_system_prompt(self, state: ComicDramaState) -> str:
        """
        获取系统提示词

        意图解析优先级：
        1. Supervisor 传递的参数（task_params）—— 最准确
        2. LLM 解析用户消息 —— 更灵活
        3. 关键词匹配 —— 兜底
        """
        user_message = state.get("user_message", "")
        creation_uuid = state.get("creation_uuid", "")
        
        logger.info("=" * 80)
        logger.info("[ASSET_REGENERATOR] ========== 开始构建系统提示词 ==========")
        logger.info(f"[ASSET_REGENERATOR] 输入状态:")
        logger.info(f"  - user_message: {user_message}")
        logger.info(f"  - creation_uuid: {creation_uuid}")

        supervisor_params = self._get_supervisor_params(state)
        if supervisor_params:
            tasks = self._parse_tasks_from_params(supervisor_params)
            task = tasks[0] if tasks else {}
            
            logger.info(f"[ASSET_REGENERATOR] Supervisor 参数:")
            logger.info(f"  - supervisor_params: {supervisor_params}")
            logger.info(f"  - parsed_task: {task}")

            target_type = task.get("target", "shot")
            target_id = task.get("target_id")
            action = task.get("action", "regenerate")
            frame_type = task.get("frame_type", "both")
            
            # 【关键】检查 actions 字段来确定操作类型
            actions = task.get("actions", [])
            logger.info(f"[ASSET_REGENERATOR] Actions 分析:")
            logger.info(f"  - raw_actions: {actions}")
            logger.info(f"  - 'prompt' in actions: {'prompt' in actions}")
            logger.info(f"  - 'image' in actions: {'image' in actions}")
            logger.info(f"  - 'video' in actions: {'video' in actions}")
            
            if "prompt" in actions and "image" not in actions:
                # 只生成提示词
                operation_type = "generate_prompt"
                logger.info(f"[ASSET_REGENERATOR] 决策: 只生成提示词 (operation_type=generate_prompt)")
            elif "image" in actions and "prompt" not in actions:
                # 只生成图片
                operation_type = "generate_image"
                logger.info(f"[ASSET_REGENERATOR] 决策: 只生成图片 (operation_type=generate_image)")
            elif "prompt" in actions and "image" in actions:
                # 同时生成提示词和图片
                operation_type = "generate_image"  # 以图片为主，但会连续生成
                logger.info(f"[ASSET_REGENERATOR] 决策: 同时生成提示词和图片 (operation_type=generate_image)")
            elif "video" in actions:
                operation_type = "generate_video"
                logger.info(f"[ASSET_REGENERATOR] 决策: 生成视频 (operation_type=generate_video)")
            else:
                # 默认根据 action 判断
                operation_type = {
                    "regenerate": "generate_image",
                    "modify_prompt": "modify_prompt",
                }.get(action, "generate_image")
                logger.info(f"[ASSET_REGENERATOR] 决策: 根据 action 判断 (action={action}, operation_type={operation_type})")

            logger.info(f"[ASSET_REGENERATOR] 最终参数:")
            logger.info(f"  - target_type: {target_type}")
            logger.info(f"  - target_id: {target_id}")
            logger.info(f"  - operation_type: {operation_type}")
            logger.info(f"  - frame_type: {frame_type}")
        else:
            logger.warning(f"[ASSET_REGENERATOR] 无 Supervisor 参数（task_params 为空），无法执行")
            return "错误：缺少 task_params 参数，无法确定操作意图。请通过 Supervisor 传递任务参数。"

        # 构建系统提示词
        tool_guide = self._get_tool_usage_guide(target_type, operation_type, frame_type, target_id, creation_uuid)

        base_prompt = f"""# 资产重新生成任务

你是资产重新生成专家，负责帮助用户重新生成或修改角色、场景、分镜的提示词和图片/视频。

## 当前任务

- 目标类型: {target_type}
- 操作类型: {operation_type}
- 帧类型: {frame_type}
- 目标 ID: {target_id or "未指定"}

{tool_guide}

## 用户消息

{user_message}

请按照上述指南，调用相应工具完成任务。
"""
        return base_prompt

    def _map_operation_type(self, op_type: str) -> str:
        """将 Supervisor 的 operation_type 映射为工具指南使用的格式"""
        mapping = {
            "generate_image": "image",
            "generate_video": "video",
            "generate_prompt": "prompt",
            "modify_prompt": "modify_prompt",
        }
        return mapping.get(op_type, "image")

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
            logger.warning(f"[AssetRegenerator] 获取风格失败: {e}")
        
        # 默认返回 anime 风格
        return get_visual_style_description("anime")

    def _get_tool_usage_guide(self, target_type: str, operation_type: str, frame_type: str = "both", target_id: Optional[int] = None, creation_uuid: str = "") -> str:
        """获取工具使用指南"""

        mapped_op_type = self._map_operation_type(operation_type)
        target_id_info = f"\n目标 ID: {target_id}" if target_id else "\n目标 ID: 未指定（需要从列表中匹配）"
        
        # 获取视觉风格
        visual_style = self._get_visual_style_for_creation(creation_uuid) if creation_uuid else "anime style"

        base_guide = f"""

【细粒度工具使用指南】

用户操作类型: {mapped_op_type} ({operation_type})
检测到的帧类型: {frame_type}{target_id_info}
视觉风格: {visual_style}
创作 UUID: {creation_uuid or "未指定"}

你作为中央协调器，需要按顺序调用以下工具完成任务：

【重要】所有查询工具都需要 creation_uuid 参数，必须使用: {creation_uuid}

"""
        
        if target_type == "character":
            if mapped_op_type == "image":
                # 用户明确要求生成图片 - 使用旧的直接提交工具
                guide = base_guide + f"""
### 角色图片生成流程（直接提交并等待完成）

**Step 1: 获取所有资源信息**
- 工具: `query_all_shots`
- 参数: creation_uuid="{creation_uuid}"
- 说明: 一次性获取所有分镜、角色、场景信息，从返回的 characters 列表中找到匹配的角色名

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
  - target_info: [{{"target_type": "character", "target_id": character_id}}]
  - timeout: 1200 (最大等待1200秒)
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
            elif mapped_op_type == "prompt":
                # 生成提示词 - Node 自身生成
                guide = base_guide + """
### 角色提示词生成流程（Node 生成）

**Step 1: 获取所有资源信息（关键！）**
- 工具: `query_all_shots`
- 参数: creation_uuid="{creation_uuid}"
- 说明: 一次性获取所有分镜、角色、场景信息
- 从返回的 characters 列表中找到匹配的角色（通过角色名或 character_id）
"""
                if target_id:
                    guide += f"""
- 目标角色 ID: {target_id}，在 characters 列表中找到对应角色
"""
                else:
                    guide += """
- **从用户消息中提取角色名**（如"张磊"、"阿九"）
- **在返回的 characters 列表中找到匹配的角色名，获取 character_id**
"""
                guide += """
**Step 2: 获取提示词模板**
- 工具: `get_character_prompt_template`
- 参数: template_type="regenerate"
- 说明: 获取角色提示词生成模板

**Step 3: 生成提示词（Node 自身完成）**
- 不需要调用工具！
- 基于 character_info 和 template_content，使用你的 LLM 能力生成提示词
- 使用视觉风格: {visual_style}

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
            elif mapped_op_type == "modify_prompt":
                # 修改提示词 - Node 自身生成
                guide = base_guide + """
### 角色提示词修改流程（Node 生成）

**Step 1: 获取所有资源信息**
- 工具: `query_all_shots`
- 参数: creation_uuid
- 说明: 一次性获取所有信息，从 characters 列表中找到目标角色

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

**Step 1: 获取所有资源信息**
- 工具: `query_all_shots`
- 参数: creation_uuid
- 说明: 一次性获取所有信息，从 characters 列表中找到匹配的角色名

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
  - timeout: 1200
  - poll_interval: 2.0
- 说明: 轮询查询任务状态，直到任务完成或超时

**Step 4: 汇报生成结果**
- 根据查询结果，汇报生成成功或失败
"""
        elif target_type == "scene":
            if mapped_op_type == "image":
                guide = base_guide + """
### 场景图片生成流程（直接提交并等待完成）

**Step 1: 获取所有资源信息**
- 工具: `query_all_shots`
- 参数: creation_uuid
- 说明: 一次性获取所有信息，从 scenes 列表中找到匹配的场景名

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
  - timeout: 1200
  - poll_interval: 2.0
- 说明: 轮询查询任务状态，直到任务完成或超时

**Step 4: 汇报生成结果**
- 根据查询结果，汇报生成成功或失败

【重要】用户说"生成图片"时：
1. 提交生成任务获取 task_id
2. 调用 query_generation_tasks_status 等待任务完成
3. 汇报最终结果给用户
"""
            elif mapped_op_type == "prompt":
                guide = base_guide + """
### 场景提示词生成流程（Node 生成）

**Step 1: 获取所有资源信息**
- 工具: `query_all_shots`
- 参数: creation_uuid
- 说明: 一次性获取所有信息，从 scenes 列表中找到目标场景

**Step 2: 获取提示词模板**
- 工具: `get_scene_prompt_template`
- 参数: template_type="regenerate"
- 说明: 获取场景提示词生成模板

**Step 3: 生成提示词（Node 自身完成）**
- 不需要调用工具！
- 基于 scene_info 和 template_content，使用你的 LLM 能力生成提示词
- 使用视觉风格: {visual_style}

**Step 4: 保存提示词**
- 工具: `save_scene_prompt`
- 参数: scene_id, prompt (你生成的提示词)
- 说明: 保存到数据库
"""
            elif mapped_op_type == "modify_prompt":
                guide = base_guide + """
### 场景提示词修改流程（Node 生成）

**Step 1: 获取所有资源信息**
- 工具: `query_all_shots`
- 参数: creation_uuid
- 说明: 一次性获取所有信息，从 scenes 列表中找到目标场景

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

**Step 1: 获取所有资源信息**
- 工具: `query_all_shots`
- 参数: creation_uuid
- 说明: 一次性获取所有信息，从 scenes 列表中找到匹配的场景名

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
  - timeout: 1200
  - poll_interval: 2.0
- 说明: 轮询查询任务状态，直到任务完成或超时

**Step 4: 汇报生成结果**
- 根据查询结果，汇报生成成功或失败
"""
        else:  # shot
            if mapped_op_type == "video":
                guide = base_guide + """
### 分镜视频生成流程（直接提交并等待完成）

**Step 1: 获取所有资源信息**
- 工具: `query_all_shots`
- 参数: creation_uuid
- 说明: 一次性获取所有分镜、角色、场景信息，从 shots 列表中找到匹配的分镜编号

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
  - timeout: 1200
  - poll_interval: 2.0
- 说明: 轮询查询任务状态，直到任务完成或超时

**Step 4: 汇报生成结果**
- 根据查询结果，汇报生成成功或失败

【重要】用户说"生成视频"时：
1. 提交生成任务获取 task_id
2. 调用 query_generation_tasks_status 等待任务完成
3. 汇报最终结果给用户
"""
            elif mapped_op_type == "prompt":
                guide = base_guide + f"""
### 分镜视频提示词生成流程（三维度 + @引用格式）

**Step 1: 获取所有资源信息**
- 工具: `query_all_shots`
- 参数: creation_uuid="{creation_uuid}"
- 说明: 获取所有分镜、角色、场景信息，找到目标分镜及其关联的场景和角色
- **记住角色名和场景名**，后续提示词中要用 @引用

**Step 2: 查询知识库**
- 工具: `batch_query_knowledge_for_video`
- 参数: query_keywords（从分镜内容提取 3-5 个关键词）
- 说明: 查询运镜技巧、构图法则等专业知识

**Step 3: 生成提示词（Node 自身完成）**
- 不需要调用工具！
- 使用你的 LLM 能力生成视频提示词
- **必须使用三维度格式**：画面 + 对白 + 背景音
- **必须使用 @引用**：`@角色名`、`@场景名`、`@分镜N`
- 名称必须与数据库中的角色名/场景标题**完全匹配**

**提示词格式示例**：
```
把@阿九作为画面主体，场景参考@鱼市。
画面：[0.1～2秒] 全景横镜头，阳光薄雾中的传统鱼市。cut [2～4秒] 中景平视，@阿九瘫坐泡沫箱堆。
对白：[0.1～10秒] @老王："台词内容"
背景音：[0.1～3秒] 远处鱼市嘈杂人声铺底。
```

**叙事原则**：
- 叙事清晰，拒绝花哨（禁止比喻、文学修辞、情绪解释）
- 只描述动作、位置、镜头运动
- 镜头之间有叙事逻辑（整体→局部、远→近）
- 单镜头时长不超过 3 秒，用 cut 连接多个镜头

**Step 4: 保存提示词**
- 工具: `save_video_prompt_result`
- 参数:
  - shot_id: 分镜 ID
  - prompt: 你生成的视频提示词（三维度格式）
  - prompt_params: {{"generation_mode": "new", "duration": 10}}
  - references: [{{"type": "character", "target_id": 角色ID, "name": "角色名"}}, {{"type": "scene", "target_id": 场景ID, "name": "场景名"}}]
- 说明: 保存到数据库
"""
            elif mapped_op_type == "modify_prompt":
                guide = base_guide + f"""
### 分镜视频提示词修改流程（三维度 + @引用格式）

**Step 1: 获取所有资源信息**
- 工具: `query_all_shots`
- 参数: creation_uuid="{creation_uuid}"
- 说明: 获取所有分镜、角色、场景信息，找到目标分镜及原有提示词
- **记住角色名和场景名**，修改后的提示词中要用 @引用

**Step 2: 提取修改意见**
从用户消息中提取修改要求：
- "修改分镜5的提示词，增加运镜细节" → feedback="增加运镜细节"

**Step 3: 查询知识库**
- 工具: `batch_query_knowledge_for_video`
- 参数: query_keywords（从分镜内容和修改意见提取关键词）
- 说明: 查询运镜技巧、构图法则等专业知识

**Step 4: 修改提示词（Node 自身完成）**
- 不需要调用工具！
- 基于原提示词 + feedback + 知识库结果，使用你的 LLM 能力修改
- **必须使用三维度格式**：画面 + 对白 + 背景音
- **必须使用 @引用**：`@角色名`、`@场景名`、`@分镜N`
- 叙事清晰，拒绝花哨

**Step 5: 保存提示词**
- 工具: `save_video_prompt_result`
- 参数:
  - shot_id: 分镜 ID
  - prompt: 修改后的视频提示词（三维度格式）
  - prompt_params: {{"generation_mode": "new"或"extend", "duration": 时长}}
  - references: [{{"type": "character", "target_id": 角色ID, "name": "角色名"}}, ...]
- 说明: 保存到数据库
"""
            else:
                guide = base_guide + """
### 分镜视频生成流程（直接提交）

**Step 1: 获取所有资源信息**
- 工具: `query_all_shots`
- 参数: creation_uuid
- 说明: 一次性获取所有分镜、角色、场景信息，从 shots 列表中找到匹配的分镜编号

**Step 2: 提交视频生成任务**
- 工具: `submit_shot_video_regeneration`
- 参数:
  - shot_id (从 Step 1 获取)
  - creation_uuid
- 说明: 提交视频生成任务
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
        
        # 查询类工具 - 使用 query_all_shots 一次性获取所有分镜、角色、场景
        from app.agent.tools.regenerate_worker_tools import (
            query_all_shots,
            submit_character_image_regeneration,
            submit_scene_image_regeneration,
            submit_shot_video_regeneration,
            query_generation_tasks_status,
        )
        
        # 新的细粒度工具（用于生成提示词）
        from app.agent.tools.template_tools import (
            get_character_prompt_template,
            get_scene_prompt_template,
        )
        # 注意：提示词生成由 Node 自身的 LLM 完成，不需要调用外部工具
        from app.agent.tools.save_tools import (
            save_character_prompt,
            save_scene_prompt,
        )
        from app.agent.tools.video_prompt_builder_tools import (
            save_video_prompt_result,
        )
        from app.agent.tools.video_knowledge_tools import (
            batch_query_knowledge_for_video,
        )

        return [
            # === 查询类（一次性获取所有分镜、角色、场景）===
            query_all_shots,

            # === 图片/视频生成（直接提交）===
            submit_character_image_regeneration,
            submit_scene_image_regeneration,
            submit_shot_video_regeneration,

            # === 提示词模板（用于指导 Node 生成提示词）===
            get_character_prompt_template,
            get_scene_prompt_template,

            # === 保存提示词 ===
            save_character_prompt,
            save_scene_prompt,
            save_video_prompt_result,

            # === 知识库（批量查询，一次调用替代多次）===
            batch_query_knowledge_for_video,

            # === 任务状态查询（用于等待生成完成）===
            query_generation_tasks_status,
        ]
    
    async def process_result(self, state: ComicDramaState, final_response: str, tool_results: List[Dict]) -> Dict[str, Any]:
        """
        处理 ReAct 循环的最终结果
        
        统计各步骤执行情况，构建响应
        """
        logger.info("=" * 80)
        logger.info(f"[ASSET_REGENERATOR] ========== 处理结果 ==========")
        logger.info(f"[ASSET_REGENERATOR] 工具调用次数: {len(tool_results)}")
        
        # 详细记录每个工具调用
        for i, result in enumerate(tool_results, 1):
            tool_name = result.get("tool", "unknown")
            tool_result = result.get("result", {})
            logger.info(f"[ASSET_REGENERATOR] 工具调用 {i}: {tool_name}")
            logger.info(f"  - 结果: {tool_result}")
        
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
        
        result = {
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
        
        logger.info(f"[ASSET_REGENERATOR] ========== 完成处理 ==========")
        logger.info(f"[ASSET_REGENERATOR] 返回结果:")
        logger.info(f"  - success: {result['success']}")
        logger.info(f"  - success_count: {success_count}")
        logger.info(f"  - failed_count: {failed_count}")
        logger.info(f"  - response_text: {response_text[:100]}...")
        logger.info(f"  - worker: {result['worker_result']['worker']}")
        logger.info("=" * 80)
        
        return result


# 便捷函数
async def regenerate_assets_worker(state: ComicDramaState) -> Dict[str, Any]:
    """LangGraph node 函数"""
    node = AssetRegeneratorWorkerNode()
    return await node.run(state)
