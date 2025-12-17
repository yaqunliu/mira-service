#!/usr/bin/env python3
"""
统一的上传工具类
实现统一的上传路径规则和内网/外网地址转换
"""
import os
from datetime import datetime
from typing import Optional, Dict, Any
from app.core.config import settings
from app.core.logger import logger
from app.utils.us3 import US3Client, US3UploadError


class UploadHelper:
    """统一的上传工具类"""
    
    def __init__(self):
        """初始化上传工具"""
        self.env = getattr(settings, 'ENV', 'dev')
        self.bucket = getattr(settings, 'DEFAULT_BUCKET') or getattr(settings, 'US3_BUCKET', 'novel-agent')
        
        # 外网地址后缀（用于保存到数据库）
        self.external_download_suffix = getattr(settings, 'DOWNLOAD_SUFFIX', '.cn-sh2.ufileos.com')
        self.external_upload_suffix = getattr(settings, 'UPLOAD_SUFFIX', '.cn-sh2.ufileos.com')
        
        # 内网地址后缀（用于实际上传和下载）
        self.internal_download_suffix = getattr(settings, 'INTERNAL_DOWNLOAD_SUFFIX', '.internal-cn-sh2-01.ufileos.com')
        self.internal_upload_suffix = getattr(settings, 'INTERNAL_UPLOAD_SUFFIX', '.internal-cn-sh2-01.ufileos.com')
    
    def generate_upload_path(
        self,
        user_uuid: str,
        file_type: str,
        filename: str,
        time_str: Optional[str] = None
    ) -> str:
        """
        生成符合规则的上传路径
        
        路径格式: {env}/{time_str}/{user_uuid}/{file_type}/{filename}
        
        Args:
            user_uuid: 用户UUID
            file_type: 文件类型（如：novels, shots, characters, chapters）
            filename: 文件名
            time_str: 时间字符串（格式：YYYYMMDD），如果为None则自动生成
            
        Returns:
            上传路径（put_key）
        """
        if not time_str:
            time_str = datetime.now().strftime('%Y%m%d')
        
        # 确保路径格式正确
        path = f"{self.env}/{time_str}/{user_uuid}/{file_type}/{filename}"
        # 统一使用正斜杠
        path = path.replace("\\", "/")
        # 移除多余的斜杠
        path = "/".join(filter(None, path.split("/")))
        
        return path
    
    def convert_to_internal_url(self, url: str) -> str:
        """
        将外网URL转换为内网URL（用于下载）
        
        Args:
            url: 外网URL
            
        Returns:
            内网URL
        """
        if not url:
            return url
        
        # 如果已经是内网地址，直接返回
        if self.internal_download_suffix in url or self.internal_upload_suffix in url:
            return url
        
        # 替换外网后缀为内网后缀
        if self.external_download_suffix in url:
            url = url.replace(self.external_download_suffix, self.internal_download_suffix)
        elif self.external_upload_suffix in url:
            url = url.replace(self.external_upload_suffix, self.internal_upload_suffix)
        
        return url
    
    def convert_to_external_url(self, url: str) -> str:
        """
        将内网URL转换为外网URL（用于保存到数据库）
        
        Args:
            url: 内网URL或put_key
            
        Returns:
            外网URL
        """
        if not url:
            return url
        
        # 如果是put_key（不包含http://或https://），先转换为URL
        if not url.startswith('http://') and not url.startswith('https://'):
            # 这是put_key，直接生成外网URL
            put_key = url.lstrip("/")
            return f"https://{self.bucket}{self.external_download_suffix}/{put_key}"
        
        # 如果已经是外网地址，直接返回
        if self.external_download_suffix in url or self.external_upload_suffix in url:
            return url
        
        # 替换内网后缀为外网后缀
        if self.internal_download_suffix in url:
            url = url.replace(self.internal_download_suffix, self.external_download_suffix)
        elif self.internal_upload_suffix in url:
            url = url.replace(self.internal_upload_suffix, self.external_upload_suffix)
        
        return url
    
    def get_internal_upload_url(self, put_key: str) -> str:
        """
        生成内网上传URL（用于实际上传）
        
        Args:
            put_key: 文件路径
            
        Returns:
            内网上传URL
        """
        put_key = put_key.lstrip("/")
        return f"https://{self.bucket}{self.internal_upload_suffix}/{put_key}"
    
    def get_internal_download_url(self, put_key: str) -> str:
        """
        生成内网下载URL（用于实际下载）
        
        Args:
            put_key: 文件路径
            
        Returns:
            内网下载URL
        """
        put_key = put_key.lstrip("/")
        return f"https://{self.bucket}{self.internal_download_suffix}/{put_key}"
    
    def get_external_download_url(self, put_key: str) -> str:
        """
        生成外网下载URL（用于保存到数据库）
        
        Args:
            put_key: 文件路径
            
        Returns:
            外网下载URL
        """
        put_key = put_key.lstrip("/")
        return f"https://{self.bucket}{self.external_download_suffix}/{put_key}"
    
    def upload_file(
        self,
        local_file: str,
        user_uuid: str,
        file_type: str,
        filename: str,
        time_str: Optional[str] = None,
        bucket: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        上传文件（使用内网地址上传，返回外网地址用于保存）
        
        Args:
            local_file: 本地文件路径
            user_uuid: 用户UUID
            file_type: 文件类型（如：novels, shots, characters, chapters）
            filename: 文件名
            time_str: 时间字符串（格式：YYYYMMDD），如果为None则自动生成
            bucket: 存储桶名称，如果为None则使用默认bucket
            
        Returns:
            包含上传结果的字典，包含：
            - success: 是否成功
            - put_key: 文件路径（用于后续操作）
            - internal_url: 内网URL（用于下载）
            - external_url: 外网URL（用于保存到数据库）
            - 其他上传结果信息
        """
        try:
            # 生成上传路径
            put_key = self.generate_upload_path(user_uuid, file_type, filename, time_str)
            
            # 创建使用内网地址的US3客户端实例（线程安全）
            us3_client = US3Client(
                upload_suffix=self.internal_upload_suffix,
                download_suffix=self.internal_download_suffix
            )
            
            # 上传文件
            upload_result = us3_client.upload_file(
                local_file=local_file,
                bucket=bucket or self.bucket,
                put_key=put_key,
                verify_hash=False  # 关闭哈希验证以提高速度
            )
            
            if not upload_result.get('success'):
                raise US3UploadError(f"上传失败: {upload_result.get('message')}")
            
            # 生成内网和外网URL
            internal_url = self.get_internal_download_url(put_key)
            external_url = self.get_external_download_url(put_key)
            
            logger.info(f"文件上传成功: {put_key}, 内网URL: {internal_url}, 外网URL: {external_url}")
            
            return {
                "success": True,
                "put_key": put_key,
                "internal_url": internal_url,
                "external_url": external_url,
                "bucket": bucket or self.bucket,
                "file_size": upload_result.get('file_size'),
                "message": "文件上传成功"
            }
                
        except Exception as e:
            error_msg = f"上传文件失败: {str(e)}"
            logger.error(error_msg, exc_info=True)
            raise US3UploadError(error_msg)
    
    def download_file(
        self,
        url_or_put_key: str,
        save_file: str,
        bucket: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        下载文件（使用内网地址下载）
        
        Args:
            url_or_put_key: 外网URL或put_key
            save_file: 保存文件的本地路径
            bucket: 存储桶名称，如果为None则使用默认bucket
            
        Returns:
            包含下载结果的字典
        """
        try:
            # 如果是URL，提取put_key并转换为内网URL
            if url_or_put_key.startswith('http://') or url_or_put_key.startswith('https://'):
                # 这是URL，转换为内网URL
                internal_url = self.convert_to_internal_url(url_or_put_key)
                # 从URL中提取put_key
                # URL格式: https://{bucket}{suffix}/{put_key}
                if self.internal_download_suffix in internal_url:
                    put_key = internal_url.split(self.internal_download_suffix + '/', 1)[1]
                elif self.external_download_suffix in url_or_put_key:
                    put_key = url_or_put_key.split(self.external_download_suffix + '/', 1)[1]
                else:
                    # 尝试从URL中提取
                    parts = internal_url.split('/', 3)
                    if len(parts) >= 4:
                        put_key = parts[3]
                    else:
                        raise ValueError(f"无法从URL中提取put_key: {url_or_put_key}")
            else:
                # 这是put_key
                put_key = url_or_put_key
                internal_url = self.get_internal_download_url(put_key)
            
            # 创建使用内网地址的US3客户端实例（线程安全）
            us3_client = US3Client(
                upload_suffix=self.internal_upload_suffix,
                download_suffix=self.internal_download_suffix
            )
            
            # 下载文件
            download_result = us3_client.download_file(
                bucket=bucket or self.bucket,
                put_key=put_key,
                save_file=save_file
            )
            
            if not download_result.get('success'):
                raise US3UploadError(f"下载失败: {download_result.get('message')}")
            
            logger.info(f"文件下载成功: {put_key} -> {save_file}")
            
            return {
                "success": True,
                "put_key": put_key,
                "save_file": save_file,
                "internal_url": internal_url,
                "message": "文件下载成功"
            }
                
        except Exception as e:
            error_msg = f"下载文件失败: {str(e)}"
            logger.error(error_msg, exc_info=True)
            raise US3UploadError(error_msg)


# 创建全局实例
upload_helper = UploadHelper()

