"""
提示词加载器

加载和渲染提示词模板文件
"""

import yaml
from pathlib import Path
from typing import Dict, Any, Optional
from jinja2 import Template

PROMPTS_DIR = Path(__file__).parent


def load_prompt(name: str) -> Dict[str, Any]:
    """
    加载提示词文件
    
    Args:
        name: 提示词文件名（不含扩展名）
        
    Returns:
        {
            "metadata": {...},  # YAML 头部配置
            "template": "..."   # Jinja2 模板内容
        }
        
    Example:
        prompt_data = load_prompt("intent_detection")
        # prompt_data["metadata"]["model"] -> "gpt-4o-mini"
        # prompt_data["template"] -> "# 意图识别\n..."
    """
    file_path = PROMPTS_DIR / f"{name}.md"
    
    if not file_path.exists():
        raise FileNotFoundError(f"提示词文件不存在: {file_path}")
    
    content = file_path.read_text(encoding="utf-8")
    
    # 解析 YAML 头部（--- 包裹的部分）
    if content.startswith("---"):
        parts = content.split("---", 2)
        if len(parts) >= 3:
            metadata = yaml.safe_load(parts[1]) or {}
            template = parts[2].strip()
        else:
            metadata = {}
            template = content
    else:
        metadata = {}
        template = content
    
    return {"metadata": metadata, "template": template}


def format_prompt(prompt_data: Dict[str, Any], context: Dict[str, Any]) -> str:
    """
    使用上下文填充提示词模板
    
    Args:
        prompt_data: load_prompt 返回的数据
        context: 模板变量字典
        
    Returns:
        渲染后的提示词字符串
        
    Example:
        prompt_data = load_prompt("intent_detection")
        filled = format_prompt(prompt_data, {
            "user_message": "帮我生成角色图片",
            "chat_history": [...],
            "current_stage": "asset_generation"
        })
    """
    template = Template(prompt_data["template"])
    return template.render(**context)


def get_prompt_config(prompt_data: Dict[str, Any], key: str, default: Any = None) -> Any:
    """
    获取提示词配置项
    
    Args:
        prompt_data: load_prompt 返回的数据
        key: 配置键名
        default: 默认值
        
    Returns:
        配置值
        
    Example:
        prompt_data = load_prompt("intent_detection")
        model = get_prompt_config(prompt_data, "model", "gpt-4o-mini")
        temperature = get_prompt_config(prompt_data, "temperature", 0.7)
    """
    return prompt_data.get("metadata", {}).get(key, default)


def load_and_format(name: str, context: Dict[str, Any]) -> str:
    """
    便捷函数：加载并填充提示词
    
    Args:
        name: 提示词文件名
        context: 模板变量字典
        
    Returns:
        渲染后的提示词字符串
    """
    prompt_data = load_prompt(name)
    return format_prompt(prompt_data, context)
