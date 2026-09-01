from typing import List, Optional, Dict, Any
from app.core.model_config import ModelConfigFactory, ModelConfig
from app.core.logger import logger


class ModelConfigService:
    """模型配置服务类（使用工厂模式）"""

    @staticmethod
    def resolve_model(model_type: str, *candidates: Optional[str]) -> Optional[str]:
        """
        按优先级挑出真正该用的模型名

        各出图任务原本是一串 `A or B or settings.XXX` 的手写兜底，有两个反复踩到的坑：

        1. 兜底链漏掉了 IMAGE_MODEL_TEXT_TO_IMAGE / IMAGE_MODEL_IMAGE_TO_IMAGE，
           直接落到已废弃的 IMAGE_MODEL_NAME（默认值是豆包），导致改 .env 不生效。
        2. creation.extra_data 里存着换供应商之前保存的模型名，优先级最高，
           会把正确配置盖掉——这类记录只能靠改库或重建创作才能清掉。

        这里统一处理：跳过「配置里登记过但已停用」的候选（就是上面第 2 种历史残留），
        保留「配置里没登记过」的候选（可能是只在 .env 里配的自定义模型，不该被吞掉）。

        Args:
            model_type: 模型类型（llm, text_to_image, image_to_image, video）
            *candidates: 按优先级从高到低的候选模型名，允许为 None / 空串

        Returns:
            选中的模型名；所有候选都为空时返回 None
        """
        all_models = ModelConfigFactory.get_models_by_type(model_type, include_disabled=True)
        disabled_names = {m.model_name for m in all_models if not m.is_enabled}

        first_non_empty = None
        for candidate in candidates:
            if not candidate:
                continue
            if first_non_empty is None:
                first_non_empty = candidate
            if candidate in disabled_names:
                logger.warning(
                    f"模型 {candidate}（{model_type}）已在模型配置中停用，跳过该候选。"
                    f"若它来自 creation.extra_data，说明是切换供应商之前的历史残留。"
                )
                continue
            return candidate

        # 所有候选都被停用时，退回优先级最高的那个，避免返回 None 让调用方崩在别处
        if first_non_empty:
            logger.warning(f"{model_type} 的候选模型全部已停用，仍使用: {first_non_empty}")
        return first_non_empty


    @staticmethod
    def get_models_by_type(model_type: str) -> List[ModelConfig]:
        """
        根据模型类型获取启用的模型列表
        
        Args:
            model_type: 模型类型（llm, text_to_image, image_to_image）
            
        Returns:
            模型配置列表，按 sort_order 排序
        """
        return ModelConfigFactory.get_models_by_type(model_type)
    
    @staticmethod
    def get_all_models() -> Dict[str, List[Dict[str, Any]]]:
        """
        获取所有类型的模型列表
        
        Returns:
            按模型类型分组的模型字典
        """
        return ModelConfigFactory.get_all_models()
    
    @staticmethod
    def get_model_by_name(
        model_name: str,
        model_type: str
    ) -> Optional[ModelConfig]:
        """
        根据模型名称和类型获取模型配置
        
        Args:
            model_name: 模型名称
            model_type: 模型类型
            
        Returns:
            模型配置对象，如果不存在则返回 None
        """
        return ModelConfigFactory.get_model_by_name(model_name, model_type)
    
    @staticmethod
    def get_default_model(model_type: str) -> Optional[ModelConfig]:
        """
        获取指定类型的默认模型
        
        Args:
            model_type: 模型类型
            
        Returns:
            默认模型配置对象，如果不存在则返回 None
        """
        return ModelConfigFactory.get_default_model(model_type)
    
    @staticmethod
    def get_model_config(
        model_name: str,
        model_type: str
    ) -> Optional[Dict[str, Any]]:
        """
        获取模型的配置信息（如 aspect_ratio, max_tokens 等）
        
        Args:
            model_name: 模型名称
            model_type: 模型类型
            
        Returns:
            模型配置字典，如果不存在则返回 None
        """
        return ModelConfigFactory.get_model_config(model_name, model_type)

