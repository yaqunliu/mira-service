#!/usr/bin/env python3
"""
创建测试产品脚本 - 支持中英文版本

不再调用Creem API，直接创建产品到数据库。
汇率：1 USD = 7 CNY

注意：
- 英文产品（Creem支付）创建后，需要手动设置 origin_product_id 为真实的Creem产品ID
- 中文产品（微信支付）不需要 origin_product_id，可以为空
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


def create_test_products():
    """创建测试产品：中英文版本"""
    engine = create_engine(str(settings.DATABASE_URL))
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    
    db = SessionLocal()
    
    try:
        # 汇率：1 USD = 7 CNY
        USD_TO_CNY = 7
        
        # 一次性积分产品 - 英文版本（Creem支付）
        onetime_products_en = [
            {
                "name": "8000 Points",
                "description": """## 8000 Points Package

**Instant delivery, never expires**

### What's Included
- **8000 Points** - Use for all AI features
- **Instant delivery** - Points arrive immediately after payment
- **Never expires** - Points are valid forever

### Best For
- Trying out AI character generation
- Creating a few storyboards and videos
- Testing platform features

### Recommended For
- New users first purchase
- Small creative projects
- Feature testing and exploration""",
                "price_usd": 1990,  # $19.90
                "points_amount": 8000,
            },
            {
                "name": "20000 Points",
                "description": """## 20000 Points Package

**Popular choice, great value**

### What's Included
- **20000 Points** - Generous usage allowance
- **Instant delivery** - Points arrive immediately after payment
- **Never expires** - Points are valid forever

### Best For
- Medium-scale novel adaptation projects
- Creating multiple storyboards and videos
- Generating multiple AI characters

### Recommended For
- Individual creators
- Small studios
- Regular platform users

> 💡 **Popular Choice**: Best value for money""",
                "price_usd": 3990,  # $39.90
                "points_amount": 20000,
            },
            {
                "name": "120000 Points",
                "description": """## 120000 Points Package

**Mega bundle, perfect for power users**

### What's Included
- **120000 Points** - Massive capacity for long-term use
- **Instant delivery** - Points arrive immediately after payment
- **Never expires** - Points are valid forever

### Best For
- Large novel adaptation projects
- Batch video content generation
- Professional content creation teams

### Recommended For
- Professional creators
- Content studios
- Users who need lots of points

> 🎁 **Great Value**: Bigger bundles save more""",
                "price_usd": 9990,  # $99.90
                "points_amount": 120000,
            },
        ]
        
        # 一次性积分产品 - 中文版本（微信支付）
        onetime_products_zh = [
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
                "price_cny": 13930,  # ¥139.30 (1990 * 7)
                "points_amount": 8000,
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
                "price_cny": 27930,  # ¥279.30 (3990 * 7)
                "points_amount": 20000,
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
                "price_cny": 69930,  # ¥699.30 (9990 * 7)
                "points_amount": 120000,
            },
        ]
        
        # 订阅产品 - 英文版本（Creem支付）
        recurring_products_en = [
            {
                "name": "Monthly · 20000 Points/Month",
                "description": """## Monthly Subscription

**Auto-delivery every month, cancel anytime**

### What's Included
- **20000 Points/Month** - Automatically delivered each month
- **Auto-renewal** - No manual action needed
- **Cancel anytime** - Flexible subscription management

### Best For
- Regular content creation
- Stable points needs
- Users who prefer automation

### Recommended For
- Individual creators
- Regular platform users
- Users who want convenience

> ⭐ **Recommended Plan**: Perfect for most users""",
                "price_usd": 3990,  # $39.90/month
                "billing_period": "every-month",
                "points_amount": 20000,
            },
            {
                "name": "Quarterly · 25000 Points/Month",
                "description": """## Quarterly Subscription

**More points, better value**

### What's Included
- **25000 Points/Month** - 25% more than monthly plan
- **Auto-renewal** - Renews every quarter
- **Cancel anytime** - Flexible subscription management

### Best For
- Users who need more points
- Long-term platform usage
- Users who want more value

### Recommended For
- Active creators
- Users who need more points
- Long-term platform users""",
                "price_usd": 11990,  # $119.90/quarter
                "billing_period": "every-month",
                "points_amount": 25000,
            },
            {
                "name": "Yearly · 30000 Points/Month",
                "description": """## Yearly Subscription

**Best value, save more with annual plan**

### What's Included
- **30000 Points/Month** - 50% more than monthly plan
- **Auto-renewal** - Renews every year
- **Cancel anytime** - Flexible subscription management

### Best For
- Professional content creators
- Long-term platform usage
- Users who want maximum value

### Recommended For
- Professional creators
- Content studios
- Long-term platform users

> 💰 **Best Value**: Most cost-effective subscription option""",
                "price_usd": 39900,  # $399.00/year
                "billing_period": "every-month",
                "points_amount": 30000,
            },
        ]
        
        # 订阅产品 - 中文版本（微信支付）
        recurring_products_zh = [
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
                "price_cny": 27930,  # ¥279.30/month (3990 * 7)
                "billing_period": "every-month",
                "points_amount": 20000,
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
                "price_cny": 83930,  # ¥839.30/quarter (11990 * 7)
                "billing_period": "every-month",
                "points_amount": 25000,
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
                "price_cny": 279300,  # ¥2793.00/year (39900 * 7)
                "billing_period": "every-month",
                "points_amount": 30000,
            },
        ]
        
        # 默认图片 URL
        default_image_url = "https://mirastream.gmonkey.top/home-page/banner-placeholder.png"
        
        created_count = 0
        skipped_count = 0
        
        # 创建英文产品（Creem支付）
        all_en_products = onetime_products_en + recurring_products_en
        for product_data in all_en_products:
            # 检查是否已存在（通过name和payment_method+language）
            existing = db.query(Product).filter_by(
                name=product_data["name"],
                payment_method="creem",
                language="en"
            ).first()
            
            if existing:
                print(f"产品已存在（英文）: {product_data['name']}")
                skipped_count += 1
                continue
            
            product = Product(
                payment_method="creem",
                language="en",
                origin_product_id=None,  # 注意：Creem支付需要此字段，需要手动设置真实的Creem产品ID
                name=product_data["name"],
                description=product_data["description"],
                price=product_data["price_usd"],
                currency="USD",
                billing_type="recurring" if product_data.get("billing_period") else "onetime",
                billing_period=product_data.get("billing_period"),
                points_amount=product_data["points_amount"],
                status="active",
                image_url=default_image_url,
            )
            db.add(product)
            created_count += 1
            print(f"创建产品成功（英文）: {product_data['name']}")
        
        # 创建中文产品（微信支付）
        all_zh_products = onetime_products_zh + recurring_products_zh
        for product_data in all_zh_products:
            # 检查是否已存在（通过name和payment_method+language）
            existing = db.query(Product).filter_by(
                name=product_data["name"],
                payment_method="wechat",
                language="zh"
            ).first()
            
            if existing:
                print(f"产品已存在（中文）: {product_data['name']}")
                skipped_count += 1
                continue
            
            product = Product(
                payment_method="wechat",
                language="zh",
                origin_product_id=None,  # 微信支付不需要此字段，可以为空
                name=product_data["name"],
                description=product_data["description"],
                price=product_data["price_cny"],
                currency="CNY",
                billing_type="recurring" if product_data.get("billing_period") else "onetime",
                billing_period=product_data.get("billing_period"),
                points_amount=product_data["points_amount"],
                status="active",
                image_url=default_image_url,
            )
            db.add(product)
            created_count += 1
            print(f"创建产品成功（中文）: {product_data['name']}")
        
        db.commit()
        print(f"\n完成！创建了 {created_count} 个产品，跳过了 {skipped_count} 个已存在的产品")
        print(f"  - 英文产品（Creem支付）: {len(all_en_products)} 个")
        print(f"  - 中文产品（微信支付）: {len(all_zh_products)} 个")
        print(f"\n⚠️  重要提示：")
        print(f"  - 英文产品（Creem支付）需要手动设置 origin_product_id 为真实的Creem产品ID")
        print(f"  - 中文产品（微信支付）不需要 origin_product_id，可以为空")
        
    except Exception as e:
        db.rollback()
        print(f"创建产品失败: {e}")
        import traceback
        traceback.print_exc()
        raise
    finally:
        db.close()


if __name__ == "__main__":
    create_test_products()
