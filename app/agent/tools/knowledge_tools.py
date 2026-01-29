"""
RAG 知识库 Tools

提供知识库查询功能，支持提示词示例、构图技巧、镜头语言等知识检索
"""

from typing import Dict, Any, List, Optional

from langchain_core.tools import tool
from pydantic import BaseModel, Field

from app.core.logger import logger


# 知识库类型枚举
KNOWLEDGE_BASE_TYPES = {
    "prompt_examples": "图片生成提示词示例库",
    "prompt_techniques": "提示词优化技巧库",
    "storyboard_techniques": "分镜制作技巧库",
    "camera_angles": "镜头语言知识库",
    "composition_rules": "构图规则知识库",
    "character_design": "角色设计知识库",
    "scene_design": "场景设计知识库",
}


@tool
async def query_knowledge_base(
    query: str,
    knowledge_type: str = "prompt_examples",
    top_k: int = 5,
) -> Dict[str, Any]:
    """
    查询知识库获取相关知识
    
    Args:
        query: 查询内容
        knowledge_type: 知识库类型
            - prompt_examples: 图片生成提示词示例
            - prompt_techniques: 提示词优化技巧
            - storyboard_techniques: 分镜制作技巧
            - camera_angles: 镜头语言知识
            - composition_rules: 构图规则
            - character_design: 角色设计
            - scene_design: 场景设计
        top_k: 返回结果数量
        
    Returns:
        相关知识列表
    """
    logger.info(f"[Knowledge Tool] 查询知识库: type={knowledge_type}, query={query[:50]}...")
    
    if knowledge_type not in KNOWLEDGE_BASE_TYPES:
        return {
            "status": "error",
            "error": f"未知的知识库类型: {knowledge_type}",
            "available_types": list(KNOWLEDGE_BASE_TYPES.keys()),
        }
    
    try:
        # 尝试导入向量存储服务
        from app.services.vector_store import VectorStoreService
        
        vector_store = VectorStoreService()
        
        # 查询向量存储
        results = await vector_store.similarity_search(
            collection_name=f"knowledge_{knowledge_type}",
            query=query,
            top_k=top_k,
        )
        
        return {
            "status": "success",
            "knowledge_type": knowledge_type,
            "knowledge_type_desc": KNOWLEDGE_BASE_TYPES[knowledge_type],
            "query": query,
            "results": [
                {
                    "content": r["content"],
                    "metadata": r.get("metadata", {}),
                    "score": r.get("score", 0),
                }
                for r in results
            ],
            "total": len(results),
        }
        
    except ImportError:
        # 向量存储服务未实现，使用模拟数据
        logger.warning("[Knowledge Tool] 向量存储服务未实现，返回模拟数据")
        
        # 模拟知识库数据
        mock_knowledge = _get_mock_knowledge(knowledge_type, query)
        
        return {
            "status": "success",
            "knowledge_type": knowledge_type,
            "knowledge_type_desc": KNOWLEDGE_BASE_TYPES[knowledge_type],
            "query": query,
            "results": mock_knowledge[:top_k],
            "total": len(mock_knowledge[:top_k]),
            "note": "使用模拟数据（向量存储服务未实现）",
        }
        
    except Exception as e:
        logger.error(f"[Knowledge Tool] 知识库查询失败: {e}")
        return {
            "status": "failed",
            "error": str(e),
        }


def _get_mock_knowledge(knowledge_type: str, query: str) -> List[Dict[str, Any]]:
    """获取模拟知识库数据"""
    
    mock_data = {
        "prompt_examples": [
            {
                "content": "A beautiful anime girl with long silver hair, wearing a blue kimono, standing under cherry blossoms, soft pink lighting, detailed illustration, high quality",
                "metadata": {"category": "character", "style": "anime"},
                "score": 0.95,
            },
            {
                "content": "Cyberpunk city at night, neon signs reflecting on wet streets, flying cars in the sky, futuristic architecture, atmospheric fog, cinematic lighting",
                "metadata": {"category": "scene", "style": "cyberpunk"},
                "score": 0.88,
            },
        ],
        "prompt_techniques": [
            {
                "content": "使用具体的形容词描述光线：golden hour lighting, soft diffused light, dramatic backlighting, rim lighting 等",
                "metadata": {"technique": "lighting"},
                "score": 0.92,
            },
            {
                "content": "添加画质关键词提升效果：masterpiece, best quality, highly detailed, 8k resolution, professional photography",
                "metadata": {"technique": "quality"},
                "score": 0.89,
            },
        ],
        "camera_angles": [
            {
                "content": "低角度仰拍（Low Angle）：从下往上拍摄，使主体显得高大威严，常用于表现权威、力量或威胁感",
                "metadata": {"angle": "low_angle", "effect": "power"},
                "score": 0.94,
            },
            {
                "content": "特写镜头（Close-up）：聚焦人物面部或重要细节，强调情感表达和心理状态",
                "metadata": {"angle": "close_up", "effect": "emotion"},
                "score": 0.91,
            },
        ],
        "composition_rules": [
            {
                "content": "三分法则：将画面分成3x3网格，主体放在交叉点或线上，创造平衡又有张力的构图",
                "metadata": {"rule": "rule_of_thirds"},
                "score": 0.96,
            },
            {
                "content": "引导线：使用道路、河流、建筑等线条引导观众视线到主体，增强画面纵深感",
                "metadata": {"rule": "leading_lines"},
                "score": 0.88,
            },
        ],
        "storyboard_techniques": [
            {
                "content": "镜头转场：使用淡入淡出表示时间流逝，使用硬切表示同一时间不同空间",
                "metadata": {"technique": "transition"},
                "score": 0.90,
            },
            {
                "content": "180度规则：保持人物位置关系一致，避免观众产生方向混乱",
                "metadata": {"technique": "180_rule"},
                "score": 0.87,
            },
        ],
        "character_design": [
            {
                "content": "角色剪影识别度：好的角色设计应该在只看轮廓的情况下就能被识别出来",
                "metadata": {"principle": "silhouette"},
                "score": 0.93,
            },
        ],
        "scene_design": [
            {
                "content": "环境叙事：场景设计应该能传达故事信息，如废弃的房间暗示过去的生活痕迹",
                "metadata": {"principle": "environmental_storytelling"},
                "score": 0.91,
            },
        ],
    }
    
    return mock_data.get(knowledge_type, [])


@tool
async def get_prompt_enhancement_suggestions(
    original_prompt: str,
    target_quality: str = "high",
) -> Dict[str, Any]:
    """
    获取提示词增强建议
    
    Args:
        original_prompt: 原始提示词
        target_quality: 目标质量级别（basic/medium/high/ultra）
        
    Returns:
        增强建议和优化后的提示词
    """
    logger.info(f"[Knowledge Tool] 提示词增强: quality={target_quality}")
    
    # 查询提示词技巧知识库
    techniques_result = await query_knowledge_base.ainvoke({
        "query": original_prompt,
        "knowledge_type": "prompt_techniques",
        "top_k": 3,
    })
    
    # 质量增强词
    quality_keywords = {
        "basic": "",
        "medium": "detailed, high quality",
        "high": "masterpiece, best quality, highly detailed, professional",
        "ultra": "masterpiece, best quality, ultra detailed, 8k resolution, professional photography, award winning",
    }
    
    quality_suffix = quality_keywords.get(target_quality, quality_keywords["high"])
    
    # 构建增强提示词
    enhanced_prompt = f"{original_prompt}, {quality_suffix}" if quality_suffix else original_prompt
    
    return {
        "status": "success",
        "original_prompt": original_prompt,
        "enhanced_prompt": enhanced_prompt,
        "target_quality": target_quality,
        "suggestions": [r["content"] for r in techniques_result.get("results", [])],
    }


@tool
async def get_camera_angle_suggestions(
    scene_description: str,
    emotion: str = "neutral",
) -> Dict[str, Any]:
    """
    根据场景和情感获取镜头角度建议
    
    Args:
        scene_description: 场景描述
        emotion: 目标情感（neutral/powerful/intimate/mysterious/tense）
        
    Returns:
        推荐的镜头角度列表
    """
    logger.info(f"[Knowledge Tool] 镜头角度建议: emotion={emotion}")
    
    # 情感到镜头的映射
    emotion_mapping = {
        "powerful": "low angle, hero shot",
        "intimate": "close-up, eye level",
        "mysterious": "dutch angle, silhouette",
        "tense": "extreme close-up, over the shoulder",
        "neutral": "medium shot, eye level",
    }
    
    suggested_angle = emotion_mapping.get(emotion, emotion_mapping["neutral"])
    
    # 查询镜头知识库
    camera_result = await query_knowledge_base.ainvoke({
        "query": f"{scene_description} {emotion}",
        "knowledge_type": "camera_angles",
        "top_k": 3,
    })
    
    return {
        "status": "success",
        "scene_description": scene_description,
        "target_emotion": emotion,
        "primary_suggestion": suggested_angle,
        "knowledge_references": [r["content"] for r in camera_result.get("results", [])],
    }


# 导出所有知识库 Tools
KNOWLEDGE_TOOLS = [
    query_knowledge_base,
    get_prompt_enhancement_suggestions,
    get_camera_angle_suggestions,
]
