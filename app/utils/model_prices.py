"""
模型价格配置工具
用于计算AI模型调用的实际成本
"""
import json
from typing import Dict, Optional
from app.core.config import settings
from app.core.logger import logger


class ModelPrices:
    """模型价格配置管理器"""
    
    _llm_prices: Optional[Dict] = None
    _image_prices: Optional[Dict] = None
    _audio_prices: Optional[Dict] = None
    
    @classmethod
    def _load_llm_prices(cls) -> Dict:
        """加载LLM模型价格配置"""
        if cls._llm_prices is None:
            try:
                cls._llm_prices = json.loads(settings.MODEL_PRICES_LLM)
            except Exception as e:
                logger.error(f"解析LLM模型价格配置失败: {e}")
                cls._llm_prices = {}
        return cls._llm_prices
    
    @classmethod
    def _load_image_prices(cls) -> Dict:
        """加载图片模型价格配置"""
        if cls._image_prices is None:
            try:
                cls._image_prices = json.loads(settings.MODEL_PRICES_IMAGE)
            except Exception as e:
                logger.error(f"解析图片模型价格配置失败: {e}")
                cls._image_prices = {}
        return cls._image_prices
    
    @classmethod
    def _load_audio_prices(cls) -> Dict:
        """加载音频模型价格配置"""
        if cls._audio_prices is None:
            try:
                cls._audio_prices = json.loads(settings.MODEL_PRICES_AUDIO)
            except Exception as e:
                logger.error(f"解析音频模型价格配置失败: {e}")
                cls._audio_prices = {}
        return cls._audio_prices
    
    @classmethod
    def calculate_llm_cost(
        cls,
        model_name: str,
        prompt_tokens: int,
        completion_tokens: int
    ) -> float:
        """
        计算LLM调用成本
        
        Args:
            model_name: 模型名称
            prompt_tokens: 输入token数
            completion_tokens: 输出token数
            
        Returns:
            成本（元）
        """
        prices = cls._load_llm_prices()
        model_config = prices.get(model_name)
        
        if not model_config:
            logger.warning(f"未找到模型 {model_name} 的价格配置，使用默认价格")
            # 默认价格：输入0.8元/百万tokens，输出2.0元/百万tokens
            input_price = 0.8 / 1_000_000
            output_price = 2.0 / 1_000_000
        else:
            # 确保价格是数字类型（如果配置中是字符串，转换为float）
            input_price_raw = model_config.get("input", 0.8)
            output_price_raw = model_config.get("output", 2.0)
            
            if isinstance(input_price_raw, str):
                try:
                    input_price_raw = float(input_price_raw)
                except (ValueError, TypeError):
                    logger.warning(f"模型 {model_name} 的输入价格配置无效: {input_price_raw}，使用默认价格 0.8")
                    input_price_raw = 0.8
            
            if isinstance(output_price_raw, str):
                try:
                    output_price_raw = float(output_price_raw)
                except (ValueError, TypeError):
                    logger.warning(f"模型 {model_name} 的输出价格配置无效: {output_price_raw}，使用默认价格 2.0")
                    output_price_raw = 2.0
            
            input_price = float(input_price_raw) / 1_000_000
            output_price = float(output_price_raw) / 1_000_000
        
        cost = (prompt_tokens * input_price) + (completion_tokens * output_price)
        return round(cost, 6)  # 保留6位小数
    
    @classmethod
    def calculate_image_cost(cls, model_name: str, image_count: int = 1) -> float:
        """
        计算图片生成成本
        
        Args:
            model_name: 模型名称
            image_count: 图片数量
            
        Returns:
            成本（元）
        """
        prices = cls._load_image_prices()
        price_per_image = prices.get(model_name, 0.35)  # 默认0.35元/张
        
        # 确保价格是数字类型（如果配置中是字符串，转换为float）
        if isinstance(price_per_image, str):
            try:
                price_per_image = float(price_per_image)
            except (ValueError, TypeError):
                logger.warning(f"模型 {model_name} 的价格配置无效: {price_per_image}，使用默认价格 0.35")
                price_per_image = 0.35
        elif not isinstance(price_per_image, (int, float)):
            logger.warning(f"模型 {model_name} 的价格配置类型错误: {type(price_per_image)}，使用默认价格 0.35")
            price_per_image = 0.35
        
        cost = float(price_per_image) * image_count
        return round(cost, 6)
    
    @classmethod
    def calculate_audio_cost(cls, model_name: str, text_bytes: int) -> float:
        """
        计算音频生成成本（按文本字节数）
        
        Args:
            model_name: 模型名称
            text_bytes: 文本字节数（UTF-8编码）
            
        Returns:
            成本（元）
        """
        prices = cls._load_audio_prices()
        price_per_mb = prices.get(model_name, 120)  # 默认120元/兆字节
        
        # 确保价格是数字类型（如果配置中是字符串，转换为float）
        if isinstance(price_per_mb, str):
            try:
                price_per_mb = float(price_per_mb)
            except (ValueError, TypeError):
                logger.warning(f"模型 {model_name} 的价格配置无效: {price_per_mb}，使用默认价格 120")
                price_per_mb = 120
        elif not isinstance(price_per_mb, (int, float)):
            logger.warning(f"模型 {model_name} 的价格配置类型错误: {type(price_per_mb)}，使用默认价格 120")
            price_per_mb = 120
        
        # 转换为兆字节
        text_mb = text_bytes / (1024 * 1024)
        cost = float(price_per_mb) * text_mb
        return round(cost, 6)
