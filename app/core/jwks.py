"""
Supabase JWT 非对称签名验证（JWKS）

背景：
    Supabase 新版项目默认使用非对称密钥（ECC P-256 / RSA）签发 JWT。
    此前代码把某个项目的 EC 公钥硬编码在源码里，一旦更换 Supabase 项目
    或密钥轮换，验签就会全部失败。

本模块从 Supabase 的 JWKS 端点动态获取签名公钥：

    {SUPABASE_URL}/auth/v1/.well-known/jwks.json

并按 token header 中的 kid 匹配对应公钥。PyJWKClient 会在本地缓存密钥，
且在 kid 未命中时自动重新拉取一次，因此密钥轮换无需重启服务。

注意：本模块使 settings.SUPABASE_URL 成为必须正确配置的项
（在此之前它并未被真正使用过）。
"""
import threading
from typing import Any, Dict, List, Optional

import jwt as pyjwt
from jwt import PyJWKClient

from app.core.config import settings
from app.core.logger import logger

# Supabase JWT signing keys 支持 ECC (P-256) 与 RSA 两种非对称算法
ASYMMETRIC_ALGORITHMS: List[str] = ["ES256", "RS256"]

# JWKS 本地缓存生命周期（秒）。密钥轮换时 kid 未命中会立即触发刷新，
# 因此这里可以设置得比较宽松。
_JWKS_CACHE_LIFESPAN = 3600

# 拉取 JWKS 的超时（秒）。验签发生在同步上下文中，超时不宜过长。
_JWKS_TIMEOUT = 5

_client: Optional[PyJWKClient] = None
_client_url: Optional[str] = None
_lock = threading.Lock()


def get_jwks_url() -> str:
    """由 SUPABASE_URL 推导 JWKS 端点地址"""
    base = (settings.SUPABASE_URL or "").rstrip("/")
    return f"{base}/auth/v1/.well-known/jwks.json"


def get_jwks_client() -> PyJWKClient:
    """
    惰性创建并复用 PyJWKClient（进程内单例，线程安全）

    Celery prefork worker 与 uvicorn 多 worker 下每个进程各持一份缓存，
    这是预期行为。
    """
    global _client, _client_url

    url = get_jwks_url()
    with _lock:
        if _client is None or _client_url != url:
            _client = PyJWKClient(
                url,
                cache_keys=True,
                lifespan=_JWKS_CACHE_LIFESPAN,
                timeout=_JWKS_TIMEOUT,
            )
            _client_url = url
            logger.info(f"初始化 Supabase JWKS 客户端: {url}")
        return _client


def reset_jwks_client() -> None:
    """清空缓存的客户端（供测试或配置热更新使用）"""
    global _client, _client_url
    with _lock:
        _client = None
        _client_url = None


def verify_asymmetric_token(token: str) -> Optional[Dict[str, Any]]:
    """
    使用 JWKS 公钥验证非对称签名的 JWT（ES256 / RS256）

    Returns:
        验证通过返回 payload；任何失败均返回 None（与 HS256 分支行为一致）
    """
    try:
        signing_key = get_jwks_client().get_signing_key_from_jwt(token)
    except Exception as e:
        # 拉取 JWKS 失败、kid 不存在、网络超时等
        logger.error(
            f"获取 Supabase JWKS 签名公钥失败: {str(e)} "
            f"(JWKS 地址: {get_jwks_url()}，请确认 SUPABASE_URL 配置正确)"
        )
        return None

    try:
        payload = pyjwt.decode(
            token,
            signing_key.key,
            algorithms=ASYMMETRIC_ALGORITHMS,
            options={
                "verify_exp": True,
                "verify_aud": False,
            },
        )
        logger.debug("Token 验证成功（JWKS 非对称签名）")
        return payload
    except Exception as e:
        logger.error(f"非对称签名 Token 验证失败: {str(e)}")
        return None
