#!/usr/bin/env python3
"""
测试订单轮询任务
用于验证 poll_pending_orders 任务能否正确执行
"""
import sys
import os

# 添加项目根目录到 Python 路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.db.session import SessionLocal
from app.services.order_service import OrderService
from app.core.logger import logger

def test_poll_pending_orders():
    """测试订单轮询功能"""
    db = SessionLocal()
    try:
        logger.info("=" * 60)
        logger.info("开始测试订单轮询功能")
        logger.info("=" * 60)
        
        result = OrderService.poll_pending_orders(db)
        
        logger.info("=" * 60)
        logger.info(f"测试完成: {result}")
        logger.info("=" * 60)
        
        print(f"\n✅ 测试成功！")
        print(f"检查订单数: {result.get('checked', 0)}")
        print(f"支付成功数: {result.get('paid', 0)}")
        print(f"过期订单数: {result.get('expired', 0)}")
        print(f"错误数: {result.get('errors', 0)}")
        
        return result
    except Exception as e:
        logger.exception(f"测试失败: {e}")
        print(f"\n❌ 测试失败: {e}")
        raise
    finally:
        db.close()


if __name__ == "__main__":
    test_poll_pending_orders()

