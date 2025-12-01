"""
积分配置解析工具
用于解析和计算积分消耗
"""
from typing import Dict, Optional
from app.core.config import settings
from app.core.logger import logger


class PointsConfig:
    """积分配置解析器"""
    
    # 操作类型到配置的映射
    _config_map = {
        "create_creation": settings.POINTS_CREATE_CREATION,
        "generate_character": settings.POINTS_GENERATE_CHARACTER,
        "generate_shot": settings.POINTS_GENERATE_SHOT,
        "generate_audio": settings.POINTS_GENERATE_AUDIO,
        "generate_video": settings.POINTS_GENERATE_VIDEO,
        "upload_novel": settings.POINTS_UPLOAD_NOVEL,
        "llm_call": settings.POINTS_LLM_CALL,
    }
    
    @staticmethod
    def parse_config(config_str: str) -> Dict[str, any]:
        """
        解析配置字符串：operation_type:计费方式:数值
        
        Args:
            config_str: 配置字符串，如 "generate_audio:per_second:1"
            
        Returns:
            解析后的配置字典
        """
        try:
            parts = config_str.split(":")
            if len(parts) != 3:
                raise ValueError(f"配置格式错误: {config_str}")
            
            return {
                "operation_type": parts[0],
                "billing_type": parts[1],
                "value": float(parts[2])
            }
        except Exception as e:
            logger.error(f"解析积分配置失败: {config_str}, 错误: {str(e)}")
            raise ValueError(f"配置解析失败: {config_str}")
    
    @staticmethod
    def get_config(operation_type: str) -> Dict[str, any]:
        """
        获取操作类型的配置
        
        Args:
            operation_type: 操作类型
            
        Returns:
            配置字典
        """
        config_str = PointsConfig._config_map.get(operation_type)
        if not config_str:
            raise ValueError(f"未找到操作类型 {operation_type} 的配置")
        
        return PointsConfig.parse_config(config_str)
    
    @staticmethod
    def calculate_points(
        operation_type: str,
        units: int = 1,
        seconds: float = 0,
        words: int = 0,
        cost: float = 0
    ) -> int:
        """
        根据操作类型和参数计算积分消耗
        
        Args:
            operation_type: 操作类型
            units: 单位数量（用于 per_unit）
            seconds: 秒数（用于 per_second）
            words: 字数（用于 per_word）
            cost: 成本（元，用于 per_cost）
            
        Returns:
            积分消耗数量（整数）
        """
        try:
            config = PointsConfig.get_config(operation_type)
            billing_type = config["billing_type"]
            value = config["value"]
            
            if billing_type == "per_unit":
                points = value * units
            elif billing_type == "per_second":
                points = value * seconds
            elif billing_type == "per_word":
                # 按千字计算
                points = value * (words / 1000.0)
            elif billing_type == "per_cost":
                # 成本转换为积分：1元 = value积分
                points = value * cost
            else:
                raise ValueError(f"不支持的计费方式: {billing_type}")
            
            # 返回整数，向上取整
            return int(points) if points >= 0 else int(points)
            
        except Exception as e:
            logger.error(f"计算积分消耗失败: operation_type={operation_type}, 错误: {str(e)}")
            raise ValueError(f"计算积分消耗失败: {str(e)}")
