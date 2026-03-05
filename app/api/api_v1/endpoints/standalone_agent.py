"""
独立创作 Agent API

用于创建不依赖于小说/章节的独立内容
"""

from typing import List, Optional
from pydantic import BaseModel, Field
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.db.session import get_async_db
from app.agent.services.standalone_intent_service import standalone_intent_service
from app.agent.triggers.vocab_trigger import trigger_vocab_creation
from app.models.user import User
from app.core.logger import logger

router = APIRouter()


class IntentRequest(BaseModel):
    """意图识别请求"""
    message: str = Field(..., description="用户消息")
    chat_history: Optional[List[dict]] = Field(default=None, description="对话历史")


class IntentResponse(BaseModel):
    """意图识别响应"""
    intent: str = Field(..., description="识别的意图")
    intent_category: str = Field(..., description="意图类别")
    confidence: float = Field(..., description="置信度")
    can_proceed: bool = Field(..., description="是否可以继续")
    redirect_to_legacy: bool = Field(default=False, description="是否需要跳转到旧页面")
    legacy_url: str = Field(default="", description="旧页面URL")
    extracted_params: dict = Field(default_factory=dict, description="提取的参数")
    missing_required: List[str] = Field(default_factory=list, description="缺失的必填参数")
    missing_optional: List[str] = Field(default_factory=list, description="缺失的可选参数")
    details: dict = Field(default_factory=dict, description="详细信息")


class CreateTaskRequest(BaseModel):
    """创建任务请求"""
    intent: str = Field(..., description="意图类型")
    params: dict = Field(..., description="任务参数")


class CreateTaskResponse(BaseModel):
    """创建任务响应"""
    creation_id: str = Field(..., description="创作ID")
    redirect_url: str = Field(..., description="跳转URL")
    message: str = Field(..., description="消息")


@router.post("/intent", response_model=IntentResponse)
async def recognize_intent(
    request: IntentRequest,
    current_user: User = Depends(get_current_user),
):
    """
    识别用户意图和提取参数
    
    用于 Agent Creator 页面，识别用户想要创建的独立内容类型
    """
    logger.info(f"[Standalone API] 意图识别请求: {request.message[:100]}...")
    
    try:
        result = await standalone_intent_service.detect_intent(
            message=request.message,
            chat_history=request.chat_history
        )
        
        return IntentResponse(
            intent=result.intent,
            intent_category=result.intent_category,
            confidence=result.confidence,
            can_proceed=result.can_proceed,
            redirect_to_legacy=result.redirect_to_legacy,
            legacy_url=result.legacy_url,
            extracted_params=result.extracted_params,
            missing_required=result.missing_required,
            missing_optional=result.missing_optional,
            details=result.details
        )
        
    except Exception as e:
        logger.error(f"[Standalone API] 意图识别失败: {e}")
        raise HTTPException(status_code=500, detail=f"意图识别失败: {str(e)}")


@router.post("/create", response_model=CreateTaskResponse)
async def create_agent_task(
    request: CreateTaskRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_db),
):
    """
    根据意图创建任务
    
    根据识别的意图和参数，创建对应的创作任务
    """
    logger.info(f"[Standalone API] 创建任务: intent={request.intent}, params={request.params}")
    
    try:
        if request.intent == "create_vocab_video":
            # 创建单词视频任务
            params = request.params
            
            # 构建 vocab 配置
            vocab_config = {
                "words": params.get("words", []),
                "difficulty": params.get("difficulty", "easy"),
                "sentence_level": params.get("sentence_level", "simple"),
                "repetitions": params.get("repetitions", 2),
                "style": params.get("style", "anime"),
            }
            
            # 触发 vocab 创建
            creation = await trigger_vocab_creation(
                db=db,
                user_id=current_user.user_id,
                config=vocab_config
            )
            
            return CreateTaskResponse(
                creation_id=creation.uuid,
                redirect_url=f"/create-agent?creationId={creation.uuid}",
                message="单词视频创作任务已创建"
            )
            
        else:
            raise HTTPException(status_code=400, detail=f"不支持的意图类型: {request.intent}")
            
    except Exception as e:
        logger.error(f"[Standalone API] 创建任务失败: {e}")
        raise HTTPException(status_code=500, detail=f"创建任务失败: {str(e)}")
