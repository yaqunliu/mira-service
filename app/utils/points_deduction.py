"""
积分扣除工具函数
用于在各个业务环节扣除积分
"""
import math
from typing import Optional, Dict, Any
from sqlalchemy.orm import Session
from app.services.points_service import PointsService
from app.utils.model_prices import ModelPrices
from app.core.logger import logger


def deduct_points_for_audio(
    db: Session,
    user_id: int,
    text_bytes: int,
    audio_duration_seconds: float,
    model_name: str,
    creation_id: int,
    novel_id: Optional[int] = None,
    description: Optional[str] = None,
    shot_id: Optional[int] = None  # 新增：用于幂等性检查
) -> bool:
    """
    扣除音频生成积分（按字数/字节数计算成本）
    
    规则：每1元扣除100积分，每1分钱扣除1积分
    
    Args:
        db: 数据库会话
        user_id: 用户ID
        text_bytes: 文本字节数（UTF-8编码）
        audio_duration_seconds: 音频时长（秒）
        model_name: 音频模型名称
        creation_id: 创作ID
        novel_id: 小说ID（可选）
        description: 描述（可选）
        
    Returns:
        是否扣除成功
    """
    try:
        # 计算实际成本（元）
        cost = ModelPrices.calculate_audio_cost(model_name, text_bytes)
        
        # 转换为积分：每1元=100积分，每1分钱=1积分
        # cost * 100 得到积分（元转分，1元=100分=100积分）
        # 使用向上取整，确保小数部分也扣除（如1.1积分扣2积分）
        points = int(math.ceil(cost * 100))
        
        # 确保至少扣除1积分，不能不扣除
        if points <= 0:
            logger.warning(f"音频生成积分计算为0或负数: cost={cost}, points={points}，调整为1积分")
            points = 1
        
        # 生成描述
        if not description:
            description = f"生成音频（{audio_duration_seconds:.1f}秒，{text_bytes}字节，成本{cost:.4f}元）"
        
        # 扣除积分（预扣机制，不检查重复，允许用户重复生成）
        # 注意：虽然传递了 shot_id，但不用于重复检查，因为用户可以重新生成音频
        PointsService.deduct_points(
            db=db,
            user_id=user_id,
            points=points,
            operation_type="generate_audio",
            creation_id=creation_id,
            novel_id=novel_id,
            description=description,
            extra_data={
                "text_bytes": text_bytes,
                "audio_duration_seconds": audio_duration_seconds,
                "model_name": model_name,
                "cost_yuan": cost,
                "points": points,
                "shot_id": shot_id  # 仅用于记录，不用于重复检查
            },
            check_duplicate=False  # 允许重复生成，不检查重复
        )
        
        logger.info(f"用户 {user_id} 音频生成扣除积分: {points} (成本: {cost:.4f}元)")
        return True
        
    except Exception as e:
        logger.error(f"音频生成积分扣除失败: {str(e)}", exc_info=True)
        raise


def deduct_points_for_video(
    db: Session,
    user_id: int,
    model_name: str,
    duration_seconds: int,
    resolution: str = "720p",
    creation_id: Optional[int] = None,
    novel_id: Optional[int] = None,
    description: Optional[str] = None,
    shot_id: Optional[int] = None
) -> bool:
    """
    扣除视频生成积分（按实际成本：模型+时长+分辨率）

    规则：每1元扣除100积分，每1分钱扣除1积分

    Args:
        db: 数据库会话
        user_id: 用户ID
        model_name: 视频模型名称
        duration_seconds: 视频时长（秒）
        resolution: 视频分辨率（480p/720p/1080p）
        creation_id: 创作ID（可选）
        novel_id: 小说ID（可选）
        description: 描述（可选）
        shot_id: 分镜ID（可选，用于记录）

    Returns:
        是否扣除成功
    """
    try:
        # 计算实际成本（元）
        cost = ModelPrices.calculate_video_cost(model_name, duration_seconds, resolution)

        # 转换为积分：每1元=100积分，每1分钱=1积分
        # 使用向上取整，确保小数部分也扣除（如1.1积分扣2积分）
        points = int(math.ceil(cost * 100))

        # 确保至少扣除1积分，不能不扣除
        if points <= 0:
            logger.warning(f"视频生成积分计算为0或负数: cost={cost}, points={points}，调整为1积分")
            points = 1

        # 生成描述
        if not description:
            description = f"生成视频（{duration_seconds}秒，{resolution}，成本{cost:.4f}元）"

        # 扣除积分（预扣机制，不检查重复，允许用户重复生成）
        PointsService.deduct_points(
            db=db,
            user_id=user_id,
            points=points,
            operation_type="generate_video",
            creation_id=creation_id,
            novel_id=novel_id,
            description=description,
            extra_data={
                "model_name": model_name,
                "duration_seconds": duration_seconds,
                "resolution": resolution,
                "cost_yuan": cost,
                "points": points,
                "shot_id": shot_id  # 仅用于记录，不用于重复检查
            },
            check_duplicate=False  # 允许重复生成，不检查重复
        )

        logger.info(f"用户 {user_id} 视频生成扣除积分: {points} (成本: {cost:.4f}元, {duration_seconds}秒, {resolution})")
        return True

    except Exception as e:
        logger.error(f"视频生成积分扣除失败: {str(e)}", exc_info=True)
        raise


def deduct_points_for_image(
    db: Session,
    user_id: int,
    image_count: int,
    model_name: str,
    reference_image_count: int = 0,
    image_size: str = "2K",
    creation_id: Optional[int] = None,
    novel_id: Optional[int] = None,
    description: Optional[str] = None,
    shot_id: Optional[int] = None,  # 用于幂等性检查
    character_id: Optional[int] = None,  # 用于幂等性检查
    scene_id: Optional[int] = None  # 用于幂等性检查
) -> bool:
    """
    扣除图片生成积分（按实际成本）

    规则：每1元扣除100积分，每1分钱扣除1积分

    Args:
        db: 数据库会话
        user_id: 用户ID
        image_count: 图片数量
        model_name: 图片模型名称
        reference_image_count: 参考图片数量（默认0）
        image_size: 图片尺寸（默认2K）
        creation_id: 创作ID（可选）
        novel_id: 小说ID（可选）
        description: 描述（可选）
        shot_id: 分镜ID（可选，用于幂等性检查）
        character_id: 角色ID（可选，用于幂等性检查）
        scene_id: 场景ID（可选，用于幂等性检查）

    Returns:
        是否扣除成功
    """
    try:
        # 计算实际成本（元）
        cost = ModelPrices.calculate_image_cost(
            model_name,
            image_count,
            reference_image_count=reference_image_count,
            image_size=image_size
        )
        
        # 转换为积分：每1元=100积分，每1分钱=1积分
        # 使用向上取整，确保小数部分也扣除（如1.1积分扣2积分）
        points = int(math.ceil(cost * 100))
        
        # 确保至少扣除1积分，不能不扣除
        if points <= 0:
            logger.warning(f"图片生成积分计算为0或负数: cost={cost}, points={points}，调整为1积分")
            points = 1
        
        # 生成描述
        if not description:
            description = f"生成图片（{image_count}张，成本{cost:.4f}元）"
        
        # 确定操作类型
        if creation_id and character_id:
            operation_type = "generate_character"
        elif creation_id and scene_id:
            operation_type = "generate_scene"
        else:
            operation_type = "generate_shot"

        # 扣除积分（预扣机制，带幂等性检查）
        PointsService.deduct_points(
            db=db,
            user_id=user_id,
            points=points,
            operation_type=operation_type,
            creation_id=creation_id,
            novel_id=novel_id,
            description=description,
            extra_data={
                "image_count": image_count,
                "model_name": model_name,
                "cost_yuan": cost,
                "points": points,
                "shot_id": shot_id,  # 用于幂等性检查
                "character_id": character_id,  # 用于幂等性检查
                "scene_id": scene_id  # 用于幂等性检查
            },
            check_duplicate=True  # 启用重复检查
        )
        
        logger.info(f"用户 {user_id} 图片生成扣除积分: {points} (成本: {cost:.4f}元, {image_count}张)")
        return True
        
    except Exception as e:
        logger.error(f"图片生成积分扣除失败: {str(e)}", exc_info=True)
        raise


def deduct_points_for_llm(
    db: Session,
    user_id: int,
    model_name: str,
    prompt_tokens: int,
    completion_tokens: int,
    total_tokens: int,
    creation_id: Optional[int] = None,
    novel_id: Optional[int] = None,
    description: Optional[str] = None
) -> bool:
    """
    扣除LLM调用积分（后扣机制，按实际成本）
    
    规则：每1元扣除100积分，每1分钱扣除1积分，允许负积分
    
    Args:
        db: 数据库会话
        user_id: 用户ID
        model_name: 模型名称
        prompt_tokens: 输入token数
        completion_tokens: 输出token数
        total_tokens: 总token数
        creation_id: 创作ID（可选）
        novel_id: 小说ID（可选）
        description: 描述（可选）
        
    Returns:
        是否扣除成功
    """
    try:
        # 计算实际成本（元）
        cost = ModelPrices.calculate_llm_cost(model_name, prompt_tokens, completion_tokens)
        
        # 转换为积分：每1元=100积分，每1分钱=1积分
        # 使用向上取整，确保小数部分也扣除（如1.1积分扣2积分）
        points = int(math.ceil(cost * 100))
        
        # 确保至少扣除1积分，不能不扣除
        if points <= 0:
            logger.warning(f"LLM调用积分计算为0或负数: cost={cost}, points={points}，调整为1积分")
            points = 1
        
        # 生成描述
        if not description:
            description = f"大模型调用（{model_name}，{total_tokens}tokens）"
        
        # 扣除积分（后扣机制，允许负积分）
        PointsService.deduct_points_after(
            db=db,
            user_id=user_id,
            points=points,
            operation_type="llm_call",
            creation_id=creation_id,
            novel_id=novel_id,
            description=description,
            extra_data={
                "model_name": model_name,
                "prompt_tokens": prompt_tokens,
                "completion_tokens": completion_tokens,
                "total_tokens": total_tokens,
                "cost_yuan": cost,
                "points": points
            }
        )
        
        logger.info(f"用户 {user_id} LLM调用扣除积分: {points} ({total_tokens}tokens)")
        return True
        
    except Exception as e:
        logger.error(f"LLM调用积分扣除失败: {str(e)}", exc_info=True)
        raise
