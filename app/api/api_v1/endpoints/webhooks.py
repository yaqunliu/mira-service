from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from sqlalchemy.orm import Session
from app.api.deps import get_db
from app.services.webhook_service import WebhookService
from app.core.config import settings
from app.core.logger import logger
import hmac
import hashlib

router = APIRouter()


@router.post("/creem", summary="Creem Webhook 接收")
async def creem_webhook(
    request: Request,
    db: Session = Depends(get_db),
    creem_signature: str | None = Header(None, convert_underscores=False),
):
    payload = await request.json()

    # 可选：签名校验（如果 Creem 提供签名）
    if settings.CREEM_WEBHOOK_SECRET and creem_signature:
        body_bytes = await request.body()
        if not _verify_signature(body_bytes, creem_signature, settings.CREEM_WEBHOOK_SECRET):
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="签名验证失败")

    result = WebhookService.process_event(db, payload)
    return result


def _verify_signature(body: bytes, signature: str, secret: str) -> bool:
    try:
        mac = hmac.new(secret.encode("utf-8"), msg=body, digestmod=hashlib.sha256)
        expected = mac.hexdigest()
        return hmac.compare_digest(expected, signature)
    except Exception as e:
        logger.error(f"Webhook 签名校验异常: {e}")
        return False

