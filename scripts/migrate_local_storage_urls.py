#!/usr/bin/env python3
"""
数据迁移脚本：把本地存储的绝对路径改写成可访问的 HTTP URL

背景：
    US3 未开通时文件落在本地磁盘。PUBLIC_BASE_URL 没配的那段时间，
    存进库的是容器内绝对路径（形如 /app/local_storage/scenes/4/x.png），
    服务端读文件没问题，但浏览器访问不到，页面上图片全是 404。

    配好 PUBLIC_BASE_URL 之后新生成的记录是对的，历史记录不会自动变，
    用这个脚本批量转换成 {PUBLIC_BASE_URL}/uploads/{put_key}。

覆盖范围：
    - 普通 URL 列：chapter/character/scene/shot/creation 上的各个 *_url
    - JSONB 列：status_detail / extra_data 里的历史记录（image_historys、
      version_history、video_historys 等），递归扫描所有字符串

幂等：已经是 HTTP URL 的记录不会被再次处理，可以重复执行。

使用方法：
    # 先看会改什么，不写库
    python scripts/migrate_local_storage_urls.py --dry-run

    # 确认无误后执行
    python scripts/migrate_local_storage_urls.py
"""

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy.orm.attributes import flag_modified

from app.db.session import SessionLocal
from app.core.config import settings
from app.core.logger import logger
from app.utils.local_storage import local_storage
from app.models.chapter import Chapter
from app.models.character import Character
from app.models.creation import Creation
from app.models.scene import Scene
from app.models.shot import Shot


# (模型, 普通 URL 列, JSONB 列)
TARGETS = [
    (Chapter, ["content_url"], []),
    (Character, ["image_url"], ["status_detail"]),
    (Scene, ["image_url"], ["status_detail", "extra_data"]),
    (Shot, ["image_url", "audio_url", "video_url"], ["status_detail", "extra_data"]),
    (Creation, ["video_url", "audio_url", "subtitle_url", "text_content_url"], ["extra_data"]),
]


def convert(value):
    """
    绝对路径 -> HTTP URL；不该动的原样返回

    只处理位于 LOCAL_STORAGE_DIR 之下的绝对路径，其余（US3 链接、
    已经转换过的 HTTP URL、外部图床地址）一律不碰。
    """
    if not isinstance(value, str) or not value.startswith("/"):
        return value

    base = str(local_storage.base_dir)
    if not value.startswith(base + os.sep):
        return value

    put_key = value[len(base):].lstrip("/")
    if not put_key:
        return value

    return local_storage.build_url(put_key)


def convert_json(node):
    """递归转换 JSON 结构里的所有字符串，返回 (新值, 改动数)"""
    if isinstance(node, str):
        new = convert(node)
        return new, int(new != node)
    if isinstance(node, list):
        count = 0
        result = []
        for item in node:
            new_item, n = convert_json(item)
            result.append(new_item)
            count += n
        return result, count
    if isinstance(node, dict):
        count = 0
        result = {}
        for key, item in node.items():
            new_item, n = convert_json(item)
            result[key] = new_item
            count += n
        return result, count
    return node, 0


def main():
    parser = argparse.ArgumentParser(description="把本地存储绝对路径改写成 HTTP URL")
    parser.add_argument("--dry-run", action="store_true", help="只打印将要修改的内容，不写库")
    args = parser.parse_args()

    if not settings.PUBLIC_BASE_URL:
        logger.error(
            "PUBLIC_BASE_URL 未配置，转换后仍然是绝对路径，无意义。"
            "请先在 .env 里配置对外访问地址（如 http://45.130.164.189:8001）再执行。"
        )
        return 1

    logger.info(f"存储目录: {local_storage.base_dir}")
    logger.info(f"目标地址前缀: {settings.PUBLIC_BASE_URL}{local_storage.url_prefix}/")
    if args.dry_run:
        logger.info("== DRY RUN：不会写库 ==")

    db = SessionLocal()
    total = 0

    try:
        for model, url_columns, json_columns in TARGETS:
            name = model.__name__
            changed_rows = 0
            changed_fields = 0

            for row in db.query(model).all():
                row_changed = False

                for column in url_columns:
                    old = getattr(row, column, None)
                    new = convert(old)
                    if new != old:
                        logger.info(f"  {name}.{column}: {old}  ->  {new}")
                        if not args.dry_run:
                            setattr(row, column, new)
                        row_changed = True
                        changed_fields += 1

                for column in json_columns:
                    old = getattr(row, column, None)
                    if not old:
                        continue
                    new, count = convert_json(old)
                    if count:
                        logger.info(f"  {name}.{column}: {count} 处路径")
                        if not args.dry_run:
                            setattr(row, column, new)
                            # JSONB 原地替换不会被 SQLAlchemy 侦测到，必须显式标脏
                            flag_modified(row, column)
                        row_changed = True
                        changed_fields += count

                if row_changed:
                    changed_rows += 1

            if changed_fields:
                logger.info(f"{name}: {changed_rows} 行 / {changed_fields} 处")
                total += changed_fields
            else:
                logger.info(f"{name}: 无需修改")

        if args.dry_run:
            db.rollback()
            logger.info(f"DRY RUN 结束，共 {total} 处待修改（未写库）")
        else:
            db.commit()
            logger.info(f"迁移完成，共修改 {total} 处")
        return 0

    except Exception as e:
        db.rollback()
        logger.opt(exception=True).error("迁移失败，已回滚: {}", str(e))
        return 1
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(main())
