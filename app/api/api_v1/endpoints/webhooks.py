import json
import hmac
import hashlib
from fastapi import APIRouter, Depends, Header, HTTPException, Request, Response
from sqlalchemy.ext.asyncio import AsyncSession
from app.api.deps import get_async_db
from app.services.webhook_service import WebhookService
from app.services.wechat_webhook_service import WechatWebhookService
from app.core.config import settings
from app.core.logger import logger

router = APIRouter()


@router.post("/creem", summary="Creem Webhook 接收")
async def creem_webhook(
    request: Request,
    db: AsyncSession = Depends(get_async_db),
    creem_signature: str | None = Header(None, convert_underscores=False),
):
    logger.info("=" * 80)
    logger.info("🔔 [CREEM WEBHOOK] 收到 Creem Webhook 回调")
    logger.info("=" * 80)
    
    body_bytes = await request.body()
    body_str = body_bytes.decode('utf-8') if body_bytes else ""
    payload = await request.json()
    
    headers_dict = dict(request.headers)
    logger.info(f"📥 [CREEM WEBHOOK] 请求头信息:")
    logger.info(f"   - Signature: {creem_signature}")
    logger.info(f"   - Content-Type: {headers_dict.get('content-type', 'N/A')}")
    logger.info(f"   - User-Agent: {headers_dict.get('user-agent', 'N/A')}")
    logger.info(f"   - 完整请求头: {headers_dict}")
    
    logger.info(f"📦 [CREEM WEBHOOK] 原始请求体 (前1000字符):")
    logger.info(f"   {body_str[:1000]}")
    logger.info(f"📦 [CREEM WEBHOOK] 完整请求体:")
    logger.info(f"   {body_str}")
    logger.info(f"📦 [CREEM WEBHOOK] 解析后的 Payload:")
    logger.info(f"   {json.dumps(payload, indent=2, ensure_ascii=False)}")
    logger.info("=" * 80)

    if settings.CREEM_WEBHOOK_SECRET and creem_signature:
        if not _verify_signature(body_bytes, creem_signature, settings.CREEM_WEBHOOK_SECRET):
            logger.error("❌ [CREEM WEBHOOK] 签名验证失败")
            raise HTTPException(status_code=401, detail="签名验证失败")
        logger.info("✅ [CREEM WEBHOOK] 签名验证成功")

    logger.info(f"🔄 [CREEM WEBHOOK] 开始处理事件...")
    result = await db.run_sync(lambda sync_session: WebhookService.process_event(sync_session, payload))
    logger.info(f"✅ [CREEM WEBHOOK] 事件处理完成: {result}")
    logger.info("=" * 80)
    return result


@router.post("/wechat", summary="微信支付回调通知")
async def wechat_webhook(
    request: Request,
    db: AsyncSession = Depends(get_async_db),
    wechatpay_signature: str | None = Header(None, alias="Wechatpay-Signature"),
    wechatpay_timestamp: str | None = Header(None, alias="Wechatpay-Timestamp"),
    wechatpay_nonce: str | None = Header(None, alias="Wechatpay-Nonce"),
    wechatpay_serial: str | None = Header(None, alias="Wechatpay-Serial"),
):
    logger.info("=" * 80)
    logger.info("🔔 [WECHAT WEBHOOK] 收到微信支付回调通知")
    logger.info("=" * 80)
    
    body = await request.body()
    body_str = body.decode('utf-8')
    payload = await request.json()
    
    headers_dict = dict(request.headers)
    logger.info(f"📥 [WECHAT WEBHOOK] 请求头信息:")
    logger.info(f"   - Wechatpay-Signature: {wechatpay_signature}")
    logger.info(f"   - Wechatpay-Timestamp: {wechatpay_timestamp}")
    logger.info(f"   - Wechatpay-Nonce: {wechatpay_nonce}")
    logger.info(f"   - Wechatpay-Serial: {wechatpay_serial}")
    logger.info(f"   - Content-Type: {headers_dict.get('content-type', 'N/A')}")
    logger.info(f"   - User-Agent: {headers_dict.get('user-agent', 'N/A')}")
    logger.info(f"   - 完整请求头: {headers_dict}")
    
    logger.info(f"📦 [WECHAT WEBHOOK] 原始请求体 (前1000字符):")
    logger.info(f"   {body_str[:1000]}")
    logger.info(f"📦 [WECHAT WEBHOOK] 完整请求体:")
    logger.info(f"   {body_str}")
    logger.info(f"📦 [WECHAT WEBHOOK] 解析后的 Payload:")
    logger.info(f"   {json.dumps(payload, indent=2, ensure_ascii=False)}")
    logger.info("=" * 80)
    
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
            logger.error("❌ [WECHAT WEBHOOK] 签名验证失败")
        else:
            logger.info("✅ [WECHAT WEBHOOK] 签名验证成功")
    
    logger.info(f"🔄 [WECHAT WEBHOOK] 开始处理回调...")
    result = await db.run_sync(lambda sync_session: WechatWebhookService.process_callback(sync_session, payload, body_str))
    logger.info(f"✅ [WECHAT WEBHOOK] 回调处理完成: {result}")
    logger.info("=" * 80)
    
    return Response(status_code=200)


def _verify_signature(body: bytes, signature: str, secret: str) -> bool:
    try:
        mac = hmac.new(secret.encode("utf-8"), msg=body, digestmod=hashlib.sha256)
        expected = mac.hexdigest()
        return hmac.compare_digest(expected, signature)
    except Exception as e:
        logger.error(f"Webhook 签名校验异常: {e}")
        return False
