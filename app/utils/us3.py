#!/usr/bin/env python3
"""
UCloud US3 文件管理客户端
基于官方Python SDK实现完整的文件上传、下载、管理功能
参考文档: https://ucloud-us3.github.io/python-sdk/%E5%BF%AB%E9%80%9F%E4%BD%BF%E7%94%A8.html
"""

import os
import time
import hashlib
from typing import Dict, Any, Optional, List, Union
from pathlib import Path
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
    
    def __init__(self, public_key: str = None, private_key: str = None, 
                 upload_suffix: str = None, download_suffix: str = None,
                 default_bucket: str = None):
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
        
        logger.info(f"US3客户端初始化成功，上传后缀: {self.upload_suffix}, 下载后缀: {self.download_suffix}")
    
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
                    'success': True,
                    'bucket': bucket,
                    'region': region,
                    'response': ret,
                    'status_code': resp.status_code,
                    'message': '存储空间创建成功'
                }
            else:
                error_msg = f"存储空间创建失败，状态码: {resp.status_code}"
                logger.error(error_msg)
                return {
                    'success': False,
                    'bucket': bucket,
                    'region': region,
                    'response': ret,
                    'status_code': resp.status_code,
                    'message': error_msg
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
                    'success': True,
                    'bucket': bucket,
                    'response': ret,
                    'status_code': resp.status_code,
                    'message': '存储空间删除成功'
                }
            else:
                error_msg = f"存储空间删除失败，状态码: {resp.status_code}"
                logger.error(error_msg)
                return {
                    'success': False,
                    'bucket': bucket,
                    'response': ret,
                    'status_code': resp.status_code,
                    'message': error_msg
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
                    'success': True,
                    'bucket': bucket,
                    'info': ret,
                    'response': ret,
                    'status_code': resp.status_code,
                    'message': '获取存储空间信息成功'
                }
            else:
                error_msg = f"获取存储空间信息失败，状态码: {resp.status_code}"
                logger.error(error_msg)
                return {
                    'success': False,
                    'bucket': bucket,
                    'info': None,
                    'response': ret,
                    'status_code': resp.status_code,
                    'message': error_msg
                }
                
        except Exception as e:
            error_msg = f"获取存储空间信息异常: {str(e)}"
            logger.error(error_msg)
            raise US3UploadError(error_msg)
    
    # ==================== 文件上传 ====================
    
    def upload_file(self, local_file: str, bucket: str = None, put_key: str = None, 
                   header: Dict[str, str] = None, verify_hash: bool = True) -> Dict[str, Any]:
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
            ret, resp = self.file_manager.putfile(bucket, put_key, local_file, header=header)
            
            if resp.status_code == 200:
                logger.info(f"文件上传成功: {bucket}/{put_key}")
                return {
                    'success': True,
                    'bucket': bucket,
                    'key': put_key,
                    'local_file': local_file,
                    'file_hash': file_hash,
                    'file_size': os.path.getsize(local_file),
                    'response': ret,
                    'status_code': resp.status_code,
                    'message': '文件上传成功'
                }
            else:
                error_msg = f"文件上传失败，状态码: {resp.status_code}"
                logger.error(error_msg)
                return {
                    'success': False,
                    'bucket': bucket,
                    'key': put_key,
                    'local_file': local_file,
                    'file_hash': file_hash,
                    'response': ret,
                    'status_code': resp.status_code,
                    'message': error_msg
                }
                
        except Exception as e:
            error_msg = f"上传文件异常: {str(e)}"
            logger.error(error_msg)
            raise US3UploadError(error_msg)
    
    def upload_file_stream(self, file_stream: bytes, bucket: str = None, put_key: str = None,
                          header: Dict[str, str] = None) -> Dict[str, Any]:
        """
        上传文件流到US3
        
        Args:
            file_stream: 文件流数据
            bucket: 存储空间名称
            put_key: 上传文件在空间中的名称
            header: 请求头
            
        Returns:
            包含上传结果的字典
        """
        try:
            bucket = self._get_bucket(bucket)
            
            if not put_key:
                raise ValueError("上传文件流时必须指定put_key")
            
            logger.info(f"开始上传文件流: {bucket}/{put_key}")
            
            # 上传文件流
            ret, resp = self.file_manager.putfile(bucket, put_key, file_stream, header=header)
            
            if resp.status_code == 200:
                logger.info(f"文件流上传成功: {bucket}/{put_key}")
                return {
                    'success': True,
                    'bucket': bucket,
                    'key': put_key,
                    'file_size': len(file_stream),
                    'response': ret,
                    'status_code': resp.status_code,
                    'message': '文件流上传成功'
                }
            else:
                error_msg = f"文件流上传失败，状态码: {resp.status_code}"
                logger.error(error_msg)
                return {
                    'success': False,
                    'bucket': bucket,
                    'key': put_key,
                    'response': ret,
                    'status_code': resp.status_code,
                    'message': error_msg
                }
                
        except Exception as e:
            error_msg = f"上传文件流异常: {str(e)}"
            logger.error(error_msg)
            raise US3UploadError(error_msg)
    
    def download_file(self, bucket: str, put_key: str, save_file: str = None) -> Dict[str, Any]:
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
            ret, resp = self.file_manager.download_file(bucket, put_key, save_file, False)
            logger.info(f"download file response: {resp}")
            
            if resp.status_code == 200:
                logger.info(f"文件下载成功: {bucket}/{put_key} -> {save_file}")
                return {
                    'success': True,
                    'bucket': bucket,
                    'key': put_key,
                    'save_file': save_file,
                    'response': ret,
                    'status_code': resp.status_code,
                    'message': '文件下载成功'
                }
            else:
                error_msg = f"文件下载失败，状态码: {resp.status_code}"
                logger.error(error_msg)
                return {
                    'success': False,
                    'bucket': bucket,
                    'key': put_key,
                    'save_file': save_file,
                    'response': ret,
                    'status_code': resp.status_code,
                    'message': error_msg
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
                    'success': True,
                    'bucket': bucket,
                    'key': put_key,
                    'response': ret,
                    'status_code': resp.status_code,
                    'message': '文件删除成功'
                }
            else:
                error_msg = f"文件删除失败，状态码: {resp.status_code}"
                logger.error(error_msg)
                return {
                    'success': False,
                    'bucket': bucket,
                    'key': put_key,
                    'response': ret,
                    'status_code': resp.status_code,
                    'message': error_msg
                }
                
        except Exception as e:
            error_msg = f"删除文件异常: {str(e)}"
            logger.error(error_msg)
            raise US3UploadError(error_msg)
    
    def list_files(self, bucket: str, prefix: str = "", max_keys: int = 20) -> Dict[str, Any]:
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
            ret, resp = self.file_manager.getfilelist(bucket, prefix=prefix, maxkeys=max_keys)
            
            if resp.status_code == 200:
                files = ret.get("DataSet", [])
                logger.info(f"获取到 {len(files)} 个文件")
                return {
                    'success': True,
                    'bucket': bucket,
                    'prefix': prefix,
                    'files': files,
                    'count': len(files),
                    'response': ret,
                    'status_code': resp.status_code,
                    'message': f'成功获取 {len(files)} 个文件'
                }
            else:
                error_msg = f"获取文件列表失败，状态码: {resp.status_code}"
                logger.error(error_msg)
                return {
                    'success': False,
                    'bucket': bucket,
                    'prefix': prefix,
                    'files': [],
                    'count': 0,
                    'response': ret,
                    'status_code': resp.status_code,
                    'message': error_msg
                }
                
        except Exception as e:
            error_msg = f"获取文件列表异常: {str(e)}"
            logger.error(error_msg)
            raise US3UploadError(error_msg)
    
    def upload_directory(self, local_dir: str, bucket: str, prefix: str = "") -> Dict[str, Any]:
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
                        if result['success']:
                            success_count += 1
                        else:
                            error_count += 1
                    except Exception as e:
                        error_count += 1
                        results.append({
                            'success': False,
                            'local_file': local_file,
                            'bucket': bucket,
                            'key': put_key,
                            'message': f'上传失败: {str(e)}'
                        })
            
            logger.info(f"目录上传完成: 成功 {success_count} 个，失败 {error_count} 个")
            return {
                'success': error_count == 0,
                'local_dir': local_dir,
                'bucket': bucket,
                'prefix': prefix,
                'results': results,
                'success_count': success_count,
                'error_count': error_count,
                'total_count': len(results),
                'message': f'目录上传完成: 成功 {success_count} 个，失败 {error_count} 个'
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
        put_key = put_key.lstrip('/')
        url = f"https://{bucket}{self.download_suffix}/{put_key}"
        return url


# 便捷函数
def upload_file_to_us3(local_file: str, bucket: str, put_key: str = None, 
                      public_key: str = None, private_key: str = None) -> Dict[str, Any]:
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


def upload_directory_to_us3(local_dir: str, bucket: str, prefix: str = "",
                           public_key: str = None, private_key: str = None) -> Dict[str, Any]:
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
