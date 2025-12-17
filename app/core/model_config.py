"""
模型配置工厂类
使用工厂模式管理所有模型配置，包括LLM、文生图、图生图模型
"""
from typing import Dict, List, Optional, Any
from dataclasses import dataclass


@dataclass
class ModelConfig:
    """模型配置数据类"""
    model_name: str
    model_type: str  # llm, text_to_image, image_to_image
    display_name: str
    description: str = ""
    config: Dict[str, Any] = None
    is_enabled: bool = True
    is_default: bool = False
    sort_order: int = 0
    
    def __post_init__(self):
        if self.config is None:
            self.config = {}
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "model_name": self.model_name,
            "model_type": self.model_type,
            "display_name": self.display_name,
            "description": self.description,
            "config": self.config,
            "is_enabled": self.is_enabled,
            "is_default": self.is_default,
            "sort_order": self.sort_order,
        }


class ModelConfigFactory:
    """模型配置工厂类"""
    
    # LLM 模型配置
    _LLM_MODELS = [
        ModelConfig(
            model_name="Qwen/Qwen-Plus",
            model_type="llm",
            display_name="通义千问 Plus",
            description="阿里云通义千问 Plus 模型",
            config={"max_tokens": 12288, "languages": ["zh"]},
            is_enabled=True,
            is_default=True,
            sort_order=1,
        ),
        ModelConfig(
            model_name="Qwen/QwQ-32B",
            model_type="llm",
            display_name="QwQ 32B",
            description="QwQ 推理模型，输入：2元/百万，输出：6元/百万",
            config={"max_tokens": 8192, "languages": ["zh"]},
            is_enabled=True,
            is_default=False,
            sort_order=2,
        ),
        ModelConfig(
            model_name="Qwen/Qwen3-32B",
            model_type="llm",
            display_name="Qwen3 32B",
            description="Qwen3-32B 密集因果模型，输入：2元/百万，输出：8元/百万",
            config={"max_tokens": 8192, "languages": ["zh"]},
            is_enabled=True,
            is_default=False,
            sort_order=3,
        ),
        # ModelConfig(
        #     model_name="moonshotai/Kimi-K2-Thinking",
        #     model_type="llm",
        #     display_name="Kimi K2 Thinking",
        #     description="Kimi 思考模型，输入：4元/百万，输出：16元/百万",
        #     config={"max_tokens": 12288, "languages": ["zh"]},
        #     is_enabled=True,
        #     is_default=False,
        #     sort_order=4,
        # ),
        # ModelConfig(
        #     model_name="moonshotai/Kimi-K2-Instruct-0905",
        #     model_type="llm",
        #     display_name="Kimi K2",
        #     description="Moonshot AI Kimi K2 模型",
        #     config={"max_tokens": 8192},
        #     is_enabled=True,
        #     is_default=False,
        #     sort_order=2,
        # ),
        # ModelConfig(
        #     model_name="deepseek-ai/DeepSeek-V3.2",
        #     model_type="llm",
        #     display_name="DeepSeek V3.2",
        #     description="DeepSeek V3.2 模型",
        #     config={"max_tokens": 16384},
        #     is_enabled=True,
        #     is_default=False,
        #     sort_order=3,
        # ),
    ]
    
    # 文生图模型配置
    _TEXT_TO_IMAGE_MODELS = [
        ModelConfig(
            model_name="Qwen/Qwen-Image",
            model_type="text_to_image",
            display_name="通义千问图像生成",
            description="阿里云通义千问图像生成模型",
            config={"aspect_ratio": "1024x576", "languages": ["zh"], "max_words": 150},
            is_enabled=True,
            is_default=True,
            sort_order=1,
        ),
        # ModelConfig(
        #     model_name="black-forest-labs/flux-kontext-pro/multi",
        #     model_type="text_to_image",
        #     display_name="Flux Kontext Pro",
        #     description="Black Forest Labs Flux Kontext Pro 模型",
        #     config={"aspect_ratio": "16:9", "languages": ["en"]},
        #     is_enabled=True,
        #     is_default=False,
        #     sort_order=2,
        # ),
    ]
    
    # 图生图模型配置
    _IMAGE_TO_IMAGE_MODELS = [
        ModelConfig(
            model_name="gemini-3-pro-image-preview",
            model_type="image_to_image",
            display_name="Nano Banana2 (图生图)",
            description="Gemini 3 Pro Image (Nano Banana2) 图生图模型，支持中文提示词",
            config={"aspect_ratio": "16:9", "image_size": "1K", "languages": ["zh"], "max_words": 300},
            is_enabled=True,
            is_default=True,
            sort_order=1,
        ),
        ModelConfig(
            model_name="black-forest-labs/flux-kontext-pro/multi",
            model_type="image_to_image",
            display_name="Flux Kontext Pro (图生图)",
            description="Black Forest Labs Flux Kontext Pro 图生图模型",
            config={"aspect_ratio": "16:9", "guidance_scale": 3.5, "languages": ["en"], "max_words": 150},
            is_enabled=True,
            is_default=False,
            sort_order=2,
        ),
    ]
    
    @classmethod
    def get_models_by_type(cls, model_type: str) -> List[ModelConfig]:
        """
        根据模型类型获取启用的模型列表
        
        Args:
            model_type: 模型类型（llm, text_to_image, image_to_image）
            
        Returns:
            模型配置列表，按 sort_order 排序
        """
        if model_type == "llm":
            models = cls._LLM_MODELS
        elif model_type == "text_to_image":
            models = cls._TEXT_TO_IMAGE_MODELS
        elif model_type == "image_to_image":
            models = cls._IMAGE_TO_IMAGE_MODELS
        else:
            return []
        
        # 过滤启用的模型并按排序顺序返回
        enabled_models = [m for m in models if m.is_enabled]
        return sorted(enabled_models, key=lambda x: x.sort_order)
    
    @classmethod
    def get_all_models(cls) -> Dict[str, List[Dict[str, Any]]]:
        """
        获取所有类型的模型列表
        
        Returns:
            按模型类型分组的模型字典
        """
        return {
            "llm": [m.to_dict() for m in cls.get_models_by_type("llm")],
            "text_to_image": [m.to_dict() for m in cls.get_models_by_type("text_to_image")],
            "image_to_image": [m.to_dict() for m in cls.get_models_by_type("image_to_image")],
        }
    
    @classmethod
    def get_model_by_name(cls, model_name: str, model_type: str) -> Optional[ModelConfig]:
        """
        根据模型名称和类型获取模型配置
        
        Args:
            model_name: 模型名称
            model_type: 模型类型
            
        Returns:
            模型配置对象，如果不存在则返回 None
        """
        models = cls.get_models_by_type(model_type)
        for model in models:
            if model.model_name == model_name:
                return model
        return None
    
    @classmethod
    def get_default_model(cls, model_type: str) -> Optional[ModelConfig]:
        """
        获取指定类型的默认模型
        
        Args:
            model_type: 模型类型
            
        Returns:
            默认模型配置对象，如果不存在则返回 None
        """
        models = cls.get_models_by_type(model_type)
        # 优先返回标记为默认的模型
        for model in models:
            if model.is_default:
                return model
        # 如果没有默认模型，返回第一个
        return models[0] if models else None
    
    @classmethod
    def get_model_config(cls, model_name: str, model_type: str) -> Optional[Dict[str, Any]]:
        """
        获取模型的配置信息（如 aspect_ratio, max_tokens 等）
        
        Args:
            model_name: 模型名称
            model_type: 模型类型
            
        Returns:
            模型配置字典，如果不存在则返回 None
        """
        model = cls.get_model_by_name(model_name, model_type)
        if not model:
            return None
        return model.config or {}

