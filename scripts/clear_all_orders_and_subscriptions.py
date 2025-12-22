#!/usr/bin/env python3
"""
清空所有订单和订阅数据

⚠️ 警告：此脚本会删除所有订单、订阅和相关数据！
仅用于开发环境，项目未上线时使用。

运行方式：
    cd mira-service
    python scripts/clear_all_orders_and_subscriptions.py

注意：如果迁移失败，请使用 cleanup_and_reset_migration.py 来清理并重置
"""

import sys
from pathlib import Path

# 添加项目根目录到路径
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from sqlalchemy import create_engine, text
from app.core.config import settings
from app.core.logger import logger


def get_db_engine():
    """获取数据库引擎"""
    database_url = str(settings.DATABASE_URL)
    return create_engine(database_url, echo=False)


def clear_all_data(engine):
    """清空所有订单和订阅相关数据"""
    logger.info("=" * 60)
    logger.warning("⚠️  开始清空所有订单和订阅数据...")
    logger.info("=" * 60)
    
    with engine.connect() as conn:
        # 1. 删除订阅积分历史
        logger.info("删除订阅积分历史...")
        result = conn.execute(text("DELETE FROM subscription_points_history"))
        logger.info(f"已删除 {result.rowcount} 条订阅积分历史记录")
        
        # 2. 删除订阅
        logger.info("删除订阅...")
        result = conn.execute(text("DELETE FROM subscriptions"))
        logger.info(f"已删除 {result.rowcount} 个订阅")
        
        # 3. 删除订单
        logger.info("删除订单...")
        result = conn.execute(text("DELETE FROM orders"))
        logger.info(f"已删除 {result.rowcount} 个订单")
        
        # 4. 删除webhook事件（可选，但建议也清理）
        logger.info("删除webhook事件...")
        result = conn.execute(text("DELETE FROM webhook_events"))
        logger.info(f"已删除 {result.rowcount} 个webhook事件")
        
        conn.commit()
        
        logger.info("=" * 60)
        logger.info("✅ 所有订单和订阅数据已清空！")
        logger.info("=" * 60)
        logger.info("现在可以安全地运行数据库迁移：")
        logger.info("  alembic upgrade head")


def main():
    """主函数"""
    logger.warning("=" * 60)
    logger.warning("⚠️  警告：此脚本会删除所有订单和订阅数据！")
    logger.warning("=" * 60)
    logger.warning("将删除以下数据：")
    logger.warning("  - 所有订单 (orders)")
    logger.warning("  - 所有订阅 (subscriptions)")
    logger.warning("  - 所有订阅积分历史 (subscription_points_history)")
    logger.warning("  - 所有webhook事件 (webhook_events)")
    logger.warning("=" * 60)
    
    # 确认
    confirm = input("\n确认删除所有数据？请输入 'DELETE ALL' 继续: ")
    if confirm != 'DELETE ALL':
        logger.info("已取消")
        return
    
    engine = get_db_engine()
    
    try:
        clear_all_data(engine)
    except Exception as e:
        logger.exception(f"清空数据时发生错误: {e}")
        raise


if __name__ == "__main__":
    main()

