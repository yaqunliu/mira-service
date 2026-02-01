#!/usr/bin/env python3
"""
生成测试用的长期 JWT Token
"""

import sys
sys.path.insert(0, 'e:\\code\\mira\\mira-service')

from datetime import datetime, timedelta, timezone
import jwt
from app.core.config import settings

def generate_test_token(user_id: int, email: str = "test@example.com", days: int = 365):
    """生成测试用的 JWT Token"""
    
    now = datetime.now(timezone.utc)
    payload = {
        "iss": "http://127.0.0.1:54321/auth/v1",
        "sub": f"test-user-{user_id}",
        "aud": "authenticated",
        "exp": now + timedelta(days=days),
        "iat": now,
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
    
    # 使用 HS256 算法生成 token
    token = jwt.encode(payload, settings.SECRET_KEY or "test-secret-key-for-development-only", algorithm="HS256")
    return token

if __name__ == "__main__":
    # 为用户 2 生成一个长期有效的 token
    token = generate_test_token(user_id=2, days=365)
    print("生成的测试 Token (有效期1年):")
    print(token)
    print("\n你可以在测试脚本中使用这个 token")
