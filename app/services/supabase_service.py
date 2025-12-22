import os
from typing import Optional, Dict, Any
from supabase import create_client, Client
from jose import jwt, JWTError
from app.core.config import settings
from app.core.logger import logger


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
        
        注意：Supabase 在签发 token 时使用的是它内部的 JWT secret（自动生成或配置的）
        后端验证时需要知道这个相同的 secret 才能验证 token 的签名
        """
        try:
            if not self.supabase_jwt_secret:
                logger.warning("未配置 SUPABASE_JWT_SECRET，无法验证 token")
                logger.warning("请运行 'supabase status --output json' 获取 JWT_SECRET 值")
                return None
            
            # 先尝试解码 token（不验证签名和 audience）以获取信息用于调试
            try:
                # jose 库的 decode 需要 key 参数，即使不验证签名也需要提供
                # 需要同时禁用签名验证和 audience 验证
                unverified_payload = jwt.decode(
                    token, 
                    key="",  # 空 key，配合 options 不验证签名
                    algorithms=["HS256"],
                    options={
                        "verify_signature": False,
                        "verify_aud": False,  # 不验证 audience
                        "verify_exp": False,   # 不验证过期时间（先获取信息）
                    }
                )
                # logger.info(f"Token payload (未验证签名): aud={unverified_payload.get('aud')}, sub={unverified_payload.get('sub')}, exp={unverified_payload.get('exp')}, iss={unverified_payload.get('iss')}")
                # 检查 token 是否过期
                import time
                exp = unverified_payload.get('exp')
                if exp and exp < time.time():
                    logger.warning(f"Token 已过期: exp={exp}, current={time.time()}")
                    return None
            except Exception as e:
                logger.warning(f"无法解码 token: {str(e)}")
                return None
            
            # 验证并解码 token
            # Supabase 的 JWT token 通常 audience 是 "authenticated"
            # 先尝试带 audience 验证
            try:
                payload = jwt.decode(
                    token,
                    self.supabase_jwt_secret,
                    algorithms=["HS256"],
                    audience="authenticated"
                )
                # logger.info("Token 验证成功（带 audience）")
                return payload
            except JWTError as audience_error:
                # 如果带 audience 验证失败，尝试不带 audience 验证
                # logger.warning(f"带 audience 验证失败: {str(audience_error)}")
                # logger.warning(f"尝试不带 audience 验证...")
                try:
                    payload = jwt.decode(
                        token,
                        self.supabase_jwt_secret,
                        algorithms=["HS256"],
                        options={"verify_aud": False}
                    )
                    logger.info("Token 验证成功（不带 audience）")
                    return payload
                except JWTError as no_audience_error:
                    logger.error(f"Token 验证失败（不带 audience）: {str(no_audience_error)}")
                    logger.error(f"JWT_SECRET 配置可能不正确，当前值前20字符: {self.supabase_jwt_secret[:20]}...")
                    logger.error("请确认 SUPABASE_JWT_SECRET 与 Supabase 的 JWT_SECRET 一致")
                    return None
        except JWTError as e:
            logger.error(f"Token 验证失败: {str(e)}")
            return None
        except Exception as e:
            logger.error(f"验证 token 时发生错误: {str(e)}")
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

