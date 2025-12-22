"""
微信支付客户端
支持Native支付和订阅支付（支付中签约）
"""
import httpx
import json
import base64
import hashlib
import hmac
import time
import uuid
from typing import Any, Dict, Optional
from cryptography.hazmat.primitives import serialization, hashes
from cryptography.hazmat.primitives.asymmetric import padding
from cryptography import x509
from app.core.config import settings
from app.core.logger import logger


class WechatPayClient:
    """微信支付客户端"""
    
    def __init__(
        self,
        appid: str = settings.WECHAT_APPID,
        mchid: str = settings.WECHAT_MCHID,
        api_v3_key: str = settings.WECHAT_API_V3_KEY,
        cert_serial_no: str = settings.WECHAT_CERT_SERIAL_NO,
        private_key_path: str = settings.WECHAT_PRIVATE_KEY_PATH,
        cert_path: str = settings.WECHAT_CERT_PATH,
        base_url: str = settings.WECHAT_API_BASE_URL,
        use_sandbox: bool = settings.WECHAT_USE_SANDBOX,
        timeout: int = settings.WECHAT_TIMEOUT,
        max_retries: int = settings.WECHAT_MAX_RETRIES,
        retry_delay: int = settings.WECHAT_RETRY_DELAY,
    ):
        self.appid = appid
        self.mchid = mchid
        self.api_v3_key = api_v3_key
        self.cert_serial_no = cert_serial_no
        self.base_url = base_url.rstrip("/")
        self.use_sandbox = use_sandbox
        self.timeout = timeout
        self.max_retries = max_retries
        self.retry_delay = retry_delay
        
        # 加载私钥
        self.private_key = None
        if private_key_path:
            try:
                with open(private_key_path, 'rb') as f:
                    self.private_key = serialization.load_pem_private_key(
                        f.read(),
                        password=None,
                    )
            except Exception as e:
                logger.warning(f"加载微信支付私钥失败: {e}")
        else:
            logger.warning("微信支付私钥路径未配置")
        
        # 加载平台证书(用于回调签名验证，可选)
        # 注意：API请求签名只需要私钥(apiclient_key.pem)，不需要证书
        # 平台证书用于验证微信支付回调通知的签名
        self.platform_cert = None
        if cert_path:
            try:
                with open(cert_path, 'rb') as f:
                    self.platform_cert = x509.load_pem_x509_certificate(f.read())
                logger.info("微信支付平台证书加载成功（用于回调签名验证）")
            except Exception as e:
                logger.warning(f"加载微信支付平台证书失败: {e}，回调签名验证将被跳过")
        else:
            logger.warning("微信支付平台证书路径未配置，回调签名验证将被跳过（开发环境可接受）")
    
    def _generate_signature(
        self,
        method: str,
        url: str,
        timestamp: str,
        nonce: str,
        body: str = "",
    ) -> str:
        """
        生成微信支付签名
        参考: https://pay.weixin.qq.com/docs/merchant/apis/wechat-pay-api-v3/getting-started/request-signature.html
        """
        if not self.private_key:
            raise ValueError("私钥未配置,无法生成签名")
        
        # 构建签名字符串
        sign_str = f"{method}\n{url}\n{timestamp}\n{nonce}\n{body}\n"
        
        # 使用私钥签名
        signature = self.private_key.sign(
            sign_str.encode('utf-8'),
            padding.PKCS1v15(),
            hashes.SHA256()
        )
        
        # Base64编码
        return base64.b64encode(signature).decode('utf-8')
    
    def _get_authorization(
        self,
        method: str,
        url: str,
        body: str = "",
    ) -> str:
        """生成Authorization请求头"""
        timestamp = str(int(time.time()))
        nonce = str(uuid.uuid4()).replace('-', '')
        
        signature = self._generate_signature(method, url, timestamp, nonce, body)
        
        # 构建Authorization字符串
        auth_str = (
            f'WECHATPAY2-SHA256-RSA2048 '
            f'mchid="{self.mchid}",'
            f'nonce_str="{nonce}",'
            f'signature="{signature}",'
            f'timestamp="{timestamp}",'
            f'serial_no="{self.cert_serial_no}"'
        )
        
        return auth_str
    
    def _convert_path_for_sandbox(self, path: str) -> str:
        """
        将API路径转换为仿真系统路径
        
        注意：
        - 微信支付V3 API没有沙箱环境，所有V3 API路径直接返回，不进行转换
        - 仿真系统（/xdc/apiv2sandbox/）仅支持V2 API格式
        - use_sandbox参数对V3 API无效，仅保留用于向后兼容
        
        如果未来需要使用V2 API的仿真系统，可以在这里添加V2 API路径的转换逻辑
        """
        # V3 API没有沙箱环境，直接返回原路径
        if path.startswith("/v3/"):
            if self.use_sandbox:
                logger.warning(
                    f"微信支付V3 API不支持沙箱环境，use_sandbox参数将被忽略。"
                    f"路径: {path}"
                )
            return path
        
        # 如果未启用沙箱，直接返回
        if not self.use_sandbox:
            return path
        
        # 这里可以添加V2 API的沙箱路径转换逻辑（如果需要）
        # 目前V3 API不支持沙箱，所以不会走到这里
        logger.warning(f"未知的API路径格式，未进行沙箱转换: {path}")
        return path
    
    def _request(
        self,
        method: str,
        path: str,
        json_data: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        发送HTTP请求（带重试机制）
        
        注意：微信支付V3 API没有沙箱环境，所有V3 API请求都直接发送到生产环境
        """
        # V3 API不支持沙箱，直接使用原路径
        actual_path = self._convert_path_for_sandbox(path)
        url = f"{self.base_url}{actual_path}"
        logger.info(f"微信支付API {method.upper()} {url}")
        body = json.dumps(json_data, separators=(',', ':')) if json_data else ""
        
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": "Mira-Payment-System/1.0",
        }
        
        # 添加Authorization
        auth = self._get_authorization(method, path, body)
        headers["Authorization"] = auth
        
        logger.info(f"微信支付API {method.upper()} {url}")
        
        # Debug 模式下记录请求详情
        if settings.DEBUG:
            logger.debug(f"[DEBUG] 微信支付API 请求详情:")
            logger.debug(f"  URL: {url}")
            logger.debug(f"  Method: {method.upper()}")
            logger.debug(f"  Path: {path}")
            logger.debug(f"  Actual Path (sandbox): {actual_path}")
            logger.debug(f"  Headers: {dict(headers)}")
            # 记录Authorization头（隐藏签名值）
            auth_parts = auth.split('signature="')
            if len(auth_parts) > 1:
                signature_part = auth_parts[1].split('"')[0]
                masked_auth = auth.replace(signature_part, signature_part[:20] + "..." if len(signature_part) > 20 else "***")
                logger.debug(f"  Authorization (masked): {masked_auth}")
            else:
                logger.debug(f"  Authorization: {auth}")
            if json_data:
                logger.debug(f"  Payload: {json_data}")
            logger.debug(f"  Body (raw): {body}")
        
        # 配置超时：分别设置连接超时和读取超时
        # connect: 连接超时（建立连接的时间）
        # read: 读取超时（等待响应的时间）
        timeout_config = httpx.Timeout(
            connect=10.0,  # 连接超时10秒
            read=self.timeout,  # 读取超时使用配置的值（默认60秒）
            write=10.0,  # 写入超时10秒
            pool=10.0,  # 连接池超时10秒
        )
        
        last_error = None
        for attempt in range(self.max_retries + 1):
            try:
                with httpx.Client(timeout=timeout_config) as client:
                    resp = client.request(method, url, headers=headers, content=body)
                    
                    # 记录响应原始内容（用于调试）
                    response_text = resp.text
                    response_status = resp.status_code
                    response_headers = dict(resp.headers)
                    
                    logger.info(f"微信支付API响应: status={response_status}, url={url}")
                    # 始终记录响应状态和基本信息
                    logger.debug(f"[DEBUG] 微信支付API 响应原始内容:")
                    logger.debug(f"  URL: {url}")
                    logger.debug(f"  Status: {response_status}")
                    logger.debug(f"  Headers: {response_headers}")
                    logger.debug(f"  Response Text (前500字符): {response_text[:500] if response_text else '(empty)'}")
                    logger.debug(f"  Response Text (完整): {response_text if response_text else '(empty)'}")
                    logger.debug(f"  Response Content Length: {len(response_text) if response_text else 0}")
                    # 如果响应不是200，或者响应为空，记录警告
                    if response_status != 200:
                        logger.warning(f"微信支付API返回非200状态: status={response_status}, response_text={response_text[:200]}")
                    if not response_text or len(response_text.strip()) == 0:
                        logger.warning(f"微信支付API响应为空: status={response_status}, url={url}")
                    
                    try:
                        resp.raise_for_status()
                    except httpx.HTTPStatusError as e:
                        error_detail = None
                        try:
                            error_detail = resp.json()
                        except Exception as json_err:
                            error_detail = {
                                "error": "无法解析JSON响应",
                                "raw_response": response_text[:1000],  # 限制长度
                                "json_error": str(json_err)
                            }
                        logger.error(f"微信支付API错误: {e.response.status_code} - {error_detail} | url={url}")
                        logger.error(f"微信支付API错误 - 完整响应: {response_text}")
                        raise
                    
                    # 尝试解析JSON响应
                    try:
                        response_data = resp.json()
                        logger.debug(f"[DEBUG] 微信支付API 响应JSON解析成功:")
                        logger.debug(f"  URL: {url}")
                        logger.debug(f"  Status: {response_status}")
                        logger.debug(f"  Response: {response_data}")
                        return response_data
                    except Exception as json_err:
                        # JSON解析失败，记录详细信息（始终记录，不只在DEBUG模式）
                        logger.error(f"微信支付API响应JSON解析失败: {json_err}")
                        logger.error(f"  URL: {url}")
                        logger.error(f"  Method: {method.upper()}")
                        logger.error(f"  Status: {response_status}")
                        logger.error(f"  Response Headers: {response_headers}")
                        logger.error(f"  Response Text (完整): {response_text if response_text else '(empty)'}")
                        logger.error(f"  Response Text (长度): {len(response_text) if response_text else 0}")
                        logger.error(f"  Response Content (bytes, 前500字节): {resp.content[:500] if resp.content else b'(empty)'}")
                        logger.error(f"  Response Content (bytes, hex, 前100字节): {resp.content[:100].hex() if resp.content else '(empty)'}")
                        # 尝试检测响应内容类型
                        content_type = response_headers.get('content-type', 'unknown')
                        logger.error(f"  Content-Type: {content_type}")
                        raise ValueError(
                            f"无法解析微信支付API响应为JSON: {json_err}, "
                            f"status={response_status}, "
                            f"content_type={content_type}, "
                            f"response_text={response_text[:500] if response_text else '(empty)'}"
                        )
            
            except (httpx.TimeoutException, httpx.ReadTimeout, httpx.ConnectTimeout) as e:
                last_error = e
                if attempt < self.max_retries:
                    wait_time = self.retry_delay * (attempt + 1)  # 指数退避
                    logger.warning(
                        f"微信支付API请求超时 (尝试 {attempt + 1}/{self.max_retries + 1}): "
                        f"url={url}, error={str(e)}, {wait_time}秒后重试"
                    )
                    time.sleep(wait_time)
                else:
                    logger.error(
                        f"微信支付API请求超时，已重试 {self.max_retries} 次: "
                        f"url={url}, error={str(e)}, timeout={self.timeout}秒"
                    )
                    raise
            
            except httpx.HTTPStatusError as e:
                # HTTP状态错误（如4xx, 5xx）不重试，直接抛出
                raise
            
            except Exception as e:
                last_error = e
                if attempt < self.max_retries:
                    wait_time = self.retry_delay * (attempt + 1)
                    logger.warning(
                        f"微信支付API请求失败 (尝试 {attempt + 1}/{self.max_retries + 1}): "
                        f"url={url}, error={str(e)}, {wait_time}秒后重试"
                    )
                    time.sleep(wait_time)
                else:
                    logger.error(
                        f"微信支付API请求失败，已重试 {self.max_retries} 次: "
                        f"url={url}, error={str(e)}"
                    )
                    raise
        
        # 如果所有重试都失败，抛出最后一个错误
        if last_error:
            raise last_error
    
    def create_native_order(
        self,
        description: str,
        out_trade_no: str,
        amount: int,  # 金额(分)
        notify_url: str,
        currency: str = "CNY",
        time_expire: Optional[str] = None,
        attach: Optional[str] = None,
        goods_detail: Optional[list] = None,
    ) -> Dict[str, Any]:
        """
        创建Native支付订单
        参考: https://pay.weixin.qq.com/docs/merchant/apis/native-payment/native-prepay.html
        """
        payload = {
            "appid": self.appid,
            "mchid": self.mchid,
            "description": description,
            "out_trade_no": out_trade_no,
            "notify_url": notify_url,
            "amount": {
                "total": amount,
                "currency": currency,
            },
        }
        logger.info(f"创建Native支付订单: {payload}")
        if time_expire:
            payload["time_expire"] = time_expire
        if attach:
            payload["attach"] = attach
        if goods_detail:
            payload["detail"] = {"goods_detail": goods_detail}
        
        return self._request("POST", "/v3/pay/transactions/native", json_data=payload)
    
    def query_order_by_out_trade_no(self, out_trade_no: str) -> Dict[str, Any]:
        """
        通过商户订单号查询订单
        参考: https://pay.weixin.qq.com/docs/merchant/apis/inquiry-order/query-order-by-out-trade-no.html
        
        注意：微信支付V3 API没有沙箱环境，所有请求都发送到生产环境
        """
        path = f"/v3/pay/transactions/out-trade-no/{out_trade_no}?mchid={self.mchid}"
        return self._request("GET", path)
    
    def query_order_by_transaction_id(self, transaction_id: str) -> Dict[str, Any]:
        """
        通过微信支付订单号查询订单
        
        注意：微信支付V3 API没有沙箱环境，所有请求都发送到生产环境
        """
        path = f"/v3/pay/transactions/id/{transaction_id}?mchid={self.mchid}"
        return self._request("GET", path)
    
    def decrypt_callback_resource(
        self,
        ciphertext: str,
        associated_data: str,
        nonce: str,
    ) -> Dict[str, Any]:
        """
        解密回调通知中的resource数据
        使用AEAD_AES_256_GCM算法
        参考: https://pay.weixin.qq.com/docs/merchant/apis/wechat-pay-api-v3/getting-started/decrypt-callback.html
        """
        try:
            from cryptography.hazmat.primitives.ciphers.aead import AESGCM
            
            # Base64解码
            ciphertext_bytes = base64.b64decode(ciphertext)
            associated_data_bytes = associated_data.encode('utf-8') if associated_data else b''
            nonce_bytes = nonce.encode('utf-8')
            key_bytes = self.api_v3_key.encode('utf-8')
            
            # 解密
            aesgcm = AESGCM(key_bytes)
            plaintext = aesgcm.decrypt(nonce_bytes, ciphertext_bytes, associated_data_bytes)
            
            # 解析JSON
            return json.loads(plaintext.decode('utf-8'))
        except Exception as e:
            logger.error(f"解密微信支付回调数据失败: {e}")
            raise
    
    def verify_callback_signature(
        self,
        timestamp: str,
        nonce: str,
        body: str,
        signature: str,
        serial_no: str,
    ) -> bool:
        """
        验证回调通知签名
        
        注意：需要使用微信支付平台证书（wechatpay_cert.pem）进行验签
        平台证书与商户API证书（apiclient_key.pem）不同
        
        参考: https://pay.weixin.qq.com/docs/merchant/apis/wechat-pay-api-v3/getting-started/verify-signature.html
        
        Args:
            timestamp: 时间戳
            nonce: 随机串
            body: 请求体
            signature: 签名值
            serial_no: 证书序列号（用于匹配对应的平台证书）
        
        Returns:
            True: 签名验证通过或未配置证书（开发环境）
            False: 签名验证失败
        """
        # 如果未配置平台证书，跳过验证（开发环境）
        if not self.platform_cert:
            logger.warning("平台证书未配置，跳过回调签名验证（开发环境可接受，生产环境建议配置）")
            return True  # 开发环境可以跳过
        
        # 构建验签串
        sign_str = f"{timestamp}\n{nonce}\n{body}\n"
        
        try:
            # 使用平台证书的公钥进行验签
            public_key = self.platform_cert.public_key()
            signature_bytes = base64.b64decode(signature)
            
            public_key.verify(
                signature_bytes,
                sign_str.encode('utf-8'),
                padding.PKCS1v15(),
                hashes.SHA256()
            )
            logger.debug("微信支付回调签名验证成功")
            return True
        except Exception as e:
            logger.error(f"微信支付回调签名验证失败: {e}")
            # 注意：生产环境应该返回False并拒绝请求
            # 开发环境可以返回True以便调试
            return False


# 创建全局实例
wechat_pay_client = WechatPayClient()

