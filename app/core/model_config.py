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
    #
    # 模型 ID 必须与 siray 各模型 OpenAPI spec 里的 enum 完全一致（带厂商前缀），
    # 下面这几个是逐个核对过的。新增前请先看 docs.siray.ai/api-reference/model-api/<模型>.md。
    #
    # 老的 Qwen/* 是接硅基流动时期的配置，在 siray 上不存在，保留但置为
    # is_enabled=False 从下拉框隐藏：用户一旦选中就会写进 creation.extra_data，
    # 覆盖 .env 里的默认模型并让后续所有 AI 步骤 400。
    _LLM_MODELS = [
        ModelConfig(
            model_name="z-ai/glm-5.2",
            model_type="llm",
            display_name="GLM 5.2",
            description="siray 中转 - 智谱 GLM 5.2",
            config={"max_tokens": 32768, "languages": ["zh", "en"]},
            is_enabled=True,
            is_default=True,
            sort_order=1,
        ),
        ModelConfig(
            model_name="deepseek/deepseek-v4-pro",
            model_type="llm",
            display_name="DeepSeek V4 Pro",
            description="siray 中转 - DeepSeek V4 Pro",
            config={"max_tokens": 12288, "languages": ["zh", "en"]},
            is_enabled=True,
            is_default=False,
            sort_order=2,
        ),
        ModelConfig(
            model_name="alibaba/qwen3-max-256k",
            model_type="llm",
            display_name="Qwen3 Max 256K",
            description="siray 中转 - 阿里云 Qwen3 Max 256K",
            config={"max_tokens": 32768, "languages": ["zh", "en"]},
            is_enabled=True,
            is_default=False,
            sort_order=3,
        ),
        ModelConfig(
            model_name="anthropic/claude-opus-4.6",
            model_type="llm",
            display_name="Claude Opus 4.6",
            description="siray 中转 - Anthropic Claude Opus 4.6",
            config={"max_tokens": 32768, "languages": ["zh", "en"]},
            is_enabled=True,
            is_default=False,
            sort_order=4,
        ),
        ModelConfig(
            model_name="Qwen/Qwen-Plus",
            model_type="llm",
            display_name="通义千问 Plus",
            description="阿里云通义千问 Plus 模型",
            config={"max_tokens": 12288, "languages": ["zh"]},
            is_enabled=False,
            is_default=False,
            sort_order=11,
        ),
        ModelConfig(
            model_name="Qwen/QwQ-32B",
            model_type="llm",
            display_name="QwQ 32B",
            description="QwQ 推理模型，输入：2元/百万，输出：6元/百万",
            config={"max_tokens": 8192, "languages": ["zh"]},
            is_enabled=False,
            is_default=False,
            sort_order=12,
        ),
        ModelConfig(
            model_name="Qwen/Qwen3-32B",
            model_type="llm",
            display_name="Qwen3 32B",
            description="Qwen3-32B 密集因果模型，输入：2元/百万，输出：8元/百万",
            config={"max_tokens": 8192, "languages": ["zh"]},
            is_enabled=False,
            is_default=False,
            sort_order=13,
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
    #
    # siray 的图片模型走异步接口（ai_client._call_siray_image_api），模型 ID 同样必须
    # 与其 spec 的 enum 一致。豆包/Gemini 是接火山云时期的配置，改用 siray 后不可用，
    # 同样置为 is_enabled=False 从下拉框隐藏。
    _TEXT_TO_IMAGE_MODELS = [
        ModelConfig(
            model_name="bytedance/seedream-4.5-t2i",
            model_type="text_to_image",
            display_name="Seedream 4.5 文生图",
            description="siray 中转 - 字节跳动 Seedream 4.5 文生图",
            config={"aspect_ratio": "16:9", "languages": ["zh", "en"], "max_words": 300},
            is_enabled=True,
            is_default=True,
            sort_order=1,
        ),
        ModelConfig(
            model_name="alibaba/qwen-image-3-t2i",
            model_type="text_to_image",
            display_name="Qwen Image 3 文生图",
            description="siray 中转 - 阿里 Qwen Image 3 文生图",
            config={"aspect_ratio": "16:9", "languages": ["zh", "en"], "max_words": 300},
            is_enabled=True,
            is_default=False,
            sort_order=2,
        ),
        ModelConfig(
            model_name="gemini-3-pro-image-preview",
            model_type="text_to_image",
            display_name="Gemini 3 Pro Image",
            description="Gemini 3 Pro Image 图像生成模型 (Nano Banana 2)",
            config={"aspect_ratio": "16:9", "languages": ["zh", "en"], "max_words": 300},
            is_enabled=False,
            is_default=False,
            sort_order=12,
        ),
        ModelConfig(
            model_name="doubao-seedream-4.5",
            model_type="text_to_image",
            display_name="豆包 Seedream 4.5",
            description="字节跳动豆包 Seedream 4.5 图像生成模型",
            config={"aspect_ratio": "16:9", "size": "2K", "languages": ["zh", "en"], "max_words": 300},
            is_enabled=False,
            is_default=False,
            sort_order=11,
        ),
        ModelConfig(
            model_name="doubao-seedream-5-0-260128",
            model_type="text_to_image",
            display_name="豆包 Seedream 5.0",
            description="字节跳动豆包 Seedream 5.0 图像生成模型",
            config={"aspect_ratio": "16:9", "size": "2K", "languages": ["zh", "en"], "max_words": 300},
            is_enabled=False,
            is_default=False,
            sort_order=13,
        ),
    ]
    
    # 图生图模型配置
    #
    # 注意：siray 的 i2i 接口只收单张参考图（image 是字符串不是数组），
    # 项目会传多张角色图，适配器只取第一张并打 warning。
    _IMAGE_TO_IMAGE_MODELS = [
        ModelConfig(
            model_name="bytedance/seedream-4.5-i2i",
            model_type="image_to_image",
            display_name="Seedream 4.5 图生图",
            description="siray 中转 - 字节跳动 Seedream 4.5 图生图（单张参考图）",
            config={"aspect_ratio": "16:9", "languages": ["zh", "en"], "max_words": 300},
            is_enabled=True,
            is_default=True,
            sort_order=1,
        ),
        ModelConfig(
            model_name="alibaba/qwen-image-3-edit",
            model_type="image_to_image",
            display_name="Qwen Image 3 图生图",
            description="siray 中转 - 阿里 Qwen Image 3 编辑模型，最多 3 张参考图",
            config={"aspect_ratio": "16:9", "languages": ["zh", "en"], "max_words": 300},
            is_enabled=True,
            is_default=False,
            sort_order=2,
        ),
        ModelConfig(
            model_name="gemini-3-pro-image-preview",
            model_type="image_to_image",
            display_name="Gemini 3 Pro Image",
            description="Gemini 3 Pro Image 图像生成模型 (Nano Banana 2)",
            config={"aspect_ratio": "16:9", "languages": ["zh", "en"], "max_words": 300},
            is_enabled=False,
            is_default=False,
            sort_order=12,
        ),
        ModelConfig(
            model_name="doubao-seedream-4.5",
            model_type="image_to_image",
            display_name="豆包 Seedream 4.5",
            description="字节跳动豆包 Seedream 4.5 图像生成模型，支持单图或多图参考",
            config={"aspect_ratio": "16:9", "size": "2K", "languages": ["zh", "en"], "max_words": 300},
            is_enabled=False,
            is_default=False,
            sort_order=11,
        ),
        ModelConfig(
            model_name="doubao-seedream-5-0-260128",
            model_type="image_to_image",
            display_name="豆包 Seedream 5.0",
            description="字节跳动豆包 Seedream 5.0 图像生成模型，支持单图或多图参考",
            config={"aspect_ratio": "16:9", "size": "2K", "languages": ["zh", "en"], "max_words": 300},
            is_enabled=False,
            is_default=False,
            sort_order=13,
        ),
    ]
    
    # 视频模型配置
    _VIDEO_MODELS = [
        ModelConfig(
            model_name="doubao-seedance-1-5-pro-251215",
            model_type="video",
            display_name="豆包 Seedance 1.5 Pro",
            description="火山引擎豆包图生视频模型，支持音频生成",
            config={
                "aspect_ratio": "16:9",
                "resolutions": ["720p", "1080p"],
                "durations": [4, 5, 6, 7, 8, 9, 10, 11, 12],
                "generation_type": "image_to_video",
            },
            is_enabled=True,
            is_default=True,
            sort_order=1,
        ),
        ModelConfig(
            model_name="sora2",
            model_type="video",
            display_name="Sora",
            description="OpenAI Sora 图生视频模型，支持 4/8/12 秒时长",
            config={
                "aspect_ratio": "16:9",
                "resolutions": ["1080p"],
                "durations": [4, 8, 12],
                "generation_type": "image_to_video",
            },
            is_enabled=True,
            is_default=False,
            sort_order=2,
        ),
        ModelConfig(
            model_name="doubao-seedance-2-0",
            model_type="video",
            display_name="豆包 Seedance 2.0",
            description="火山引擎豆包参考生视频模型，支持角色图+场景图+@引用提示词",
            config={
                "aspect_ratio": "16:9",
                "resolutions": ["720p", "1080p"],
                "durations": [4, 5, 6, 7, 8, 9, 10],
                "generation_type": "reference_to_video",
            },
            is_enabled=True,
            is_default=False,
            sort_order=3,
        ),
        # ModelConfig(
        #     model_name="Wan-AI/Wan2.6-I2V",
        #     model_type="video",
        #     display_name="Wan2.6 图生视频",
        #     description="Wan-AI/Wan2.6-I2V 图生视频模型，支持 720P/1080P",
        #     config={
        #         "aspect_ratio": "16:9",
        #         "resolutions": ["720P", "1080P"],
        #         "durations": [5, 10, 15],
        #         "generation_type": "image_to_video",
        #     },
        #     is_enabled=True,
        #     is_default=False,
        #     sort_order=4,
        # ),
    ]

    @classmethod
    def get_models_by_type(cls, model_type: str, include_disabled: bool = False) -> List[ModelConfig]:
        """
        根据模型类型获取模型列表

        Args:
            model_type: 模型类型（llm, text_to_image, image_to_image, video）
            include_disabled: 是否包含 is_enabled=False 的条目。默认只返回启用的；
                传 True 用于区分「已停用的已知模型」和「配置里没登记过的模型」。

        Returns:
            模型配置列表，按 sort_order 排序
        """
        if model_type == "llm":
            models = cls._LLM_MODELS
        elif model_type == "text_to_image":
            models = cls._TEXT_TO_IMAGE_MODELS
        elif model_type == "image_to_image":
            models = cls._IMAGE_TO_IMAGE_MODELS
        elif model_type == "video":
            models = cls._VIDEO_MODELS
        else:
            return []

        # 过滤启用的模型并按排序顺序返回
        if not include_disabled:
            models = [m for m in models if m.is_enabled]
        return sorted(models, key=lambda x: x.sort_order)
    
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
            "video": [m.to_dict() for m in cls.get_models_by_type("video")],
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
    
    @classmethod
    def get_video_generation_type(cls, model_name: str) -> str:
        """
        获取视频模型的生成类型
        
        Args:
            model_name: 视频模型名称
            
        Returns:
            生成类型: "image_to_video" 或 "reference_to_video"
            默认返回 "image_to_video"
        """
        config = cls.get_model_config(model_name, "video")
        if config:
            return config.get("generation_type", "image_to_video")
        return "image_to_video"

