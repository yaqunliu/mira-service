#!/usr/bin/env python3
"""
创建微信支付测试产品脚本

由于微信支付V3 API没有沙箱环境，使用0.01元的价格进行测试。

创建两个测试产品：
1. 一次性支付：0.01元，获得10000积分
2. 订阅产品（按年支付）：0.01元/年，每月获得10000积分
"""

import sys
from pathlib import Path

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from sqlalchemy.orm import sessionmaker
from sqlalchemy import create_engine
from app.core.config import settings
from app.models.product import Product
from datetime import datetime
import uuid


def create_wechat_test_products():
    """创建微信支付测试产品"""
    engine = create_engine(str(settings.DATABASE_URL))
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    
    db = SessionLocal()
    
    try:
        # 默认图片 URL
        default_image_url = "https://mirastream.gmonkey.top/home-page/banner-placeholder.png"
        
        # 测试产品列表（中文，微信支付）
        test_products = [
            {
                "name": "测试产品 - 一次性支付",
                "description": """## 测试产品 - 一次性支付

**用于测试微信支付V3 API**

### 产品信息
- **价格**: ¥0.01（1分钱）
- **积分**: 10000 积分
- **支付方式**: 微信支付
- **类型**: 一次性支付

### 说明
- 此产品仅用于测试微信支付功能
- 由于微信支付V3 API没有沙箱环境，使用0.01元进行测试
- 支付成功后立即获得10000积分""",
                "price_cny": 1,  # 0.01元 = 1分
                "points_amount": 10000,
                "billing_type": "onetime",
                "billing_period": None,
            },
            {
                "name": "测试产品 - 年付订阅",
                "description": """## 测试产品 - 年付订阅

**用于测试微信支付V3 API订阅功能**

### 产品信息
- **价格**: ¥0.01/年（1分钱/年）
- **积分**: 10000 积分/月
- **支付方式**: 微信支付
- **类型**: 订阅（按年支付）
- **计费周期**: 每年

### 说明
- 此产品仅用于测试微信支付订阅功能
- 由于微信支付V3 API没有沙箱环境，使用0.01元进行测试
- 支付成功后立即获得首月10000积分
- 后续每月1号自动发放10000积分
- 注意：微信订阅不支持自动续费，到期后需要手动续费""",
                "price_cny": 1,  # 0.01元 = 1分
                "points_amount": 10000,
                "billing_type": "recurring",
                "billing_period": "every-year",
            },
        ]
        
        created_count = 0
        skipped_count = 0
        updated_count = 0
        
        for product_data in test_products:
            # 检查是否已存在（通过name和payment_method+language）
            existing = db.query(Product).filter_by(
                name=product_data["name"],
                payment_method="wechat",
                language="zh"
            ).first()
            
            if existing:
                # 如果已存在，检查是否需要更新价格和积分
                need_update = False
                if existing.price != product_data["price_cny"]:
                    existing.price = product_data["price_cny"]
                    need_update = True
                if existing.points_amount != product_data["points_amount"]:
                    existing.points_amount = product_data["points_amount"]
                    need_update = True
                if existing.billing_type != product_data["billing_type"]:
                    existing.billing_type = product_data["billing_type"]
                    need_update = True
                if existing.billing_period != product_data.get("billing_period"):
                    existing.billing_period = product_data.get("billing_period")
                    need_update = True
                if existing.status != "active":
                    existing.status = "active"
                    need_update = True
                
                if need_update:
                    db.commit()
                    updated_count += 1
                    print(f"更新产品（中文）: {product_data['name']}")
                else:
                    skipped_count += 1
                    print(f"产品已存在（中文）: {product_data['name']}")
                continue
            
            product = Product(
                payment_method="wechat",
                language="zh",
                origin_product_id=None,  # 微信支付不需要此字段
                name=product_data["name"],
                description=product_data["description"],
                price=product_data["price_cny"],
                currency="CNY",
                billing_type=product_data["billing_type"],
                billing_period=product_data.get("billing_period"),
                points_amount=product_data["points_amount"],
                status="active",
                image_url=default_image_url,
            )
            db.add(product)
            created_count += 1
            print(f"创建产品成功（中文）: {product_data['name']}")
            print(f"  - 价格: ¥{product_data['price_cny']/100:.2f} ({product_data['price_cny']}分)")
            print(f"  - 积分: {product_data['points_amount']}")
            print(f"  - 类型: {product_data['billing_type']}")
            if product_data.get("billing_period"):
                print(f"  - 计费周期: {product_data['billing_period']}")
        
        db.commit()
        print(f"\n完成！")
        print(f"  - 创建了 {created_count} 个产品")
        print(f"  - 更新了 {updated_count} 个产品")
        print(f"  - 跳过了 {skipped_count} 个已存在的产品")
        print(f"\n⚠️  重要提示：")
        print(f"  - 这些是测试产品，价格设置为0.01元（1分钱）")
        print(f"  - 用于测试微信支付V3 API（没有沙箱环境）")
        print(f"  - 产品名称包含'测试'标识，便于识别")
        
    except Exception as e:
        db.rollback()
        print(f"创建产品失败: {e}")
        import traceback
        traceback.print_exc()
        raise
    finally:
        db.close()


if __name__ == "__main__":
    create_wechat_test_products()

