"""
Video Knowledge Tools - 视频生成知识库查询工具

提供查询运镜技巧、镜头语言等专业知识的功能，供 AssetRegeneratorWorker 使用。
"""

from typing import Dict, Any, List, Optional
from langchain_core.tools import tool

from app.core.logger import logger
from app.utils.file_utils import read_knowledge_file


@tool
async def query_knowledge_for_video(
    shot_description: str,
    query_keywords: Optional[List[str]] = None,
    top_k: int = 3
) -> Dict[str, Any]:
    """
    查询视频生成所需的专业知识
    
    根据分镜描述自动分析关键词，查询运镜技巧、镜头语言等相关知识。
    
    Args:
        shot_description: 分镜描述（用于分析查询意图）
        query_keywords: 手动指定的查询关键词（可选）
        top_k: 返回的最大结果数
        
    Returns:
        {
            "success": bool,
            "shot_description": str,
            "keywords": List[str],  # 自动分析或手动指定的关键词
            "knowledge_context": str,  # 合并的知识上下文
            "sources": List[str]  # 知识来源
        }
    """
    logger.info(f"[Knowledge Tool] 查询视频知识: {shot_description[:50]}...")
    
    try:
        # 如果没有提供关键词，自动分析
        if not query_keywords:
            query_keywords = _analyze_keywords(shot_description)
        
        # 查询知识库
        knowledge_parts = []
        sources = []
        
        # 查询镜头技巧
        if any(kw in query_keywords for kw in ["镜头", "运镜", "拍摄", "角度", "景别"]):
            camera_tech = read_knowledge_file("director/camera_techniques.md")
            if camera_tech:
                knowledge_parts.append("## 镜头技巧\n" + camera_tech[:2000])
                sources.append("camera_techniques")
        
        # 查询构图法则
        if any(kw in query_keywords for kw in ["构图", "画面", "布局", "位置"]):
            composition = read_knowledge_file("director/composition_rules.md")
            if composition:
                knowledge_parts.append("## 构图法则\n" + composition[:2000])
                sources.append("composition_rules")
        
        # 查询光线与氛围
        if any(kw in query_keywords for kw in ["光线", "光影", "氛围", "色调", "明暗"]):
            lighting = read_knowledge_file("director/lighting_mood.md")
            if lighting:
                knowledge_parts.append("## 光线与氛围\n" + lighting[:2000])
                sources.append("lighting_mood")
        
        # 查询分镜技巧
        if any(kw in query_keywords for kw in ["分镜", "转场", "切换", "连贯"]):
            storyboard = read_knowledge_file("director/storyboard_examples.md")
            if storyboard:
                knowledge_parts.append("## 分镜技巧\n" + storyboard[:2000])
                sources.append("storyboard_examples")
        
        # 合并知识上下文
        knowledge_context = "\n\n".join(knowledge_parts) if knowledge_parts else ""
        
        return {
            "success": True,
            "shot_description": shot_description,
            "keywords": query_keywords,
            "knowledge_context": knowledge_context,
            "sources": sources
        }
        
    except Exception as e:
        logger.error(f"[Knowledge Tool] 查询视频知识失败: {e}")
        return {
            "success": False,
            "shot_description": shot_description,
            "keywords": query_keywords or [],
            "knowledge_context": "",
            "sources": [],
            "error": str(e)
        }


def _analyze_keywords(shot_description: str) -> List[str]:
    """自动分析分镜描述，提取查询关键词"""
    description = shot_description.lower()
    keywords = []
    
    # 镜头相关
    if any(word in description for word in ["推", "拉", "摇", "移", "跟", "升降", "环绕"]):
        keywords.extend(["镜头", "运镜"])
    
    # 景别相关
    if any(word in description for word in ["特写", "近景", "中景", "全景", "远景"]):
        keywords.extend(["镜头", "景别"])
    
    # 动作相关
    if any(word in description for word in ["打斗", "战斗", "追逐", "奔跑", "跳跃"]):
        keywords.extend(["镜头", "运镜", "动作"])
    
    # 情绪相关
    if any(word in description for word in ["紧张", "恐怖", "温馨", "悲伤", "欢快"]):
        keywords.extend(["光线", "氛围"])
    
    # 转场相关
    if any(word in description for word in ["转场", "切换", "过渡", "衔接"]):
        keywords.extend(["分镜", "转场"])
    
    # 构图相关
    if any(word in description for word in ["对称", "三分", "黄金", "中心", "框架"]):
        keywords.extend(["构图"])
    
    # 如果没有提取到关键词，返回默认关键词
    if not keywords:
        keywords = ["镜头", "构图"]
    
    return list(set(keywords))  # 去重


@tool
async def batch_query_knowledge_for_video(
    keywords_list: List[List[str]],
    top_k: int = 3
) -> Dict[str, Any]:
    """
    批量查询视频生成所需的专业知识（替代多次调用 query_knowledge_for_video）

    一次性传入多组关键词，每组查询 top_k 条结果，最终去重合并返回。

    Args:
        keywords_list: 关键词列表的列表，如 [["运镜", "特写"], ["光线", "氛围"], ["构图", "三分"]]
        top_k: 每组关键词返回的最大结果数（默认3）

    Returns:
        {
            "success": bool,
            "keywords_list": List[List[str]],
            "knowledge_context": str,  # 合并去重的知识上下文
            "sources": List[str]  # 知识来源（去重）
        }
    """
    logger.info(f"[Knowledge Tool] 批量查询视频知识, {len(keywords_list)} 组关键词")

    try:
        all_keywords = set()
        for kw_group in keywords_list:
            if isinstance(kw_group, list):
                all_keywords.update(kw_group)
            elif isinstance(kw_group, str):
                all_keywords.add(kw_group)

        knowledge_parts = []
        sources = []

        # 镜头技巧
        if any(kw in all_keywords for kw in ["镜头", "运镜", "拍摄", "角度", "景别", "特写", "近景", "中景", "全景", "远景", "推", "拉", "摇", "移", "跟", "升降", "环绕", "动作"]):
            camera_tech = read_knowledge_file("director/camera_techniques.md")
            if camera_tech:
                knowledge_parts.append("## 镜头技巧\n" + camera_tech[:2000])
                sources.append("camera_techniques")

        # 构图法则
        if any(kw in all_keywords for kw in ["构图", "画面", "布局", "位置", "对称", "三分", "黄金", "中心", "框架"]):
            composition = read_knowledge_file("director/composition_rules.md")
            if composition:
                knowledge_parts.append("## 构图法则\n" + composition[:2000])
                sources.append("composition_rules")

        # 光线与氛围
        if any(kw in all_keywords for kw in ["光线", "光影", "氛围", "色调", "明暗"]):
            lighting = read_knowledge_file("director/lighting_mood.md")
            if lighting:
                knowledge_parts.append("## 光线与氛围\n" + lighting[:2000])
                sources.append("lighting_mood")

        # 分镜技巧
        if any(kw in all_keywords for kw in ["分镜", "转场", "切换", "连贯", "过渡", "衔接"]):
            storyboard = read_knowledge_file("director/storyboard_examples.md")
            if storyboard:
                knowledge_parts.append("## 分镜技巧\n" + storyboard[:2000])
                sources.append("storyboard_examples")

        knowledge_context = "\n\n".join(knowledge_parts) if knowledge_parts else ""

        logger.info(f"[Knowledge Tool] 批量查询完成, 匹配 {len(sources)} 个知识源")

        return {
            "success": True,
            "keywords_list": keywords_list,
            "knowledge_context": knowledge_context,
            "sources": sources
        }

    except Exception as e:
        logger.error(f"[Knowledge Tool] 批量查询视频知识失败: {e}")
        return {
            "success": False,
            "keywords_list": keywords_list,
            "knowledge_context": "",
            "sources": [],
            "error": str(e)
        }


@tool
async def query_camera_techniques(technique_type: Optional[str] = None) -> Dict[str, Any]:
    """
    查询镜头技巧知识
    
    Args:
        technique_type: 技巧类型（可选）
            - "movement": 镜头运动（推、拉、摇、移等）
            - "angle": 拍摄角度（俯视、仰视等）
            - "shot_size": 景别（特写、全景等）
            
    Returns:
        {
            "success": bool,
            "technique_type": str,
            "content": str
        }
    """
    logger.info(f"[Knowledge Tool] 查询镜头技巧: {technique_type}")
    
    try:
        content = read_knowledge_file("director/camera_techniques.md")
        
        return {
            "success": True,
            "technique_type": technique_type or "all",
            "content": content or ""
        }
        
    except Exception as e:
        return {
            "success": False,
            "technique_type": technique_type,
            "content": "",
            "error": str(e)
        }


@tool
async def query_composition_rules() -> Dict[str, Any]:
    """
    查询构图法则知识
    
    Returns:
        {
            "success": bool,
            "content": str
        }
    """
    logger.info("[Knowledge Tool] 查询构图法则")
    
    try:
        content = read_knowledge_file("director/composition_rules.md")
        
        return {
            "success": True,
            "content": content or ""
        }
        
    except Exception as e:
        return {
            "success": False,
            "content": "",
            "error": str(e)
        }


# ==================== 工具列表导出 ====================

VIDEO_KNOWLEDGE_TOOLS = [
    query_knowledge_for_video,
    batch_query_knowledge_for_video,
    query_camera_techniques,
    query_composition_rules,
]
