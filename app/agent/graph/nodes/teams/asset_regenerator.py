"""
资产重新生成节点 - AssetRegenerator

职责：
1. 分析用户要重新生成什么（角色/场景/分镜）
2. 分析要生成哪些具体资源
3. 分析生成参数（首帧/尾帧/视频等）
4. 调用 regenerate_tools 执行

支持：
- 角色图片重新生成
- 场景图片重新生成
- 分镜首帧/尾帧/视频重新生成
- 失败资源批量重试
"""

from typing import Dict, Any, List, Optional
from langchain_core.messages import SystemMessage, HumanMessage
from langchain_openai import ChatOpenAI

from app.agent.state.schemas import ComicDramaState
from app.core.config import settings
from app.core.logger import logger


class AssetRegenerator:
    """
    资产重新生成节点

    职责：
    1. 解析用户意图：要重新生成什么类型的资产
    2. 确定目标资源：哪些角色/场景/分镜
    3. 确定生成参数：首帧/尾帧/视频等
    4. 执行重新生成
    """

    def __init__(self):
        self.llm = ChatOpenAI(
            model=settings.LLM_MODEL_DEFAULT,
            api_key=settings.OPENAI_API_KEY,
            base_url=settings.OPENAI_BASE_URL,
            temperature=0.1,
        )

    def _get_character_prompt(self, user_message: str, available_resources: str) -> str:
        """获取角色分析提示词"""
        return f"""你是角色重新生成分析专家。请分析用户的需求，确定要重新生成哪些角色以及生成什么内容。

用户消息：{user_message}

可用角色：
{available_resources}

请分析并返回 JSON：
{{
    "resource_type": "image" | "image_prompt",
    "operation_type": "regenerate" | "modify",
    "scope": "specific" | "all" | "failed",
    "targets": [
        {{
            "type": "name",
            "value": "角色名",
            "params": {{}}
        }}
    ],
    "modification_type": "simplify" | "detail" | "fix" | "style" | "custom" | null,
    "feedback": "用户的修改意见或null",
    "reason": "分析说明"
}}

判断规则：

1. **resource_type 判断**（重要！）：
   - 如果用户消息包含"图片提示词"或"图像提示词" -> "image_prompt"
   - 如果用户消息包含"图片"、"图像"（但不包含"提示词"）-> "image"
   - 默认 "image"

2. **operation_type 判断**（关键！）：
   - **重新生成(regenerate)**: 用户只是要求"重新生成提示词"，没有提出任何具体修改意见
     - 例如："重新生成阿九的图片提示词"
     - 这种情况下，operation_type="regenerate"
   - **修改(modify)**: 用户提出了具体的修改意见或要求
     - 例如："重新生成阿九的图片提示词，让他更可爱一点"
     - 例如："修改阿九的提示词，把胸口的玉改成铃铛"
     - 这种情况下，operation_type="modify"

3. **modification_type 判断**（仅当 operation_type="modify" 时）：
   - "simplify": 用户要求简化、精简提示词
   - "detail": 用户要求添加更多细节
   - "fix": 用户指出错误并要求修正
   - "style": 用户要求改变风格
   - "custom": 用户提出了具体的自定义修改要求

4. **feedback 提取**（仅当 operation_type="modify" 时）：
   - 提取用户的具体修改意见，作为字符串
   - 例如："让他更可爱一点，胸口挂着铃铛"

5. **targets 提取**：
   - 用户提到角色名如"主角"、"小明"、"阿九-青年" -> targets=[{{"type": "name", "value": "角色名"}}]

6. **scope 判断**：
   - 用户说"全部角色"、"所有角色" -> scope="all"
   - 用户说"生成失败的角色"、"重试失败" -> scope="failed"
   - 指定具体角色名 -> scope="specific"

**关键区分（重要！）**：
- "生成图片" = 生成图片文件（resource_type="image"）
- "生成图片提示词" = 生成图片文字提示词（resource_type="image_prompt"）
- "重新生成"（无修改意见）= 使用模板从头生成新提示词（operation_type="regenerate"）
- "修改"（有修改意见）= 基于原提示词进行修改（operation_type="modify"）

示例：

**重新生成示例（无修改意见）**：
- "重新生成主角的图片提示词" -> {{"resource_type": "image_prompt", "operation_type": "regenerate", "scope": "specific", "targets": [{{"type": "name", "value": "主角"}}], "modification_type": null, "feedback": null}}
- "给阿九-青年重新生成图片提示词" -> {{"resource_type": "image_prompt", "operation_type": "regenerate", "scope": "specific", "targets": [{{"type": "name", "value": "阿九-青年"}}], "modification_type": null, "feedback": null}}

**修改示例（有修改意见）**：
- "重新生成阿九的图片提示词，让他更可爱萌一点" -> {{"resource_type": "image_prompt", "operation_type": "modify", "scope": "specific", "targets": [{{"type": "name", "value": "阿九"}}], "modification_type": "custom", "feedback": "让他更可爱萌一点"}}
- "修改阿九的提示词，把胸口的玉改成铃铛" -> {{"resource_type": "image_prompt", "operation_type": "modify", "scope": "specific", "targets": [{{"type": "name", "value": "阿九"}}], "modification_type": "fix", "feedback": "把胸口的玉改成铃铛"}}
- "简化主角的提示词，太长了" -> {{"resource_type": "image_prompt", "operation_type": "modify", "scope": "specific", "targets": [{{"type": "name", "value": "主角"}}], "modification_type": "simplify", "feedback": "太长了，简化一下"}}

只返回纯 JSON，不要任何其他内容，不要添加 ```json 代码块标签，不要添加任何解释说明。"""

    def _get_scene_prompt(self, user_message: str, available_resources: str) -> str:
        """获取场景分析提示词"""
        return f"""你是场景重新生成分析专家。请分析用户的需求，确定要重新生成哪些场景以及生成什么内容。

用户消息：{user_message}

可用场景：
{available_resources}

请分析并返回 JSON：
{{
    "resource_type": "image" | "image_prompt",
    "scope": "specific" | "all" | "failed",
    "targets": [
        {{
            "type": "name",
            "value": "场景名",
            "params": {{}}
        }}
    ],
    "reason": "分析说明"
}}

判断规则：

1. **resource_type 判断**（直接关键词匹配）：
   - 如果用户消息包含"图片提示词"或"图像提示词" -> "image_prompt"
   - 如果用户消息包含"图片"、"图像"（但不包含"提示词"）-> "image"
   - 默认 "image"

2. **targets 提取**：
   - 用户提到场景名如"客厅"、"战场"、"场景5" -> targets=[{{"type": "name", "value": "客厅"}}]
   - 注意："场景5"表示名称是"场景5"或编号为5的场景

3. **scope 判断**：
   - 用户说"全部场景"、"所有场景" -> scope="all"
   - 用户说"生成失败的场景"、"重试失败" -> scope="failed"
   - 指定具体场景名 -> scope="specific"

示例：
- "重新生成客厅的图片" -> {{"resource_type": "image", "scope": "specific", "targets": [{{"type": "name", "value": "客厅"}}]}}
- "重新生成客厅的图片提示词" -> {{"resource_type": "image_prompt", "scope": "specific", "targets": [{{"type": "name", "value": "客厅"}}]}}
- "重新生成所有场景" -> {{"resource_type": "image", "scope": "all", "targets": []}}
- "重试失败的场景生成" -> {{"resource_type": "image", "scope": "failed", "targets": []}}

只返回纯 JSON，不要任何其他内容，不要添加 ```json 代码块标签，不要添加任何解释说明。"""

    def _get_shot_prompt(self, user_message: str, available_resources: str) -> str:
        """获取分镜分析提示词"""
        return f"""你是分镜重新生成分析专家。请分析用户的需求，确定要重新生成哪些分镜以及生成什么内容。

用户消息：{user_message}

可用分镜列表（格式：分镜编号: 标题）：
{available_resources}

请分析并返回 JSON：
{{
    "resource_type": "image" | "image_prompt" | "video" | "video_prompt",
    "scope": "specific" | "all" | "failed",
    "targets": [
        {{
            "type": "number",
            "value": 1,
            "params": {{
                "frame_type": "start" | "end" | "both",
                "generation_mode": "first_frame_only" | "first_last_frame"
            }}
        }}
    ],
    "reason": "分析说明"
}}

判断规则：

1. **resource_type 判断**（直接关键词匹配）：
   - 如果用户消息包含"图片提示词" -> "image_prompt"
   - 如果用户消息包含"视频提示词"或"视频生成提示词" -> "video_prompt"
   - 如果用户消息包含"生成视频"或"视频生成"（但不包含"提示词"）-> "video"
   - 如果用户消息包含"图片"、"图像"、"帧"（但不包含"提示词"）-> "image"
   - 默认 "image"

2. **frame_type 判断**（仅 image 或 image_prompt 时）：
   - 提到"尾帧"、"结束帧"、"最后一帧" -> "end"
   - 提到"首帧"、"开始帧"、"第一帧" -> "start"
   - 提到"图片"但没指定首尾 -> "both"

3. **generation_mode 判断**（仅 video 时，重要！）：
   - 提到"只用首帧"、"首帧生成"、"首帧模式" -> "first_frame_only"
   - 提到"首尾帧"、"双帧"、"全部" 或 没有指定模式 -> "first_last_frame"
   - **默认必须设置为 "first_last_frame"**
   - **当 resource_type 为 "video" 时，必须在 params 中设置 generation_mode 字段**

4. **targets 提取**（重要！）：
   - 用户说"分镜1" -> 匹配编号为 1 的分镜
   - 用户说"分镜11" -> 匹配编号为 11 的分镜（不是 1）
   - "分镜1生成首帧" -> {{"type": "number", "value": 1, "params": {{"frame_type": "start"}}}}
   - "分镜1生成视频" -> {{"type": "number", "value": 1, "params": {{"generation_mode": "first_last_frame"}}}}（video 必须带 generation_mode）
   - "分镜1重新生成视频提示词" -> {{"type": "number", "value": 1, "params": {{}}}}（video_prompt 不需要 generation_mode）

5. **scope 判断**：
   - "全部"、"所有" -> "all"
   - "失败的"、"重试" -> "failed"
   - 指定编号 -> "specific"

**关键区分（重要！）**：
- "生成图片" = 生成图片文件（resource_type="image"）
- "生成图片提示词" = 生成图片文字提示词（resource_type="image_prompt"）
- "生成视频" = 生成视频文件（resource_type="video"）
- "生成视频提示词" = 生成视频文字提示词（resource_type="video_prompt"）

**重要提示**：
- 请仔细查看"可用分镜列表"中的分镜编号
- 用户提到的分镜编号必须与列表中的编号完全匹配
- 当生成视频时（resource_type="video"），**必须**在 params 中设置 "generation_mode" 字段

示例：
- "给我的分镜1重新生成首帧，分镜2重新生成尾帧" -> 
  {{
    "resource_type": "image",
    "scope": "specific",
    "targets": [
      {{"type": "number", "value": 1, "params": {{"frame_type": "start"}}}},
      {{"type": "number", "value": 2, "params": {{"frame_type": "end"}}}}
    ]
  }}

- "给分镜1生成首帧提示词" ->
  {{
    "resource_type": "image_prompt",
    "scope": "specific",
    "targets": [
      {{"type": "number", "value": 1, "params": {{"frame_type": "start"}}}}
    ]
  }}

- "给分镜1生成视频" ->
  {{
    "resource_type": "video",
    "scope": "specific",
    "targets": [
      {{"type": "number", "value": 1, "params": {{"generation_mode": "first_last_frame"}}}}
    ]
  }}

- "给分镜5重新生成视频提示词" ->
  {{
    "resource_type": "video_prompt",
    "scope": "specific",
    "targets": [
      {{"type": "number", "value": 5, "params": {{}}}}
    ]
  }}

- "用首帧给分镜1和2生成视频" ->
  {{
    "resource_type": "video",
    "scope": "specific",
    "targets": [
      {{"type": "number", "value": 1, "params": {{"generation_mode": "first_frame_only"}}}},
      {{"type": "number", "value": 2, "params": {{"generation_mode": "first_frame_only"}}}}
    ]
  }}

- "重新生成所有失败的分镜视频" ->
  {{
    "resource_type": "video",
    "scope": "failed",
    "targets": []
  }}

只返回纯 JSON，不要任何其他内容，不要添加 ```json 代码块标签，不要添加任何解释说明。"""

    async def run(self, state: ComicDramaState) -> Dict[str, Any]:
        """
        执行资产重新生成

        Args:
            state: 当前状态

        Returns:
            执行结果
        """
        creation_uuid = state.get("creation_uuid")
        user_message = state.get("user_message", "")

        logger.info(f"[AssetRegenerator] 开始分析: '{user_message}'")

        try:
            # 1. 先获取所有角色和场景名称，用于智能检测目标类型
            character_names = await self._get_character_names(creation_uuid)
            scene_names = await self._get_scene_names(creation_uuid)

            # 2. 检测目标类型（角色/场景/分镜）- 使用名称匹配
            target_type = self._detect_target_type(user_message, character_names, scene_names)
            logger.info(f"[AssetRegenerator] 检测到目标类型: {target_type}")

            # 2. 获取可用资源列表
            available_resources = await self._get_available_resources(creation_uuid, target_type)

            # 3. 使用对应的 LLM 分析用户需求
            analysis = await self._analyze_by_type(target_type, user_message, available_resources)

            if not analysis:
                return {
                    "response_text": "无法解析您的重新生成请求，请明确说明要重新生成什么",
                    "success": False,
                }

            logger.info(f"[AssetRegenerator] 分析结果: {analysis}")

            # 4. 根据分析结果执行重新生成
            resource_type = analysis.get("resource_type", "image")
            operation_type = analysis.get("operation_type", "regenerate")  # regenerate / modify
            scope = analysis.get("scope", "specific")
            targets = analysis.get("targets", [])
            modification_type = analysis.get("modification_type")  # simplify / detail / fix / style / custom
            feedback = analysis.get("feedback")  # 用户的修改意见

            # 检查是否是提示词重新生成请求（image_prompt / video_prompt / prompt_regenerate）
            if resource_type in ["image_prompt", "video_prompt", "prompt_regenerate"]:
                # 调用 PromptRegenerator 处理提示词重新生成或修改
                from app.agent.graph.nodes.teams.prompt_regenerator import PromptRegenerator
                prompt_regenerator = PromptRegenerator()

                # 构建新的 state 传递给 PromptRegenerator
                # 添加所有必要信息，包括 operation_type 和修改相关参数
                prompt_state = {
                    "creation_uuid": creation_uuid,
                    "user_message": user_message,
                    "messages": state.get("messages", []),
                    "target_type": target_type,  # character / scene / shot
                    "resource_type": resource_type,  # image_prompt / video_prompt
                    "operation_type": operation_type,  # regenerate / modify
                    "targets": targets,  # 目标列表
                    "modification_type": modification_type,  # simplify / detail / fix / style / custom
                    "feedback": feedback,  # 用户的修改意见
                }

                result = await prompt_regenerator.run(prompt_state)
                return result

            # 5. 确定要重新生成的资源
            if scope == "failed":
                # 获取失败的资源
                resources_to_regenerate = await self._get_failed_resources(
                    creation_uuid=creation_uuid,
                    target_type=target_type,
                    resource_type=resource_type,
                )
            else:
                # 根据 targets 解析资源
                resources_to_regenerate = await self._resolve_resources_by_targets(
                    creation_uuid=creation_uuid,
                    target_type=target_type,
                    targets=targets,
                    scope=scope,
                )

            if not resources_to_regenerate:
                return {
                    "response_text": f"未找到要重新生成的{target_type}资源",
                    "success": False,
                }

            # 6. 执行重新生成（传递 targets 以获取每个资源的参数）
            results = await self._execute_regeneration(
                creation_uuid=creation_uuid,
                resources=resources_to_regenerate,
                target_type=target_type,
                resource_type=resource_type,
                targets=targets,
            )

            # 7. 构建响应
            success_count = sum(1 for r in results if r.get("success"))
            failed_count = len(results) - success_count

            message = self._build_response_message(
                target_type=target_type,
                resource_type=resource_type,
                success_count=success_count,
                failed_count=failed_count,
                resources=resources_to_regenerate,
            )

            return {
                "response_text": message,
                "success": success_count > 0,
                "regenerated_count": success_count,
                "failed_count": failed_count,
                "results": results,
            }

        except Exception as e:
            logger.error(f"[AssetRegenerator] 执行失败: {e}")
            import traceback
            logger.error(f"[AssetRegenerator] 异常栈: {traceback.format_exc()}")
            return {
                "response_text": f"重新生成过程中出现错误：{str(e)}",
                "success": False,
            }

    async def _get_character_names(self, creation_uuid: str) -> List[str]:
        """获取所有角色名称"""
        from app.agent.tools.db_tools import query_characters
        try:
            result = await query_characters.ainvoke({
                "creation_uuid": creation_uuid,
                "include_images": False,
            })
            characters = result.get("characters", [])
            names = []
            for c in characters:
                name = c.get("name", "")
                if name:
                    names.append(name)
                    # 也添加名称的变体（如"阿九-青年" -> "阿九"）
                    if "-" in name:
                        names.append(name.split("-")[0])
            return names
        except Exception as e:
            logger.warning(f"[AssetRegenerator] 获取角色名称失败: {e}")
            return []

    async def _get_scene_names(self, creation_uuid: str) -> List[str]:
        """获取所有场景名称"""
        from app.agent.tools.db_tools import query_scenes
        try:
            result = await query_scenes.ainvoke({"creation_uuid": creation_uuid})
            scenes = result.get("scenes", [])
            return [s.get("title", "") for s in scenes if s.get("title")]
        except Exception as e:
            logger.warning(f"[AssetRegenerator] 获取场景名称失败: {e}")
            return []

    def _detect_target_type(self, user_message: str, character_names: List[str] = None, scene_names: List[str] = None) -> str:
        """检测目标类型（角色/场景/分镜）

        优先级：
        1. 检查消息中是否包含角色名称
        2. 检查消息中是否包含场景名称
        3. 检查关键词（角色/人物/场景/背景）
        4. 默认分镜
        """
        msg_lower = user_message.lower()

        # 1. 检查是否包含角色名称
        if character_names:
            for name in character_names:
                if name and name.lower() in msg_lower:
                    logger.info(f"[AssetRegenerator] 检测到角色名称 '{name}' 在消息中")
                    return "character"

        # 2. 检查是否包含场景名称
        if scene_names:
            for name in scene_names:
                if name and name.lower() in msg_lower:
                    logger.info(f"[AssetRegenerator] 检测到场景名称 '{name}' 在消息中")
                    return "scene"

        # 3. 检查关键词
        if "角色" in msg_lower or "人物" in msg_lower:
            return "character"
        elif "场景" in msg_lower or "背景" in msg_lower:
            return "scene"
        else:
            # 默认分镜
            return "shot"

    async def _get_available_resources(self, creation_uuid: str, target_type: str) -> str:
        """获取可用资源列表"""
        from app.agent.tools.db_tools import query_shots, query_characters, query_scenes

        resources_desc = []

        if target_type == "shot":
            shots_result = await query_shots.ainvoke({
                "creation_uuid": creation_uuid,
                "include_details": True,  # 需要详细信息包括 shot_number
            })
            if shots_result.get("shots"):
                shots = shots_result["shots"]
                resources_desc.append(f"分镜: {len(shots)} 个")
                for s in shots[:10]:
                    shot_number = s.get('shot_number') or s.get('sequence') or s.get('id', '?')
                    title = s.get('title') or s.get('description', '无标题')[:20] if s.get('description') else '无标题'
                    resources_desc.append(f"  - 分镜{shot_number}: {title}")

        elif target_type == "character":
            chars_result = await query_characters.ainvoke({
                "creation_uuid": creation_uuid,
                "include_images": False,
            })
            if chars_result.get("characters"):
                characters = chars_result["characters"]
                resources_desc.append(f"角色: {len(characters)} 个")
                for c in characters[:5]:
                    resources_desc.append(f"  - {c.get('name', '未命名')}")

        elif target_type == "scene":
            scenes_result = await query_scenes.ainvoke({"creation_uuid": creation_uuid})
            if scenes_result.get("scenes"):
                scenes = scenes_result["scenes"]
                resources_desc.append(f"场景: {len(scenes)} 个")
                for s in scenes[:5]:
                    resources_desc.append(f"  - {s.get('title', '未命名')}")

        return "\n".join(resources_desc) if resources_desc else "暂无资源"

    async def _analyze_by_type(
        self,
        target_type: str,
        user_message: str,
        available_resources: str,
    ) -> Optional[Dict[str, Any]]:
        """根据目标类型使用对应的 LLM 分析"""
        try:
            if target_type == "character":
                prompt = self._get_character_prompt(user_message, available_resources)
            elif target_type == "scene":
                prompt = self._get_scene_prompt(user_message, available_resources)
            else:  # shot
                prompt = self._get_shot_prompt(user_message, available_resources)

            response = await self.llm.ainvoke([
                SystemMessage(content=prompt),
                HumanMessage(content="请分析用户需求")
            ])

            import json
            import re

            content = response.content.strip()

            content = self._clean_response_content(content)

            # 从 markdown 代码块提取
            if "```" in content:
                match = re.search(r'```(?:json)?\s*([\s\S]*?)\s*```', content)
                if match:
                    content = match.group(1)

            analysis = json.loads(content)
            return analysis

        except Exception as e:
            logger.error(f"[AssetRegenerator] 分析请求失败: {e}")
            # 兜底：从消息中直接检测
            return self._fallback_analysis(target_type, user_message)

    def _fallback_analysis(self, target_type: str, user_message: str) -> Dict[str, Any]:
        """兜底分析：从用户消息中直接提取信息"""
        import re

        msg_lower = user_message.lower()

        # 检测 scope
        scope = "specific"
        if "全部" in user_message or "所有" in user_message:
            scope = "all"
        elif "失败" in user_message or "重试" in user_message:
            scope = "failed"

        targets = []

        if target_type == "shot":
            # 检测 resource_type
            resource_type = "video" if "视频" in user_message else "image"

            # 检测 generation_mode（仅视频时）
            generation_mode = "first_last_frame"  # 默认使用首尾帧模式
            if "只用首帧" in user_message or "首帧生成" in user_message or "单帧" in user_message:
                generation_mode = "first_frame_only"
            elif "首尾帧" in user_message or "双帧" in user_message:
                generation_mode = "first_last_frame"

            # 提取分镜编号和参数
            # 模式: "分镜1...首帧"
            pattern = r'分镜\s*(\d+)[^。]*?(首帧|尾帧|开始帧|结束帧)?'
            matches = re.findall(pattern, user_message, re.IGNORECASE)

            for match in matches:
                number = int(match[0])
                frame_type_keyword = match[1]

                params = {}

                # 视频模式添加 generation_mode
                if resource_type == "video":
                    params["generation_mode"] = generation_mode

                if frame_type_keyword in ["首帧", "开始帧"]:
                    params["frame_type"] = "start"
                elif frame_type_keyword in ["尾帧", "结束帧"]:
                    params["frame_type"] = "end"

                targets.append({
                    "type": "number",
                    "value": number,
                    "params": params
                })

            if not targets:
                # 简单提取编号
                numbers = re.findall(r'分镜\s*(\d+)', user_message)
                for n in numbers:
                    params = {}
                    # 视频模式添加 generation_mode
                    if resource_type == "video":
                        params["generation_mode"] = generation_mode
                    targets.append({
                        "type": "number",
                        "value": int(n),
                        "params": params
                    })

            return {
                "resource_type": resource_type,
                "scope": scope,
                "targets": targets,
                "reason": "兜底分析",
            }

        elif target_type == "character":
            # 检测 resource_type
            resource_type = "image_prompt" if "提示词" in user_message else "image"

            # 检测 operation_type：是否有修改意见
            # 简单的启发式：如果消息长度超过基本请求，可能包含修改意见
            operation_type = "regenerate"
            modification_type = None
            feedback = None

            # 检测常见的修改关键词
            modify_keywords = ["改成", "改为", "变成", "添加", "删除", "去掉", "加上", "更", "有点", "太", "不够"]
            has_modify_intent = any(kw in user_message for kw in modify_keywords)

            if has_modify_intent:
                operation_type = "modify"
                modification_type = "custom"
                # 提取修改意见（简单实现：取"重新生成"之后的内容）
                if "重新生成" in user_message:
                    parts = user_message.split("重新生成", 1)
                    if len(parts) > 1:
                        feedback = parts[1].strip("，。！？")

            # 兜底：如果没有提取到角色名，尝试从消息中提取
            if not targets:
                # 尝试匹配 "给 XXX 重新生成" 或 "重新生成 XXX 的图片"
                patterns = [
                    r'给\s*([^\s]+(?:-[^\s]+)?)\s*重新生成',
                    r'重新生成\s*([^\s]+(?:-[^\s]+)?)\s*的?图片',
                    r'([^\s]+(?:-[^\s]+)?)\s*的?图片.*重新生成',
                ]
                for pattern in patterns:
                    match = re.search(pattern, user_message)
                    if match:
                        name = match.group(1).strip()
                        if name and name not in ["全部", "所有", "失败"]:
                            targets.append({
                                "type": "name",
                                "value": name,
                                "params": {}
                            })
                            break

            return {
                "resource_type": resource_type,
                "operation_type": operation_type,
                "scope": scope,
                "targets": targets,
                "modification_type": modification_type,
                "feedback": feedback,
                "reason": "兜底分析",
            }

        else:  # scene
            # 检测 resource_type
            resource_type = "image_prompt" if "提示词" in user_message else "image"

            # 检测 operation_type
            operation_type = "regenerate"
            modification_type = None
            feedback = None

            modify_keywords = ["改成", "改为", "变成", "添加", "删除", "去掉", "加上", "更", "有点", "太", "不够"]
            if any(kw in user_message for kw in modify_keywords):
                operation_type = "modify"
                modification_type = "custom"

            return {
                "resource_type": resource_type,
                "operation_type": operation_type,
                "scope": scope,
                "targets": targets,
                "modification_type": modification_type,
                "feedback": feedback,
                "reason": "兜底分析",
            }

    def _clean_response_content(self, content: str) -> str:
        """清理 AI 响应内容，移除多余标签"""
        import re

        content = content.strip()

        content = re.sub(r'^<[^>]*>\s*', '', content)
        content = re.sub(r'\s*</[^>]*>$', '', content)

        content = re.sub(r'^<text[^>]*>\s*', '', content, flags=re.IGNORECASE)
        content = re.sub(r'\s*</text>$', '', content, flags=re.IGNORECASE)

        content = re.sub(r'^<think[^>]*>\s*', '', content, flags=re.IGNORECASE)
        content = re.sub(r'\s*<\/think>$', '', content, flags=re.IGNORECASE)

        content = re.sub(r'^<reasoning[^>]*>\s*', '', content, flags=re.IGNORECASE)
        content = re.sub(r'\s*<\/reasoning>$', '', content, flags=re.IGNORECASE)

        content = re.sub(r'^与分析.*?相关\s*', '', content, flags=re.IGNORECASE)
        content = re.sub(r'\s*与分析.*?相关$', '', content, flags=re.IGNORECASE)

        content = content.strip()

        return content

    async def _get_failed_resources(
        self,
        creation_uuid: str,
        target_type: str,
        resource_type: str,
    ) -> List[Dict[str, Any]]:
        """获取生成失败的资源"""
        from app.agent.tools.db_tools import query_shots, query_characters, query_scenes

        resources = []

        if target_type == "shot":
            result = await query_shots.ainvoke({
                "creation_uuid": creation_uuid,
                "include_details": True,
            })
            shots = result.get("shots", [])

            for shot in shots:
                is_failed = False

                if resource_type == "video":
                    # 视频生成失败：没有 video_url
                    if not shot.get("video_url"):
                        is_failed = True
                else:  # image
                    # 图片生成失败：没有 image_url 和 end_frame_image_url
                    if not shot.get("image_url") and not shot.get("end_frame_image_url"):
                        is_failed = True

                if is_failed:
                    resources.append(shot)

        elif target_type == "character":
            result = await query_characters.ainvoke({
                "creation_uuid": creation_uuid,
                "include_images": True,
            })
            characters = result.get("characters", [])

            for char in characters:
                # 角色生成失败：没有 image_url
                if not char.get("image_url"):
                    resources.append(char)

        elif target_type == "scene":
            result = await query_scenes.ainvoke({"creation_uuid": creation_uuid})
            scenes = result.get("scenes", [])

            for scene in scenes:
                # 场景生成失败：没有 image_url
                if not scene.get("image_url"):
                    resources.append(scene)

        logger.info(f"[AssetRegenerator] 找到 {len(resources)} 个失败的{target_type}资源")
        return resources

    async def _resolve_resources_by_targets(
        self,
        creation_uuid: str,
        target_type: str,
        targets: List[Dict[str, Any]],
        scope: str,
    ) -> List[Dict[str, Any]]:
        """根据 targets 解析资源"""
        from app.agent.tools.resource_resolver import resolve_resource_reference
        from app.agent.tools.db_tools import query_shots, query_characters, query_scenes

        resources = []

        if scope == "all":
            # 获取所有资源
            if target_type == "shot":
                result = await query_shots.ainvoke({
                    "creation_uuid": creation_uuid,
                    "include_details": False,
                })
                resources = result.get("shots", [])
            elif target_type == "character":
                result = await query_characters.ainvoke({
                    "creation_uuid": creation_uuid,
                    "include_images": False,
                })
                resources = result.get("characters", [])
            elif target_type == "scene":
                result = await query_scenes.ainvoke({"creation_uuid": creation_uuid})
                resources = result.get("scenes", [])

        else:
            # 根据 targets 解析
            for target in targets:
                target_value = target.get("value")
                if not target_value:
                    continue

                if target_type == "shot":
                    # 分镜按编号解析
                    match_result = await resolve_resource_reference.ainvoke({
                        "creation_uuid": creation_uuid,
                        "target": "shot",
                        "user_reference": f"分镜{target_value}",
                    })
                elif target_type == "character":
                    match_result = await resolve_resource_reference.ainvoke({
                        "creation_uuid": creation_uuid,
                        "target": "character",
                        "user_reference": target_value,
                    })
                else:  # scene
                    match_result = await resolve_resource_reference.ainvoke({
                        "creation_uuid": creation_uuid,
                        "target": "scene",
                        "user_reference": target_value,
                    })

                if match_result.get("success"):
                    matched = match_result.get("matched_resources", [])
                    # 将 target 的 params 附加到资源上
                    for resource in matched:
                        resource["_regenerate_params"] = target.get("params", {})
                    resources.extend(matched)

        return resources

    async def _execute_regeneration(
        self,
        creation_uuid: str,
        resources: List[Dict[str, Any]],
        target_type: str,
        resource_type: str,
        targets: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        """执行重新生成"""
        from app.agent.tools.regenerate_tools import regenerate

        results = []

        # 构建 targets 查找字典
        target_params = {}
        for target in targets:
            if target.get("type") == "number":
                target_params[target["value"]] = target.get("params", {})
            elif target.get("type") == "name":
                target_params[target["value"]] = target.get("params", {})

        for resource in resources:
            try:
                # 获取该资源的特定参数
                resource_params = resource.get("_regenerate_params", {})

                # 如果没有附加参数，从 target_params 查找
                if not resource_params:
                    if target_type == "shot":
                        key = resource.get("shot_number")
                    elif target_type == "character":
                        key = resource.get("name")
                    else:
                        key = resource.get("title")

                    resource_params = target_params.get(key, {})

                # 确定 regenerate 参数
                if target_type == "shot":
                    frame_type = resource_params.get("frame_type", "both")
                    generation_mode = resource_params.get("generation_mode", "first_last_frame")

                    if resource_type == "video":
                        regen_target_type = "shot_video"
                        mode = generation_mode
                    else:  # image
                        if frame_type == "start":
                            regen_target_type = "shot_start"
                        elif frame_type == "end":
                            regen_target_type = "shot_end"
                        else:
                            regen_target_type = "shot_image"
                        mode = "auto"

                elif target_type == "character":
                    regen_target_type = "character"
                    mode = "auto"

                elif target_type == "scene":
                    regen_target_type = "scene"
                    mode = "auto"

                else:
                    continue

                # 获取资源 ID
                resource_id = resource.get("shot_id") or resource.get("character_id") or resource.get("scene_id") or resource.get("id")

                logger.info(f"[AssetRegenerator] 重新生成: type={regen_target_type}, id={resource_id}, mode={mode}, params={resource_params}")

                # 调用 regenerate
                result = await regenerate.ainvoke({
                    "target_type": regen_target_type,
                    "target_id": resource_id,
                    "creation_uuid": creation_uuid,
                    "save_version": True,
                    "mode": mode,
                })

                results.append({
                    "id": resource_id,
                    "name": resource.get("name") or resource.get("shot_number") or resource.get("title"),
                    "success": result.get("success", False),
                    "task_id": result.get("task_id"),
                    "error": result.get("error"),
                })

            except Exception as e:
                logger.error(f"[AssetRegenerator] 重新生成失败: {e}")
                results.append({
                    "id": resource.get("id"),
                    "name": resource.get("name") or resource.get("shot_number"),
                    "success": False,
                    "error": str(e),
                })

        return results

    def _build_response_message(
        self,
        target_type: str,
        resource_type: str,
        success_count: int,
        failed_count: int,
        resources: List[Dict[str, Any]],
    ) -> str:
        """构建响应消息"""
        type_names = {
            "character": "角色",
            "scene": "场景",
            "shot": "分镜",
        }

        resource_names = {
            "image": "图片",
            "video": "视频",
        }

        target_name = type_names.get(target_type, target_type)
        resource_name = resource_names.get(resource_type, "资源")

        if success_count == 1:
            resource = resources[0]
            name = resource.get("name") or resource.get("shot_number") or resource.get("title", "")
            message = f"🔄 已为{target_name}「{name}」重新提交{resource_name}生成任务"
        else:
            message = f"🔄 已为 {success_count} 个{target_name}重新提交{resource_name}生成任务"

        if failed_count > 0:
            message += f"\n（{failed_count} 个失败）"

        message += "\n\n生成完成后会更新，请稍后在看板查看结果。"

        return message


# 便捷函数
async def regenerate_assets(state: ComicDramaState) -> Dict[str, Any]:
    """LangGraph node 函数"""
    node = AssetRegenerator()
    return await node.run(state)
