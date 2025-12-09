from typing import List, Optional, Dict, Any
from app.core.model_config import ModelConfigFactory, ModelConfig
from app.core.logger import logger


class ModelConfigService:
    """模型配置服务类（使用工厂模式）"""
    
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

