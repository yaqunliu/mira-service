from typing import Optional, Dict, Any
import httpx
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.models.chapter import Chapter
from app.models.creation import Creation
from app.core.logger import logger
from app.core.config import settings


class ScriptLoader:
    """剧本加载器 - 从 chapter 的 content_url 下载并读取剧本内容"""

    async def get_script_from_creation(
        self,
        db: AsyncSession,
        creation_uuid: str
    ) -> Dict[str, Any]:
        """根据创作 UUID 获取剧本内容"""
        try:
            creation_stmt = select(Creation).where(Creation.uuid == creation_uuid)
            creation_result = await db.execute(creation_stmt)
            creation = creation_result.scalar_one_or_none()

            if not creation:
                return {"error": "创作项目不存在"}

            if not creation.chapter_id:
                return {"error": "创作项目未关联章节"}

            chapter_stmt = select(Chapter).where(Chapter.chapter_id == creation.chapter_id)
            chapter_result = await db.execute(chapter_stmt)
            chapter = chapter_result.scalar_one_or_none()

            if not chapter:
                return {"error": "章节不存在"}

            if not chapter.content_url:
                return {"error": "章节没有剧本文件"}

            logger.info(f"开始下载剧本文件: {chapter.content_url}")

            content = await self._download_and_read(chapter.content_url)

            if content is None:
                return {"error": "剧本下载失败"}

            return {
                "content": content,
                "title": chapter.title,
                "chapter_number": chapter.chapter_number,
                "word_count": chapter.word_count,
                "preview": chapter.preview
            }

        except Exception as e:
            logger.error(f"获取剧本失败: {e}", exc_info=True)
            return {"error": f"获取剧本失败: {str(e)}"}

    async def get_script_from_chapter(
        self,
        db: AsyncSession,
        chapter_id: int
    ) -> Dict[str, Any]:
        """根据章节 ID 获取剧本内容"""
        try:
            chapter_stmt = select(Chapter).where(Chapter.chapter_id == chapter_id)
            chapter_result = await db.execute(chapter_stmt)
            chapter = chapter_result.scalar_one_or_none()

            if not chapter:
                return {"error": "章节不存在"}

            if not chapter.content_url:
                return {"error": "章节没有剧本文件"}

            logger.info(f"开始下载剧本文件: {chapter.content_url}")

            content = await self._download_and_read(chapter.content_url)

            if content is None:
                return {"error": "剧本下载失败"}

            return {
                "content": content,
                "title": chapter.title,
                "chapter_number": chapter.chapter_number,
                "word_count": chapter.word_count,
                "preview": chapter.preview
            }

        except Exception as e:
            logger.error(f"获取剧本失败: {e}", exc_info=True)
            return {"error": f"获取剧本失败: {str(e)}"}

    async def _download_and_read(self, url: str) -> Optional[str]:
        """下载并读取文件内容"""
        try:
            async with httpx.AsyncClient(timeout=60.0) as client:
                response = await client.get(url, follow_redirects=True)
                response.raise_for_status()
                return response.text
        except httpx.HTTPStatusError as e:
            logger.error(f"HTTP 错误: {e}")
            return None
        except httpx.RequestError as e:
            logger.error(f"请求错误: {e}")
            return None
        except Exception as e:
            logger.error(f"下载文件失败: {e}")
            return None


script_loader = ScriptLoader()
