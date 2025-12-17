import httpx
import re
from typing import Any, Dict, Optional, List
from app.core.config import settings
from app.core.logger import logger


class CreemClient:
    def __init__(
        self,
        api_key: str = settings.CREEM_API_KEY,
        base_url: str = str(settings.CREEM_API_URL).rstrip("/"),
        timeout: int = settings.CREEM_TIMEOUT,
    ) -> None:
        self.api_key = api_key
        self.base_url = base_url
        self.timeout = timeout
        self._headers = {
            "x-api-key": self.api_key,
            "Content-Type": "application/json",
        }

    def _request(self, method: str, path: str, params: Dict[str, Any] | None = None, json: Dict[str, Any] | None = None):
        url = f"{self.base_url}{path}"
        logger.info(f"Creem API {method.upper()} {url}")
        with httpx.Client(timeout=self.timeout) as client:
            resp = client.request(method, url, headers=self._headers, params=params, json=json)
            try:
                resp.raise_for_status()
            except httpx.HTTPStatusError as e:
                # 尝试解析错误响应
                error_detail = None
                try:
                    error_detail = resp.json()
                except Exception:
                    error_detail = resp.text
                    # 如果error detail 为网页 则忽略
                    if "DOCTYPE html" in error_detail:
                        # 找到网页的标题 title 并提取出来
                        title = re.search(r"<title>(.*?)</title>", error_detail).group(1)
                        error_detail = title
                logger.error(f"Creem API 错误: {e.response.status_code} - {error_detail} | url={url} | payload={json}")
                # 将错误信息附加到异常中
                e.response._error_detail = error_detail
                raise
            return resp.json()

    # 产品列表
    def search_products(self, page_number: int = 1, page_size: int = 100) -> Dict[str, Any]:
        return self._request(
            "GET",
            "/v1/products/search",
            params={"page_number": page_number, "page_size": page_size},
        )

    # 创建产品（一次性或订阅）
    def create_product(
        self,
        name: str,
        price: int,
        currency: str = "USD",
        billing_type: str = "onetime",
        billing_period: Optional[str] = None,
        description: Optional[str] = None,
        image_url: Optional[str] = None,
        tax_mode: str = "inclusive",
        tax_category: Optional[List[str]] = None,
        default_success_url: Optional[str] = None,
        custom_field: Optional[List[Dict[str, Any]]] = None,
        abandoned_cart_recovery_enabled: bool = False,
    ) -> Dict[str, Any]:
        # 验证必需参数
        if price < 100:
            raise ValueError("price must be >= 100 (in cents)")
        
        # 确保 currency 是大写
        currency = currency.upper()
        
        # 如果是 recurring 类型，billing_period 是必需的
        if billing_type == "recurring" and not billing_period:
            raise ValueError("billing_period is required when billing_type is 'recurring'")
        
        payload: Dict[str, Any] = {
            "name": name,
            "price": price,
            "currency": currency,
            "billing_type": billing_type,
        }
        
        # 必需参数：tax_mode
        payload["tax_mode"] = tax_mode
        
        # 必需参数：tax_category（数组格式）
        if tax_category:
            payload["tax_category"] = tax_category
        else:
            # 默认使用 saas 类别
            payload["tax_category"] = ["saas", "digital-goods-service"]
        
        # 可选参数
        if billing_period:
            payload["billing_period"] = billing_period
        if description:
            payload["description"] = description
        if image_url:
            payload["image_url"] = image_url
        if default_success_url:
            payload["default_success_url"] = default_success_url
        if custom_field:
            payload["custom_field"] = custom_field
        if abandoned_cart_recovery_enabled:
            payload["abandoned_cart_recovery_enabled"] = abandoned_cart_recovery_enabled

        return self._request("POST", "/v1/products", json=payload)

    # 创建 checkout session（最小参数：product_id + success_url）
    def create_checkout_session(
        self,
        creem_product_id: str,
        success_url: str,
    ) -> Dict[str, Any]:
        if not success_url:
            raise ValueError("success_url is required for checkout creation")

        # 规范化 URL：将 127.0.0.1 替换为 localhost（Creem API 要求）
        normalized_url = success_url.replace("127.0.0.1", "localhost")

        payload: Dict[str, Any] = {
            "product_id": creem_product_id,
            "success_url": normalized_url,
        }

        # 使用官方文档推荐的 /v1/checkouts
        return self._request("POST", "/v1/checkouts", json=payload)

    # 获取订阅详情
    def get_subscription(self, creem_subscription_id: str) -> Dict[str, Any]:
        return self._request("GET", f"/v1/subscriptions/{creem_subscription_id}")

    # 获取 checkout 详情（用于轮询容错）
    def get_checkout(self, checkout_id: str) -> Dict[str, Any]:
        """
        通过 checkout_id 查询 checkout 详情
        返回的 checkout 对象包含 order 信息，可以直接判断支付状态
        """
        params: Dict[str, Any] = {
            "checkout_id": checkout_id,
        }
        return self._request("GET", "/v1/checkouts", params=params)

    # 查询交易（用于轮询容错，备用方案）
    def search_transactions(
        self,
        order_id: Optional[str] = None,
        subscription_id: Optional[str] = None,
        page_number: int = 1,
        page_size: int = 50,
    ) -> Dict[str, Any]:
        params: Dict[str, Any] = {
            "page_number": page_number,
            "page_size": page_size,
        }
        if order_id:
            params["order_id"] = order_id
        if subscription_id:
            params["subscription"] = subscription_id
        return self._request("GET", "/v1/transactions/search", params=params)


creem_client = CreemClient()

