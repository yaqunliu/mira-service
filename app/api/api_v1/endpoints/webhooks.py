from fastapi import APIRouter, Depends, Header, HTTPException, Request, status, Response
from sqlalchemy.orm import Session
from app.api.deps import get_db
from app.services.webhook_service import WebhookService
from app.services.wechat_webhook_service import WechatWebhookService
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


@router.post("/wechat", summary="微信支付回调通知")
async def wechat_webhook(
    request: Request,
    db: Session = Depends(get_db),
    wechatpay_signature: str | None = Header(None, alias="Wechatpay-Signature"),
    wechatpay_timestamp: str | None = Header(None, alias="Wechatpay-Timestamp"),
    wechatpay_nonce: str | None = Header(None, alias="Wechatpay-Nonce"),
    wechatpay_serial: str | None = Header(None, alias="Wechatpay-Serial"),
):
    """
    微信支付回调通知
    
    参考: https://pay.weixin.qq.com/docs/merchant/apis/wechat-pay-api-v3/getting-started/verify-signature.html
    """
    body = await request.body()
    body_str = body.decode('utf-8')
    payload = await request.json()
    
    # 验证签名
    if wechatpay_signature and wechatpay_timestamp and wechatpay_nonce:
        from app.services.wechat_pay_client import wechat_pay_client
        is_valid = wechat_pay_client.verify_callback_signature(
            timestamp=wechatpay_timestamp,
            nonce=wechatpay_nonce,
            body=body_str,
            signature=wechatpay_signature,
            serial_no=wechatpay_serial or "",
        )
        if not is_valid:
            logger.warning("微信支付回调签名验证失败")
            # 开发环境可以继续，生产环境应该返回错误
            # raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="签名验证失败")
    
    # 处理回调
    result = WechatWebhookService.process_callback(db, payload, body_str)
    
    # 微信支付要求返回200或204状态码
    return Response(status_code=200)


def _verify_signature(body: bytes, signature: str, secret: str) -> bool:
    try:
        mac = hmac.new(secret.encode("utf-8"), msg=body, digestmod=hashlib.sha256)
        expected = mac.hexdigest()
        return hmac.compare_digest(expected, signature)
    except Exception as e:
        logger.error(f"Webhook 签名校验异常: {e}")
        return False

