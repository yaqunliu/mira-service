"""
分析类 Tools

提供剧本分析、角色提取、场景提取等功能
"""

from typing import Dict, Any, List, Optional

from langchain_core.tools import tool
from pydantic import BaseModel, Field

from app.core.logger import logger


@tool
async def analyze_script(
    script_text: str,
    analysis_type: str = "full",
) -> Dict[str, Any]:
    """
    分析剧本内容，提取结构信息
    
    Args:
        script_text: 剧本文本
        analysis_type: 分析类型（full=完整分析, summary=仅摘要, structure=仅结构）
        
    Returns:
        分析结果，包含摘要、主题、风格、角色列表、场景列表等
    """
    logger.info(f"[Analysis Tool] 分析剧本: type={analysis_type}, length={len(script_text)}")
    
    from langchain_openai import ChatOpenAI
    from app.core.config import settings
    
    llm = ChatOpenAI(
        model=settings.LLM_MODEL_DEFAULT,
        api_key=settings.OPENAI_API_KEY,
        base_url=settings.OPENAI_BASE_URL,
        temperature=0.3,
    )
    
    prompt = f"""分析以下剧本内容，返回 JSON 格式结果：

## 剧本内容
{script_text[:8000]}

## 分析要求
请提取以下信息：
1. summary: 剧本摘要（100字以内）
2. theme: 主题
3. style: 风格（悬疑/喜剧/动作/爱情/科幻等）
4. characters: 角色列表，每个包含 name, description, personality
5. scenes: 场景列表，每个包含 name, description, mood
6. estimated_duration: 预估时长（分钟）

## 输出格式
严格返回 JSON 格式，不要包含其他内容：
{{
    "summary": "...",
    "theme": "...",
    "style": "...",
    "characters": [...],
    "scenes": [...],
    "estimated_duration": 0
}}"""

    try:
        response = await llm.ainvoke(prompt)
        
        import json
        content = response.content.strip()
        # 处理可能的 markdown 代码块
        if content.startswith("```"):
            content = content.split("```")[1]
            if content.startswith("json"):
                content = content[4:]
        
        result = json.loads(content)
        result["status"] = "success"
        return result
        
    except Exception as e:
        logger.error(f"[Analysis Tool] 剧本分析失败: {e}")
        return {
            "status": "failed",
            "error": str(e),
        }


@tool
async def extract_characters(
    script_text: str,
    include_details: bool = True,
) -> Dict[str, Any]:
    """
    从剧本中提取角色信息
    
    Args:
        script_text: 剧本文本
        include_details: 是否包含详细描述
        
    Returns:
        角色列表，每个包含 name, description, personality, appearance
    """
    logger.info(f"[Analysis Tool] 提取角色: length={len(script_text)}")
    
    from langchain_openai import ChatOpenAI
    from app.core.config import settings
    
    llm = ChatOpenAI(
        model=settings.LLM_MODEL_DEFAULT,
        api_key=settings.OPENAI_API_KEY,
        base_url=settings.OPENAI_BASE_URL,
        temperature=0.3,
    )
    
    detail_prompt = """
对于每个角色，请提供：
- name: 角色名称
- description: 角色简介（50字以内）
- personality: 性格特征
- appearance: 外貌描述（用于图片生成）
- importance: 重要程度（main/supporting/minor）
""" if include_details else """
对于每个角色，请提供：
- name: 角色名称
- importance: 重要程度（main/supporting/minor）
"""
    
    prompt = f"""从以下剧本中提取所有角色信息：

## 剧本内容
{script_text[:8000]}

## 提取要求
{detail_prompt}

## 输出格式
严格返回 JSON 格式：
{{
    "characters": [
        {{"name": "...", "description": "...", ...}},
        ...
    ],
    "total_count": 0
}}"""

    try:
        response = await llm.ainvoke(prompt)
        
        import json
        content = response.content.strip()
        if content.startswith("```"):
            content = content.split("```")[1]
            if content.startswith("json"):
                content = content[4:]
        
        result = json.loads(content)
        result["status"] = "success"
        return result
        
    except Exception as e:
        logger.error(f"[Analysis Tool] 角色提取失败: {e}")
        return {
            "status": "failed",
            "error": str(e),
            "characters": [],
        }


@tool
async def extract_scenes(
    script_text: str,
    include_details: bool = True,
) -> Dict[str, Any]:
    """
    从剧本中提取场景信息
    
    Args:
        script_text: 剧本文本
        include_details: 是否包含详细描述
        
    Returns:
        场景列表，每个包含 name, description, location, time, mood
    """
    logger.info(f"[Analysis Tool] 提取场景: length={len(script_text)}")
    
    from langchain_openai import ChatOpenAI
    from app.core.config import settings
    
    llm = ChatOpenAI(
        model=settings.LLM_MODEL_DEFAULT,
        api_key=settings.OPENAI_API_KEY,
        base_url=settings.OPENAI_BASE_URL,
        temperature=0.3,
    )
    
    detail_prompt = """
对于每个场景，请提供：
- name: 场景名称
- description: 场景描述（用于图片生成）
- location: 地点类型（室内/室外/城市/乡村等）
- time: 时间（白天/夜晚/黄昏/清晨等）
- mood: 氛围（欢快/悲伤/紧张/神秘等）
- characters_present: 出场角色列表
""" if include_details else """
对于每个场景，请提供：
- name: 场景名称
- location: 地点类型
"""
    
    prompt = f"""从以下剧本中提取所有场景信息：

## 剧本内容
{script_text[:8000]}

## 提取要求
{detail_prompt}

## 输出格式
严格返回 JSON 格式：
{{
    "scenes": [
        {{"name": "...", "description": "...", ...}},
        ...
    ],
    "total_count": 0
}}"""

    try:
        response = await llm.ainvoke(prompt)
        
        import json
        content = response.content.strip()
        if content.startswith("```"):
            content = content.split("```")[1]
            if content.startswith("json"):
                content = content[4:]
        
        result = json.loads(content)
        result["status"] = "success"
        return result
        
    except Exception as e:
        logger.error(f"[Analysis Tool] 场景提取失败: {e}")
        return {
            "status": "failed",
            "error": str(e),
            "scenes": [],
        }


@tool
async def generate_image_prompt(
    subject_type: str,
    description: str,
    style: str = "anime",
    additional_context: Optional[str] = None,
) -> Dict[str, Any]:
    """
    生成图片提示词
    
    Args:
        subject_type: 主题类型（character/scene/shot）
        description: 基础描述
        style: 风格（anime/realistic/cartoon等）
        additional_context: 附加上下文
        
    Returns:
        生成的提示词
    """
    logger.info(f"[Analysis Tool] 生成图片提示词: type={subject_type}")
    
    from langchain_openai import ChatOpenAI
    from app.core.config import settings
    
    llm = ChatOpenAI(
        model=settings.LLM_MODEL_DEFAULT,
        api_key=settings.OPENAI_API_KEY,
        base_url=settings.OPENAI_BASE_URL,
        temperature=0.7,
    )
    
    type_guidance = {
        "character": "角色形象图，需要突出五官特征、服装、表情",
        "scene": "场景背景图，需要突出环境氛围、光线、空间感",
        "shot": "分镜画面图，需要包含人物动作、表情、构图",
    }
    
    guidance = type_guidance.get(subject_type, "通用图片")
    
    prompt = f"""为以下内容生成图片提示词：

## 类型
{subject_type} - {guidance}

## 描述
{description}

## 风格
{style}

## 附加上下文
{additional_context or "无"}

## 要求
1. 提示词使用英文
2. 包含主体描述、风格、构图、光线等要素
3. 长度控制在 100-200 词
4. 避免敏感内容

## 输出
直接返回提示词文本，不要包含其他内容。"""

    try:
        response = await llm.ainvoke(prompt)
        
        return {
            "status": "success",
            "prompt": response.content.strip(),
            "subject_type": subject_type,
            "style": style,
        }
        
    except Exception as e:
        logger.error(f"[Analysis Tool] 提示词生成失败: {e}")
        return {
            "status": "failed",
            "error": str(e),
        }


# 导出所有分析类 Tools
ANALYSIS_TOOLS = [
    analyze_script,
    extract_characters,
    extract_scenes,
    generate_image_prompt,
]
