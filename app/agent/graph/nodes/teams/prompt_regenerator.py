"""
提示词重新生成节点 - PromptRegenerator

职责：
1. 分析用户要重新生成什么类型的提示词（角色/场景/分镜/视频）
2. 分析用户的修改意见（简化/加细节/修正/改风格/自定义）
3. 调用 LLM 根据原提示词和修改意见生成新提示词
4. 保存新提示词到数据库

支持：
- 角色图片提示词重新生成
- 场景图片提示词重新生成
- 分镜首帧/尾帧提示词重新生成
- 分镜视频提示词重新生成
"""

from typing import Dict, Any, List, Optional
from langchain_core.messages import SystemMessage, HumanMessage
from langchain_openai import ChatOpenAI
from sqlalchemy.orm.attributes import flag_modified

from app.agent.state.schemas import ComicDramaState
from app.core.config import settings
from app.core.logger import logger


class PromptRegenerator:
    """
    提示词重新生成节点

    职责：
    1. 解析用户意图：要重新生成什么类型的提示词
    2. 确定目标资源：哪些角色/场景/分镜
    3. 确定修改类型：简化/加细节/修正/改风格/自定义
    4. 执行提示词重新生成
    """

    MODIFICATION_TYPES = {
        "simplify": "简化提示词，去除冗余描述，保留核心要素",
        "detail": "添加更多细节和描述，丰富画面内容",
        "fix": "修正错误或不准确的内容，确保描述正确",
        "style": "改变风格或调性，调整视觉表现",
        "custom": "根据用户自定义意见修改",
    }

    OPERATION_TYPES = {
        "regenerate": "重新生成 - 忽略旧提示词，直接使用模板重新生成新提示词",
        "modify": "修改 - 基于旧提示词，根据用户反馈进行修改优化",
    }

    def __init__(self):
        self.llm = ChatOpenAI(
            model=settings.LLM_MODEL_DEFAULT,
            api_key=settings.OPENAI_API_KEY,
            base_url=settings.OPENAI_BASE_URL,
            temperature=0.7,
        )

    def _get_character_prompt(self, user_message: str, available_resources: str) -> str:
        """获取角色提示词分析提示词"""
        return f"""你是角色提示词重新生成分析专家。请分析用户的需求，确定要重新生成哪些角色的提示词、操作类型以及修改类型。

用户消息：{user_message}

可用角色：
{available_resources}

请分析并返回 JSON：
{{
    "target_type": "character",
    "prompt_type": "image",
    "scope": "specific" | "all" | "failed",
    "targets": [
        {{
            "type": "name",
            "value": "角色名",
            "params": {{
                "operation_type": "regenerate" | "modify",
                "modification_type": "simplify" | "detail" | "fix" | "style" | "custom",
                "feedback": "用户的具体修改意见"
            }}
        }}
    ],
    "reason": "分析说明"
}}

操作类型说明：
- regenerate: 重新生成 - 忽略旧提示词，直接使用模板重新生成新提示词
- modify: 修改 - 基于旧提示词，根据用户反馈进行修改优化

修改类型说明：
- simplify: 简化提示词，去除冗余描述
- detail: 添加更多细节和描述
- fix: 修正错误或不准确的内容
- style: 改变风格或调性
- custom: 根据用户自定义意见修改

判断规则：

**操作类型判断（重要）：**
1. 用户说"重新生成提示词"、"重新生成"、"再来一次" -> operation_type="regenerate"（忽略旧提示词）
2. 用户说"修改提示词"、"改一下"、"优化"、"太啰嗦"、"有错"、"加细节" -> operation_type="modify"（基于旧提示词修改）

**修改类型判断：**
1. 用户提到"太啰嗦"、"简化"、"简短" -> modification_type="simplify"
2. 用户提到"加细节"、"更丰富"、"详细" -> modification_type="detail"
3. 用户提到"有错"、"不对"、"修正" -> modification_type="fix"
4. 用户提到"风格"、"调性" -> modification_type="style"
5. 其他具体修改意见 -> modification_type="custom"

示例：
- "重新生成主角的提示词" -> {{"scope": "specific", "targets": [{{"type": "name", "value": "主角", "params": {{"operation_type": "regenerate"}}}}]}}
- "修改主角的提示词，太啰嗦了" -> {{"scope": "specific", "targets": [{{"type": "name", "value": "主角", "params": {{"operation_type": "modify", "modification_type": "simplify", "feedback": "太啰嗦了"}}}}]}}
- "给所有角色提示词加细节" -> {{"scope": "all", "targets": [], "params": {{"operation_type": "modify", "modification_type": "detail"}}}}
- "重新生成失败的提示词" -> {{"scope": "failed", "targets": []}}

只返回纯 JSON，不要任何其他内容，不要添加 ```json 代码块标签，不要添加任何解释说明。"""

    def _get_scene_prompt(self, user_message: str, available_resources: str) -> str:
        """获取场景提示词分析提示词"""
        return f"""你是场景提示词重新生成分析专家。请分析用户的需求，确定要重新生成哪些场景的提示词、操作类型以及修改类型。

用户消息：{user_message}

可用场景：
{available_resources}

请分析并返回 JSON：
{{
    "target_type": "scene",
    "prompt_type": "image",
    "scope": "specific" | "all" | "failed",
    "targets": [
        {{
            "type": "name",
            "value": "场景名",
            "params": {{
                "operation_type": "regenerate" | "modify",
                "modification_type": "simplify" | "detail" | "fix" | "style" | "custom",
                "feedback": "用户的具体修改意见"
            }}
        }}
    ],
    "reason": "分析说明"
}}

操作类型说明：
- regenerate: 重新生成 - 忽略旧提示词，直接使用模板重新生成新提示词
- modify: 修改 - 基于旧提示词，根据用户反馈进行修改优化

修改类型说明：
- simplify: 简化提示词，去除冗余描述
- detail: 添加更多细节和描述
- fix: 修正错误或不准确的内容
- style: 改变风格或调性
- custom: 根据用户自定义意见修改

判断规则：

**操作类型判断（重要）：**
1. 用户说"重新生成提示词"、"重新生成"、"再来一次" -> operation_type="regenerate"（忽略旧提示词）
2. 用户说"修改提示词"、"改一下"、"优化"、"太啰嗦"、"有错"、"加细节" -> operation_type="modify"（基于旧提示词修改）

**修改类型判断：**
1. 用户提到"太啰嗦"、"简化" -> modification_type="simplify"
2. 用户提到"加细节"、"更丰富" -> modification_type="detail"
3. 用户提到"有错"、"不对" -> modification_type="fix"
4. 用户提到"风格" -> modification_type="style"
5. 其他具体修改意见 -> modification_type="custom"

示例：
- "重新生成客厅的提示词" -> {{"scope": "specific", "targets": [{{"type": "name", "value": "客厅", "params": {{"operation_type": "regenerate"}}}}]}}
- "修改客厅的提示词，太啰嗦了" -> {{"scope": "specific", "targets": [{{"type": "name", "value": "客厅", "params": {{"operation_type": "modify", "modification_type": "simplify"}}}}]}}
- "给所有场景提示词加细节" -> {{"scope": "all", "targets": [], "params": {{"operation_type": "modify", "modification_type": "detail"}}}}

只返回纯 JSON，不要任何其他内容，不要添加 ```json 代码块标签，不要添加任何解释说明。"""

    def _get_shot_prompt(self, user_message: str, available_resources: str) -> str:
        """获取分镜提示词分析提示词"""
        return f"""你是分镜提示词重新生成分析专家。请分析用户的需求，确定要重新生成哪些分镜的提示词、操作类型、提示词类型以及修改类型。

用户消息：{user_message}

可用分镜：
{available_resources}

请分析并返回 JSON：
{{
    "target_type": "shot",
    "prompt_type": "image" | "video",
    "scope": "specific" | "all" | "failed",
    "targets": [
        {{
            "type": "number",
            "value": 1,
            "params": {{
                "operation_type": "regenerate" | "modify",
                "frame_type": "start" | "end" | "both",
                "modification_type": "simplify" | "detail" | "fix" | "style" | "custom",
                "feedback": "用户的具体修改意见"
            }}
        }}
    ],
    "reason": "分析说明"
}}

操作类型说明：
- regenerate: 重新生成 - 忽略旧提示词，直接使用模板重新生成新提示词
- modify: 修改 - 基于旧提示词，根据用户反馈进行修改优化

修改类型说明：
- simplify: 简化提示词，去除冗余描述
- detail: 添加更多细节和描述
- fix: 修正错误或不准确的内容
- style: 改变风格或调性
- custom: 根据用户自定义意见修改

判断规则：

**操作类型判断（重要）：**
1. 用户说"重新生成提示词"、"重新生成"、"再来一次" -> operation_type="regenerate"（忽略旧提示词）
2. 用户说"修改提示词"、"改一下"、"优化"、"太啰嗦"、"有错"、"加细节" -> operation_type="modify"（基于旧提示词修改）

1. **prompt_type 判断**：
   - 提到"视频提示词"、"视频prompt" -> "video"
   - 提到"图片提示词"、"提示词" -> "image"
   - 默认 "image"

2. **frame_type 判断**（仅图片时）：
   - 提到"尾帧"、"结束帧" -> "end"
   - 提到"首帧"、"开始帧" -> "start"
   - 提到"提示词"但没指定首尾 -> "both"

3. **modification_type 判断**（仅modify操作时需要）：
   - "太啰嗦"、"简化"、"简短" -> "simplify"
   - "加细节"、"更丰富"、"详细点" -> "detail"
   - "有错"、"不对"、"修正" -> "fix"
   - "风格"、"调性" -> "style"
   - 其他 -> "custom"

4. **targets 提取**：
   - "分镜1" -> {{"type": "number", "value": 1}}
   - "分镜1提示词简化" -> {{"type": "number", "value": 1, "params": {{"operation_type": "modify", "modification_type": "simplify"}}}}
   - "分镜1和2，1要简化，2要加细节" -> [
       {{"type": "number", "value": 1, "params": {{"operation_type": "modify", "modification_type": "simplify"}}}},
       {{"type": "number", "value": 2, "params": {{"operation_type": "modify", "modification_type": "detail"}}}}
     ]

5. **scope 判断**：
   - "全部"、"所有" -> "all"
   - "失败的"、"重试" -> "failed"
   - 指定编号 -> "specific"

重要：如果不同分镜有不同的修改要求，请在 targets 中为每个分镜指定 params。

示例：
- "重新生成分镜1的提示词" -> 
  {{
    "target_type": "shot",
    "prompt_type": "image",
    "scope": "specific",
    "targets": [{{"type": "number", "value": 1, "params": {{"operation_type": "regenerate", "frame_type": "both"}}}}]
  }}

- "修改分镜1的提示词，太啰嗦了" -> 
  {{
    "target_type": "shot",
    "prompt_type": "image",
    "scope": "specific",
    "targets": [{{"type": "number", "value": 1, "params": {{"operation_type": "modify", "frame_type": "both", "modification_type": "simplify", "feedback": "太啰嗦了"}}}}]
  }}

- "给分镜1和2的尾帧提示词加细节" ->
  {{
    "target_type": "shot",
    "prompt_type": "image",
    "scope": "specific",
    "targets": [
      {{"type": "number", "value": 1, "params": {{"operation_type": "modify", "frame_type": "end", "modification_type": "detail"}}}},
      {{"type": "number", "value": 2, "params": {{"operation_type": "modify", "frame_type": "end", "modification_type": "detail"}}}}
    ]
  }}

- "重新生成分镜1的视频提示词" ->
  {{
    "target_type": "shot",
    "prompt_type": "video",
    "scope": "specific",
    "targets": [{{"type": "number", "value": 1, "params": {{}}}}]
  }}

只返回纯 JSON，不要任何其他内容，不要添加 ```json 代码块标签，不要添加任何解释说明。"""

    async def run(self, state: ComicDramaState) -> Dict[str, Any]:
        """
        执行提示词重新生成

        Args:
            state: 当前状态

        Returns:
            执行结果
        """
        creation_uuid = state.get("creation_uuid")
        user_message = state.get("user_message", "")

        logger.info(f"[PromptRegenerator] 开始分析: '{user_message}'")

        try:
            # 1. 检测目标类型（角色/场景/分镜）
            target_type = self._detect_target_type(user_message)
            logger.info(f"[PromptRegenerator] 检测到目标类型: {target_type}")

            # 2. 获取可用资源列表
            available_resources = await self._get_available_resources(creation_uuid, target_type)

            # 3. 使用对应的 LLM 分析用户需求
            analysis = await self._analyze_by_type(target_type, user_message, available_resources)

            if not analysis:
                return {
                    "response_text": "无法解析您的提示词重新生成请求，请明确说明要重新生成什么",
                    "success": False,
                }

            logger.info(f"[PromptRegenerator] 分析结果: {analysis}")

            # 4. 根据分析结果执行重新生成
            prompt_type = analysis.get("prompt_type", "image")
            scope = analysis.get("scope", "specific")
            targets = analysis.get("targets", [])

            # 5. 确定要重新生成提示词的资源
            if scope == "failed":
                resources_to_regenerate = await self._get_failed_prompt_resources(
                    creation_uuid=creation_uuid,
                    target_type=target_type,
                    prompt_type=prompt_type,
                )
            else:
                resources_to_regenerate = await self._resolve_resources_by_targets(
                    creation_uuid=creation_uuid,
                    target_type=target_type,
                    targets=targets,
                    scope=scope,
                )

            if not resources_to_regenerate:
                return {
                    "response_text": f"未找到要重新生成提示词的{target_type}资源",
                    "success": False,
                }

            # 6. 执行提示词重新生成
            results = await self._execute_prompt_regeneration(
                creation_uuid=creation_uuid,
                resources=resources_to_regenerate,
                target_type=target_type,
                prompt_type=prompt_type,
                targets=targets,
            )

            # 7. 构建响应
            success_count = sum(1 for r in results if r.get("success"))
            failed_count = len(results) - success_count

            message = self._build_response_message(
                target_type=target_type,
                prompt_type=prompt_type,
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
            logger.error(f"[PromptRegenerator] 执行失败: {e}")
            import traceback
            logger.error(f"[PromptRegenerator] 异常栈: {traceback.format_exc()}")
            return {
                "response_text": f"提示词重新生成过程中出现错误：{str(e)}",
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
                    has_start = "有" if s.get("image_prompt") else "无"
                    has_end = "有" if s.get("end_frame_prompt") else "无"
                    has_video = "有" if s.get("video_prompt") else "无"
                    resources_desc.append(f"  - 分镜{s.get('shot_number')}: {s.get('title', '无标题')} (首帧:{has_start} 尾帧:{has_end} 视频:{has_video})")

        elif target_type == "character":
            chars_result = await query_characters.ainvoke({
                "creation_uuid": creation_uuid,
                "include_images": False,
            })
            if chars_result.get("characters"):
                characters = chars_result["characters"]
                resources_desc.append(f"角色: {len(characters)} 个")
                for c in characters[:5]:
                    has_prompt = "有" if c.get("image_prompt") else "无"
                    resources_desc.append(f"  - {c.get('name', '未命名')} (提示词:{has_prompt})")

        elif target_type == "scene":
            scenes_result = await query_scenes.ainvoke({"creation_uuid": creation_uuid})
            if scenes_result.get("scenes"):
                scenes = scenes_result["scenes"]
                resources_desc.append(f"场景: {len(scenes)} 个")
                for s in scenes[:5]:
                    has_prompt = "有" if s.get("image_prompt") else "无"
                    resources_desc.append(f"  - {s.get('title', '未命名')} (提示词:{has_prompt})")

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

            if "```" in content:
                match = re.search(r'```(?:json)?\s*([\s\S]*?)\s*```', content)
                if match:
                    content = match.group(1)

            analysis = json.loads(content)
            return analysis

        except Exception as e:
            logger.error(f"[PromptRegenerator] 分析请求失败: {e}")
            return self._fallback_analysis(target_type, user_message)

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

    def _fallback_analysis(self, target_type: str, user_message: str) -> Dict[str, Any]:
        """兜底分析：从用户消息中直接提取信息"""
        import re

        msg_lower = user_message.lower()

        scope = "specific"
        if "全部" in user_message or "所有" in user_message:
            scope = "all"
        elif "失败" in user_message or "重试" in user_message:
            scope = "failed"

        # 判断操作类型：重新生成 vs 修改
        operation_type = "modify"  # 默认是修改
        if "重新生成" in user_message and ("提示词" in user_message or "prompt" in user_message.lower()):
            operation_type = "regenerate"
        elif "再来一次" in user_message or "重新来" in user_message:
            operation_type = "regenerate"

        # 判断修改类型
        modification_type = "custom"
        if "简化" in user_message or "啰嗦" in user_message or "简短" in user_message:
            modification_type = "simplify"
        elif "细节" in user_message or "丰富" in user_message or "详细" in user_message:
            modification_type = "detail"
        elif "错" in user_message or "不对" in user_message or "修正" in user_message:
            modification_type = "fix"
        elif "风格" in user_message:
            modification_type = "style"

        targets = []

        if target_type == "shot":
            prompt_type = "video" if "视频" in user_message else "image"

            pattern = r'分镜\s*(\d+)[^。]*?(首帧|尾帧|开始帧|结束帧)?'
            matches = re.findall(pattern, user_message, re.IGNORECASE)

            for match in matches:
                number = int(match[0])
                frame_type_keyword = match[1]

                params = {
                    "operation_type": operation_type,
                    "modification_type": modification_type,
                    "feedback": user_message
                }
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
                numbers = re.findall(r'分镜\s*(\d+)', user_message)
                for n in numbers:
                    targets.append({
                        "type": "number",
                        "value": int(n),
                        "params": {
                            "operation_type": operation_type,
                            "modification_type": modification_type,
                            "feedback": user_message
                        }
                    })

            return {
                "target_type": "shot",
                "prompt_type": prompt_type,
                "scope": scope,
                "targets": targets,
                "reason": "兜底分析",
            }

        elif target_type == "character":
            names = re.findall(r'角色["\']?(\w+)["\']?', user_message)
            for name in names:
                targets.append({
                    "type": "name",
                    "value": name,
                    "params": {
                        "operation_type": operation_type,
                        "modification_type": modification_type,
                        "feedback": user_message
                    }
                })

            return {
                "target_type": "character",
                "prompt_type": "image",
                "scope": scope,
                "targets": targets,
                "reason": "兜底分析",
            }

        else:  # scene
            return {
                "target_type": "scene",
                "prompt_type": "image",
                "scope": scope,
                "targets": targets,
                "reason": "兜底分析",
            }

    async def _get_failed_prompt_resources(
        self,
        creation_uuid: str,
        target_type: str,
        prompt_type: str,
    ) -> List[Dict[str, Any]]:
        """获取提示词缺失的资源"""
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
                extra_data = shot.get("extra_data") or {}

                if prompt_type == "video":
                    if not extra_data.get("video_prompt"):
                        is_failed = True
                else:  # image
                    if not shot.get("image_prompt") and not extra_data.get("end_frame_prompt"):
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
                if not char.get("image_prompt"):
                    resources.append(char)

        elif target_type == "scene":
            result = await query_scenes.ainvoke({"creation_uuid": creation_uuid})
            scenes = result.get("scenes", [])

            for scene in scenes:
                extra_data = scene.get("extra_data") or {}
                if not extra_data.get("image_prompt"):
                    resources.append(scene)

        logger.info(f"[PromptRegenerator] 找到 {len(resources)} 个缺失提示词的{target_type}资源")
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
            for target in targets:
                target_value = target.get("value")
                if not target_value:
                    continue

                if target_type == "shot":
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
                    for resource in matched:
                        resource["_regenerate_params"] = target.get("params", {})
                    resources.extend(matched)

        return resources

    async def _execute_prompt_regeneration(
        self,
        creation_uuid: str,
        resources: List[Dict[str, Any]],
        target_type: str,
        prompt_type: str,
        targets: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        """执行提示词重新生成"""
        from app.agent.tools.async_db import get_async_session
        from app.models.shot import Shot
        from app.models.character import Character
        from app.models.scene import Scene
        from sqlalchemy import select

        results = []

        target_params = {}
        for target in targets:
            if target.get("type") == "number":
                target_params[target["value"]] = target.get("params", {})
            elif target.get("type") == "name":
                target_params[target["value"]] = target.get("params", {})

        # 第一步：收集所有需要的数据（在数据库会话中）
        resources_data = []
        async with get_async_session() as db:
            for resource in resources:
                try:
                    resource_params = resource.get("_regenerate_params", {})

                    if not resource_params:
                        if target_type == "shot":
                            key = resource.get("shot_number")
                        elif target_type == "character":
                            key = resource.get("name")
                        else:
                            key = resource.get("title")
                        resource_params = target_params.get(key, {})

                    operation_type = resource_params.get("operation_type", "modify")
                    modification_type = resource_params.get("modification_type", "custom")
                    feedback = resource_params.get("feedback", "")
                    frame_type = resource_params.get("frame_type", "both")

                    if target_type == "shot":
                        shot_id = resource.get("shot_id")
                        # 使用 joinedload 预先加载 scene 关系，避免懒加载
                        from sqlalchemy.orm import joinedload
                        stmt = select(Shot).where(Shot.shot_id == shot_id).options(joinedload(Shot.scene))
                        result = await db.execute(stmt)
                        shot = result.scalar_one_or_none()

                        if not shot:
                            results.append({"id": shot_id, "success": False, "error": "分镜不存在"})
                            continue

                        # 提取需要的数据，而不是传递 ORM 对象
                        if prompt_type == "video":
                            old_prompt = (shot.extra_data or {}).get("video_prompt", "")
                            prompt_field = "video_prompt"
                        else:  # image
                            if frame_type == "end":
                                old_prompt = (shot.extra_data or {}).get("end_frame_prompt", "")
                                prompt_field = "end_frame_prompt"
                            else:  # start or both
                                old_prompt = shot.image_prompt or ""
                                prompt_field = "image_prompt"

                        # 构建资源数据字典（在会话内部访问所有关系属性）
                        scene_title = None
                        if shot.scene:
                            scene_title = shot.scene.title

                        resource_data_dict = {
                            "shot_id": shot.shot_id,
                            "shot_number": shot.shot_number,
                            "title": shot.title,
                            "description": shot.description,
                            "narration": shot.narration,
                            "scene_title": scene_title,
                        }

                        resources_data.append({
                            "target_type": "shot",
                            "resource_id": shot_id,
                            "name": f"分镜{shot.shot_number}",
                            "operation_type": operation_type,
                            "modification_type": modification_type,
                            "feedback": feedback,
                            "frame_type": frame_type,
                            "prompt_type": prompt_type,
                            "prompt_field": prompt_field,
                            "old_prompt": old_prompt,
                            "resource_data": resource_data_dict,
                        })

                    elif target_type == "character":
                        character_id = resource.get("character_id")
                        stmt = select(Character).where(Character.character_id == character_id)
                        result = await db.execute(stmt)
                        character = result.scalar_one_or_none()

                        if not character:
                            results.append({"id": character_id, "success": False, "error": "角色不存在"})
                            continue

                        old_prompt = character.image_prompt or ""

                        resource_data_dict = {
                            "character_id": character.character_id,
                            "name": character.name,
                            "role_type": character.role_type,
                            "appearance_desc": character.appearance_desc,
                            "personality": character.personality,
                            "costume_desc": character.costume_desc,
                        }

                        resources_data.append({
                            "target_type": "character",
                            "resource_id": character_id,
                            "name": character.name,
                            "operation_type": operation_type,
                            "modification_type": modification_type,
                            "feedback": feedback,
                            "prompt_field": "image_prompt",
                            "old_prompt": old_prompt,
                            "resource_data": resource_data_dict,
                        })

                    elif target_type == "scene":
                        scene_id = resource.get("scene_id")
                        stmt = select(Scene).where(Scene.scene_id == scene_id)
                        result = await db.execute(stmt)
                        scene = result.scalar_one_or_none()

                        if not scene:
                            results.append({"id": scene_id, "success": False, "error": "场景不存在"})
                            continue

                        old_prompt = (scene.extra_data or {}).get("image_prompt", "")

                        resource_data_dict = {
                            "scene_id": scene.scene_id,
                            "title": scene.title,
                            "location": scene.location,
                            "time_setting": scene.time_setting,
                            "atmosphere": scene.atmosphere,
                        }

                        resources_data.append({
                            "target_type": "scene",
                            "resource_id": scene_id,
                            "name": scene.title,
                            "operation_type": operation_type,
                            "modification_type": modification_type,
                            "feedback": feedback,
                            "prompt_field": "image_prompt",
                            "old_prompt": old_prompt,
                            "resource_data": resource_data_dict,
                        })

                except Exception as e:
                    logger.error(f"[PromptRegenerator] 收集资源数据失败: {e}")
                    results.append({
                        "id": resource.get("shot_id") or resource.get("character_id") or resource.get("scene_id"),
                        "name": resource.get("name") or resource.get("shot_number") or resource.get("title"),
                        "success": False,
                        "error": str(e),
                    })

        # 第二步：在数据库会话外部调用 LLM 生成提示词
        generated_prompts = []
        for data in resources_data:
            try:
                resource_type_map = {
                    ("shot", "video"): "video",
                    ("shot", "image"): "shot_end" if data.get("frame_type") == "end" else "shot_start",
                    ("character", None): "character",
                    ("scene", None): "scene",
                }

                target_type_key = data["target_type"]
                prompt_type_key = data.get("prompt_type")
                resource_type = resource_type_map.get((target_type_key, prompt_type_key), "shot_start")

                if data["operation_type"] == "regenerate":
                    new_prompt = await self._generate_prompt_from_template(
                        resource_type=resource_type,
                        resource_data=data["resource_data"],
                    )
                else:  # modify
                    new_prompt = await self._modify_prompt_with_llm(
                        old_prompt=data["old_prompt"],
                        resource_type=resource_type,
                        resource_data=data["resource_data"],
                        modification_type=data["modification_type"],
                        feedback=data["feedback"],
                    )

                generated_prompts.append({
                    "target_type": data["target_type"],
                    "resource_id": data["resource_id"],
                    "name": data["name"],
                    "operation_type": data["operation_type"],
                    "prompt_field": data["prompt_field"],
                    "new_prompt": new_prompt,
                })

            except Exception as e:
                logger.error(f"[PromptRegenerator] 生成提示词失败: {e}")
                results.append({
                    "id": data["resource_id"],
                    "name": data["name"],
                    "success": False,
                    "error": str(e),
                })

        # 第三步：保存生成的提示词到数据库（在数据库会话中）
        async with get_async_session() as db:
            for data in generated_prompts:
                try:
                    if data["target_type"] == "shot":
                        stmt = select(Shot).where(Shot.shot_id == data["resource_id"])
                        result = await db.execute(stmt)
                        shot = result.scalar_one_or_none()

                        if shot:
                            if data["prompt_field"] == "video_prompt":
                                if shot.extra_data is None:
                                    shot.extra_data = {}
                                shot.extra_data["video_prompt"] = data["new_prompt"]
                                flag_modified(shot, "extra_data")
                            elif data["prompt_field"] == "end_frame_prompt":
                                if shot.extra_data is None:
                                    shot.extra_data = {}
                                shot.extra_data["end_frame_prompt"] = data["new_prompt"]
                                flag_modified(shot, "extra_data")
                            else:  # image_prompt
                                shot.image_prompt = data["new_prompt"]

                    elif data["target_type"] == "character":
                        stmt = select(Character).where(Character.character_id == data["resource_id"])
                        result = await db.execute(stmt)
                        character = result.scalar_one_or_none()

                        if character:
                            character.image_prompt = data["new_prompt"]

                    elif data["target_type"] == "scene":
                        stmt = select(Scene).where(Scene.scene_id == data["resource_id"])
                        result = await db.execute(stmt)
                        scene = result.scalar_one_or_none()

                        if scene:
                            if scene.extra_data is None:
                                scene.extra_data = {}
                            scene.extra_data["image_prompt"] = data["new_prompt"]
                            flag_modified(scene, "extra_data")

                    await db.commit()

                    results.append({
                        "id": data["resource_id"],
                        "name": data["name"],
                        "success": True,
                        "operation_type": data["operation_type"],
                        "prompt_field": data["prompt_field"],
                        "new_prompt": data["new_prompt"][:100] + "..." if len(data["new_prompt"]) > 100 else data["new_prompt"],
                    })

                except Exception as e:
                    logger.error(f"[PromptRegenerator] 保存提示词失败: {e}")
                    results.append({
                        "id": data["resource_id"],
                        "name": data["name"],
                        "success": False,
                        "error": str(e),
                    })

        return results

    async def _generate_prompt_from_template(
        self,
        resource_type: str,
        resource_data: Dict[str, Any],
    ) -> str:
        """
        重新生成 - 使用模板直接生成新提示词，忽略旧提示词

        根据资源类型读取对应的提示词模板，结合资源信息生成全新的提示词
        """
        from app.utils.file_utils import read_prompt_file

        template_map = {
            "character": "character.md",
            "scene": "scene_image.md",
            "shot_start": "shot_image_v4.md",
            "shot_end": "shot_image_v4.md",
            "video": "video_generation_v6.md",
        }

        template_file = template_map.get(resource_type, "shot_image_v4.md")
        template_content = read_prompt_file(template_file) if template_file else ""

        resource_context = self._build_resource_context(resource_type, resource_data)

        prompt = f"""你是一个专业的AI提示词工程师。请根据以下资源信息和模板，生成一个全新的提示词。

## 资源信息
{resource_context}

## 提示词模板
{template_content[:1500] if template_content else ""}

## 要求
1. 使用中文输出提示词
2. 根据资源信息生成完整、详细的提示词
3. 遵循模板中的格式和要求
4. 提示词长度适中（100-200字）
5. 只输出提示词，不要其他内容

请生成新的提示词："""

        response = await self.llm.ainvoke([HumanMessage(content=prompt)])
        new_prompt = response.content.strip()

        if new_prompt.startswith("```") and new_prompt.endswith("```"):
            new_prompt = new_prompt[3:-3].strip()

        return new_prompt

    async def _modify_prompt_with_llm(
        self,
        old_prompt: str,
        resource_type: str,
        resource_data: Dict[str, Any],
        modification_type: str,
        feedback: str,
    ) -> str:
        """
        修改 - 基于旧提示词，根据用户反馈进行修改优化

        保留原提示词的核心要素和约束，根据修改类型和反馈进行调整
        """
        from app.utils.file_utils import read_prompt_file

        modification_desc = self.MODIFICATION_TYPES.get(modification_type, "根据用户意见修改")

        template_map = {
            "character": "character.md",
            "scene": "scene_image.md",
            "shot_start": "shot_image_v4.md",
            "shot_end": "shot_image_v4.md",
            "video": "video_generation_v6.md",
        }

        template_file = template_map.get(resource_type, "shot_image_v4.md")
        template_content = read_prompt_file(template_file) if template_file else ""

        resource_context = self._build_resource_context(resource_type, resource_data)

        prompt = f"""你是一个专业的AI提示词工程师。请基于原提示词，根据用户反馈进行修改优化。

## 原提示词（需要在此基础上修改）
{old_prompt if old_prompt else "（无原提示词，请根据资源信息生成）"}

## 资源信息
{resource_context}

## 修改要求
修改类型: {modification_type} ({modification_desc})
用户反馈: {feedback if feedback else "无具体反馈"}

## 提示词模板参考（了解约束和规范）
{template_content[:800] if template_content else ""}

## 修改规则（重要）

1. **simplify (简化)**: 
   - 保留原提示词的核心要素和关键约束
   - 去除冗余、重复的描述
   - 使提示词更简洁明了，但不丢失重要信息

2. **detail (加细节)**: 
   - 在保留原提示词的基础上
   - 添加更多细节描述，丰富画面内容
   - 增强视觉表现力和层次感

3. **fix (修正)**: 
   - 识别并修正原提示词中的错误或不准确之处
   - 保持其他正确内容不变
   - 确保描述准确、符合资源信息

4. **style (改风格)**: 
   - 调整风格描述，改变视觉调性
   - 保留主体内容，改变表现方式

5. **custom (自定义)**: 
   - 根据用户具体反馈进行修改
   - 保留原提示词中不需要修改的部分

## 要求
1. 使用中文输出提示词
2. **必须基于原提示词进行修改**，不要完全重写
3. 保留原提示词中的核心约束和关键要素
4. 根据修改类型有针对性地调整
5. 提示词长度适中（100-200字）
6. 只输出提示词，不要其他内容

请基于原提示词生成修改后的提示词："""

        response = await self.llm.ainvoke([HumanMessage(content=prompt)])
        new_prompt = response.content.strip()

        if new_prompt.startswith("```") and new_prompt.endswith("```"):
            new_prompt = new_prompt[3:-3].strip()

        return new_prompt

    def _build_resource_context(self, resource_type: str, resource_data: Dict[str, Any]) -> str:
        """构建资源上下文信息（现在接收字典而不是 ORM 对象）"""
        context_parts = []

        if resource_type == "character":
            context_parts.append(f"角色名称: {resource_data.get('name', '未命名')}")
            context_parts.append(f"角色类型: {resource_data.get('role_type') or '未指定'}")
            context_parts.append(f"外貌描述: {resource_data.get('appearance_desc') or '无'}")
            context_parts.append(f"性格特点: {resource_data.get('personality') or '无'}")
            context_parts.append(f"服装描述: {resource_data.get('costume_desc') or '无'}")

        elif resource_type == "scene":
            context_parts.append(f"场景标题: {resource_data.get('title', '未命名')}")
            context_parts.append(f"地点: {resource_data.get('location') or '未指定'}")
            context_parts.append(f"时间: {resource_data.get('time_setting') or '未指定'}")
            context_parts.append(f"氛围: {resource_data.get('atmosphere') or '未指定'}")

        elif resource_type in ["shot_start", "shot_end", "video"]:
            context_parts.append(f"分镜编号: {resource_data.get('shot_number', '未知')}")
            context_parts.append(f"分镜标题: {resource_data.get('title') or '无标题'}")
            context_parts.append(f"分镜描述: {resource_data.get('description') or '无'}")
            context_parts.append(f"旁白: {resource_data.get('narration') or '无'}")
            if resource_data.get('scene_title'):
                context_parts.append(f"场景: {resource_data['scene_title']}")

        return "\n".join(context_parts)

    def _build_response_message(
        self,
        target_type: str,
        prompt_type: str,
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

        prompt_names = {
            "image": "图片",
            "video": "视频",
        }

        target_name = type_names.get(target_type, target_type)
        prompt_name = prompt_names.get(prompt_type, "")

        if success_count == 1:
            resource = resources[0]
            name = resource.get("name") or resource.get("shot_number") or resource.get("title", "")
            message = f"✅ 已为{target_name}「{name}」重新生成{prompt_name}提示词"
        else:
            message = f"✅ 已为 {success_count} 个{target_name}重新生成{prompt_name}提示词"

        if failed_count > 0:
            message += f"\n（{failed_count} 个失败）"

        return message


async def regenerate_prompts(state: ComicDramaState) -> Dict[str, Any]:
    """LangGraph node 函数"""
    node = PromptRegenerator()
    return await node.run(state)
