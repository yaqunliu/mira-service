import json
import hmac
import hashlib
from fastapi import APIRouter, Depends, Header, HTTPException, Request, status, Response
from sqlalchemy.orm import Session
from app.api.deps import get_db
from app.services.webhook_service import WebhookService
from app.services.wechat_webhook_service import WechatWebhookService
from app.core.config import settings
from app.core.logger import logger

router = APIRouter()


@router.post("/creem", summary="Creem Webhook 接收")
async def creem_webhook(
    request: Request,
    db: Session = Depends(get_db),
    creem_signature: str | None = Header(None, convert_underscores=False),
):
    # ========== WEBHOOK 接收日志 ==========
    logger.info("=" * 80)
    logger.info("🔔 [CREEM WEBHOOK] 收到 Creem Webhook 回调")
    logger.info("=" * 80)
    
    # 获取原始请求体
    body_bytes = await request.body()
    body_str = body_bytes.decode('utf-8') if body_bytes else ""
    payload = await request.json()
    
    # 记录请求头信息
    headers_dict = dict(request.headers)
    logger.info(f"📥 [CREEM WEBHOOK] 请求头信息:")
    logger.info(f"   - Signature: {creem_signature}")
    logger.info(f"   - Content-Type: {headers_dict.get('content-type', 'N/A')}")
    logger.info(f"   - User-Agent: {headers_dict.get('user-agent', 'N/A')}")
    logger.info(f"   - 完整请求头: {headers_dict}")
    
    # 记录请求体（原始和解析后的）
    logger.info(f"📦 [CREEM WEBHOOK] 原始请求体 (前1000字符):")
    logger.info(f"   {body_str[:1000]}")
    logger.info(f"📦 [CREEM WEBHOOK] 完整请求体:")
    logger.info(f"   {body_str}")
    logger.info(f"📦 [CREEM WEBHOOK] 解析后的 Payload:")
    logger.info(f"   {json.dumps(payload, indent=2, ensure_ascii=False)}")
    logger.info("=" * 80)

    # 可选：签名校验（如果 Creem 提供签名）
    if settings.CREEM_WEBHOOK_SECRET and creem_signature:
        if not _verify_signature(body_bytes, creem_signature, settings.CREEM_WEBHOOK_SECRET):
            logger.error("❌ [CREEM WEBHOOK] 签名验证失败")
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="签名验证失败")
        logger.info("✅ [CREEM WEBHOOK] 签名验证成功")

    logger.info(f"🔄 [CREEM WEBHOOK] 开始处理事件...")
    result = WebhookService.process_event(db, payload)
    logger.info(f"✅ [CREEM WEBHOOK] 事件处理完成: {result}")
    logger.info("=" * 80)
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
    # ========== WEBHOOK 接收日志 ==========
    logger.info("=" * 80)
    logger.info("🔔 [WECHAT WEBHOOK] 收到微信支付回调通知")
    logger.info("=" * 80)
    
    body = await request.body()
    body_str = body.decode('utf-8')
    payload = await request.json()
    
    # 记录请求头信息
    headers_dict = dict(request.headers)
    logger.info(f"📥 [WECHAT WEBHOOK] 请求头信息:")
    logger.info(f"   - Wechatpay-Signature: {wechatpay_signature}")
    logger.info(f"   - Wechatpay-Timestamp: {wechatpay_timestamp}")
    logger.info(f"   - Wechatpay-Nonce: {wechatpay_nonce}")
    logger.info(f"   - Wechatpay-Serial: {wechatpay_serial}")
    logger.info(f"   - Content-Type: {headers_dict.get('content-type', 'N/A')}")
    logger.info(f"   - User-Agent: {headers_dict.get('user-agent', 'N/A')}")
    logger.info(f"   - 完整请求头: {headers_dict}")
    
    # 记录请求体（原始和解析后的）
    logger.info(f"📦 [WECHAT WEBHOOK] 原始请求体 (前1000字符):")
    logger.info(f"   {body_str[:1000]}")
    logger.info(f"📦 [WECHAT WEBHOOK] 完整请求体:")
    logger.info(f"   {body_str}")
    logger.info(f"📦 [WECHAT WEBHOOK] 解析后的 Payload:")
    logger.info(f"   {json.dumps(payload, indent=2, ensure_ascii=False)}")
    logger.info("=" * 80)
    
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
            logger.error("❌ [WECHAT WEBHOOK] 签名验证失败")
            # 开发环境可以继续，生产环境应该返回错误
            # raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="签名验证失败")
        else:
            logger.info("✅ [WECHAT WEBHOOK] 签名验证成功")
    
    # 处理回调
    logger.info(f"🔄 [WECHAT WEBHOOK] 开始处理回调...")
    result = WechatWebhookService.process_callback(db, payload, body_str)
    logger.info(f"✅ [WECHAT WEBHOOK] 回调处理完成: {result}")
    logger.info("=" * 80)
    
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

