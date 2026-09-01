#!/usr/bin/env python3
"""
UCloud US3 文件管理客户端
基于官方Python SDK实现完整的文件上传、下载、管理功能
参考文档: https://ucloud-us3.github.io/python-sdk/%E5%BF%AB%E9%80%9F%E4%BD%BF%E7%94%A8.html
"""

import os
import time
import shutil
import hashlib
import httpx
from typing import Dict, Any, Optional, List, Union
from pathlib import Path
from io import BytesIO
from urllib.parse import urlparse
from app.core.config import settings
from app.core.logger import logger

try:
    from ufile import config as ufile_config, filemanager

    US3_SDK_AVAILABLE = True
    logger.info("检测到UCloud US3 SDK，将使用官方SDK")
except ImportError:
    US3_SDK_AVAILABLE = False
    logger.warning("未检测到UCloud US3 SDK，请安装: pip install ufile")


class US3UploadError(Exception):
    """US3上传异常"""

    pass


class US3Client:
    """UCloud US3 文件管理客户端"""

    def __init__(
        self,
        public_key: str = None,
        private_key: str = None,
        upload_suffix: str = None,
        download_suffix: str = None,
        default_bucket: str = None,
        region: str = None,
    ):
        """
        初始化US3客户端

        Args:
            public_key: 账户公钥
            private_key: 账户私钥
            upload_suffix: 上传host后缀
            download_suffix: 下载host后缀
            default_bucket: 默认存储空间名称
        """
        if not US3_SDK_AVAILABLE:
            raise ImportError("UCloud US3 SDK未安装，请运行: pip install ufile")

        # 从配置文件获取配置
        self.public_key = public_key or settings.US3_PUBLIC_KEY
        self.private_key = private_key or settings.US3_PRIVATE_KEY
        self.upload_suffix = upload_suffix or settings.UPLOAD_SUFFIX
        self.download_suffix = download_suffix or settings.DOWNLOAD_SUFFIX
        self.default_bucket = default_bucket or settings.DEFAULT_BUCKET
        
        if not self.public_key or not self.private_key:
            raise ValueError("UCloud US3 公钥或私钥未配置")

        # 设置默认配置
        ufile_config.set_default(uploadsuffix=self.upload_suffix)
        ufile_config.set_default(downloadsuffix=self.download_suffix)

        # 创建文件管理器
        self.file_manager = filemanager.FileManager(self.public_key, self.private_key)
        logger.info(
            f"US3客户端初始化成功，上传后缀: {self.upload_suffix}, 下载后缀: {self.download_suffix}"
        )

    def _get_bucket(self, bucket: str = None) -> str:
        """获取存储空间名称，优先使用传入的bucket，否则使用默认bucket"""
        if bucket:
            return bucket
        if self.default_bucket:
            return self.default_bucket
        raise ValueError("未指定存储空间名称，请在参数中指定或配置默认bucket")

    def _calculate_file_hash(self, file_path: str) -> str:
        """计算文件MD5哈希值"""
        hash_md5 = hashlib.md5()
        with open(file_path, "rb") as f:
            for chunk in iter(lambda: f.read(4096), b""):
                hash_md5.update(chunk)
        return hash_md5.hexdigest()

    # ==================== 存储空间管理 ====================

    def create_bucket(self, bucket: str, region: str = "cn-bj") -> Dict[str, Any]:
        """
        创建存储空间

        Args:
            bucket: 存储空间名称
            region: 地域

        Returns:
            包含创建结果的字典
        """
        try:
            logger.info(f"开始创建存储空间: {bucket}")

            ret, resp = self.file_manager.create_bucket(bucket, region=region)

            if resp.status_code == 200:
                logger.info(f"存储空间创建成功: {bucket}")
                return {
                    "success": True,
                    "bucket": bucket,
                    "region": region,
                    "response": ret,
                    "status_code": resp.status_code,
                    "message": "存储空间创建成功",
                }
            else:
                error_msg = f"存储空间创建失败，状态码: {resp.status_code}"
                logger.error(error_msg)
                return {
                    "success": False,
                    "bucket": bucket,
                    "region": region,
                    "response": ret,
                    "status_code": resp.status_code,
                    "message": error_msg,
                }

        except Exception as e:
            error_msg = f"创建存储空间异常: {str(e)}"
            logger.error(error_msg)
            raise US3UploadError(error_msg)

    def delete_bucket(self, bucket: str) -> Dict[str, Any]:
        """
        删除存储空间

        Args:
            bucket: 存储空间名称

        Returns:
            包含删除结果的字典
        """
        try:
            logger.info(f"开始删除存储空间: {bucket}")

            ret, resp = self.file_manager.delete_bucket(bucket)

            if resp.status_code == 204:
                logger.info(f"存储空间删除成功: {bucket}")
                return {
                    "success": True,
                    "bucket": bucket,
                    "response": ret,
                    "status_code": resp.status_code,
                    "message": "存储空间删除成功",
                }
            else:
                error_msg = f"存储空间删除失败，状态码: {resp.status_code}"
                logger.error(error_msg)
                return {
                    "success": False,
                    "bucket": bucket,
                    "response": ret,
                    "status_code": resp.status_code,
                    "message": error_msg,
                }

        except Exception as e:
            error_msg = f"删除存储空间异常: {str(e)}"
            logger.error(error_msg)
            raise US3UploadError(error_msg)

    def get_bucket_info(self, bucket: str) -> Dict[str, Any]:
        """
        获取存储空间信息

        Args:
            bucket: 存储空间名称

        Returns:
            包含存储空间信息的字典
        """
        try:
            logger.info(f"开始获取存储空间信息: {bucket}")

            ret, resp = self.file_manager.get_bucket_info(bucket)

            if resp.status_code == 200:
                logger.info(f"获取存储空间信息成功: {bucket}")
                return {
                    "success": True,
                    "bucket": bucket,
                    "info": ret,
                    "response": ret,
                    "status_code": resp.status_code,
                    "message": "获取存储空间信息成功",
                }
            else:
                error_msg = f"获取存储空间信息失败，状态码: {resp.status_code}"
                logger.error(error_msg)
                return {
                    "success": False,
                    "bucket": bucket,
                    "info": None,
                    "response": ret,
                    "status_code": resp.status_code,
                    "message": error_msg,
                }

        except Exception as e:
            error_msg = f"获取存储空间信息异常: {str(e)}"
            logger.error(error_msg)
            raise US3UploadError(error_msg)

    # ==================== 文件上传 ====================

    def upload_file(
        self,
        local_file: str,
        bucket: str = None,
        put_key: str = None,
        header: Dict[str, str] = None,
        verify_hash: bool = True,
    ) -> Dict[str, Any]:
        """
        上传文件到US3

        Args:
            local_file: 本地文件路径
            bucket: 存储空间名称，如果为None则使用默认bucket
            put_key: 上传文件在空间中的名称，如果为None则使用文件名
            header: 请求头
            verify_hash: 是否验证文件哈希值

        Returns:
            包含上传结果的字典
        """
        try:
            # 检查本地文件是否存在
            if not os.path.exists(local_file):
                raise US3UploadError(f"本地文件不存在: {local_file}")

            # 获取存储空间名称
            bucket = self._get_bucket(bucket)

            # 如果没有指定put_key，使用文件名
            if not put_key:
                put_key = os.path.basename(local_file)

            # 计算文件哈希值
            file_hash = None
            if verify_hash:
                file_hash = self._calculate_file_hash(local_file)
                logger.info(f"文件哈希值: {file_hash}")

            logger.info(f"开始上传文件: {local_file} -> {bucket}/{put_key}")

            # 上传文件
            ret, resp = self.file_manager.putfile(
                bucket, put_key, local_file, header=header
            )

            if resp.status_code == 200:
                logger.info(f"文件上传成功: {bucket}/{put_key}")
                return {
                    "success": True,
                    "bucket": bucket,
                    "key": put_key,
                    "local_file": local_file,
                    "file_hash": file_hash,
                    "file_size": os.path.getsize(local_file),
                    "response": ret,
                    "status_code": resp.status_code,
                    "message": "文件上传成功",
                }
            else:
                error_msg = f"文件上传失败，状态码: {resp.status_code}"
                print(resp)
                logger.error(error_msg)
                return {
                    "success": False,
                    "bucket": bucket,
                    "key": put_key,
                    "local_file": local_file,
                    "file_hash": file_hash,
                    "response": ret,
                    "status_code": resp.status_code,
                    "message": error_msg,
                }

        except Exception as e:
            error_msg = f"上传文件异常: {str(e)}"
            logger.error(error_msg)
            raise US3UploadError(error_msg)

    def upload_file_stream(
        self,
        file_stream: bytes,
        bucket: str = None,
        put_key: str = None,
        header: Dict[str, str] = None,
        content_type: str = None,
    ) -> Dict[str, Any]:
        """
        上传文件流到US3

        Args:
            file_stream: 文件流数据
            bucket: 存储空间名称
            put_key: 上传文件在空间中的名称
            header: 请求头
            content_type: 内容类型（如 'image/png', 'image/jpeg'）

        Returns:
            包含上传结果的字典
        """
        try:
            bucket = self._get_bucket(bucket)

            if not put_key:
                raise ValueError("上传文件流时必须指定put_key")

            logger.info(f"开始上传文件流: {bucket}/{put_key}, 大小: {len(file_stream)} 字节")

            # 确保 put_key 是字符串类型（UTF-8编码）
            if isinstance(put_key, bytes):
                put_key = put_key.decode('utf-8')
            
            # 确保 file_stream 是 bytes 类型
            if not isinstance(file_stream, bytes):
                if hasattr(file_stream, 'read'):
                    # 如果是文件对象，读取为 bytes
                    file_stream = file_stream.read()
                else:
                    raise ValueError(f"file_stream 必须是 bytes 类型，当前类型: {type(file_stream)}")
            
            # 设置请求头，确保正确处理二进制数据
            if header is None:
                header = {}
            
            # 如果指定了 content_type，添加到 header 中
            if content_type and 'Content-Type' not in header:
                header['Content-Type'] = content_type
            
            # 使用临时文件方式上传，避免编码问题
            # US3 SDK 的 putfile 可能对 BytesIO 支持不好，使用临时文件更可靠
            import tempfile
            temp_file_path = None
            try:
                # 创建临时文件
                temp_fd, temp_file_path = tempfile.mkstemp()
                try:
                    with os.fdopen(temp_fd, 'wb') as tmp_file:
                        tmp_file.write(file_stream)
                    
                    # 使用临时文件路径上传
                    ret, resp = self.file_manager.putfile(
                        bucket, put_key, temp_file_path, header=header
                    )
                finally:
                    # 清理临时文件
                    if temp_file_path and os.path.exists(temp_file_path):
                        try:
                            os.remove(temp_file_path)
                        except Exception as e:
                            logger.warning(f"删除临时文件失败: {temp_file_path}, {str(e)}")
            except Exception as e:
                # 如果临时文件方式失败，清理并重新抛出异常
                if temp_file_path and os.path.exists(temp_file_path):
                    try:
                        os.remove(temp_file_path)
                    except:
                        pass
                raise

            if resp.status_code == 200:
                logger.info(f"文件流上传成功: {bucket}/{put_key}")
                return {
                    "success": True,
                    "bucket": bucket,
                    "key": put_key,
                    "file_size": len(file_stream),
                    "response": ret,
                    "status_code": resp.status_code,
                    "message": "文件流上传成功",
                }
            else:
                error_msg = f"文件流上传失败，状态码: {resp.status_code}"
                logger.error(error_msg)
                return {
                    "success": False,
                    "bucket": bucket,
                    "key": put_key,
                    "response": ret,
                    "status_code": resp.status_code,
                    "message": error_msg,
                }

        except Exception as e:
            error_msg = f"上传文件流异常: {str(e)}"
            logger.error(error_msg)
            raise US3UploadError(error_msg)

    def download_file(
        self, bucket: str, put_key: str, save_file: str = None
    ) -> Dict[str, Any]:
        """
        从US3下载文件

        Args:
            bucket: 存储空间名称
            put_key: 文件在空间中的名称
            save_file: 保存文件的本地路径，如果为None则使用put_key作为文件名

        Returns:
            包含下载结果的字典
        """
        try:
            bucket = self._get_bucket(bucket)
            # 如果没有指定保存路径，使用put_key作为文件名
            if not save_file:
                save_file = os.path.basename(put_key)

            logger.info(f"开始下载文件: {bucket}/{put_key} -> {save_file}")

            # 下载文件
            ret, resp = self.file_manager.download_file(
                bucket, put_key, save_file, False
            )
            logger.info(f"download file response: {resp}")

            if resp.status_code == 200:
                logger.info(f"文件下载成功: {bucket}/{put_key} -> {save_file}")
                return {
                    "success": True,
                    "bucket": bucket,
                    "key": put_key,
                    "save_file": save_file,
                    "response": ret,
                    "status_code": resp.status_code,
                    "message": "文件下载成功",
                }
            else:
                error_msg = f"文件下载失败，状态码: {resp.status_code}"
                logger.error(error_msg)
                return {
                    "success": False,
                    "bucket": bucket,
                    "key": put_key,
                    "save_file": save_file,
                    "response": ret,
                    "status_code": resp.status_code,
                    "message": error_msg,
                }

        except Exception as e:
            error_msg = f"下载文件异常: {str(e)}"
            logger.error(error_msg)
            raise US3UploadError(error_msg)

    def delete_file(self, bucket: str, put_key: str) -> Dict[str, Any]:
        """
        删除US3中的文件

        Args:
            bucket: 存储空间名称
            put_key: 文件在空间中的名称

        Returns:
            包含删除结果的字典
        """
        try:
            logger.info(f"开始删除文件: {bucket}/{put_key}")

            # 删除文件
            ret, resp = self.file_manager.deletefile(bucket, put_key)

            if resp.status_code == 204:
                logger.info(f"文件删除成功: {bucket}/{put_key}")
                return {
                    "success": True,
                    "bucket": bucket,
                    "key": put_key,
                    "response": ret,
                    "status_code": resp.status_code,
                    "message": "文件删除成功",
                }
            else:
                error_msg = f"文件删除失败，状态码: {resp.status_code}"
                logger.error(error_msg)
                return {
                    "success": False,
                    "bucket": bucket,
                    "key": put_key,
                    "response": ret,
                    "status_code": resp.status_code,
                    "message": error_msg,
                }

        except Exception as e:
            error_msg = f"删除文件异常: {str(e)}"
            logger.error(error_msg)
            raise US3UploadError(error_msg)

    def list_files(
        self, bucket: str, prefix: str = "", max_keys: int = 20
    ) -> Dict[str, Any]:
        """
        列出存储空间中的文件

        Args:
            bucket: 存储空间名称
            prefix: 文件前缀过滤
            max_keys: 最大返回文件数量

        Returns:
            包含文件列表的字典
        """
        try:
            logger.info(f"开始列出文件: {bucket}, 前缀: {prefix}, 最大数量: {max_keys}")

            # 获取文件列表
            ret, resp = self.file_manager.getfilelist(
                bucket, prefix=prefix, maxkeys=max_keys
            )

            if resp.status_code == 200:
                files = ret.get("DataSet", [])
                logger.info(f"获取到 {len(files)} 个文件")
                return {
                    "success": True,
                    "bucket": bucket,
                    "prefix": prefix,
                    "files": files,
                    "count": len(files),
                    "response": ret,
                    "status_code": resp.status_code,
                    "message": f"成功获取 {len(files)} 个文件",
                }
            else:
                error_msg = f"获取文件列表失败，状态码: {resp.status_code}"
                logger.error(error_msg)
                return {
                    "success": False,
                    "bucket": bucket,
                    "prefix": prefix,
                    "files": [],
                    "count": 0,
                    "response": ret,
                    "status_code": resp.status_code,
                    "message": error_msg,
                }

        except Exception as e:
            error_msg = f"获取文件列表异常: {str(e)}"
            logger.error(error_msg)
            raise US3UploadError(error_msg)

    def upload_directory(
        self, local_dir: str, bucket: str, prefix: str = ""
    ) -> Dict[str, Any]:
        """
        上传整个目录到US3

        Args:
            local_dir: 本地目录路径
            bucket: 存储空间名称
            prefix: 上传文件的前缀

        Returns:
            包含上传结果的字典
        """
        try:
            if not os.path.isdir(local_dir):
                raise US3UploadError(f"本地目录不存在: {local_dir}")

            results = []
            success_count = 0
            error_count = 0

            # 遍历目录中的所有文件
            for root, dirs, files in os.walk(local_dir):
                for file in files:
                    local_file = os.path.join(root, file)
                    # 计算相对路径作为put_key
                    rel_path = os.path.relpath(local_file, local_dir)
                    put_key = f"{prefix}/{rel_path}" if prefix else rel_path
                    # 统一使用正斜杠
                    put_key = put_key.replace("\\", "/")

                    try:
                        result = self.upload_file(local_file, bucket, put_key)
                        results.append(result)
                        if result["success"]:
                            success_count += 1
                        else:
                            error_count += 1
                    except Exception as e:
                        error_count += 1
                        results.append(
                            {
                                "success": False,
                                "local_file": local_file,
                                "bucket": bucket,
                                "key": put_key,
                                "message": f"上传失败: {str(e)}",
                            }
                        )

            logger.info(f"目录上传完成: 成功 {success_count} 个，失败 {error_count} 个")
            return {
                "success": error_count == 0,
                "local_dir": local_dir,
                "bucket": bucket,
                "prefix": prefix,
                "results": results,
                "success_count": success_count,
                "error_count": error_count,
                "total_count": len(results),
                "message": f"目录上传完成: 成功 {success_count} 个，失败 {error_count} 个",
            }

        except Exception as e:
            error_msg = f"上传目录异常: {str(e)}"
            logger.error(error_msg)
            raise US3UploadError(error_msg)

    def get_file_url(self, put_key: str, bucket: str = None) -> str:
        """
        生成文件的访问URL

        Args:
            put_key: 文件在空间中的名称
            bucket: 存储空间名称，如果为None则使用默认bucket

        Returns:
            文件的访问URL
        """
        bucket = self._get_bucket(bucket)
        # US3 URL格式: https://{bucket}.{download_suffix}/{put_key}
        if not self.download_suffix:
            raise ValueError("DOWNLOAD_SUFFIX 未配置，无法生成文件URL")

        # 确保put_key不以/开头
        put_key = put_key.lstrip("/")
        url = f"https://{bucket}{self.download_suffix}/{put_key}"
        return url

    @staticmethod
    def is_us3_url(url_or_key: str) -> bool:
        """
        判断 URL 或 key 是否是 US3 链接
        
        Args:
            url_or_key: URL 或文件 key
            
        Returns:
            如果是 US3 链接返回 True，否则返回 False
        """
        if not url_or_key:
            return False
        
        # 检查是否包含 ufileos.com（US3 的域名特征）
        return 'ufileos.com' in url_or_key

    @staticmethod
    def parse_us3_url(url: str) -> tuple[Optional[str], Optional[str]]:
        """
        解析 US3 URL，提取 bucket 和 put_key
        
        Args:
            url: US3 URL，格式为 https://{bucket}.{suffix}/{put_key}
            
        Returns:
            (bucket, put_key) 元组，如果解析失败返回 (None, None)
        """
        try:
            parsed = urlparse(url)
            # US3 URL 格式: https://{bucket}.{suffix}/{put_key}
            # 例如: https://mira-video.hk.ufileos.com/staging/20251211/...
            hostname = parsed.hostname
            if not hostname or 'ufileos.com' not in hostname:
                return None, None
            
            # 提取 bucket（hostname 的第一部分）
            bucket = hostname.split('.')[0]
            
            # 提取 put_key（path 去掉开头的 /）
            put_key = parsed.path.lstrip('/')
            
            return bucket, put_key
        except Exception as e:
            logger.warning(f"解析 US3 URL 失败: {url}, error: {e}")
            return None, None


def download_file_smart(
    url_or_key: str,
    save_file: str,
    bucket: Optional[str] = None,
    timeout: int = 60
) -> Dict[str, Any]:
    """
    智能下载文件：如果是 US3 链接且 bucket 匹配则使用 US3 下载，否则使用 HTTP 下载
    
    Args:
        url_or_key: 文件 URL 或 US3 key
        save_file: 保存文件的本地路径
        bucket: US3 bucket（如果 url_or_key 是 key 时需要指定）
        timeout: HTTP 下载超时时间（秒）
        
    Returns:
        包含下载结果的字典
    """
    try:
        # 优先判断是否是本地存储引用（US3 降级方案）
        # 命中时直接读文件系统，不走网络，也就不依赖服务自身的 URL 可达性
        from app.utils.local_storage import local_storage

        local_path = local_storage.locate(url_or_key)
        if local_path:
            logger.info(f"检测到本地存储文件: {local_path}")
            os.makedirs(os.path.dirname(os.path.abspath(save_file)), exist_ok=True)
            shutil.copyfile(local_path, save_file)
            return {
                "success": True,
                "save_file": save_file,
                "file_size": os.path.getsize(save_file),
                "storage_backend": "local",
                "message": "本地存储文件读取成功"
            }

        # 判断是否是 US3 链接
        if US3Client.is_us3_url(url_or_key):
            logger.info(f"检测到 US3 链接: {url_or_key}")
            
            # 解析 US3 URL 获取 bucket 和 put_key
            parsed_bucket, put_key = US3Client.parse_us3_url(url_or_key)
            
            if not put_key:
                # 如果解析失败，尝试将 url_or_key 作为 put_key 使用
                logger.warning(f"无法从 URL 解析 bucket 和 key，尝试作为 put_key 使用: {url_or_key}")
                put_key = url_or_key
                if not bucket:
                    # 如果也没有提供 bucket，尝试从配置获取
                    bucket = settings.DEFAULT_BUCKET
                    if not bucket:
                        logger.warning(f"无法确定 US3 bucket，使用 HTTP 下载: {url_or_key}")
                        return download_file_http(url_or_key, save_file, timeout)
            else:
                # 使用解析出的 bucket（如果提供了 bucket 参数则优先使用）
                if bucket:
                    logger.info(f"使用提供的 bucket: {bucket}")
                else:
                    bucket = parsed_bucket
                    if not bucket:
                        bucket = settings.DEFAULT_BUCKET
                        if not bucket:
                            logger.warning(f"无法确定 US3 bucket，使用 HTTP 下载: {url_or_key}")
                            return download_file_http(url_or_key, save_file, timeout)
            
            # 获取当前配置的 bucket
            configured_bucket = settings.DEFAULT_BUCKET or settings.US3_BUCKET
            if not configured_bucket:
                logger.warning(f"未配置 US3 bucket，使用 HTTP 下载: {url_or_key}")
                return download_file_http(url_or_key, save_file, timeout)
            
            # 检查 bucket 是否匹配
            if bucket != configured_bucket:
                logger.warning(
                    f"Bucket 不匹配，使用 HTTP 下载: "
                    f"URL bucket={bucket}, 配置 bucket={configured_bucket}, url={url_or_key}"
                )
                return download_file_http(url_or_key, save_file, timeout)
            
            # Bucket 匹配，使用 US3 下载
            logger.info(f"Bucket 匹配 ({bucket})，使用 US3 下载: {url_or_key}")
            us3_client = US3Client()
            download_result = us3_client.download_file(
                bucket=bucket,
                put_key=put_key,
                save_file=save_file
            )
            
            # 如果 US3 下载失败（如 404），尝试使用 HTTP 下载作为后备
            if not download_result.get('success') and download_result.get('status_code') == 404:
                logger.warning(f"US3 下载失败（404），尝试使用 HTTP 下载: {url_or_key}")
                return download_file_http(url_or_key, save_file, timeout)
            
            return download_result
        else:
            # 使用 HTTP 下载
            logger.info(f"检测到普通 URL，使用 HTTP 下载: {url_or_key}")
            return download_file_http(url_or_key, save_file, timeout)
            
    except Exception as e:
        error_msg = f"智能下载文件失败: {str(e)}"
        logger.error(error_msg, exc_info=True)
        # 发生异常时，尝试使用 HTTP 下载作为后备
        logger.warning(f"发生异常，尝试使用 HTTP 下载: {url_or_key}")
        return download_file_http(url_or_key, save_file, timeout)


def download_file_http(
    url: str,
    save_file: str,
    timeout: int = 60
) -> Dict[str, Any]:
    """
    使用 HTTP 下载文件
    
    Args:
        url: 文件 URL
        save_file: 保存文件的本地路径
        timeout: 超时时间（秒）
        
    Returns:
        包含下载结果的字典
    """
    try:
        logger.info(f"开始 HTTP 下载文件: {url} -> {save_file}")
        
        # 确保保存目录存在
        save_dir = os.path.dirname(save_file)
        if save_dir and not os.path.exists(save_dir):
            os.makedirs(save_dir, exist_ok=True)
        
        # 使用 httpx 下载
        timeout_config = httpx.Timeout(
            connect=10.0,
            read=timeout,
            write=10.0,
            pool=10.0,
        )
        
        with httpx.Client(timeout=timeout_config, follow_redirects=True) as client:
            response = client.get(url)
            response.raise_for_status()
            
            # 保存文件
            with open(save_file, 'wb') as f:
                f.write(response.content)
        
        file_size = os.path.getsize(save_file)
        logger.info(f"HTTP 文件下载成功: {url} -> {save_file}, 大小: {file_size} 字节")
        
        return {
            "success": True,
            "url": url,
            "save_file": save_file,
            "file_size": file_size,
            "status_code": response.status_code,
            "message": "文件下载成功",
        }
        
    except httpx.HTTPStatusError as e:
        error_msg = f"HTTP 下载失败，状态码: {e.response.status_code}"
        logger.error(f"{error_msg}: {url}")
        return {
            "success": False,
            "url": url,
            "save_file": save_file,
            "status_code": e.response.status_code,
            "message": error_msg,
        }
    except Exception as e:
        error_msg = f"HTTP 下载异常: {str(e)}"
        logger.error(f"{error_msg}: {url}", exc_info=True)
        return {
            "success": False,
            "url": url,
            "save_file": save_file,
            "message": error_msg,
        }


# 便捷函数
def upload_file_to_us3(
    local_file: str,
    bucket: str,
    put_key: str = None,
    public_key: str = None,
    private_key: str = None,
) -> Dict[str, Any]:
    """
    便捷的文件上传函数

    Args:
        local_file: 本地文件路径
        bucket: 存储空间名称
        put_key: 上传文件在空间中的名称
        public_key: 账户公钥
        private_key: 账户私钥

    Returns:
        包含上传结果的字典
    """
    client = US3Client(public_key, private_key)
    return client.upload_file(local_file, bucket, put_key)


def upload_directory_to_us3(
    local_dir: str,
    bucket: str,
    prefix: str = "",
    public_key: str = None,
    private_key: str = None,
) -> Dict[str, Any]:
    """
    便捷的目录上传函数

    Args:
        local_dir: 本地目录路径
        bucket: 存储空间名称
        prefix: 上传文件的前缀
        public_key: 账户公钥
        private_key: 账户私钥

    Returns:
        包含上传结果的字典
    """
    client = US3Client(public_key, private_key)
    return client.upload_directory(local_dir, bucket, prefix)
