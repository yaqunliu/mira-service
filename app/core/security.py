from datetime import datetime, timedelta
from typing import Any, Union
from jose import jwt
import bcrypt
import base64
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.backends import default_backend
from app.core.config import settings


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
    """解码并验证 JWT 令牌，支持 HS256 和 ES256"""
    if settings.ALGORITHM == "ES256":
        return _decode_es256(token)
    else:
        return jwt.decode(
            token,
            settings.SECRET_KEY,
            algorithms=[settings.ALGORITHM],
            options={"verify_exp": True}
        )


def _decode_es256(token: str) -> dict:
    """使用 ES256 (ECDSA P-256) 解码 JWT"""
    public_key = _get_supabase_ec_public_key()
    
    return jwt.decode(
        token,
        public_key,
        algorithms=["ES256"],
        options={"verify_exp": True}
    )


def _get_supabase_ec_public_key():
    """获取 Supabase 的 EC P-256 公钥用于 ES256 验证
    
    JWK 格式的坐标是 Base64URL 编码的，需要正确解码
    """
    x_b64url = "M5Sjqn5zwC9Kl1zVfUUGvv9boQjCGd45G8sdopBExB4"
    y_b64url = "P6IXMvA2WYXSHSOMTBH2jsw_9rrzGy89FjPf6oOsIxQ"
    
    x_bytes = base64.urlsafe_b64decode(x_b64url + "==")
    y_bytes = base64.urlsafe_b64decode(y_b64url + "==")
    
    uncompressed_point = b"\x04" + x_bytes + y_bytes
    
    public_key = ec.EllipticCurvePublicKey.from_encoded_point(
        ec.SECP256R1(),
        uncompressed_point
    )
    
    return public_key


def get_password_hash(password: str) -> str:
    """获取密码哈希"""
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """验证密码"""
    return bcrypt.checkpw(
        plain_password.encode("utf-8"), hashed_password.encode("utf-8")
    )
