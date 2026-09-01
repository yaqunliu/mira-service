#!/usr/bin/env python3
"""
本地磁盘存储后端

US3 未开通时的降级方案：把文件写到本地目录，返回与 US3 上传结果同构的字典，
使调用方（upload_helper）无需关心当前用的是哪个后端。

docker-compose 中 api 与 celery_worker 共享 ./:/app 挂载，因此 worker 写入的文件
api 容器可以直接读到，无需经过网络。
"""
import os
import shutil
from pathlib import Path
from typing import Any, Dict, Optional

from app.core.config import settings
from app.core.logger import logger


class LocalStorageError(Exception):
    """本地存储异常"""
    pass


class LocalStorage:
    """本地磁盘存储后端"""

    def __init__(self):
        self.base_dir = Path(settings.LOCAL_STORAGE_DIR).expanduser().resolve()
        self.url_prefix = "/" + settings.LOCAL_STORAGE_URL_PREFIX.strip("/")
        self.public_base_url = (settings.PUBLIC_BASE_URL or "").rstrip("/")

    # ------------------------------------------------------------------
    # 路径与 URL
    # ------------------------------------------------------------------

    def _resolve_target(self, put_key: str) -> Path:
        """
        把 put_key 解析为落盘的绝对路径，并防止路径穿越（../ 逃出 base_dir）
        """
        if not put_key:
            raise LocalStorageError("put_key 不能为空")

        target = (self.base_dir / put_key.lstrip("/")).resolve()

        # 确保解析后的路径仍在 base_dir 内
        if not str(target).startswith(str(self.base_dir) + os.sep):
            raise LocalStorageError(f"非法的 put_key（路径穿越）: {put_key}")

        return target

    def build_url(self, put_key: str) -> str:
        """
        生成保存到数据库的引用地址

        - 配置了 PUBLIC_BASE_URL：返回 HTTP URL，浏览器与服务端都能访问
        - 未配置：返回绝对文件路径，下载方直接读文件系统
        """
        if self.public_base_url:
            return f"{self.public_base_url}{self.url_prefix}/{put_key.lstrip('/')}"
        return str(self._resolve_target(put_key))

    def locate(self, url_or_path: str) -> Optional[Path]:
        """
        把一个存储引用（build_url 的产物）反解析回本地文件路径

        Args:
            url_or_path: 绝对路径，或包含 url_prefix 的 HTTP URL

        Returns:
            存在的本地文件路径；无法解析或文件不存在时返回 None
        """
        if not url_or_path:
            return None

        candidate: Optional[Path] = None

        marker = self.url_prefix + "/"
        if marker in url_or_path:
            # http://host/uploads/dev/2026.../chapter_0001.txt -> dev/2026.../chapter_0001.txt
            put_key = url_or_path.split(marker, 1)[1].split("?", 1)[0]
            try:
                candidate = self._resolve_target(put_key)
            except LocalStorageError:
                return None
        elif url_or_path.startswith("/"):
            candidate = Path(url_or_path)

        if candidate and candidate.is_file():
            return candidate
        return None

    # ------------------------------------------------------------------
    # 写入
    # ------------------------------------------------------------------

    def _result(self, put_key: str, target: Path) -> Dict[str, Any]:
        url = self.build_url(put_key)
        return {
            "success": True,
            "put_key": put_key,
            "internal_url": url,
            "external_url": url,
            "bucket": "local",
            "file_size": target.stat().st_size,
            "storage_backend": "local",
            "message": "文件已保存到本地存储",
        }

    def save_file(self, local_file: str, put_key: str) -> Dict[str, Any]:
        """把本地文件复制到存储目录"""
        if not os.path.exists(local_file):
            raise LocalStorageError(f"本地文件不存在: {local_file}")

        target = self._resolve_target(put_key)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(local_file, target)

        logger.info(f"[LocalStorage] 已保存文件: {target}")
        return self._result(put_key, target)

    def save_bytes(self, data: bytes, put_key: str) -> Dict[str, Any]:
        """把字节流写入存储目录"""
        if not isinstance(data, bytes):
            raise LocalStorageError(f"data 必须是 bytes 类型，当前类型: {type(data)}")

        target = self._resolve_target(put_key)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)

        logger.info(f"[LocalStorage] 已保存文件: {target}, 大小: {len(data)} 字节")
        return self._result(put_key, target)


class LocalStorageClient:
    """
    与 US3Client 接口兼容的本地存储客户端

    部分任务（场景图、视频、Agent 图片）直接构造 US3Client 而不经过 upload_helper，
    这个类提供同名同签名的方法，使那些调用点可以无差别替换。
    只实现被实际用到的三个方法，其余 US3Client 方法不在此覆盖范围。
    """

    def __init__(self, *args, **kwargs):
        # 吞掉 US3Client 的构造参数（bucket / suffix 等），本地存储用不到
        self._storage = local_storage

    def upload_file(
        self,
        local_file: str,
        bucket: str = None,
        put_key: str = None,
        header: Dict[str, str] = None,
        verify_hash: bool = True,
    ) -> Dict[str, Any]:
        """对齐 US3Client.upload_file，返回值含 'key' 字段"""
        if not put_key:
            put_key = os.path.basename(local_file)

        result = self._storage.save_file(local_file=local_file, put_key=put_key)
        # US3Client 的返回用 'key'，调用方会读它再传给 get_file_url
        result["key"] = put_key
        return result

    def upload_file_stream(
        self,
        file_stream: bytes,
        bucket: str = None,
        put_key: str = None,
        header: Dict[str, str] = None,
        content_type: str = None,
    ) -> Dict[str, Any]:
        """对齐 US3Client.upload_file_stream"""
        if not put_key:
            raise LocalStorageError("上传文件流时必须指定put_key")

        result = self._storage.save_bytes(data=file_stream, put_key=put_key)
        result["key"] = put_key
        return result

    def get_file_url(self, put_key: str, bucket: str = None) -> str:
        """对齐 US3Client.get_file_url"""
        return self._storage.build_url(put_key)


def get_storage_client():
    """
    返回当前可用的存储客户端

    US3 已配置时返回 US3Client，否则返回接口兼容的 LocalStorageClient。
    供那些直接构造 US3Client 的调用点使用，避免 US3 未配置时在构造阶段就抛
    ValueError（这会让整个任务失败，且错误信息与真正的业务无关）。
    """
    if use_local_storage():
        return LocalStorageClient()

    from app.utils.us3 import US3Client
    return US3Client()


def use_local_storage() -> bool:
    """
    当前是否应该使用本地存储

    显式开启，或 US3 公私钥任一缺失时自动降级。
    """
    if settings.LOCAL_STORAGE_ENABLED:
        return True
    return not (settings.US3_PUBLIC_KEY and settings.US3_PRIVATE_KEY)


# 全局单例
local_storage = LocalStorage()
