#!/usr/bin/env python3
"""
数据迁移脚本：将现有创作关联的角色ID迁移到 character_ids 字段

功能：
1. 查询所有创作（creations）
2. 对于每个创作，查询 characters 表中 creation_id 等于该创作ID的所有角色
3. 将这些角色的 character_id 收集到列表中
4. 更新创作的 character_ids 字段

使用方法：
    python scripts/migrate_character_ids.py
"""

import sys
import os

# 添加项目根目录到Python路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.db.session import SessionLocal
from app.models.creation import Creation
from app.models.character import Character
from app.core.logger import logger


def migrate_character_ids():
    """迁移角色ID到创作的 character_ids 字段"""
    db = SessionLocal()
    
    try:
        # 查询所有创作（排除已删除的）
        creations = db.query(Creation).filter(
            Creation.deleted_at.is_(None)
        ).all()
        
        total_creations = len(creations)
        logger.info(f"找到 {total_creations} 个创作，开始迁移...")
        
        updated_count = 0
        skipped_count = 0
        error_count = 0
        
        for idx, creation in enumerate(creations, 1):
            try:
                # 查询该创作关联的所有角色
                characters = db.query(Character).filter(
                    Character.creation_id == creation.creation_id,
                    Character.deleted_at.is_(None)
                ).all()
                
                # 收集角色ID
                character_ids = [char.character_id for char in characters]
                
                if character_ids:
                    # 更新创作的 character_ids 字段
                    creation.character_ids = character_ids
                    updated_count += 1
                    logger.info(
                        f"[{idx}/{total_creations}] 创作 {creation.creation_id} ({creation.title}): "
                        f"更新了 {len(character_ids)} 个角色ID: {character_ids}"
                    )
                else:
                    # 如果没有角色，设置为空列表或 None
                    if creation.character_ids is None:
                        creation.character_ids = []
                        skipped_count += 1
                        logger.info(
                            f"[{idx}/{total_creations}] 创作 {creation.creation_id} ({creation.title}): "
                            f"没有关联的角色，设置为空列表"
                        )
                    else:
                        skipped_count += 1
                        logger.info(
                            f"[{idx}/{total_creations}] 创作 {creation.creation_id} ({creation.title}): "
                            f"已有 character_ids={creation.character_ids}，跳过"
                        )
                
            except Exception as e:
                error_count += 1
                logger.error(
                    f"[{idx}/{total_creations}] 处理创作 {creation.creation_id} 时出错: {str(e)}",
                    exc_info=True
                )
        
        # 提交所有更改
        db.commit()
        
        logger.info("=" * 60)
        logger.info("迁移完成！")
        logger.info(f"总计: {total_creations} 个创作")
        logger.info(f"已更新: {updated_count} 个")
        logger.info(f"已跳过: {skipped_count} 个")
        logger.info(f"错误: {error_count} 个")
        logger.info("=" * 60)
        
    except Exception as e:
        db.rollback()
        logger.error(f"迁移过程中发生错误: {str(e)}", exc_info=True)
        raise
    finally:
        db.close()


if __name__ == "__main__":
    print("=" * 60)
    print("角色ID迁移脚本")
    print("=" * 60)
    print()
    print("此脚本将把现有创作关联的角色ID迁移到 character_ids 字段")
    print()
    
    # 确认执行
    confirm = input("是否继续执行迁移？(y/N): ").strip().lower()
    if confirm != 'y':
        print("已取消迁移")
        sys.exit(0)
    
    print()
    print("开始迁移...")
    print()
    
    try:
        migrate_character_ids()
        print()
        print("迁移成功完成！")
        sys.exit(0)
    except Exception as e:
        print()
        print(f"迁移失败: {str(e)}")
        sys.exit(1)

