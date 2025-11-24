from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.orm import Session

from app.core.security import verify_password, get_password_hash, create_access_token
from app.db.session import get_db
from app.models.user import User
from app.schemas.user import UserCreate, User, Token
from app.api.deps import get_current_user
from app.utils.response import success_response

router = APIRouter()


@router.post("/register", status_code=status.HTTP_201_CREATED)
async def register(
    user_data: UserCreate,
    db: Session = Depends(get_db)
):
    """用户注册"""
    # 检查用户名是否已存在
    existing_user = db.query(User).filter(User.username == user_data.username).first()
    if existing_user:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="用户名已存在"
        )
    
    # 检查邮箱是否已存在
    existing_email = db.query(User).filter(User.email == user_data.email).first()
    if existing_email:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="邮箱已被注册"
        )
    
    # 创建新用户
    hashed_password = get_password_hash(user_data.password)
    new_user = User(
        username=user_data.username,
        email=user_data.email,
        hashed_password=hashed_password
    )
    
    db.add(new_user)
    db.commit()
    db.refresh(new_user)
    
    return success_response(
        data=User.model_validate(new_user).model_dump(),
        message="用户注册成功"
    )


@router.post("/login")
async def login(
    form_data: OAuth2PasswordRequestForm = Depends(),
    db: Session = Depends(get_db)
):
    """用户登录"""
    # 查找用户（OAuth2PasswordRequestForm 使用 username 字段）
    user = db.query(User).filter(User.username == form_data.username).first()
    
    # 验证用户和密码
    if not user or not verify_password(form_data.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="用户名或密码错误",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    # 创建访问令牌
    access_token = create_access_token(subject=user.username)
    
    return success_response(
        data={
            "access_token": access_token,
            "token_type": "bearer"
        },
        message="登录成功"
    )


@router.post("/refresh")
async def refresh_token(
    current_user: User = Depends(get_current_user)
):
    """刷新访问令牌"""
    # 生成新的访问令牌
    access_token = create_access_token(subject=current_user.username)
    
    return success_response(
        data={
            "access_token": access_token,
            "token_type": "bearer"
        },
        message="令牌刷新成功"
    )
