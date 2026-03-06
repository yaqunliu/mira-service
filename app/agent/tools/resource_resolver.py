"""
资源解析工具 - 使用 LLM 智能解析用户的资源引用

职责：
1. 接收用户的自然语言描述（如"分镜5"、"幽影出场的分镜"）
2. 查询所有可用资源
3. 使用 LLM 智能匹配用户指的是哪个资源
4. 返回匹配结果
"""

import json
import re
from typing import Dict, Any, List, Optional

from langchain_core.tools import tool
from langchain_openai import ChatOpenAI

from app.core.config import settings
from app.core.logger import logger


@tool
async def resolve_resource_reference(
    creation_uuid: str,
    target: str,
    user_reference: str,
) -> Dict[str, Any]:
    """
    使用 LLM 智能解析用户的资源引用

    例如用户说"给分镜5重新生成"，LLM 应该理解是 shot_number=5 而不是 description 包含"5"
    同时会判断 frame_type（首帧/尾帧/两者）

    Args:
        creation_uuid: 创作项目 UUID
        target: 资源类型 (shot/character/scene)
        user_reference: 用户的原始描述（如"分镜5"、"幽影"、"第一个分镜"、"分镜5的尾帧"）

    Returns:
        匹配结果，包含 matched_resources、confidence 和 frame_type
    """
    logger.info(f"[ResourceResolver] 解析资源引用: target={target}, reference='{user_reference}'")

    # 1. 获取所有可用资源
    all_resources = await _fetch_all_resources(creation_uuid, target)

    if not all_resources:
        return {
            "success": False,
            "error": f"未找到任何 {target} 资源",
            "matched_resources": [],
        }

    # 2. 使用 LLM 进行智能匹配
    try:
        match_result = await _llm_match_resources(target, user_reference, all_resources)

        # 3. 将匹配结果映射回原始资源
        matched_resources = _map_matched_resources(match_result, all_resources, target)

        # 4. 提取 frame_type（仅用于分镜）
        frame_type = match_result.get("frame_type")
        if target == "shot" and frame_type:
            logger.info(f"[ResourceResolver] LLM 判断 frame_type={frame_type}")

        return {
            "success": True,
            "matched_resources": matched_resources,
            "frame_type": frame_type,  # 可能为 null
            "ambiguous": match_result.get("ambiguous", len(matched_resources) > 1),
            "message": match_result.get("message", ""),
            "confidence": match_result.get("confidence", 0.5),
            "match_reasons": match_result.get("reasons", []),
        }

    except Exception as e:
        logger.error(f"[ResourceResolver] LLM 匹配失败: {e}")
        import traceback
        logger.error(f"[ResourceResolver] 异常栈: {traceback.format_exc()}")

        # 降级为简单匹配
        fallback_result = _fallback_match(target, user_reference, all_resources)
        # 兜底：从用户描述中检测 frame_type
        fallback_result["frame_type"] = _detect_frame_type_from_reference(user_reference)
        return fallback_result


async def _fetch_all_resources(creation_uuid: str, target: str) -> List[Dict[str, Any]]:
    """获取所有可用资源"""
    from app.agent.tools.db_tools import query_shots, query_characters, query_scenes
    
    logger.info(f"[_fetch_all_resources] 开始查询: creation_uuid={creation_uuid}, target={target}")
    
    if target == "shot":
        result = await query_shots.ainvoke({
            "creation_uuid": creation_uuid,
            "include_details": False
        })
        # logger.info(f"[_fetch_all_resources] query_shots 结果: {result}")
        # query_shots 返回 {"total": n, "shots": [...]}
        shots = result.get("shots", []) if result else []
        logger.info(f"[_fetch_all_resources] 返回 {len(shots)} 个分镜")
        return shots
    
    elif target == "character":
        result = await query_characters.ainvoke({
            "creation_uuid": creation_uuid,
            "include_images": False
        })
        logger.info(f"[_fetch_all_resources] query_characters 结果: {result}")
        # query_characters 返回 {"total": n, "characters": [...]}
        characters = result.get("characters", []) if result else []
        logger.info(f"[_fetch_all_resources] 返回 {len(characters)} 个角色")
        return characters
    
    elif target == "scene":
        result = await query_scenes.ainvoke({
            "creation_uuid": creation_uuid
        })
        logger.info(f"[_fetch_all_resources] query_scenes 结果: {result}")
        # query_scenes 返回 {"total": n, "scenes": [...]}
        scenes = result.get("scenes", []) if result else []
        logger.info(f"[_fetch_all_resources] 返回 {len(scenes)} 个场景")
        return scenes
    
    return []


async def _llm_match_resources(
    target: str,
    user_reference: str,
    all_resources: List[Dict[str, Any]]
) -> Dict[str, Any]:
    """使用 LLM 进行资源匹配，同时判断 frame_type（用于分镜图片生成）"""

    system_prompt = """你是一个智能资源匹配助手。你的任务是理解用户的自然语言描述，并准确匹配到对应的资源。

匹配规则（按优先级排序）：
1. **数字编号优先**：如"分镜5"应匹配 编号=5（sequence=5 或 shot_number=5），而不是 description 包含"5"
2. **名称精确匹配**：如"幽影"应匹配 name="幽影"的角色，**不要**匹配 name="幽影-青年"或"幽影-战斗"等
   - **重要**：角色名称必须完全相等才匹配，不允许前缀匹配或部分匹配
   - 例如：用户说"阿九-青年"，只能匹配 name="阿九-青年"，**不能**匹配 name="阿九-青年-战斗"
3. **描述匹配**：如"幽影出场的分镜"应匹配 description 包含"幽影"的分镜
4. **序数词匹配**：如"第一个分镜"应匹配 编号 最小的分镜
5. **模糊匹配**：如"老王出场的场景"应匹配 description 包含"老王"的场景

重要：返回的 matched_ids 必须是资源的 ID 字段（如 shot_id, character_id, scene_id），不是编号！

对于分镜图片生成任务，必须判断 frame_type，只能是以下三种之一：
- 用户明确说"尾帧"、"结束帧"、"最后一帧" -> frame_type="end"
- 用户明确说"首帧"、"开始帧"、"第一帧" -> frame_type="start"
- 用户说"图片"、"分镜图"、"重新生成"等未明确指定首尾的情况 -> frame_type="both"

重要：frame_type 必须是 "start"、"end"、"both" 三者之一，不能为 null！

输出格式（必须严格遵循）：
```json
{
    "matched_ids": ["资源ID1", "资源ID2"],
    "frame_type": "start" | "end" | "both",
    "ambiguous": false,
    "confidence": 0.95,
    "message": "匹配说明",
    "reasons": [
        {"id": "资源ID1", "reason": "编号=5 匹配 '分镜5'", "confidence": 0.99}
    ]
}
```"""

    # 构建资源列表描述（限制数量避免 token 超限）
    resources_desc = []
    for i, r in enumerate(all_resources[:30], 1):  # 最多30个
        if target == "shot":
            # query_shots 返回的是 sequence 字段，不是 shot_number
            shot_num = r.get('shot_number') or r.get('sequence') or r.get('id')
            description = r.get('description') or r.get('title') or ''
            desc = f"ID:{r.get('shot_id') or r.get('id')}, 编号:{shot_num}, 描述:{description[:40]}"
        elif target == "character":
            desc = f"ID:{r.get('character_id') or r.get('id')}, 名称:{r.get('name', '未命名')}"
        elif target == "scene":
            desc = f"ID:{r.get('scene_id') or r.get('id')}, 标题:{r.get('title', '未命名')}"
        else:
            desc = f"ID:{r.get('id')}"
        resources_desc.append(f"{i}. {desc}")
    
    user_prompt = f"""用户说: "{user_reference}"

可用资源列表（共{len(all_resources)}个，显示前{len(resources_desc)}个）:
{chr(10).join(resources_desc)}

请分析用户想指的是哪个或哪些资源，返回 JSON 格式的结果。"""

    llm = ChatOpenAI(
        model="gpt-4o-mini",
        temperature=0.1,
        api_key=settings.OPENAI_API_KEY,
    )
    
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt}
    ]
    
    response = await llm.ainvoke(messages)
    content = response.content.strip()
    
    # 解析 JSON
    if content.startswith("```json"):
        content = content[7:]
    if content.startswith("```"):
        content = content[3:]
    if content.endswith("```"):
        content = content[:-3]
    content = content.strip()
    
    return json.loads(content)


def _map_matched_resources(
    match_result: Dict[str, Any],
    all_resources: List[Dict[str, Any]],
    target: str
) -> List[Dict[str, Any]]:
    """将匹配的 ID 映射回原始资源"""
    matched_ids = set(match_result.get("matched_ids", []))
    
    matched = []
    for r in all_resources:
        resource_id = str(r.get("shot_id") or r.get("character_id") or r.get("scene_id") or r.get("id"))
        if resource_id in matched_ids:
            matched.append(r)
    
    return matched


def _detect_frame_type_from_reference(user_reference: str) -> str:
    """从用户描述中检测 frame_type，默认返回 both"""
    ref_lower = user_reference.lower()

    # 尾帧关键词
    if any(kw in ref_lower for kw in ["尾帧", "结束帧", "最后一帧", "尾帧图片", "结束帧图片"]):
        return "end"

    # 首帧关键词
    if any(kw in ref_lower for kw in ["首帧", "开始帧", "第一帧", "首帧图片", "开始帧图片"]):
        return "start"

    # 未明确指定，默认 both
    return "both"


def _fallback_match(
    target: str,
    user_reference: str,
    all_resources: List[Dict[str, Any]]
) -> Dict[str, Any]:
    """降级方案：简单规则匹配"""
    matched = []
    ref_lower = user_reference.lower()
    
    # 提取数字
    numbers = re.findall(r'\d+', user_reference)
    
    for r in all_resources:
        score = 0
        reasons = []
        
        # 数字编号匹配（最高优先级）- 支持 shot_number 和 sequence 字段
        if target == "shot" and numbers:
            shot_num = r.get("shot_number") or r.get("sequence")
            if shot_num and str(shot_num) in numbers:
                score = 100
                reasons.append(f"编号={shot_num} 匹配 '{user_reference}'")
        
        # 名称精确匹配（重要：必须是完全相等，不允许前缀匹配）
        if score == 0:
            name = r.get("name", "").lower() if target == "character" else r.get("title", "").lower()
            # 精确匹配：用户输入必须完全等于资源名称
            if name and name == ref_lower:
                score = 80
                reasons.append(f"名称 '{name}' 精确匹配")
            # 如果用户输入包含额外信息（如"阿九-青年 的图片"），提取名称部分再匹配
            elif name:
                # 提取可能的名称（去掉"的图片"、"的提示词"等后缀）
                clean_ref = ref_lower.replace("的图片", "").replace("的图像", "").replace("的提示词", "").strip()
                if name == clean_ref:
                    score = 80
                    reasons.append(f"名称 '{name}' 精确匹配")
        
        # 描述匹配
        if score == 0:
            desc = r.get("description", "").lower()
            if desc and ref_lower in desc:
                score = 50
                reasons.append("描述包含关键词")
        
        if score > 0:
            matched.append((r, score, reasons))
    
    # 按分数排序
    matched.sort(key=lambda x: x[1], reverse=True)
    
    return {
        "success": True,
        "matched_resources": [m[0] for m in matched[:5]],
        "ambiguous": len(matched) > 1 and matched[0][1] - matched[1][1] < 20,
        "message": f"找到 {len(matched)} 个匹配结果（降级匹配）",
        "confidence": matched[0][1] / 100 if matched else 0,
        "reasons": matched[0][2] if matched else [],
    }
