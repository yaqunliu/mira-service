"""
Prompt Generation Tools - 提示词生成工具

提供基于 LLM 的提示词生成功能，供 AssetRegeneratorWorker 使用。
Agent 调用这些工具来生成角色、场景、分镜的提示词。
"""

import json
from typing import Dict, Any, List, Optional
from langchain_core.tools import tool
from langchain_openai import ChatOpenAI
from langchain_core.messages import HumanMessage

from app.core.logger import logger
from app.core.config import settings


# ==================== 辅助函数 ====================

def _get_llm(temperature: float = 0.7) -> ChatOpenAI:
    """获取 LLM 实例"""
    return ChatOpenAI(
        model=settings.LLM_MODEL_DEFAULT,
        api_key=settings.OPENAI_API_KEY,
        base_url=settings.OPENAI_BASE_URL,
        temperature=temperature,
        timeout=120,
        max_retries=2,
    )


def _extract_prompt_from_response(response_text: str) -> str:
    """从 LLM 响应中提取提示词"""
    # 尝试从 <提示词> 标签中提取
    import re
    match = re.search(r'<提示词>(.*?)</提示词>', response_text, re.DOTALL)
    if match:
        return match.group(1).strip()
    
    # 如果没有标签，返回整个响应
    return response_text.strip()


def _extract_json_from_response(response_text: str) -> Dict[str, Any]:
    """从 LLM 响应中提取 JSON"""
    import re
    # 尝试匹配 ```json ... ``` 格式
    match = re.search(r'```json\s*(.*?)\s*```', response_text, re.DOTALL)
    if match:
        json_str = match.group(1)
    else:
        # 尝试直接匹配 JSON 对象
        match = re.search(r'\{.*\}', response_text, re.DOTALL)
        if match:
            json_str = match.group(0)
        else:
            json_str = response_text
    
    try:
        return json.loads(json_str)
    except json.JSONDecodeError as e:
        logger.error(f"JSON 解析失败: {e}, text={response_text[:200]}")
        return {
            "error": "JSON 解析失败",
            "raw_response": response_text
        }


# ==================== 提示词生成工具 ====================

@tool
async def generate_character_prompt(
    character_info: Dict[str, Any],
    template_content: str,
    visual_style: str = "日本动漫风格",
    operation_type: str = "regenerate",
    old_prompt: Optional[str] = None,
    feedback: Optional[str] = None
) -> Dict[str, Any]:
    """
    生成角色图片提示词
    
    基于角色信息和模板，使用 LLM 生成角色参考图提示词。
    
    Args:
        character_info: 角色信息字典
            {
                "name": str,
                "basic_info": str,
                "appearance": str,
                ...
            }
        template_content: 模板内容（从 get_character_prompt_template 获取）
        visual_style: 视觉风格
        operation_type: 操作类型 "regenerate" 或 "modify"
        old_prompt: 原提示词（operation_type="modify" 时必填）
        feedback: 修改意见（operation_type="modify" 时必填）
        
    Returns:
        {
            "success": bool,
            "prompt": str,  # 生成的提示词
            "raw_response": str  # LLM 原始响应
        }
    """
    logger.info(f"[Prompt Gen] 生成角色提示词: {character_info.get('name', 'Unknown')}, type={operation_type}")
    
    try:
        # 准备模板变量
        template_vars = {
            "CHARACTER_NAME": character_info.get("name", ""),
            "ROLE_TYPE": character_info.get("role_type", "角色"),
            "AGE": character_info.get("age", ""),
            "GENDER": character_info.get("gender", ""),
            "APPEARANCE_DESC": character_info.get("appearance", ""),
            "PERSONALITY": character_info.get("personality", ""),
            "COSTUME_DESC": character_info.get("costume", ""),
            "VISUAL_STYLE": visual_style,
        }
        
        # 如果是修改模式，添加修改相关信息
        if operation_type == "modify":
            template_vars["OLD_PROMPT"] = old_prompt or ""
            template_vars["FEEDBACK"] = feedback or ""
        
        # 填充模板
        filled_template = template_content
        for key, value in template_vars.items():
            filled_template = filled_template.replace(f"{{{{{key}}}}}", str(value))
        
        # 调用 LLM 生成提示词
        llm = _get_llm(temperature=0.7)
        messages = [HumanMessage(content=filled_template)]
        
        response = await llm.ainvoke(messages)
        response_text = response.content
        
        # 提取提示词
        generated_prompt = _extract_prompt_from_response(response_text)
        
        return {
            "success": True,
            "prompt": generated_prompt,
            "raw_response": response_text,
            "character_name": character_info.get("name"),
            "operation_type": operation_type
        }
        
    except Exception as e:
        logger.error(f"[Prompt Gen] 生成角色提示词失败: {e}")
        return {
            "success": False,
            "prompt": "",
            "raw_response": "",
            "error": str(e)
        }


@tool
async def generate_scene_prompt(
    scene_info: Dict[str, Any],
    template_content: str,
    visual_style: str = "日本动漫风格",
    operation_type: str = "regenerate",
    old_prompt: Optional[str] = None,
    feedback: Optional[str] = None
) -> Dict[str, Any]:
    """
    生成场景图片提示词
    
    基于场景信息和模板，使用 LLM 生成场景环境图提示词。
    
    Args:
        scene_info: 场景信息字典
            {
                "title": str,
                "location": str,
                "time_setting": str,
                "space_type": str,
                "atmosphere": str,
                ...
            }
        template_content: 模板内容（从 get_scene_prompt_template 获取）
        visual_style: 视觉风格
        operation_type: 操作类型 "regenerate" 或 "modify"
        old_prompt: 原提示词（operation_type="modify" 时必填）
        feedback: 修改意见（operation_type="modify" 时必填）
        
    Returns:
        {
            "success": bool,
            "prompt": str,
            "raw_response": str
        }
    """
    logger.info(f"[Prompt Gen] 生成场景提示词: {scene_info.get('title', 'Unknown')}, type={operation_type}")
    
    try:
        # 准备模板变量
        template_vars = {
            "SCENE_TITLE": scene_info.get("title", ""),
            "LOCATION": scene_info.get("location", ""),
            "TIME_SETTING": scene_info.get("time_setting", ""),
            "SPACE_TYPE": scene_info.get("space_type", ""),
            "ATMOSPHERE": scene_info.get("atmosphere", ""),
            "VISUAL_STYLE": visual_style,
        }
        
        if operation_type == "modify":
            template_vars["OLD_PROMPT"] = old_prompt or ""
            template_vars["FEEDBACK"] = feedback or ""
        
        # 填充模板
        filled_template = template_content
        for key, value in template_vars.items():
            filled_template = filled_template.replace(f"{{{{{key}}}}}", str(value))
        
        # 调用 LLM
        llm = _get_llm(temperature=0.7)
        messages = [HumanMessage(content=filled_template)]
        
        response = await llm.ainvoke(messages)
        response_text = response.content
        
        generated_prompt = _extract_prompt_from_response(response_text)
        
        return {
            "success": True,
            "prompt": generated_prompt,
            "raw_response": response_text,
            "scene_title": scene_info.get("title"),
            "operation_type": operation_type
        }
        
    except Exception as e:
        logger.error(f"[Prompt Gen] 生成场景提示词失败: {e}")
        return {
            "success": False,
            "prompt": "",
            "raw_response": "",
            "error": str(e)
        }


@tool
async def generate_shot_image_prompt(
    shot_info: Dict[str, Any],
    scene_info: Dict[str, Any],
    character_profiles: List[Dict[str, Any]],
    template_content: str,
    frame_type: str = "start",
    visual_style: str = "日本动漫风格",
    previous_shot_info: Optional[Dict[str, Any]] = None,
    operation_type: str = "regenerate",
    old_prompt: Optional[str] = None,
    feedback: Optional[str] = None
) -> Dict[str, Any]:
    """
    生成分镜图片提示词
    
    基于分镜信息、场景信息、角色信息，使用 LLM 生成分镜首帧或尾帧提示词。
    
    Args:
        shot_info: 分镜信息字典
        scene_info: 场景信息字典
        character_profiles: 角色信息列表
        template_content: 模板内容（从 get_shot_image_prompt_template 获取）
        frame_type: 帧类型 "start" 或 "end"
        visual_style: 视觉风格
        previous_shot_info: 上一个分镜信息（可选，用于连贯性）
        operation_type: 操作类型 "regenerate" 或 "modify"
        old_prompt: 原提示词（operation_type="modify" 时必填）
        feedback: 修改意见（operation_type="modify" 时必填）
        
    Returns:
        {
            "success": bool,
            "prompt": str,
            "frame_type": str,
            "raw_response": str
        }
    """
    logger.info(f"[Prompt Gen] 生成分镜图片提示词: shot={shot_info.get('shot_number')}, frame={frame_type}")
    
    try:
        # 构建角色描述
        character_desc = ""
        for char in character_profiles:
            character_desc += f"\n- {char.get('name', '未知角色')}: {char.get('appearance', '')}"
        
        # 构建上一个分镜信息
        prev_shot_desc = ""
        if previous_shot_info:
            prev_shot_desc = f"""
上一个分镜信息（保持连贯性）：
- 分镜编号: {previous_shot_info.get('shot_number', '')}
- 描述: {previous_shot_info.get('description', '')}
- 注意: 当前分镜的画面应该与上一个分镜保持视觉连贯性
"""
        
        # 准备模板变量
        template_vars = {
            "SHOT_NUMBER": str(shot_info.get("shot_number", "")),
            "SHOT_TITLE": shot_info.get("title", ""),
            "SHOT_DESCRIPTION": shot_info.get("description", ""),
            "NARRATION": shot_info.get("narration", ""),
            "SCENE_TITLE": scene_info.get("title", ""),
            "LOCATION": scene_info.get("location", ""),
            "TIME_SETTING": scene_info.get("time_setting", ""),
            "ATMOSPHERE": scene_info.get("atmosphere", ""),
            "CHARACTER_PROFILES": character_desc,
            "VISUAL_STYLE": visual_style,
            "PREVIOUS_SHOT_INFO": prev_shot_desc,
        }
        
        if operation_type == "modify":
            template_vars["OLD_PROMPT"] = old_prompt or ""
            template_vars["FEEDBACK"] = feedback or ""
        
        # 填充模板
        filled_template = template_content
        for key, value in template_vars.items():
            filled_template = filled_template.replace(f"{{{{{key}}}}}", str(value))
        
        # 调用 LLM
        llm = _get_llm(temperature=0.7)
        messages = [HumanMessage(content=filled_template)]
        
        response = await llm.ainvoke(messages)
        response_text = response.content
        
        generated_prompt = _extract_prompt_from_response(response_text)
        
        return {
            "success": True,
            "prompt": generated_prompt,
            "frame_type": frame_type,
            "raw_response": response_text,
            "shot_number": shot_info.get("shot_number"),
            "operation_type": operation_type
        }
        
    except Exception as e:
        logger.error(f"[Prompt Gen] 生成分镜图片提示词失败: {e}")
        return {
            "success": False,
            "prompt": "",
            "frame_type": frame_type,
            "raw_response": "",
            "error": str(e)
        }


@tool
async def generate_shot_video_prompt(
    shot_info: Dict[str, Any],
    scene_info: Dict[str, Any],
    character_profiles: List[Dict[str, Any]],
    template_content: str,
    start_frame_prompt: Optional[str] = None,
    end_frame_prompt: Optional[str] = None,
    visual_style: str = "日本动漫风格",
    knowledge_context: Optional[str] = None,
    previous_shot_info: Optional[Dict[str, Any]] = None,
    operation_type: str = "regenerate",
    old_prompt: Optional[str] = None,
    feedback: Optional[str] = None
) -> Dict[str, Any]:
    """
    生成分镜视频提示词
    
    基于分镜信息、首帧/尾帧提示词、知识库上下文，使用 LLM 生成视频提示词。
    采用三维度时间轴驱动格式（画面+背景音+人物对白）。
    
    Args:
        shot_info: 分镜信息字典
        scene_info: 场景信息字典
        character_profiles: 角色信息列表
        template_content: 模板内容（从 get_shot_video_prompt_template 获取）
        start_frame_prompt: 首帧图片提示词
        end_frame_prompt: 尾帧图片提示词
        visual_style: 视觉风格
        knowledge_context: 知识库上下文（可选，运镜技巧等）
        previous_shot_info: 上一个分镜信息（可选）
        operation_type: 操作类型 "regenerate" 或 "modify"
        old_prompt: 原提示词（operation_type="modify" 时必填）
        feedback: 修改意见（operation_type="modify" 时必填）
        
    Returns:
        {
            "success": bool,
            "video_prompt": str,  # 视频提示词（JSON 格式）
            "cut_method": str,
            "cut_reason": str,
            "raw_response": str
        }
    """
    logger.info(f"[Prompt Gen] 生成分镜视频提示词: shot={shot_info.get('shot_number')}")
    
    try:
        # 构建角色描述
        character_desc = ""
        for char in character_profiles:
            character_desc += f"\n- {char.get('name', '未知角色')}: {char.get('appearance', '')}"
        
        # 构建上一个分镜信息
        prev_shot_desc = ""
        if previous_shot_info:
            prev_shot_desc = f"""
上一个分镜信息：
- 分镜编号: {previous_shot_info.get('shot_number', '')}
- 描述: {previous_shot_info.get('description', '')}
- 关系: 同一场景连续 / 转场
"""
        
        # 准备模板变量
        template_vars = {
            "SHOT_NUMBER": str(shot_info.get("shot_number", "")),
            "SHOT_TITLE": shot_info.get("title", ""),
            "SHOT_DESCRIPTION": shot_info.get("description", ""),
            "NARRATION": shot_info.get("narration", ""),
            "SHOT_VIDEO_DURATION": str(shot_info.get("video_duration", "5")),
            "SCENE_TITLE": scene_info.get("title", ""),
            "LOCATION": scene_info.get("location", ""),
            "TIME_SETTING": scene_info.get("time_setting", ""),
            "ATMOSPHERE": scene_info.get("atmosphere", ""),
            "CHARACTER_PROFILES": character_desc,
            "VISUAL_STYLE": visual_style,
            "START_FRAME_PROMPT": start_frame_prompt or "",
            "END_FRAME_PROMPT": end_frame_prompt or "",
            "KNOWLEDGE_CONTEXT": knowledge_context or "",
            "PREVIOUS_SHOT_INFO": prev_shot_desc,
        }
        
        if operation_type == "modify":
            template_vars["OLD_PROMPT"] = old_prompt or ""
            template_vars["FEEDBACK"] = feedback or ""
        
        # 填充模板
        filled_template = template_content
        for key, value in template_vars.items():
            filled_template = filled_template.replace(f"{{{{{key}}}}}", str(value))
        
        # 调用 LLM
        llm = _get_llm(temperature=0.7)
        messages = [HumanMessage(content=filled_template)]
        
        response = await llm.ainvoke(messages)
        response_text = response.content
        
        # 提取 JSON 格式的视频提示词
        video_data = _extract_json_from_response(response_text)
        
        if "error" in video_data:
            return {
                "success": False,
                "video_prompt": "",
                "cut_method": "",
                "cut_reason": "",
                "raw_response": response_text,
                "error": video_data.get("error")
            }
        
        return {
            "success": True,
            "video_prompt": video_data.get("video_prompt", ""),
            "cut_method": video_data.get("cut_method", ""),
            "cut_reason": video_data.get("cut_reason", ""),
            "raw_response": response_text,
            "shot_number": shot_info.get("shot_number"),
            "operation_type": operation_type
        }
        
    except Exception as e:
        logger.error(f"[Prompt Gen] 生成分镜视频提示词失败: {e}")
        return {
            "success": False,
            "video_prompt": "",
            "cut_method": "",
            "cut_reason": "",
            "raw_response": "",
            "error": str(e)
        }


# ==================== 工具列表导出 ====================

PROMPT_GENERATION_TOOLS = [
    generate_character_prompt,
    generate_scene_prompt,
    generate_shot_image_prompt,
    generate_shot_video_prompt,
]
