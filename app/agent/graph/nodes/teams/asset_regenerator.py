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
        return f"""你是角色重新生成分析专家。请分析用户的需求，确定要重新生成哪些角色。

用户消息：{user_message}

可用角色：
{available_resources}

请分析并返回 JSON：
{{
    "resource_type": "image",
    "scope": "specific" | "all" | "failed",
    "targets": [
        {{
            "type": "name",
            "value": "角色名",
            "params": {{}}
        }}
    ],
    "reason": "分析说明"
}}

判断规则：
1. 用户提到角色名如"主角"、"小明" -> targets=[{{"type": "name", "value": "主角"}}]
2. 用户说"全部角色"、"所有角色" -> scope="all"
3. 用户说"生成失败的角色"、"重试失败" -> scope="failed"

示例：
- "重新生成主角的图片" -> {{"scope": "specific", "targets": [{{"type": "name", "value": "主角"}}]}}
- "重新生成所有角色" -> {{"scope": "all", "targets": []}}
- "重试失败的角色生成" -> {{"scope": "failed", "targets": []}}

只返回 JSON，不要其他内容。"""

    def _get_scene_prompt(self, user_message: str, available_resources: str) -> str:
        """获取场景分析提示词"""
        return f"""你是场景重新生成分析专家。请分析用户的需求，确定要重新生成哪些场景。

用户消息：{user_message}

可用场景：
{available_resources}

请分析并返回 JSON：
{{
    "resource_type": "image",
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
1. 用户提到场景名如"客厅"、"战场" -> targets=[{{"type": "name", "value": "客厅"}}]
2. 用户说"全部场景"、"所有场景" -> scope="all"
3. 用户说"生成失败的场景"、"重试失败" -> scope="failed"

示例：
- "重新生成客厅的图片" -> {{"scope": "specific", "targets": [{{"type": "name", "value": "客厅"}}]}}
- "重新生成所有场景" -> {{"scope": "all", "targets": []}}
- "重试失败的场景生成" -> {{"scope": "failed", "targets": []}}

只返回 JSON，不要其他内容。"""

    def _get_shot_prompt(self, user_message: str, available_resources: str) -> str:
        """获取分镜分析提示词"""
        return f"""你是分镜重新生成分析专家。请分析用户的需求，确定要重新生成哪些分镜以及生成什么内容。

用户消息：{user_message}

可用分镜：
{available_resources}

请分析并返回 JSON：
{{
    "resource_type": "image" | "video",
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

1. **resource_type 判断**：
   - 提到"视频" -> "video"
   - 提到"图片"、"图像"、"帧" -> "image"
   - 默认 "image"

2. **frame_type 判断**（仅图片时）：
   - 提到"尾帧"、"结束帧"、"最后一帧" -> "end"
   - 提到"首帧"、"开始帧"、"第一帧" -> "start"
   - 提到"图片"但没指定首尾 -> "both"

3. **generation_mode 判断**（仅视频时）：
   - 提到"只用首帧"、"首帧生成" -> "first_frame_only"
   - 提到"首尾帧"、"全部" -> "first_last_frame"
   - 默认 "first_last_frame"

4. **targets 提取**：
   - "分镜1" -> {{"type": "number", "value": 1, "params": {{}}}}
   - "分镜1生成首帧" -> {{"type": "number", "value": 1, "params": {{"frame_type": "start"}}}}
   - "分镜1和2生成视频" -> [
       {{"type": "number", "value": 1, "params": {{"generation_mode": "first_last_frame"}}}},
       {{"type": "number", "value": 2, "params": {{"generation_mode": "first_last_frame"}}}}
     ]

5. **scope 判断**：
   - "全部"、"所有" -> "all"
   - "失败的"、"重试" -> "failed"
   - 指定编号 -> "specific"

重要：如果不同分镜有不同的参数（如分镜1要首帧，分镜2要尾帧），请在 targets 中为每个分镜指定 params。

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

只返回 JSON，不要其他内容。"""

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
            # 1. 检测目标类型（角色/场景/分镜）
            target_type = self._detect_target_type(user_message)
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
            scope = analysis.get("scope", "specific")
            targets = analysis.get("targets", [])

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

    def _detect_target_type(self, user_message: str) -> str:
        """检测目标类型（角色/场景/分镜）"""
        msg_lower = user_message.lower()

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
                "include_details": False,
            })
            if shots_result.get("shots"):
                shots = shots_result["shots"]
                resources_desc.append(f"分镜: {len(shots)} 个")
                for s in shots[:10]:
                    resources_desc.append(f"  - 分镜{s.get('shot_number')}: {s.get('title', '无标题')}")

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

            # 提取分镜编号和参数
            # 模式: "分镜1...首帧"
            pattern = r'分镜\s*(\d+)[^。]*?(首帧|尾帧|开始帧|结束帧)?'
            matches = re.findall(pattern, user_message, re.IGNORECASE)

            for match in matches:
                number = int(match[0])
                frame_type_keyword = match[1]

                params = {}
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
                    targets.append({
                        "type": "number",
                        "value": int(n),
                        "params": {}
                    })

            return {
                "resource_type": resource_type,
                "scope": scope,
                "targets": targets,
                "reason": "兜底分析",
            }

        elif target_type == "character":
            # 提取角色名
            names = re.findall(r'角色["\']?(\w+)["\']?', user_message)
            for name in names:
                targets.append({
                    "type": "name",
                    "value": name,
                    "params": {}
                })

            return {
                "resource_type": "image",
                "scope": scope,
                "targets": targets,
                "reason": "兜底分析",
            }

        else:  # scene
            return {
                "resource_type": "image",
                "scope": scope,
                "targets": targets,
                "reason": "兜底分析",
            }

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
