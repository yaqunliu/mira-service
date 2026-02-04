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

判断规则（重要！必须严格遵守）：

**操作类型判断（关键！这是最重要的判断）：**

**必须严格遵守以下规则**：
- 如果用户消息**只包含**"重新生成提示词"的请求，**没有任何**具体的修改要求 → operation_type="regenerate"
- 如果用户消息**除了**"重新生成提示词"之外，**还包含**任何具体的修改要求（如：更可爱、改变某个元素、添加细节等） → operation_type="modify"

**具体示例**：
- "重新生成阿九的提示词" → **只有请求，无修改意见** → operation_type="regenerate"
- "重新生成阿九的提示词，让他更可爱一点" → **有请求，也有修改意见** → operation_type="modify"
- "重新生成阿九的提示词，胸口的玉改成铃铛" → **有请求，也有修改意见** → operation_type="modify"
- "修改阿九的提示词，把胸口的玉改成铃铛" → **明确修改** → operation_type="modify"

**判断技巧**：看用户是否说了"要..."、"希望..."、"改成..."、"变成..."、"更..."等表达修改意愿的词。如果有，就是 modify；如果没有，就是 regenerate。

**修改类型判断**（仅当 operation_type="modify" 时）：
1. 用户提到"太啰嗦"、"简化"、"简短" -> modification_type="simplify"
2. 用户提到"加细节"、"更丰富"、"详细" -> modification_type="detail"
3. 用户提到"有错"、"不对"、"修正"、"改成" -> modification_type="fix"
4. 用户提到"风格"、"调性" -> modification_type="style"
5. 其他具体修改意见（如"让他更可爱"） -> modification_type="custom"

**示例**：

**重新生成示例（无修改意见）**：
- 输入："重新生成主角的提示词"
- 输出：{{"scope": "specific", "targets": [{{"type": "name", "value": "主角", "params": {{"operation_type": "regenerate", "modification_type": null, "feedback": null}}}}]}}
- 原因：用户只说了"重新生成"，没有说"要改成什么样"

**修改示例（有修改意见）**：
- 输入："重新生成主角的提示词，太啰嗦了"
- 输出：{{"scope": "specific", "targets": [{{"type": "name", "value": "主角", "params": {{"operation_type": "modify", "modification_type": "simplify", "feedback": "太啰嗦了"}}}}]}}
- 原因：用户说了"太啰嗦了"，这是修改意见

- 输入："重新生成阿九的提示词，让他更可爱萌一点，胸口挂着铃铛"
- 输出：{{"scope": "specific", "targets": [{{"type": "name", "value": "阿九", "params": {{"operation_type": "modify", "modification_type": "custom", "feedback": "让他更可爱萌一点，胸口挂着铃铛"}}}}]}}
- 原因：用户说了"让他更可爱萌一点"和"胸口挂着铃铛"，这些都是修改意见

**特别注意**：
- 只要用户说了"要..."、"希望..."、"改成..."、"变成..."、"更..."等词，就是 modify
- 如果用户只说了"重新生成"，没有说任何修改要求，就是 regenerate
- modification_type 和 feedback 在 regenerate 时必须为 null

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

判断规则（重要！必须严格遵守）：

**操作类型判断（关键！这是最重要的判断）：**

**必须严格遵守以下规则**：
- 如果用户消息**只包含**"重新生成提示词"的请求，**没有任何**具体的修改要求 → operation_type="regenerate"
- 如果用户消息**除了**"重新生成提示词"之外，**还包含**任何具体的修改要求（如：改变风格、添加细节、修改某个元素等） → operation_type="modify"

**具体示例**：
- "重新生成客厅的提示词" → **只有请求，无修改意见** → operation_type="regenerate"
- "重新生成客厅的提示词，设置成赛璐璐风格" → **有请求，也有修改意见** → operation_type="modify"
- "重新生成客厅的提示词，增加阳光" → **有请求，也有修改意见** → operation_type="modify"
- "修改客厅的提示词，让氛围更暗" → **明确修改** → operation_type="modify"

**判断技巧**：看用户是否说了"要..."、"希望..."、"改成..."、"变成..."、"更..."、"设置成..."等表达修改意愿的词。如果有，就是 modify；如果没有，就是 regenerate。

**修改类型判断**（仅当 operation_type="modify" 时）：
1. 用户提到"太啰嗦"、"简化" -> modification_type="simplify"
2. 用户提到"加细节"、"更丰富" -> modification_type="detail"
3. 用户提到"有错"、"不对" -> modification_type="fix"
4. 用户提到"风格" -> modification_type="style"
5. 其他具体修改意见 -> modification_type="custom"

**特别注意**：
- 只要用户说了"要..."、"希望..."、"改成..."、"变成..."、"更..."、"设置成..."等词，就是 modify
- 如果用户只说了"重新生成"，没有说任何修改要求，就是 regenerate

示例：
- "重新生成客厅的提示词" -> {{"scope": "specific", "targets": [{{"type": "name", "value": "客厅", "params": {{"operation_type": "regenerate"}}}}]}}
- "重新生成客厅的提示词，设置成赛璐璐风格" -> {{"scope": "specific", "targets": [{{"type": "name", "value": "客厅", "params": {{"operation_type": "modify", "modification_type": "style", "feedback": "设置成赛璐璐风格"}}}}]}}
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

        logger.info(f"[_execute_prompt_regeneration] 开始执行，target_type={target_type}, prompt_type={prompt_type}, resources数量={len(resources)}")

        target_params = {}
        for target in targets:
            if target.get("type") == "number":
                target_params[target["value"]] = target.get("params", {})
            elif target.get("type") == "name":
                target_params[target["value"]] = target.get("params", {})

        logger.info(f"[_execute_prompt_regeneration] target_params={target_params}")

        # 第一步：收集所有需要的数据（在数据库会话中）
        resources_data = []
        logger.info(f"[_execute_prompt_regeneration] 开始收集资源数据，resources数量={len(resources)}")
        async with get_async_session() as db:
            for idx, resource in enumerate(resources):
                try:
                    logger.info(f"[_execute_prompt_regeneration] 处理第{idx+1}个资源: {resource.get('name') or resource.get('character_id') or resource.get('shot_id')}")
                    resource_params = resource.get("_regenerate_params", {})

                    if not resource_params:
                        if target_type == "shot":
                            key = resource.get("shot_number")
                        elif target_type == "character":
                            key = resource.get("name")
                        else:
                            key = resource.get("title")
                        resource_params = target_params.get(key, {})
                        logger.info(f"[_execute_prompt_regeneration] 从target_params获取参数: key={key}, params={resource_params}")

                    operation_type = resource_params.get("operation_type", "modify")
                    modification_type = resource_params.get("modification_type", "custom")
                    feedback = resource_params.get("feedback", "")
                    frame_type = resource_params.get("frame_type", "both")

                    logger.info(f"[_execute_prompt_regeneration] 最终参数: operation_type={operation_type}, modification_type={modification_type}, feedback={feedback[:50] if feedback else 'None'}...")
                    logger.info(f"[_execute_prompt_regeneration] 判断条件: target_type={target_type}, resource.keys()={list(resource.keys())}")

                    if target_type == "shot":
                        # resource 中的 id 字段可能是 'id' 或 'shot_id'
                        shot_id = resource.get("shot_id") or resource.get("id")
                        # 使用 joinedload 预先加载 scene 关系，避免懒加载
                        from sqlalchemy.orm import joinedload
                        stmt = select(Shot).where(Shot.shot_id == shot_id).options(joinedload(Shot.scene))
                        result = await db.execute(stmt)
                        shot = result.scalar_one_or_none()

                        if not shot:
                            results.append({"id": shot_id, "success": False, "error": "分镜不存在"})
                            continue

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

                        # 根据 frame_type 确定需要生成的提示词
                        frames_to_generate = []
                        if prompt_type == "video":
                            old_prompt = (shot.extra_data or {}).get("video_prompt", "")
                            frames_to_generate.append({
                                "frame_type": "video",
                                "prompt_field": "video_prompt",
                                "old_prompt": old_prompt,
                            })
                        else:  # image
                            if frame_type == "both":
                                # 同时生成首帧和尾帧
                                frames_to_generate.append({
                                    "frame_type": "start",
                                    "prompt_field": "image_prompt",
                                    "old_prompt": shot.image_prompt or "",
                                })
                                frames_to_generate.append({
                                    "frame_type": "end",
                                    "prompt_field": "end_frame_prompt",
                                    "old_prompt": (shot.extra_data or {}).get("end_frame_prompt", ""),
                                })
                            elif frame_type == "end":
                                frames_to_generate.append({
                                    "frame_type": "end",
                                    "prompt_field": "end_frame_prompt",
                                    "old_prompt": (shot.extra_data or {}).get("end_frame_prompt", ""),
                                })
                            else:  # start
                                frames_to_generate.append({
                                    "frame_type": "start",
                                    "prompt_field": "image_prompt",
                                    "old_prompt": shot.image_prompt or "",
                                })

                        # 为每个帧类型添加资源数据
                        for frame_info in frames_to_generate:
                            resources_data.append({
                                "target_type": "shot",
                                "resource_id": shot_id,
                                "name": f"分镜{shot.shot_number}",
                                "operation_type": operation_type,
                                "modification_type": modification_type,
                                "feedback": feedback,
                                "frame_type": frame_info["frame_type"],
                                "prompt_type": prompt_type,
                                "prompt_field": frame_info["prompt_field"],
                                "old_prompt": frame_info["old_prompt"],
                                "resource_data": resource_data_dict,
                            })

                    elif target_type == "character":
                        # resource 中的 id 字段可能是 'id' 或 'character_id'
                        character_id = resource.get("character_id") or resource.get("id")
                        logger.info(f"[_execute_prompt_regeneration] 查询角色: character_id={character_id}, resource_id={resource.get('id')}, resource_character_id={resource.get('character_id')}")
                        stmt = select(Character).where(Character.character_id == character_id)
                        result = await db.execute(stmt)
                        character = result.scalar_one_or_none()

                        if not character:
                            logger.error(f"[_execute_prompt_regeneration] 角色不存在: character_id={character_id}")
                            results.append({"id": character_id, "success": False, "error": "角色不存在"})
                            continue

                        logger.info(f"[_execute_prompt_regeneration] 找到角色: {character.name}, image_prompt={'有' if character.image_prompt else '无'}")
                        old_prompt = character.image_prompt or ""

                        resource_data_dict = {
                            "character_id": character.character_id,
                            "name": character.name,
                            "basic_info": character.basic_info,
                            "appearance": character.appearance,
                            "body": character.body,
                            "hair": character.hair,
                            "clothing": character.clothing,
                            "tags": character.tags,
                            "visual_style": character.visual_style,
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
                        logger.info(f"[_execute_prompt_regeneration] 角色数据已添加到resources_data")

                    elif target_type == "scene":
                        # resource 中的 id 字段可能是 'id' 或 'scene_id'
                        scene_id = resource.get("scene_id") or resource.get("id")
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
        logger.info(f"[_execute_prompt_regeneration] 开始生成提示词，resources_data数量={len(resources_data)}")

        for idx, data in enumerate(resources_data):
            try:
                logger.info(f"[_execute_prompt_regeneration] 处理第{idx+1}个资源的提示词生成: {data['name']}, operation_type={data['operation_type']}")

                # 根据 target_type 和 prompt_type 确定 resource_type
                target_type_key = data["target_type"]
                prompt_type_key = data.get("prompt_type", "image")  # 默认为 image
                frame_type = data.get("frame_type", "start")

                # 确定需要生成的资源类型列表
                resource_types_to_generate = []
                if target_type_key == "shot":
                    if prompt_type_key == "video":
                        resource_types_to_generate = [("video", data["prompt_field"])]
                    else:  # image
                        if frame_type == "both":
                            resource_types_to_generate = [
                                ("shot_start", "image_prompt"),
                                ("shot_end", "end_frame_prompt")
                            ]
                        elif frame_type == "end":
                            resource_types_to_generate = [("shot_end", "end_frame_prompt")]
                        else:  # start
                            resource_types_to_generate = [("shot_start", "image_prompt")]
                elif target_type_key == "character":
                    resource_types_to_generate = [("character", data["prompt_field"])]
                elif target_type_key == "scene":
                    resource_types_to_generate = [("scene", data["prompt_field"])]
                else:
                    resource_types_to_generate = [("shot_start", "image_prompt")]

                # 为每个资源类型生成提示词
                for resource_type, prompt_field in resource_types_to_generate:
                    logger.info(f"[_execute_prompt_regeneration] 生成 {resource_type} 提示词, prompt_field={prompt_field}")

                    if data["operation_type"] == "regenerate":
                        logger.info(f"[_execute_prompt_regeneration] 调用 _generate_prompt_from_template")
                        new_prompt = await self._generate_prompt_from_template(
                            resource_type=resource_type,
                            resource_data=data["resource_data"],
                        )
                    else:  # modify
                        logger.info(f"[_execute_prompt_regeneration] 调用 _modify_prompt_with_llm, modification_type={data['modification_type']}")
                        new_prompt = await self._modify_prompt_with_llm(
                            old_prompt=data["old_prompt"],
                            resource_type=resource_type,
                            resource_data=data["resource_data"],
                            modification_type=data["modification_type"],
                            feedback=data["feedback"],
                        )

                    logger.info(f"[_execute_prompt_regeneration] 生成提示词成功，新提示词长度={len(new_prompt)}")

                    generated_prompts.append({
                        "target_type": data["target_type"],
                        "resource_id": data["resource_id"],
                        "name": data["name"],
                        "operation_type": data["operation_type"],
                        "prompt_field": prompt_field,
                        "new_prompt": new_prompt,
                    })

            except Exception as e:
                logger.error(f"[PromptRegenerator] 生成提示词失败: {e}")
                import traceback
                logger.error(f"[PromptRegenerator] 异常栈: {traceback.format_exc()}")
                results.append({
                    "id": data["resource_id"],
                    "name": data["name"],
                    "success": False,
                    "error": str(e),
                })

        # 第三步：保存生成的提示词到数据库（在数据库会话中）
        logger.info(f"[_execute_prompt_regeneration] 开始保存提示词到数据库，generated_prompts数量={len(generated_prompts)}")
        async with get_async_session() as db:
            for idx, data in enumerate(generated_prompts):
                try:
                    logger.info(f"[_execute_prompt_regeneration] 保存第{idx+1}个提示词: {data['name']}, target_type={data['target_type']}, prompt_field={data['prompt_field']}")
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

                    logger.info(f"[_execute_prompt_regeneration] 保存成功: {data['name']}")
                    results.append({
                        "id": data["resource_id"],
                        "name": data["name"],
                        "success": True,
                        "operation_type": data["operation_type"],
                        "prompt_field": data["prompt_field"],
                        "new_prompt": data["new_prompt"][:100] + "..." if len(data["new_prompt"]) > 100 else data["new_prompt"],
                    })

                except Exception as e:
                    logger.error(f"[_execute_prompt_regeneration] 保存提示词失败: {e}")
                    import traceback
                    logger.error(f"[_execute_prompt_regeneration] 异常栈: {traceback.format_exc()}")
                    results.append({
                        "id": data["resource_id"],
                        "name": data["name"],
                        "success": False,
                        "error": str(e),
                    })

        logger.info(f"[_execute_prompt_regeneration] 执行完成，成功={sum(1 for r in results if r.get('success'))}, 失败={sum(1 for r in results if not r.get('success'))}")
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

        try:
            template_map = {
                "character": "regenerate_character.md",  # 使用重新生成专用模板
                "scene": "regenerate_scene.md",  # 使用重新生成专用模板
                "shot_start": "regenerate_shot_start.md",  # 使用重新生成专用模板
                "shot_end": "regenerate_shot_end.md",  # 使用重新生成专用模板
                "video": "regenerate_video.md",  # 使用重新生成专用模板
            }

            template_file = template_map.get(resource_type, "shot_image_v4.md")
            template_content = read_prompt_file(template_file) if template_file else ""

            if not template_content:
                logger.warning(f"[PromptRegenerator] 模板文件为空或不存在: {template_file}")

            resource_context = self._build_resource_context(resource_type, resource_data)

            # 替换模板中的变量
            visual_style = resource_data.get('visual_style') or '日本动漫风格'
            if resource_type == "scene":
                template_content = template_content.replace("{{SCENE_TITLE}}", resource_data.get('title', '') or "未命名") \
                                                   .replace("{{LOCATION}}", resource_data.get('location') or "未指定") \
                                                   .replace("{{TIME_SETTING}}", resource_data.get('time_setting') or "未指定") \
                                                   .replace("{{ATMOSPHERE}}", resource_data.get('atmosphere') or "未指定") \
                                                   .replace("{{SPACE_TYPE}}", resource_data.get('space_type') or "未指定") \
                                                   .replace("{{VISUAL_STYLE}}", visual_style)
            elif resource_type == "character":
                template_content = template_content.replace("{{CHARACTER_NAME}}", resource_data.get('name', '') or "未命名") \
                                                   .replace("{{BASIC_INFO}}", resource_data.get('basic_info') or "无") \
                                                   .replace("{{APPEARANCE}}", resource_data.get('appearance') or "无") \
                                                   .replace("{{VISUAL_STYLE}}", visual_style)
            elif resource_type in ["shot_start", "shot_end"]:
                template_content = template_content.replace("{{SHOT_NUMBER}}", str(resource_data.get('shot_number', ''))) \
                                                   .replace("{{SHOT_TITLE}}", resource_data.get('title') or f"分镜{resource_data.get('shot_number', '')}") \
                                                   .replace("{{SHOT_DESCRIPTION}}", resource_data.get('description') or "无") \
                                                   .replace("{{SHOT_NARRATION}}", resource_data.get('narration') or "无") \
                                                   .replace("{{SCENE_TITLE}}", resource_data.get('scene_title') or "未指定") \
                                                   .replace("{{SCENE_LOCATION}}", resource_data.get('scene_location') or "未指定") \
                                                   .replace("{{SCENE_TIME}}", resource_data.get('scene_time') or "未指定") \
                                                   .replace("{{SCENE_ATMOSPHERE}}", resource_data.get('scene_atmosphere') or "未指定") \
                                                   .replace("{{CHARACTER_PROFILES}}", resource_data.get('character_profiles') or "无角色信息") \
                                                   .replace("{{VISUAL_STYLE}}", visual_style)

            prompt = f"""你是一个专业的AI提示词工程师。请根据以下资源信息和模板，生成一个全新的提示词。

## 资源信息
{resource_context}

## 提示词模板
{template_content[:2000] if template_content else "请根据资源信息生成合适的提示词"}

## 要求
1. 使用中文输出提示词
2. 根据资源信息生成完整、详细的提示词
3. 遵循模板中的格式和要求
4. 提示词长度适中（100-300字）
5. 只输出提示词，不要其他内容

请生成新的提示词："""

            response = await self.llm.ainvoke([HumanMessage(content=prompt)])
            new_prompt = response.content.strip()

            if new_prompt.startswith("```") and new_prompt.endswith("```"):
                new_prompt = new_prompt[3:-3].strip()

            logger.info(f"[PromptRegenerator] 生成新提示词成功，长度: {len(new_prompt)}")
            return new_prompt

        except Exception as e:
            logger.error(f"[PromptRegenerator] 生成提示词失败: {e}")
            import traceback
            logger.error(f"[PromptRegenerator] 异常栈: {traceback.format_exc()}")
            # 返回一个默认提示词，而不是抛出异常
            return f"生成提示词时出错: {str(e)}"

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

        try:
            modification_desc = self.MODIFICATION_TYPES.get(modification_type, "根据用户意见修改")

            # 修改操作使用 modify_prompt.md 模板
            template_content = read_prompt_file("modify_prompt.md")

            resource_context = self._build_resource_context(resource_type, resource_data)

            # 替换模板中的变量
            if template_content:
                template_content = template_content.replace("{{OLD_PROMPT}}", old_prompt if old_prompt else "（无原提示词）") \
                                                   .replace("{{MODIFICATION_TYPE}}", modification_type) \
                                                   .replace("{{FEEDBACK}}", feedback if feedback else "无具体反馈") \
                                                   .replace("{{RESOURCE_CONTEXT}}", resource_context)

            prompt = f"""你是一个专业的AI提示词工程师。请基于原提示词，根据用户反馈进行修改优化。

## 原提示词（需要在此基础上修改）
<old_prompt>
{old_prompt if old_prompt else "（无原提示词，请根据资源信息生成）"}
</old_prompt>

## 资源信息
{resource_context}

## 修改要求
<modification_type>
{modification_type}
</modification_type>

<feedback>
{feedback if feedback else "无具体反馈"}
</feedback>

## 修改规则参考
{template_content[:1500] if template_content else "根据修改类型和用户反馈进行修改"}

## 要求
1. 使用中文输出提示词
2. **必须基于原提示词进行修改**，不要完全重写
3. 保留原提示词中的核心约束和关键要素
4. 根据修改类型有针对性地调整
5. 提示词长度适中（100-300字）
6. 只输出提示词，不要其他内容

请基于原提示词生成修改后的提示词："""

            response = await self.llm.ainvoke([HumanMessage(content=prompt)])
            new_prompt = response.content.strip()

            if new_prompt.startswith("```") and new_prompt.endswith("```"):
                new_prompt = new_prompt[3:-3].strip()

            logger.info(f"[PromptRegenerator] 修改提示词成功，长度: {len(new_prompt)}")
            return new_prompt

        except Exception as e:
            logger.error(f"[PromptRegenerator] 修改提示词失败: {e}")
            import traceback
            logger.error(f"[PromptRegenerator] 异常栈: {traceback.format_exc()}")
            # 返回一个默认提示词，而不是抛出异常
            return f"修改提示词时出错: {str(e)}"

    def _build_resource_context(self, resource_type: str, resource_data: Dict[str, Any]) -> str:
        """构建资源上下文信息（现在接收字典而不是 ORM 对象）"""
        context_parts = []

        if resource_type == "character":
            context_parts.append(f"角色名称: {resource_data.get('name', '未命名')}")
            context_parts.append(f"基本信息: {resource_data.get('basic_info') or '无'}")
            context_parts.append(f"外貌: {resource_data.get('appearance') or '无'}")
            context_parts.append(f"身材: {resource_data.get('body') or '无'}")
            context_parts.append(f"发型: {resource_data.get('hair') or '无'}")
            context_parts.append(f"服装: {resource_data.get('clothing') or '无'}")
            context_parts.append(f"标签: {', '.join(resource_data.get('tags') or [])}")
            context_parts.append(f"视觉风格: {resource_data.get('visual_style') or '未指定'}")

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
