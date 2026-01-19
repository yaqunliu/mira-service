from fastapi import APIRouter, Depends, HTTPException
from app.api.deps import get_current_user
from app.models.user import User
from app.services.model_config_service import ModelConfigService
from app.utils.response import success_response

router = APIRouter()


@router.get("/")
async def get_model_configs(
    model_type: str = None,
    user: User = Depends(get_current_user),
):
    """
    获取创作配置列表（模型配置）
    
    用于前端配置界面选择模型和模式。
    
    Args:
        model_type: 模型类型（可选），可选值：llm, text_to_image, image_to_image
                   如果不提供，返回所有类型的模型
    
    Returns:
        创作配置列表，按类型分组
        格式：
        {
            "data": {
                "llm": [...],
                "text_to_image": [...],
                "image_to_image": [...]
            },
            "message": "获取创作配置列表成功"
        }
        或当指定 model_type 时：
        {
            "data": [...],
            "message": "获取创作配置列表成功"
        }
        
        每个模型配置包含：
        - model_name: 模型名称（用于API调用）
        - model_type: 模型类型
        - display_name: 显示名称（用于前端展示）
        - description: 模型描述
        - config: 模型配置（如 max_tokens, aspect_ratio 等）
        - is_enabled: 是否启用
        - is_default: 是否为默认模型
        - sort_order: 排序顺序
    """
    try:
        if model_type:
            # 验证 model_type
            valid_types = ["llm", "text_to_image", "image_to_image", "video"]
            if model_type not in valid_types:
                raise HTTPException(
                    status_code=400,
                    detail=f"model_type 必须是以下值之一: {', '.join(valid_types)}"
                )
            
            models = ModelConfigService.get_models_by_type(model_type)
            models_data = [model.to_dict() for model in models]
            
            return success_response(
                data=models_data,
                message="获取创作配置列表成功"
            )
        else:
            # 返回所有类型的模型（用于前端配置界面）
            all_models = ModelConfigService.get_all_models()
            
            return success_response(
                data=all_models,
                message="获取创作配置列表成功"
            )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"获取模型配置失败: {str(e)}")


@router.get("/default/{model_type}")
async def get_default_model(
    model_type: str,
    user: User = Depends(get_current_user),
):
    """
    获取指定类型的默认模型
    
    用于前端初始化时获取默认模型配置。
    
    Args:
        model_type: 模型类型，可选值：llm, text_to_image, image_to_image
    
    Returns:
        默认模型配置
        格式：
        {
            "data": {
                "model_name": "...",
                "model_type": "...",
                "display_name": "...",
                ...
            },
            "message": "获取默认模型成功"
        }
    """
    try:
        valid_types = ["llm", "text_to_image", "image_to_image", "video"]
        if model_type not in valid_types:
            raise HTTPException(
                status_code=400,
                detail=f"model_type 必须是以下值之一: {', '.join(valid_types)}"
            )
        
        model = ModelConfigService.get_default_model(model_type)
        
        if not model:
            raise HTTPException(
                status_code=404,
                detail=f"未找到 {model_type} 类型的默认模型"
            )
        
        return success_response(
            data=model.to_dict(),
            message="获取默认创作配置成功"
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"获取默认模型失败: {str(e)}")
