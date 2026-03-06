"""
视觉风格配置

定义 visual_style key 到风格描述的映射
用于将 creation.extra_data.visual_style 转换为提示词中使用的风格描述
"""

from typing import Dict, Optional

# visual_style key 到风格描述的映射
VISUAL_STYLE_MAP: Dict[str, str] = {
    # 动漫风格
    "anime": "anime style, japanese animation, cel shading, vibrant colors, clean lines, high quality anime art",
    
    # 写实风格
    "realism": "photorealistic, realistic, natural lighting, detailed textures, professional photography, lifelike",
    
    # 赛博朋克
    "cyberpunk": "cyberpunk style, neon lights, futuristic, high tech low life, rain, reflections, glowing neon signs",
    
    # 浮世绘
    "ukiyoe": "ukiyo-e style, japanese woodblock print, flat colors, traditional japanese art, hokusai style, bold outlines",
    
    # 水彩
    "watercolor": "watercolor painting, soft colors, translucent, flowing brushstrokes, delicate, artistic",
    
    # 赛璐璐
    "cel_shading": "cel shading style, anime cel, flat colors with sharp shadows, cartoon style, clean black outlines",
    
    # 油画
    "oil_painting": "oil painting, rich colors, thick brushstrokes, classical art style, textured canvas",
    
    # 素描
    "sketch": "pencil sketch, monochrome, line drawing, hand drawn, graphite texture",
    
    # 3D渲染
    "3d_render": "3D render, CG art, digital sculpture, volumetric lighting, ray tracing, blender style",
    
    # 像素
    "pixel": "pixel art, retro game style, 8-bit, 16-bit, low resolution, dithering",
}

# 中文风格描述（用于日志或展示）
VISUAL_STYLE_NAME_MAP: Dict[str, str] = {
    "anime": "日本动漫风格",
    "realism": "写实风格",
    "cyberpunk": "赛博朋克风格",
    "ukiyoe": "浮世绘风格",
    "watercolor": "水彩风格",
    "cel_shading": "赛璐璐风格",
    "oil_painting": "油画风格",
    "sketch": "素描风格",
    "3d_render": "3D渲染风格",
    "pixel": "像素风格",
}


def get_visual_style_description(visual_style_key: str) -> str:
    """
    获取视觉风格的英文描述（用于提示词）
    
    Args:
        visual_style_key: 风格 key，如 "anime", "realism"
        
    Returns:
        风格描述字符串
    """
    return VISUAL_STYLE_MAP.get(visual_style_key, VISUAL_STYLE_MAP["anime"])


def get_visual_style_name(visual_style_key: str) -> str:
    """
    获取视觉风格的中文名称（用于日志）
    
    Args:
        visual_style_key: 风格 key
        
    Returns:
        中文风格名称
    """
    return VISUAL_STYLE_NAME_MAP.get(visual_style_key, "日本动漫风格")


def get_all_visual_styles() -> Dict[str, Dict[str, str]]:
    """
    获取所有风格信息
    
    Returns:
        包含所有风格信息的字典
    """
    return {
        key: {
            "key": key,
            "name": VISUAL_STYLE_NAME_MAP.get(key, key),
            "description": desc,
        }
        for key, desc in VISUAL_STYLE_MAP.items()
    }
