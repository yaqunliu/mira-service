"""
小说处理 Celery 任务
"""
import os
import tempfile
from typing import Dict, Any
from sqlalchemy.orm import Session
from app.core.celery_app import celery_app
from app.db.session import SessionLocal
from app.models.novel import Novel
from app.models.chapter import Chapter
from app.utils.novel_parser import read_novel_file, parse_novel_metadata, split_chapters
from app.utils.us3 import US3Client
from app.core.config import settings
from app.core.logger import logger
from app.utils.task_types import TaskType


@celery_app.task(bind=True, name="process_novel_upload_task")
def process_novel_upload_task(
    self,
    user_id: int,
    temp_file_path: str,
    original_filename: str
) -> Dict[str, Any]:
    """
    处理小说上传任务
    
    Args:
        user_id: 用户ID
        temp_file_path: 临时文件路径
        original_filename: 原始文件名
        
    Returns:
        处理结果字典
    """
    db: Session = SessionLocal()
    novel = None
    
    try:
        # 步骤1: 读取文件
        logger.info(f"开始处理小说文件: {temp_file_path}")
        content = read_novel_file(temp_file_path)
        
        # 更新进度：开始解析
        self.update_state(
            state='PROGRESS',
            meta={
                'task_type': TaskType.NOVEL_UPLOAD,  # 标识任务类型
                'current': 0,
                'total': 100,
                'status': '正在解析小说内容',
                'stage': 'parsing'
            }
        )
        
        # 步骤2: 解析小说
        metadata = parse_novel_metadata(content, original_filename)
        chapters_data = split_chapters(content)
        
        logger.info(f"解析完成: 标题={metadata['title']}, 作者={metadata['author']}, 章节数={len(chapters_data)}")
        
        # 更新进度：解析完成
        self.update_state(
            state='PROGRESS',
            meta={
                'task_type': TaskType.NOVEL_UPLOAD,
                'current': 10,
                'total': 100,
                'status': f'解析完成，共 {len(chapters_data)} 个章节',
                'stage': 'parsing_complete',
                'chapter_count': len(chapters_data)
            }
        )
        
        # 更新进度：创建数据库记录
        self.update_state(
            state='PROGRESS',
            meta={
                'task_type': TaskType.NOVEL_UPLOAD,
                'current': 5,
                'total': 100,
                'status': '正在创建小说记录',
                'stage': 'creating_novel'
            }
        )
        
        # 步骤3: 创建小说主记录
        # 获取当前任务的 task_id
        task_id = self.request.id if hasattr(self.request, 'id') else None
        
        novel = Novel(
            title=metadata['title'],
            author=metadata['author'],
            owner_id=user_id,
            status="processing",
            chapter_count=0,
            task_id=task_id  # 存储任务ID，用于前端查询
        )
        db.add(novel)
        db.commit()
        db.refresh(novel)
        
        novel_id = novel.novel_id
        logger.info(f"创建小说记录成功: novel_id={novel_id}, task_id={task_id}")
        
        # 步骤4: US3存储与数据库写入循环
        us3_client = US3Client()
        success_count = 0
        error_count = 0
        total_chapters = len(chapters_data)
        
        # 更新进度：开始处理章节
        self.update_state(
            state='PROGRESS',
            meta={
                'task_type': TaskType.NOVEL_UPLOAD,
                'current': 0,
                'total': total_chapters,
                'status': '开始处理章节',
                'stage': 'uploading_chapters'
            }
        )
        
        for index, chapter_data in enumerate(chapters_data, start=1):
            try:
                chapter_title = chapter_data['title']
                chapter_content = chapter_data['content']
                
                # 4.1 将章节内容保存为临时文件并上传到US3
                # 文件路径规范: novels/{novel_id}/chapter_{chapter_index:04d}.txt
                put_key = f"novels/{novel_id}/chapter_{index:04d}.txt"
                
                # 创建临时文件
                with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', suffix='.txt', delete=False) as tmp_file:
                    tmp_file.write(chapter_content)
                    tmp_file_path = tmp_file.name
                
                try:
                    # 上传到US3
                    # 使用默认bucket（从配置中读取）
                    upload_result = us3_client.upload_file(
                        local_file=tmp_file_path,
                        bucket=None,  # 使用默认bucket
                        put_key=put_key
                    )
                    
                    if not upload_result['success']:
                        logger.error(f"章节 {index} 上传US3失败: {upload_result.get('message')}")
                        error_count += 1
                        continue
                    
                    content_url = put_key  # 使用put_key作为content_url
                    logger.info(f"章节 {index} 上传US3成功: {content_url}")
                    
                finally:
                    # 清理临时文件
                    if os.path.exists(tmp_file_path):
                        os.remove(tmp_file_path)
                
                # 4.2 创建章节数据库记录
                # 生成章节内容预览（前30个字）
                # 去除首尾空白，将换行和多个空格替换为单个空格，然后取前30个字符
                cleaned_content = ' '.join(chapter_content.strip().split())
                preview_text = cleaned_content[:30]
                if len(cleaned_content) > 30:
                    preview_text += '...'
                
                chapter = Chapter(
                    novel_id=novel_id,
                    title=chapter_title,
                    content_url=content_url,
                    chapter_number=index,
                    word_count=len(chapter_content),
                    preview=preview_text  # 章节内容预览
                )
                db.add(chapter)
                success_count += 1
                
                # 更新进度：每处理一个章节更新一次
                progress_percent = int((index / total_chapters) * 100)
                self.update_state(
                    state='PROGRESS',
                    meta={
                        'task_type': TaskType.NOVEL_UPLOAD,
                        'current': index,
                        'total': total_chapters,
                        'percent': progress_percent,
                        'status': f'正在处理第 {index}/{total_chapters} 章',
                        'stage': 'uploading_chapters',
                        'success_count': success_count,
                        'error_count': error_count
                    }
                )
                
                # 每10个章节提交一次事务
                if index % 10 == 0:
                    db.commit()
                    logger.info(f"已处理 {index}/{total_chapters} 个章节 ({progress_percent}%)")
                    
            except Exception as e:
                logger.error(f"处理章节 {index} 时出错: {str(e)}")
                error_count += 1
                continue
        
        # 提交剩余的章节
        db.commit()
        
        # 更新进度：处理完成
        self.update_state(
            state='PROGRESS',
            meta={
                'task_type': TaskType.NOVEL_UPLOAD,
                'current': total_chapters,
                'total': total_chapters,
                'percent': 100,
                'status': '所有章节处理完成',
                'stage': 'completing',
                'success_count': success_count,
                'error_count': error_count
            }
        )
        
        # 步骤5: 更新小说状态
        novel.status = "completed"
        novel.chapter_count = success_count
        db.commit()
        
        logger.info(f"小说处理完成: novel_id={novel_id}, 成功章节数={success_count}, 失败章节数={error_count}")
        
        # 步骤6: 清理临时文件
        if os.path.exists(temp_file_path):
            os.remove(temp_file_path)
            logger.info(f"已删除临时文件: {temp_file_path}")
        
        return {
            "success": success_count == total_chapters,
            "task_type": TaskType.NOVEL_UPLOAD,  # 标识任务类型，便于前端识别
            "novel_id": novel_id,
            "title": metadata['title'],
            "chapter_count": success_count,
            "error_count": error_count,
            "message": f"小说处理完成，成功 {success_count} 个章节"
        }
        
    except Exception as e:
        logger.opt(exception=True).error("处理小说上传任务失败: {}", str(e))
        
        # 步骤7: 错误处理与回滚
        if novel:
            try:
                novel.status = "failed"
                db.commit()
            except Exception:
                pass
        
        # 清理临时文件
        if temp_file_path and os.path.exists(temp_file_path):
            try:
                os.remove(temp_file_path)
            except Exception:
                pass
        
        # 返回失败结果，不进行重试
        return {
            "success": False,
            "task_type": TaskType.NOVEL_UPLOAD,
            "error": str(e),
            "message": f"小说处理失败: {str(e)}"
        }
        
    finally:
        db.close()

