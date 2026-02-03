"""
Regenerate Agent - 专门处理资源重新生成

职责：
1. 分析用户消息，理解要重新生成什么
2. 确定目标资源（角色/场景/分镜）
3. 确定生成参数（首帧/尾帧/视频等）
4. 调用相应的工具执行重新生成

支持：
- 角色图片重新生成
- 场景图片重新生成  
- 分镜首帧/尾帧/视频重新生成
"""

import re
from typing import Dict, Any, List, Optional
from datetime import datetime

from langchain_core.tools import tool
from langchain_openai import ChatOpenAI

from app.core.config import settings
from app.core.logger import logger


# ==================== 类型定义 ====================

class RegenerateRequest:
    """重新生成请求"""
    def __init__(
        self,
        target_type: str,  # "character", "scene", "shot"
        resource_type: str,  # "image", "video"
        frame_type: Optional[str],  # "start", "end", "both" (仅分镜图片)
        target_numbers: List[int],  # 分镜编号
        target_names: List[str],  # 角色/场景名称
        scope: str,  # "specific", "all", "failed"
        user_message: str,
    ):
        self.target_type = target_type
        self.resource_type = resource_type
        self.frame_type = frame_type
        self.target_numbers = target_numbers
        self.target_names = target_names
        self.scope = scope
        self.user_message = user_message


# ==================== 分析 Prompt ====================

REGENERATE_ANALYSIS_PROMPT = """你是一个专门处理资源重新生成的Agent。请分析用户的需求，提取关键信息。

用户消息: {user_message}

请分析并返回JSON格式：
{{
    "target_type": "character" | "scene" | "shot",
    "resource_type": "image" | "video",
    "frame_type": "start" | "end" | "both" | null,
    "target_numbers": [分镜编号列表],
    "target_names": [角色/场景名称列表],
    "scope": "specific" | "all" | "failed",
    "confidence": 0.0-1.0,
    "reasoning": "分析理由"
}}

判断规则：

1. **target_type 判断**：
   - 提到"角色"、"人物" -> "character"
   - 提到"场景"、"背景" -> "scene"
   - 提到"分镜"、"镜头" -> "shot"

2. **resource_type 判断**：
   - 提到"视频" -> "video"
   - 提到"图片"、"图像"、"帧" -> "image"
   - 默认 "image"

3. **frame_type 判断**（仅分镜图片时重要）：
   - 提到"尾帧"、"结束帧"、"最后一帧" -> "end"
   - 提到"首帧"、"开始帧"、"第一帧" -> "start"
   - 提到"图片"但没指定首尾 -> "both"
   - 视频生成时 -> null

4. **target_numbers 提取**：
   - "分镜5" -> [5]
   - "分镜1和3" -> [1, 3]
   - "第2个分镜" -> [2]

5. **scope 判断**：
   - "全部"、"所有" -> "all"
   - "失败的"、"重试" -> "failed"
   - 指定编号 -> "specific"

示例：
- "给我的分镜1和3重新生成尾帧" -> {{"target_type": "shot", "resource_type": "image", "frame_type": "end", "target_numbers": [1, 3], "target_names": [], "scope": "specific"}}
- "重新生成所有角色图片" -> {{"target_type": "character", "resource_type": "image", "frame_type": null, "target_numbers": [], "target_names": [], "scope": "all"}}
- "用首帧生成分镜5的视频" -> {{"target_type": "shot", "resource_type": "video", "frame_type": "start", "target_numbers": [5], "target_names": [], "scope": "specific"}}

只返回JSON，不要其他内容。"""


# ==================== Regenerate Agent ====================

class RegenerateAgent:
    """重新生成专用 Agent"""

    def __init__(self):
        self.llm = ChatOpenAI(
            model=settings.LLM_MODEL_NAME or "gpt-4",
            api_key=settings.OPENAI_API_KEY,
            base_url=str(settings.OPENAI_BASE_URL) if settings.OPENAI_BASE_URL else None,
            temperature=0.1,
        )

    async def analyze_request(self, user_message: str) -> RegenerateRequest:
        """分析用户请求"""
        prompt = REGENERATE_ANALYSIS_PROMPT.format(user_message=user_message)

        response = await self.llm.ainvoke([{"role": "user", "content": prompt}])
        content = response.content.strip()

        # 解析 JSON
        import json
        if content.startswith("```json"):
            content = content[7:]
        if content.startswith("```"):
            content = content[3:]
        if content.endswith("```"):
            content = content[:-3]
        content = content.strip()

        result = json.loads(content)

        logger.info(f"[RegenerateAgent] 分析结果: {result}")

        return RegenerateRequest(
            target_type=result.get("target_type", "shot"),
            resource_type=result.get("resource_type", "image"),
            frame_type=result.get("frame_type"),
            target_numbers=result.get("target_numbers", []),
            target_names=result.get("target_names", []),
            scope=result.get("scope", "specific"),
            user_message=user_message,
        )

    async def execute(
        self,
        creation_uuid: str,
        request: RegenerateRequest
    ) -> Dict[str, Any]:
        """执行重新生成"""

        # 根据 target_type 路由到不同的处理器
        if request.target_type == "character":
            return await self._handle_character_regenerate(creation_uuid, request)
        elif request.target_type == "scene":
            return await self._handle_scene_regenerate(creation_uuid, request)
        elif request.target_type == "shot":
            return await self._handle_shot_regenerate(creation_uuid, request)
        else:
            return {"success": False, "error": f"不支持的 target_type: {request.target_type}"}

    async def _handle_character_regenerate(
        self,
        creation_uuid: str,
        request: RegenerateRequest
    ) -> Dict[str, Any]:
        """处理角色重新生成"""
        from app.agent.tools.db_tools import query_characters
        from app.agent.tools.regenerate_tools import regenerate

        logger.info(f"[RegenerateAgent] 处理角色重新生成: scope={request.scope}, names={request.target_names}")

        # 获取角色列表
        result = await query_characters.ainvoke({
            "creation_uuid": creation_uuid,
            "include_images": False
        })

        characters = result.get("characters", []) if result else []

        if not characters:
            return {"success": False, "error": "没有找到角色资源"}

        # 筛选要重新生成的角色
        to_regenerate = []
        if request.scope == "all":
            to_regenerate = characters
        elif request.target_names:
            # 按名称匹配
            for name in request.target_names:
                for char in characters:
                    if name.lower() in char.get("name", "").lower():
                        to_regenerate.append(char)
                        break
        else:
            # 默认全部
            to_regenerate = characters

        if not to_regenerate:
            return {"success": False, "error": "没有匹配到要重新生成的角色"}

        # 执行重新生成
        results = []
        for char in to_regenerate:
            result = await regenerate.ainvoke({
                "target_type": "character",
                "target_id": char.get("character_id"),
                "creation_uuid": creation_uuid,
                "save_version": True,
                "mode": "auto",
            })
            results.append({
                "id": char.get("character_id"),
                "name": char.get("name"),
                "success": result.get("success"),
            })

        success_count = sum(1 for r in results if r["success"])

        return {
            "success": True,
            "message": f"已为 {success_count}/{len(results)} 个角色重新提交生成任务",
            "regenerated_count": success_count,
            "results": results,
        }

    async def _handle_scene_regenerate(
        self,
        creation_uuid: str,
        request: RegenerateRequest
    ) -> Dict[str, Any]:
        """处理场景重新生成"""
        from app.agent.tools.db_tools import query_scenes
        from app.agent.tools.regenerate_tools import regenerate

        logger.info(f"[RegenerateAgent] 处理场景重新生成: scope={request.scope}")

        # 获取场景列表
        result = await query_scenes.ainvoke({"creation_uuid": creation_uuid})
        scenes = result.get("scenes", []) if result else []

        if not scenes:
            return {"success": False, "error": "没有找到场景资源"}

        # 筛选要重新生成的场景
        to_regenerate = []
        if request.scope == "all":
            to_regenerate = scenes
        else:
            # 默认全部
            to_regenerate = scenes

        # 执行重新生成
        results = []
        for scene in to_regenerate:
            result = await regenerate.ainvoke({
                "target_type": "scene",
                "target_id": scene.get("scene_id"),
                "creation_uuid": creation_uuid,
                "save_version": True,
                "mode": "auto",
            })
            results.append({
                "id": scene.get("scene_id"),
                "name": scene.get("title"),
                "success": result.get("success"),
            })

        success_count = sum(1 for r in results if r["success"])

        return {
            "success": True,
            "message": f"已为 {success_count}/{len(results)} 个场景重新提交生成任务",
            "regenerated_count": success_count,
            "results": results,
        }

    async def _handle_shot_regenerate(
        self,
        creation_uuid: str,
        request: RegenerateRequest
    ) -> Dict[str, Any]:
        """处理分镜重新生成"""
        from app.agent.tools.db_tools import query_shots
        from app.agent.tools.regenerate_tools import regenerate

        logger.info(f"[RegenerateAgent] 处理分镜重新生成: numbers={request.target_numbers}, frame_type={request.frame_type}, resource_type={request.resource_type}")

        # 获取分镜列表
        result = await query_shots.ainvoke({
            "creation_uuid": creation_uuid,
            "include_details": False
        })
        shots = result.get("shots", []) if result else []

        if not shots:
            return {"success": False, "error": "没有找到分镜资源"}

        # 筛选要重新生成的分镜
        to_regenerate = []
        if request.scope == "all":
            to_regenerate = shots
        elif request.target_numbers:
            # 按编号匹配
            for shot in shots:
                if shot.get("shot_number") in request.target_numbers:
                    to_regenerate.append(shot)
        else:
            # 默认全部
            to_regenerate = shots

        if not to_regenerate:
            return {"success": False, "error": "没有匹配到要重新生成的分镜"}

        # 确定 target_type 和 mode
        if request.resource_type == "video":
            # 视频生成
            target_type = "shot_video"
            mode = "first_frame_only" if request.frame_type == "start" else "first_last_frame"
        else:
            # 图片生成
            if request.frame_type == "start":
                target_type = "shot_start"
                mode = "auto"
            elif request.frame_type == "end":
                target_type = "shot_end"
                mode = "auto"
            else:
                target_type = "shot_image"
                mode = "auto"

        # 执行重新生成
        results = []
        for shot in to_regenerate:
            result = await regenerate.ainvoke({
                "target_type": target_type,
                "target_id": shot.get("shot_id"),
                "creation_uuid": creation_uuid,
                "save_version": True,
                "mode": mode,
            })
            results.append({
                "id": shot.get("shot_id"),
                "name": f"分镜{shot.get('shot_number')}",
                "success": result.get("success"),
                "task_id": result.get("task_id"),
            })

        success_count = sum(1 for r in results if r["success"])

        # 构建响应消息
        frame_desc = {
            "start": "首帧",
            "end": "尾帧",
            "both": "图片",
        }.get(request.frame_type, "图片")

        resource_desc = "视频" if request.resource_type == "video" else frame_desc

        return {
            "success": True,
            "message": f"已为 {success_count}/{len(results)} 个分镜重新提交{resource_desc}生成任务",
            "regenerated_count": success_count,
            "results": results,
            "target_type": "shot",
            "resource_type": request.resource_type,
            "frame_type": request.frame_type,
        }


# ==================== Tool 接口 ====================

@tool
async def regenerate_with_agent(
    creation_uuid: str,
    user_message: str,
) -> Dict[str, Any]:
    """
    使用 RegenerateAgent 执行资源重新生成

    Args:
        creation_uuid: 创作项目 UUID
        user_message: 用户原始消息

    Returns:
        重新生成结果
    """
    logger.info(f"[regenerate_with_agent] 创建 RegenerateAgent 处理: '{user_message}'")

    agent = RegenerateAgent()

    # 1. 分析请求
    request = await agent.analyze_request(user_message)

    # 2. 执行重新生成
    result = await agent.execute(creation_uuid, request)

    return result
