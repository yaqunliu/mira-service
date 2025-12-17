#!/usr/bin/env python3
"""
创建测试产品脚本
用于在数据库中创建测试产品，包含 markdown 格式的 description
"""

from sqlalchemy.orm import sessionmaker
from sqlalchemy import create_engine
from app.core.config import settings
from app.services.creem_client import CreemClient
from app.services.product_service import ProductService
from app.models.product import Product
from datetime import datetime
import uuid
import httpx
import json


def create_test_products():
    """创建测试产品：先调用 Creem API 创建，再回填本地数据库"""
    engine = create_engine(str(settings.DATABASE_URL))
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    
    db = SessionLocal()
    
    try:
        # 一次性积分产品
        onetime_products = [
            {
                "name": "8000 积分",
                "description": """## 8000 积分包

**即时到账，永久有效**

### 包含内容
- **8000 积分** - 可用于所有 AI 功能
- **即时到账** - 支付成功后立即到账
- **永久有效** - 积分不会过期

### 适用场景
- 体验 AI 角色生成功能
- 创作少量分镜和视频
- 测试平台功能

### 推荐用途
- 新手用户首次购买
- 小规模创作项目
- 功能测试和体验""",
                "price": 1990,  # $19.90
                "currency": "USD",
                "billing_type": "onetime",
                "points_amount": 8000,
                "status": "active",
            },
            {
                "name": "20000 积分",
                "description": """## 20000 积分包

**热门选择，性价比高**

### 包含内容
- **20000 积分** - 充足的使用额度
- **即时到账** - 支付成功后立即到账
- **永久有效** - 积分不会过期

### 适用场景
- 完成中等规模的小说改编项目
- 创作多个分镜和视频
- 生成多个 AI 角色

### 推荐用途
- 个人创作者
- 小型工作室
- 定期使用平台的用户

> 💡 **热门推荐**：性价比最高的选择""",
                "price": 3990,  # $39.90
                "currency": "USD",
                "billing_type": "onetime",
                "points_amount": 20000,
                "status": "active",
            },
            {
                "name": "120000 积分",
                "description": """## 120000 积分包

**超值大包，适合重度用户**

### 包含内容
- **120000 积分** - 超大容量，长期使用
- **即时到账** - 支付成功后立即到账
- **永久有效** - 积分不会过期

### 适用场景
- 大型小说改编项目
- 批量生成视频内容
- 专业内容创作团队

### 推荐用途
- 专业创作者
- 内容工作室
- 需要大量积分的用户

> 🎁 **超值优惠**：购买大包更划算""",
                "price": 9990,  # $99.90
                "currency": "USD",
                "billing_type": "onetime",
                "points_amount": 120000,
                "status": "active",
            },
        ]
        
        # 订阅产品
        recurring_products = [
            {
                "name": "月付 · 20000积分/月",
                "description": """## 月付订阅套餐

**每月自动发放，灵活取消**

### 包含内容
- **20000 积分/月** - 每月自动到账
- **自动续费** - 无需手动操作
- **随时取消** - 灵活管理订阅

### 适用场景
- 定期创作内容
- 稳定的积分需求
- 希望自动管理的用户

### 推荐用途
- 个人创作者
- 定期使用平台的用户
- 希望省心的用户

> ⭐ **推荐套餐**：适合大多数用户""",
                "price": 3990,  # $39.90/月
                "currency": "USD",
                "billing_type": "recurring",
                "billing_period": "every-month",
                "points_amount": 20000,
                "status": "active",
            },
            {
                "name": "季度 · 25000积分/月",
                "description": """## 季度订阅套餐

**更多积分，更省心**

### 包含内容
- **25000 积分/月** - 比月付多 25%
- **自动续费** - 每季度自动续费
- **随时取消** - 灵活管理订阅

### 适用场景
- 需要更多积分的用户
- 长期使用平台
- 希望获得更多积分的用户

### 推荐用途
- 活跃创作者
- 需要更多积分的用户
- 长期使用平台的用户""",
                "price": 11990,  # $119.90/季度
                "currency": "USD",
                "billing_type": "recurring",
                "billing_period": "every-month",
                "points_amount": 25000,
                "status": "active",
            },
            {
                "name": "年付 · 30000积分/月",
                "description": """## 年付订阅套餐

**最超值选择，年付更省**

### 包含内容
- **30000 积分/月** - 比月付多 50%
- **自动续费** - 每年自动续费
- **随时取消** - 灵活管理订阅

### 适用场景
- 专业内容创作者
- 长期使用平台
- 希望获得最大价值的用户

### 推荐用途
- 专业创作者
- 内容工作室
- 长期使用平台的用户

> 💰 **年付更省**：最超值的订阅选择""",
                "price": 39900,  # $399.00/年
                "currency": "USD",
                "billing_type": "recurring",
                "billing_period": "every-month",
                "points_amount": 30000,
                "status": "active",
            },
        ]
        
        all_products = onetime_products + recurring_products
        created_count = 0
        skipped_count = 0
        
        client = CreemClient()
        
        # 默认图片 URL
        default_image_url = "https://mirastream.gmonkey.top/home-page/banner-placeholder.png"

        for product_data in all_products:
            # 先在 Creem 创建产品
            payload_metadata = {"points_amount": product_data["points_amount"]}
            try:
                # 打印请求参数
                print(f"\n正在创建产品: {product_data['name']}")
                request_params = {
                    'name': product_data['name'],
                    'price': product_data['price'],
                    'currency': product_data['currency'],
                    'billing_type': product_data['billing_type'],
                    'billing_period': product_data.get('billing_period'),
                    'status': product_data['status'],
                    'image_url': default_image_url,
                    'tax_mode': 'inclusive',
                    'tax_category': 'digital-goods-service',
                }
                print(f"请求参数: {json.dumps(request_params, indent=2, ensure_ascii=False)}")
                
                creem_resp = client.create_product(
                    name=product_data["name"],
                    price=product_data["price"],
                    currency=product_data["currency"],
                    billing_type=product_data["billing_type"],
                    billing_period=product_data.get("billing_period"),
                    description=product_data["description"],
                    image_url=default_image_url,
                    tax_mode="inclusive",
                    tax_category="digital-goods-service",
                )
                print(f"Creem 响应: {json.dumps(creem_resp, indent=2, ensure_ascii=False)}")
            except httpx.HTTPStatusError as e:
                # 打印详细的 HTTP 错误信息
                error_detail = getattr(e.response, '_error_detail', None)
                if error_detail:
                    print(f"\n❌ Creem 创建失败: {product_data['name']}")
                    print(f"状态码: {e.response.status_code}")
                    print(f"错误详情: {json.dumps(error_detail, indent=2, ensure_ascii=False)}")
                else:
                    # 尝试从响应中读取错误信息
                    try:
                        error_body = e.response.json()
                        print(f"\n❌ Creem 创建失败: {product_data['name']}")
                        print(f"状态码: {e.response.status_code}")
                        print(f"错误详情: {json.dumps(error_body, indent=2, ensure_ascii=False)}")
                    except Exception:
                        print(f"\n❌ Creem 创建失败: {product_data['name']}")
                        print(f"状态码: {e.response.status_code}")
                        print(f"错误文本: {e.response.text}")
                continue
            except Exception as exc:  # pragma: no cover - 脚本运行时捕获
                print(f"\n❌ Creem 创建失败: {product_data['name']} => {exc}")
                print(f"异常类型: {type(exc).__name__}")
                import traceback
                traceback.print_exc()
                continue

            creem_product_id = creem_resp.get("id") or creem_resp.get("product_id")
            if not creem_product_id:
                print(f"Creem 未返回 product_id，跳过: {product_data['name']}，响应: {creem_resp}")
                continue

            # 检查本地是否已有同 ID
            existing = db.query(Product).filter_by(creem_product_id=creem_product_id).first()
            if existing:
                print(f"产品已存在（本地）: {product_data['name']} / {creem_product_id}")
                skipped_count += 1
                continue

            # 回填本地数据库
            upsert_payload = {
                "id": creem_product_id,
                "name": creem_resp.get("name") or product_data["name"],
                "description": creem_resp.get("description") or product_data["description"],
                "price": creem_resp.get("price") or product_data["price"],
                "currency": creem_resp.get("currency") or product_data["currency"],
                "billing_type": creem_resp.get("billing_type") or product_data["billing_type"],
                "billing_period": creem_resp.get("billing_period") or product_data.get("billing_period"),
                "points_amount": product_data["points_amount"],
                "status": creem_resp.get("status") or product_data["status"],
                "image_url": creem_resp.get("image_url"),
                "product_url": creem_resp.get("product_url"),
                "features": creem_resp.get("features"),
                "mode": creem_resp.get("mode"),
                "metadata": payload_metadata,
            }

            ProductService.upsert_product(db, upsert_payload)
            created_count += 1
            print(f"创建产品成功: {product_data['name']} / {creem_product_id}")
        
        db.commit()
        print(f"\n完成！创建了 {created_count} 个产品，跳过了 {skipped_count} 个已存在的产品")
        
    except Exception as e:
        db.rollback()
        print(f"创建产品失败: {e}")
        raise
    finally:
        db.close()


if __name__ == "__main__":
    create_test_products()

