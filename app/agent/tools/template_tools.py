"""
Template Tools - 提示词模板获取工具

提供获取各类提示词生成模板的功能，供 AssetRegeneratorWorker 使用。
所有模板从 app/prompt/ 目录读取。
"""

from typing import Dict, Any, Optional
from langchain_core.tools import tool
from app.core.logger import logger
from app.utils.file_utils import read_prompt_file


@tool
async def get_character_prompt_template(template_type: str = "regenerate") -> Dict[str, Any]:
    """
    获取角色提示词生成模板
    
    用于生成角色图片提示词（四视图布局）。
    
    Args:
        template_type: 模板类型
            - "regenerate": 重新生成模板（默认）
            - "modify": 修改模板
            
    Returns:
        {
            "success": bool,
            "template_type": str,
            "template_content": str,  # 完整的模板内容
            "description": str  # 模板用途说明
        }
    """
    logger.info(f"[Template Tool] 获取角色提示词模板: type={template_type}")
    
    try:
        if template_type == "modify":
            template_content = read_prompt_file("modify_prompt.md")
            description = "角色提示词修改模板，用于基于原提示词进行修改"
        else:
            template_content = read_prompt_file("regenerate_character.md")
            description = "角色提示词重新生成模板，用于生成四视图角色参考图"
        
        if not template_content:
            return {
                "success": False,
                "template_type": template_type,
                "template_content": "",
                "description": "",
                "error": f"无法读取模板文件: regenerate_character.md"
            }
        
        return {
            "success": True,
            "template_type": template_type,
            "template_content": template_content,
            "description": description
        }
        
    except Exception as e:
        logger.error(f"[Template Tool] 获取角色模板失败: {e}")
        return {
            "success": False,
            "template_type": template_type,
            "template_content": "",
            "description": "",
            "error": str(e)
        }


@tool
async def get_scene_prompt_template(template_type: str = "regenerate") -> Dict[str, Any]:
    """
    获取场景提示词生成模板
    
    用于生成场景环境图片提示词（空场景，无人物）。
    
    Args:
        template_type: 模板类型
            - "regenerate": 重新生成模板（默认）
            - "modify": 修改模板
            
    Returns:
        {
            "success": bool,
            "template_type": str,
            "template_content": str,
            "description": str
        }
    """
    logger.info(f"[Template Tool] 获取场景提示词模板: type={template_type}")
    
    try:
        if template_type == "modify":
            template_content = read_prompt_file("modify_prompt.md")
            description = "场景提示词修改模板，用于基于原提示词进行修改"
        else:
            template_content = read_prompt_file("regenerate_scene.md")
            description = "场景提示词重新生成模板，用于生成空场景环境图"
        
        if not template_content:
            return {
                "success": False,
                "template_type": template_type,
                "template_content": "",
                "description": "",
                "error": f"无法读取模板文件: regenerate_scene.md"
            }
        
        return {
            "success": True,
            "template_type": template_type,
            "template_content": template_content,
            "description": description
        }
        
    except Exception as e:
        logger.error(f"[Template Tool] 获取场景模板失败: {e}")
        return {
            "success": False,
            "template_type": template_type,
            "template_content": "",
            "description": "",
            "error": str(e)
        }


@tool
async def get_shot_image_prompt_template(frame_type: str = "start") -> Dict[str, Any]:
    """
    获取分镜图片提示词生成模板
    
    用于生成分镜首帧或尾帧图片提示词。
    
    Args:
        frame_type: 帧类型
            - "start": 首帧提示词模板（默认）
            - "end": 尾帧提示词模板
            - "both": 同时返回首帧和尾帧模板
            
    Returns:
        {
            "success": bool,
            "frame_type": str,
            "template_content": str,  # 或 Dict[str, str] 当 frame_type="both"
            "description": str
        }
    """
    logger.info(f"[Template Tool] 获取分镜图片提示词模板: frame_type={frame_type}")
    
    try:
        if frame_type == "start":
            template_content = read_prompt_file("regenerate_shot_start.md")
            description = "分镜首帧提示词模板，用于生成分镜开始时的画面"
        elif frame_type == "end":
            template_content = read_prompt_file("regenerate_shot_end.md")
            description = "分镜尾帧提示词模板，用于生成分镜结束时的画面"
        elif frame_type == "both":
            start_template = read_prompt_file("regenerate_shot_start.md")
            end_template = read_prompt_file("regenerate_shot_end.md")
            template_content = {
                "start": start_template,
                "end": end_template
            }
            description = "分镜首帧和尾帧提示词模板组合"
        else:
            return {
                "success": False,
                "frame_type": frame_type,
                "template_content": "",
                "description": "",
                "error": f"不支持的帧类型: {frame_type}"
            }
        
        if not template_content:
            return {
                "success": False,
                "frame_type": frame_type,
                "template_content": "",
                "description": "",
                "error": f"无法读取模板文件"
            }
        
        return {
            "success": True,
            "frame_type": frame_type,
            "template_content": template_content,
            "description": description
        }
        
    except Exception as e:
        logger.error(f"[Template Tool] 获取分镜图片模板失败: {e}")
        return {
            "success": False,
            "frame_type": frame_type,
            "template_content": "",
            "description": "",
            "error": str(e)
        }


@tool
async def get_shot_video_prompt_template() -> Dict[str, Any]:
    """
    获取分镜视频提示词生成模板
    
    用于生成分镜视频提示词（三维度时间轴驱动格式：画面+背景音+人物对白）。
    
    Returns:
        {
            "success": bool,
            "template_type": str,
            "template_content": str,
            "description": str
        }
    """
    logger.info("[Template Tool] 获取分镜视频提示词模板")
    
    try:
        template_content = read_prompt_file("regenerate_video.md")
        description = "分镜视频提示词模板，采用三维度时间轴驱动格式（画面+背景音+人物对白）"
        
        if not template_content:
            return {
                "success": False,
                "template_type": "video",
                "template_content": "",
                "description": "",
                "error": "无法读取模板文件: regenerate_video.md"
            }
        
        return {
            "success": True,
            "template_type": "video",
            "template_content": template_content,
            "description": description
        }
        
    except Exception as e:
        logger.error(f"[Template Tool] 获取视频模板失败: {e}")
        return {
            "success": False,
            "template_type": "video",
            "template_content": "",
            "description": "",
            "error": str(e)
        }


@tool
async def get_visual_style_guide() -> Dict[str, Any]:
    """
    获取视觉风格指南
    
    返回当前项目支持的视觉风格列表和描述。
    
    Returns:
        {
            "success": bool,
            "styles": [
                {"name": str, "description": str, "prompt_keyword": str}
            ]
        }
    """
    logger.info("[Template Tool] 获取视觉风格指南")
    
    # 预定义的视觉风格列表
    styles = [
        {
            "name": "日本动漫风格",
            "description": "日式动画风格，线条清晰，色彩鲜明",
            "prompt_keyword": "日本动漫风格，高质量动画"
        },
        {
            "name": "写实风格",
            "description": "真实照片风格，细节丰富",
            "prompt_keyword": "写实风格，照片级质量"
        },
        {
            "name": "赛博朋克风格",
            "description": "未来科技感，霓虹灯光，高科技低生活",
            "prompt_keyword": "赛博朋克风格，霓虹灯光，高科技"
        },
        {
            "name": "水墨风格",
            "description": "中国传统水墨画风格",
            "prompt_keyword": "水墨风格，中国传统绘画"
        },
        {
            "name": "像素风格",
            "description": "复古像素艺术风格",
            "prompt_keyword": "像素艺术风格，复古游戏"
        }
    ]
    
    return {
        "success": True,
        "styles": styles
    }


# ==================== 工具列表导出 ====================

TEMPLATE_TOOLS = [
    get_character_prompt_template,
    get_scene_prompt_template,
    get_shot_image_prompt_template,
    get_shot_video_prompt_template,
    get_visual_style_guide,
]
