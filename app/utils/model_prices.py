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
    _video_prices: Optional[Dict] = None
    
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
    def _load_video_prices(cls) -> Dict:
        """加载视频模型价格配置"""
        if cls._video_prices is None:
            try:
                cls._video_prices = json.loads(settings.MODEL_PRICES_VIDEO)
            except Exception as e:
                logger.error(f"解析视频模型价格配置失败: {e}")
                cls._video_prices = {}
        return cls._video_prices
    
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
    def calculate_image_cost(
        cls, 
        model_name: str, 
        image_count: int = 1,
        reference_image_count: int = 0,
        image_size: str = "2K"
    ) -> float:
        """
        计算图片生成成本
        
        Args:
            model_name: 模型名称
            image_count: 输出图片数量
            reference_image_count: 参考图片数量
            image_size: 图片分辨率（1K/2K/4K）
            
        Returns:
            成本（元）
        """
        # 默认使用配置的价格
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

    @classmethod
    def calculate_video_cost(
        cls,
        model_name: str,
        duration_seconds: int,
        resolution: str = "720p"
    ) -> float:
        """
        计算视频生成成本（按秒计费）

        Args:
            model_name: 模型名称
            duration_seconds: 视频时长（秒）
            resolution: 视频分辨率（480p/720p/1080p）

        Returns:
            成本（元）

        价格表（元/秒）:
        - Wan-AI/Wan2.2-I2V: 720p=0.35, 480p=0.18
        - Wan-AI/Wan2.2-T2V: 720p=0.35, 480p=0.18
        - Wan-AI/Wan2.5-I2V: 1080p=1.095, 720p=0.73, 480p=0.365
        - Wan-AI/Wan2.5-T2V: 1080p=1.095, 720p=0.73, 480p=0.365
        - openai/sora-2/text-to-video: 720p=0.71
        - openai/sora-2/text-to-video-pro: 1080p=3.56, 720p=2.14
        - openai/sora-2/image-to-video: 720p=0.71
        - openai/sora-2/image-to-video-pro: 1080p=3.56, 720p=2.14
        """
        prices = cls._load_video_prices()

        # 尝试获取该模型+分辨率的价格配置
        model_config = prices.get(model_name, {})

        # 如果配置是字典（包含分辨率），根据分辨率获取价格
        if isinstance(model_config, dict):
            price_per_second = model_config.get(resolution)

            # 如果没有找到对应分辨率，尝试默认分辨率
            if price_per_second is None:
                if "720p" in model_config:
                    price_per_second = model_config["720p"]
                    logger.warning(f"模型 {model_name} 没有 {resolution} 价格配置，使用 720p: {price_per_second}")
                else:
                    # 使用配置中的第一个价格
                    price_per_second = list(model_config.values())[0] if model_config else None

        # 如果配置是数字（单一价格）
        elif isinstance(model_config, (int, float)):
            price_per_second = model_config

        # 如果配置是字符串，尝试转换
        elif isinstance(model_config, str):
            try:
                price_per_second = float(model_config)
            except (ValueError, TypeError):
                price_per_second = None

        else:
            price_per_second = None

        # 如果还是没有价格，使用默认值
        if price_per_second is None:
            logger.warning(f"未找到模型 {model_name} ({resolution}) 的价格配置，使用默认价格 0.71元/秒")
            price_per_second = 0.71  # Sora2 I2V 720p 默认价格

        # 确保价格是数字类型
        if isinstance(price_per_second, str):
            try:
                price_per_second = float(price_per_second)
            except (ValueError, TypeError):
                logger.warning(f"模型 {model_name} ({resolution}) 的价格配置无效: {price_per_second}，使用默认价格 0.71")
                price_per_second = 0.71

        cost = float(price_per_second) * duration_seconds
        logger.info(f"视频成本计算: {model_name} ({resolution}), {duration_seconds}秒, {price_per_second}元/秒 = {cost}元")
        return round(cost, 6)
