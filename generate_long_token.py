#!/usr/bin/env python3
"""
生成长期有效的测试 JWT Token
"""

import sys
sys.path.insert(0, 'e:\\code\\mira\\mira-service')

from datetime import datetime, timedelta, timezone

# 手动实现 JWT 生成，不依赖外部库
def base64url_encode(data: bytes) -> str:
    import base64
    return base64.urlsafe_b64encode(data).rstrip(b'=').decode('ascii')

def generate_jwt(payload: dict, secret: str) -> str:
    import hmac
    import hashlib
    import json
    
    # Header
    header = {"alg": "HS256", "typ": "JWT"}
    header_b64 = base64url_encode(json.dumps(header, separators=(',', ':')).encode())
    
    # Payload
    payload_b64 = base64url_encode(json.dumps(payload, separators=(',', ':')).encode())
    
    # Signature
    message = f"{header_b64}.{payload_b64}"
    signature = hmac.new(
        secret.encode(),
        message.encode(),
        hashlib.sha256
    ).digest()
    signature_b64 = base64url_encode(signature)
    
    return f"{message}.{signature_b64}"

def generate_test_token(user_id: int, email: str = "test@example.com", days: int = 365):
    """生成测试用的 JWT Token"""
    
    now = datetime.now(timezone.utc)
    exp = now + timedelta(days=days)
    
    payload = {
        "iss": "http://127.0.0.1:54321/auth/v1",
        "sub": f"test-user-{user_id}",
        "aud": "authenticated",
        "exp": int(exp.timestamp()),
        "iat": int(now.timestamp()),
        "email": email,
        "phone": "",
        "app_metadata": {
            "provider": "email",
            "providers": ["email"]
        },
        "user_metadata": {
            "email": email,
            "email_verified": True,
            "full_name": "Test User",
            "name": "Test User"
        },
        "role": "authenticated",
        "aal": "aal1",
        "amr": [{"method": "password", "timestamp": int(now.timestamp())}],
        "session_id": f"test-session-{user_id}",
        "is_anonymous": False
    }
    
    # 使用简单的 secret
    secret = "test-secret-key-for-development-only-2026"
    token = generate_jwt(payload, secret)
    return token

if __name__ == "__main__":
    # 为用户 2 生成一个长期有效的 token
    token = generate_test_token(user_id=2, days=365)
    print("=" * 60)
    print("生成的测试 Token (有效期1年):")
    print("=" * 60)
    print(token)
    print("\n" + "=" * 60)
    print("使用方式:")
    print("python test_agent_voice.py <上面的token>")
    print("=" * 60)
