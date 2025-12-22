#!/usr/bin/env python3
"""
清理所有相关数据并删除上次迁移创建的数据表

⚠️ 警告：此脚本会：
1. 删除所有订单、订阅和相关数据
2. 删除上次迁移创建的新表（creem_payments, wechat_payments等）
3. 删除上次迁移添加的新列（payment_method等）
4. 回滚迁移版本

运行方式：
    cd mira-service
    python scripts/cleanup_and_reset_migration.py
"""

import sys
from pathlib import Path

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from sqlalchemy import create_engine, text
from app.core.config import settings
from app.core.logger import logger


def get_db_engine():
    """获取数据库引擎"""
    database_url = str(settings.DATABASE_URL)
    return create_engine(database_url, echo=False)


def cleanup_all(engine):
    """清理所有数据和上次迁移的表/列"""
    logger.info("=" * 60)
    logger.warning("⚠️  开始清理所有数据和上次迁移的表/列...")
    logger.info("=" * 60)
    
    with engine.connect() as conn:
        # 1. 删除订阅积分历史
        logger.info("删除订阅积分历史...")
        try:
            result = conn.execute(text("DELETE FROM subscription_points_history"))
            logger.info(f"已删除 {result.rowcount} 条订阅积分历史记录")
        except Exception as e:
            logger.warning(f"删除订阅积分历史失败（可能表不存在）: {e}")
        
        # 2. 删除订阅
        logger.info("删除订阅...")
        try:
            result = conn.execute(text("DELETE FROM subscriptions"))
            logger.info(f"已删除 {result.rowcount} 个订阅")
        except Exception as e:
            logger.warning(f"删除订阅失败: {e}")
        
        # 3. 删除订单
        logger.info("删除订单...")
        try:
            result = conn.execute(text("DELETE FROM orders"))
            logger.info(f"已删除 {result.rowcount} 个订单")
        except Exception as e:
            logger.warning(f"删除订单失败: {e}")
        
        # 4. 删除webhook事件
        logger.info("删除webhook事件...")
        try:
            result = conn.execute(text("DELETE FROM webhook_events"))
            logger.info(f"已删除 {result.rowcount} 个webhook事件")
        except Exception as e:
            logger.warning(f"删除webhook事件失败: {e}")
        
        # 5. 删除所有支付相关的表
        logger.info("删除所有支付相关的表...")
        tables_to_drop = [
            'subscription_points_history',
            'wechat_subscriptions',
            'creem_subscriptions',
            'subscriptions',
            'wechat_payments',
            'creem_payments',
            'orders',
            'products',
        ]
        
        for table in tables_to_drop:
            try:
                conn.execute(text(f"DROP TABLE IF EXISTS {table} CASCADE"))
                logger.info(f"  ✅ 已删除表: {table}")
            except Exception as e:
                logger.warning(f"  ⚠️  删除表 {table} 失败: {e}")
        
        # 6. 删除webhook_events表的source字段（如果存在）
        logger.info("删除webhook_events表的source字段...")
        try:
            conn.execute(text("DROP INDEX IF EXISTS ix_webhook_events_source"))
            conn.execute(text("ALTER TABLE webhook_events DROP COLUMN IF EXISTS source"))
            logger.info("  ✅ 已删除 webhook_events.source 字段")
        except Exception as e:
            logger.warning(f"  ⚠️  删除 webhook_events.source 失败: {e}")
        
        # 7. 删除 subscriptions 表的旧字段（如果存在）
        logger.info("检查并删除 subscriptions 表的旧字段...")
        try:
            # 检查表是否存在
            result = conn.execute(text("""
                SELECT column_name 
                FROM information_schema.columns 
                WHERE table_name = 'subscriptions'
            """))
            existing_columns = [row[0] for row in result]
            
            if 'points_amount' in existing_columns:
                conn.execute(text("ALTER TABLE subscriptions DROP COLUMN IF EXISTS points_amount"))
                logger.info("  ✅ 已删除 subscriptions.points_amount 列")
        except Exception as e:
            logger.warning(f"  ⚠️  处理 subscriptions 字段失败: {e}")
        
        # 8. 回滚迁移版本到merge_uuid_supabase_temp
        logger.info("回滚迁移版本...")
        try:
            conn.execute(text("UPDATE alembic_version SET version_num = 'merge_uuid_supabase_temp'"))
            logger.info("  ✅ 已回滚迁移版本到 merge_uuid_supabase_temp")
        except Exception as e:
            logger.warning(f"  ⚠️  回滚迁移版本失败: {e}")
        
        conn.commit()
        
        logger.info("=" * 60)
        logger.info("✅ 清理完成！")
        logger.info("=" * 60)
        logger.info("现在可以运行新的迁移：")
        logger.info("  uv run alembic upgrade head")
        logger.info("")
        logger.info("新的迁移文件：payment_system_001")
        logger.info("从 merge_uuid_supabase_temp 开始，创建所有支付相关的表")


def main():
    """主函数"""
    logger.warning("=" * 60)
    logger.warning("⚠️  警告：此脚本会删除所有订单、订阅数据和上次迁移的表/列！")
    logger.warning("=" * 60)
    logger.warning("将执行以下操作：")
    logger.warning("  1. 删除所有订单、订阅、积分历史、webhook事件")
    logger.warning("  2. 删除所有支付相关的表（products, orders, subscriptions等）")
    logger.warning("  3. 删除webhook_events表的source字段")
    logger.warning("  4. 回滚迁移版本到 merge_uuid_supabase_temp")
    logger.warning("=" * 60)
    
    confirm = input("\n确认执行？请输入 'CLEAN ALL' 继续: ")
    if confirm != 'CLEAN ALL':
        logger.info("已取消")
        return
    
    engine = get_db_engine()
    
    try:
        cleanup_all(engine)
    except Exception as e:
        logger.exception(f"清理过程中发生错误: {e}")
        raise


if __name__ == "__main__":
    main()

