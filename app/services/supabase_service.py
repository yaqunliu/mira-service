import os
from typing import Optional, Dict, Any
from supabase import create_client, Client
from jose import jwt, JWTError
from app.core.config import settings
from app.core.logger import logger
from app.core.jwks import ASYMMETRIC_ALGORITHMS, verify_asymmetric_token


class SupabaseService:
    """Supabase 服务类，用于验证 Supabase JWT token"""
    
    def __init__(self):
        self.supabase_url = settings.SUPABASE_URL
        self.supabase_anon_key = settings.SUPABASE_ANON_KEY
        self.supabase_jwt_secret = settings.SUPABASE_JWT_SECRET
        self.client: Optional[Client] = None
        
        # 记录配置信息（不记录完整 secret）
        # logger.info(f"Supabase 配置: URL={self.supabase_url}, JWT_SECRET 已配置={bool(self.supabase_jwt_secret)}")
        
        if self.supabase_anon_key:
            try:
                self.client = create_client(self.supabase_url, self.supabase_anon_key)
            except Exception as e:
                logger.warning(f"创建 Supabase 客户端失败: {str(e)}")
    
    def verify_token(self, token: str) -> Optional[Dict[str, Any]]:
        """
        验证 Supabase JWT token
        返回解码后的 payload，如果无效则返回 None
        
        自动检测 token 的算法并使用对应的验证方式：
        - ES256 / RS256（Supabase 云项目默认）：从 JWKS 端点动态获取公钥验签，
          只依赖 SUPABASE_URL，不需要 SUPABASE_JWT_SECRET
        - HS256（本地 supabase CLI 或 legacy 共享密钥）：使用 SUPABASE_JWT_SECRET
        """
        try:
            alg = self._get_token_algorithm(token)
            # logger.info(f"检测到 token 算法: {alg}")

            if alg in ASYMMETRIC_ALGORITHMS:
                return verify_asymmetric_token(token)

            if not self.supabase_jwt_secret:
                logger.warning(f"token 使用 {alg} 算法，但未配置 SUPABASE_JWT_SECRET，无法验证")
                logger.warning("本地开发请运行 'supabase status --output json' 获取 JWT_SECRET 值")
                return None

            return self._verify_token_hs256(token)
        except JWTError as e:
            logger.error(f"Token 验证失败: {str(e)}")
            return None
        except Exception as e:
            logger.error(f"验证 token 时发生错误: {str(e)}")
            return None
    
    def _get_token_algorithm(self, token: str) -> str:
        """从 token header 中提取算法"""
        try:
            header = jwt.get_unverified_header(token)
            return header.get("alg", "HS256")
        except Exception:
            return "HS256"
    
    def _verify_token_hs256(self, token: str) -> Optional[Dict[str, Any]]:
        """使用 HS256 验证 JWT token"""
        try:
            unverified_payload = jwt.decode(
                token, 
                key="",
                algorithms=["HS256"],
                options={
                    "verify_signature": False,
                    "verify_aud": False,
                    "verify_exp": False,
                }
            )
            
            import time
            exp = unverified_payload.get('exp')
            if exp and exp < time.time():
                logger.warning(f"Token 已过期: exp={exp}")
                return None
            
            try:
                payload = jwt.decode(
                    token,
                    self.supabase_jwt_secret,
                    algorithms=["HS256"],
                    audience="authenticated"
                )
                return payload
            except JWTError as audience_error:
                try:
                    payload = jwt.decode(
                        token,
                        self.supabase_jwt_secret,
                        algorithms=["HS256"],
                        options={"verify_aud": False}
                    )
                    logger.debug("Token 验证成功（HS256，不带 audience）")
                    return payload
                except JWTError as no_audience_error:
                    logger.error(f"HS256 Token 验证失败: {str(no_audience_error)}")
                    return None
        except Exception as e:
            logger.error(f"HS256 Token 验证错误: {str(e)}")
            return None
    
    def get_user_from_token(self, token: str) -> Optional[Dict[str, Any]]:
        """
        从 token 中获取用户信息
        """
        payload = self.verify_token(token)
        if payload:
            user_metadata = payload.get("user_metadata", {})
            # 从 user_metadata 中提取 avatar_url 或 picture
            avatar_url = user_metadata.get("avatar_url") or user_metadata.get("picture")
            
            # logger.info(f"从 JWT token 提取用户信息: email={payload.get('email')}, avatar_url={avatar_url}")
            # logger.debug(f"User metadata: {user_metadata}")
            
            return {
                "supabase_user_id": payload.get("sub"),
                "email": payload.get("email"),
                "email_verified": payload.get("email_verified", False),
                "user_metadata": user_metadata,
                "avatar_url": avatar_url,  # 添加 avatar_url 字段，方便使用
            }
        return None


supabase_service = SupabaseService()

