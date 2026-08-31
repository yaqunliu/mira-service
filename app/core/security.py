from datetime import datetime, timedelta
from typing import Any, Union
from jose import jwt, JWTError
import bcrypt
from app.core.config import settings
from app.core.jwks import ASYMMETRIC_ALGORITHMS, verify_asymmetric_token


def create_access_token(
    subject: Union[str, Any], expires_delta: timedelta = None
) -> str:
    """创建访问令牌"""
    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(
            minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES
        )
    to_encode = {"exp": expire, "sub": str(subject)}
    encoded_jwt = jwt.encode(
        to_encode, settings.SECRET_KEY, algorithm=settings.ALGORITHM
    )
    return encoded_jwt


def decode_token(token: str) -> dict:
    """
    解码并验证 JWT 令牌

    - ES256 / RS256：走 JWKS 动态公钥（见 app.core.jwks）
    - 其他（默认 HS256）：使用 settings.SECRET_KEY
    """
    if settings.ALGORITHM in ASYMMETRIC_ALGORITHMS:
        payload = verify_asymmetric_token(token)
        if payload is None:
            raise JWTError("非对称签名 Token 验证失败")
        return payload

    return jwt.decode(
        token,
        settings.SECRET_KEY,
        algorithms=[settings.ALGORITHM],
        options={"verify_exp": True}
    )


def get_password_hash(password: str) -> str:
    """获取密码哈希"""
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """验证密码"""
    return bcrypt.checkpw(
        plain_password.encode("utf-8"), hashed_password.encode("utf-8")
    )
