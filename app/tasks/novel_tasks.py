"""
小说处理 Celery 任务
"""
import os
import tempfile
from typing import Dict, Any, List, Tuple
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed
from sqlalchemy.orm import Session
from app.core.celery_app import celery_app
from app.db.session import SessionLocal
from app.models.novel import Novel
from app.models.chapter import Chapter
from app.models.user import User
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
        
        # 获取用户UUID用于构建上传路径
        user = db.query(User).filter(User.user_id == user_id).first()
        if not user:
            raise ValueError(f"用户不存在: user_id={user_id}")
        user_uuid = user.uuid
        
        # 获取环境变量（默认dev）
        env = getattr(settings, 'ENV', 'dev')
        # 生成时间戳（格式：YYYYMMDD）
        time_str = datetime.now().strftime('%Y%m%d')
        
        # 步骤4: US3存储与数据库写入（并发上传）
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
        
        # 定义上传单个章节的函数
        def upload_single_chapter(index: int, chapter_data: Dict[str, str]) -> Tuple[int, bool, str, Dict[str, Any]]:
            """
            上传单个章节
            
            Returns:
                (index, success, content_url, chapter_info)
            """
            # 每个线程创建自己的US3Client实例，确保线程安全
            us3_client = US3Client()
            try:
                chapter_title = chapter_data['title']
                chapter_content = chapter_data['content']
                
                # 构建上传路径：环境/时间/user_uuid/【小说章节创作】/文件
                # 文件路径规范: {env}/{time_str}/{user_uuid}/【小说章节创作】/novels/{novel_id}/chapter_{chapter_index:04d}.txt
                put_key = f"{env}/{time_str}/{user_uuid}/【小说章节创作】/novels/{novel_id}/chapter_{index:04d}.txt"
                
                # 创建临时文件
                tmp_file_path = None
                try:
                    with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', suffix='.txt', delete=False) as tmp_file:
                        tmp_file.write(chapter_content)
                        tmp_file_path = tmp_file.name
                    
                    # 上传到US3（关闭哈希验证以提高速度）
                    upload_result = us3_client.upload_file(
                        local_file=tmp_file_path,
                        bucket=None,  # 使用默认bucket
                        put_key=put_key,
                        verify_hash=False  # 关闭哈希验证以提高上传速度
                    )
                    
                    if not upload_result['success']:
                        logger.error(f"章节 {index} 上传US3失败: {upload_result.get('message')}")
                        return (index, False, "", {
                            'title': chapter_title,
                            'content': chapter_content,
                            'error': upload_result.get('message', '上传失败')
                        })
                    
                    content_url = put_key  # 使用put_key作为content_url
                    logger.info(f"章节 {index} 上传US3成功: {content_url}")
                    
                    # 生成章节内容预览（前30个字）
                    cleaned_content = ' '.join(chapter_content.strip().split())
                    preview_text = cleaned_content[:30]
                    if len(cleaned_content) > 30:
                        preview_text += '...'
                    
                    return (index, True, content_url, {
                        'title': chapter_title,
                        'content': chapter_content,
                        'preview': preview_text,
                        'word_count': len(chapter_content)
                    })
                    
                finally:
                    # 清理临时文件
                    if tmp_file_path and os.path.exists(tmp_file_path):
                        try:
                            os.remove(tmp_file_path)
                        except Exception as e:
                            logger.warning(f"删除临时文件失败: {tmp_file_path}, {str(e)}")
                            
            except Exception as e:
                logger.error(f"处理章节 {index} 时出错: {str(e)}", exc_info=True)
                return (index, False, "", {
                    'title': chapter_data.get('title', ''),
                    'content': chapter_data.get('content', ''),
                    'error': str(e)
                })
        
        # 使用线程池并发上传（5个并发）
        chapter_results: List[Tuple[int, bool, str, Dict[str, Any]]] = []
        completed_count = 0
        
        with ThreadPoolExecutor(max_workers=5) as executor:
            # 提交所有上传任务
            future_to_index = {
                executor.submit(upload_single_chapter, index, chapter_data): index
                for index, chapter_data in enumerate(chapters_data, start=1)
            }
            
            # 处理完成的任务
            for future in as_completed(future_to_index):
                try:
                    result = future.result()
                    chapter_results.append(result)
                    completed_count += 1
                    
                    index, success, content_url, chapter_info = result
                    if success:
                        success_count += 1
                    else:
                        error_count += 1
                    
                    # 更新进度
                    progress_percent = int((completed_count / total_chapters) * 100)
                    self.update_state(
                        state='PROGRESS',
                        meta={
                            'task_type': TaskType.NOVEL_UPLOAD,
                            'current': completed_count,
                            'total': total_chapters,
                            'percent': progress_percent,
                            'status': f'正在处理第 {completed_count}/{total_chapters} 章',
                            'stage': 'uploading_chapters',
                            'success_count': success_count,
                            'error_count': error_count
                        }
                    )
                    
                    if completed_count % 10 == 0:
                        logger.info(f"已处理 {completed_count}/{total_chapters} 个章节 ({progress_percent}%)")
                        
                except Exception as e:
                    index = future_to_index[future]
                    logger.error(f"章节 {index} 处理异常: {str(e)}", exc_info=True)
                    error_count += 1
                    chapter_results.append((index, False, "", {'error': str(e)}))
        
        # 按章节序号排序结果
        chapter_results.sort(key=lambda x: x[0])
        
        # 批量创建数据库记录
        chapters_to_add = []
        for index, success, content_url, chapter_info in chapter_results:
            if success:
                chapter = Chapter(
                    novel_id=novel_id,
                    title=chapter_info['title'],
                    content_url=content_url,
                    chapter_number=index,
                    word_count=chapter_info['word_count'],
                    preview=chapter_info['preview']
                )
                chapters_to_add.append(chapter)
        
        # 批量添加章节记录（每10个提交一次）
        batch_size = 10
        for i in range(0, len(chapters_to_add), batch_size):
            batch = chapters_to_add[i:i + batch_size]
            for chapter in batch:
                db.add(chapter)
            db.commit()
            logger.info(f"已提交 {min(i + batch_size, len(chapters_to_add))}/{len(chapters_to_add)} 个章节到数据库")
        
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

