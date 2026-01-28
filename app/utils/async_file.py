"""
异步文件操作工具 - Async File Operations

提供异步文件读写、目录操作等功能
"""

import os
import aiofiles
import aiofiles.os
from pathlib import Path
from typing import AsyncGenerator, BinaryIO, Optional, Union
from app.core.logger import logger


PathType = Union[str, Path]


class AsyncFileUtils:
    """
    异步文件操作工具类

    封装 aiofiles 提供异步文件操作
    """

    @staticmethod
    async def read(
        file_path: PathType,
        mode: str = "r",
        encoding: str = "utf-8"
    ) -> str:
        """
        异步读取文件内容

        Args:
            file_path: 文件路径
            mode: 读取模式
            encoding: 编码格式

        Returns:
            文件内容字符串
        """
        async with aiofiles.open(file_path, mode=mode, encoding=encoding) as f:
            return await f.read()

    @staticmethod
    async def read_bytes(file_path: PathType) -> bytes:
        """
        异步读取二进制文件

        Args:
            file_path: 文件路径

        Returns:
            二进制数据
        """
        async with aiofiles.open(file_path, "rb") as f:
            return await f.read()

    @staticmethod
    async def write(
        file_path: PathType,
        content: str,
        mode: str = "w",
        encoding: str = "utf-8"
    ) -> None:
        """
        异步写入文件

        Args:
            file_path: 文件路径
            content: 写入内容
            mode: 写入模式
            encoding: 编码格式
        """
        Path(file_path).parent.mkdir(parents=True, exist_ok=True)
        async with aiofiles.open(file_path, mode=mode, encoding=encoding) as f:
            await f.write(content)

    @staticmethod
    async def write_bytes(file_path: PathType, content: bytes) -> None:
        """
        异步写入二进制文件

        Args:
            file_path: 文件路径
            content: 二进制数据
        """
        Path(file_path).parent.mkdir(parents=True, exist_ok=True)
        async with aiofiles.open(file_path, "wb") as f:
            await f.write(content)

    @staticmethod
    async def append(
        file_path: PathType,
        content: str,
        encoding: str = "utf-8"
    ) -> None:
        """
        异步追加内容到文件

        Args:
            file_path: 文件路径
            content: 追加内容
            encoding: 编码格式
        """
        async with aiofiles.open(file_path, "a", encoding=encoding) as f:
            await f.write(content)

    @staticmethod
    async def exists(file_path: PathType) -> bool:
        """
        异步检查文件是否存在

        Args:
            file_path: 文件路径

        Returns:
            是否存在
        """
        return await aiofiles.os.path.exists(file_path)

    @staticmethod
    async def is_file(file_path: PathType) -> bool:
        """
        异步检查是否为文件

        Args:
            file_path: 路径

        Returns:
            是否为文件
        """
        return await aiofiles.os.path.isfile(file_path)

    @staticmethod
    async def is_dir(file_path: PathType) -> bool:
        """
        异步检查是否为目录

        Args:
            file_path: 路径

        Returns:
            是否为目录
        """
        return await aiofiles.os.path.isdir(file_path)

    @staticmethod
    async def list_dir(dir_path: PathType) -> list:
        """
        异步列出目录内容

        Args:
            dir_path: 目录路径

        Returns:
            文件/目录名列表
        """
        entries = []
        async for entry in aiofiles.os.scandir(dir_path):
            entries.append(entry.name)
        return entries

    @staticmethod
    async def mkdir(
        dir_path: PathType,
        parents: bool = True,
        exist_ok: bool = True
    ) -> None:
        """
        异步创建目录

        Args:
            dir_path: 目录路径
            parents: 是否创建父目录
            exist_ok: 目录存在时是否报错
        """
        await aiofiles.os.makedirs(dir_path, exist_ok=exist_ok) if parents else await aiofiles.os.mkdir(dir_path)

    @staticmethod
    async def remove(file_path: PathType) -> None:
        """
        异步删除文件

        Args:
            file_path: 文件路径
        """
        if await aiofiles.os.path.exists(file_path):
            await aiofiles.os.remove(file_path)

    @staticmethod
    async def rmdir(dir_path: PathType) -> None:
        """
        异步删除空目录

        Args:
            dir_path: 目录路径
        """
        if await aiofiles.os.path.isdir(dir_path):
            await aiofiles.os.rmdir(dir_path)

    @staticmethod
    async def rename(src: PathType, dst: PathType) -> None:
        """
        异步重命名文件或目录

        Args:
            src: 原路径
            dst: 目标路径
        """
        await aiofiles.os.rename(src, dst)

    @staticmethod
    async def get_size(file_path: PathType) -> int:
        """
        异步获取文件大小

        Args:
            file_path: 文件路径

        Returns:
            文件大小（字节）
        """
        stat = await aiofiles.os.stat(file_path)
        return stat.st_size

    @staticmethod
    async def get_mtime(file_path: PathType) -> float:
        """
        异步获取文件修改时间

        Args:
            file_path: 文件路径

        Returns:
            修改时间戳
        """
        stat = await aiofiles.os.stat(file_path)
        return stat.st_mtime

    @staticmethod
    async def walk(
        dir_path: PathType,
        topdown: bool = True
    ) -> AsyncGenerator[tuple, None, None]:
        """
        异步遍历目录树

        Args:
            dir_path: 起始目录
            topdown: 是否自顶向下遍历

        Yields:
            (dirpath, dirnames, filenames) 元组
        """
        for dirpath, dirnames, filenames in await aiofiles.os.walk(dir_path, topdown=topdown):
            yield (dirpath, dirnames, filenames)

    @staticmethod
    async def glob(
        dir_path: PathType,
        pattern: str
    ) -> list:
        """
        异步查找匹配文件

        Args:
            dir_path: 搜索目录
            pattern: 匹配模式

        Returns:
            匹配的文件路径列表
        """
        path = Path(dir_path)
        return [str(p) for p in path.glob(pattern)]


async def async_read_large_file(
    file_path: PathType,
    chunk_size: int = 8192
) -> AsyncGenerator[bytes, None]:
    """
    异步分块读取大文件

    Args:
        file_path: 文件路径
        chunk_size: 块大小

    Yields:
        文件块二进制数据
    """
    async with aiofiles.open(file_path, "rb") as f:
        while True:
            chunk = await f.read(chunk_size)
            if not chunk:
                break
            yield chunk


async def async_write_large_file(
    file_path: PathType,
    data_generator: AsyncGenerator[bytes, None]
) -> None:
    """
    异步分块写入大文件

    Args:
        file_path: 文件路径
        data_generator: 数据生成器
    """
    Path(file_path).parent.mkdir(parents=True, exist_ok=True)
    async with aiofiles.open(file_path, "wb") as f:
        async for chunk in data_generator:
            await f.write(chunk)


class ChunkedFileUploader:
    """
    分块文件上传器

    支持大文件的分块上传和断点续传
    """

    def __init__(
        self,
        file_path: PathType,
        total_size: int,
        chunk_size: int = 1024 * 1024  # 1MB
    ):
        """
        初始化上传器

        Args:
            file_path: 目标文件路径
            total_size: 文件总大小
            chunk_size: 块大小
        """
        self.file_path = file_path
        self.total_size = total_size
        self.chunk_size = chunk_size
        self.uploaded_chunks = set()
        self.current_position = 0

    async def upload_chunk(self, chunk_data: bytes, chunk_index: int) -> dict:
        """
        上传单个块

        Args:
            chunk_data: 块数据
            chunk_index: 块索引

        Returns:
            上传结果
        """
        start = chunk_index * self.chunk_size
        self.current_position = start + len(chunk_data)
        self.uploaded_chunks.add(chunk_index)

        async with aiofiles.open(self.file_path, "r+b") as f:
            await f.seek(start)
            await f.write(chunk_data)

        return {
            "chunk_index": chunk_index,
            "uploaded": self.current_position,
            "total": self.total_size,
            "progress": self.current_position / self.total_size * 100
        }

    async def complete_upload(self) -> dict:
        """
        完成上传

        Returns:
            完成结果
        """
        return {
            "file_path": str(self.file_path),
            "total_size": self.total_size,
            "chunks_uploaded": len(self.uploaded_chunks)
        }
