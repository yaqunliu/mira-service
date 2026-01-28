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
    """
    if model_type:
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
        all_models = ModelConfigService.get_all_models()
        
        return success_response(
            data=all_models,
            message="获取创作配置列表成功"
        )


@router.get("/default/{model_type}")
async def get_default_model(
    model_type: str,
    user: User = Depends(get_current_user),
):
    """
    获取指定类型的默认模型
    """
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
