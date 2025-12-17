"""
产品同步定时任务（每小时）
"""
from app.core.celery_app import celery_app
from app.db.session import SessionLocal
from app.services.product_service import ProductService
from app.core.logger import logger


@celery_app.task(name="sync_products")
def sync_products():
    """
    产品同步任务
    从 Creem API 同步产品到本地数据库
    每小时执行一次（由 Celery Beat 调度）
    """
    db = SessionLocal()
    try:
        logger.info("=" * 60)
        logger.info("开始执行产品同步任务")
        logger.info("=" * 60)
        
        result = ProductService.sync_from_creem(db)
        
        logger.info("=" * 60)
        logger.info(f"产品同步完成: total={result.get('synced_count', 0)}, created={result.get('created_count', 0)}, updated={result.get('updated_count', 0)}")
        logger.info("=" * 60)
        
        return result
    except Exception as e:
        logger.exception(f"产品同步任务执行失败: {e}")
        raise
    finally:
        db.close()

