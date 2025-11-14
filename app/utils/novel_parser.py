"""
小说解析工具
用于解析小说文件，提取元数据和分割章节
"""
import re
from typing import List, Dict, Tuple, Optional
from pathlib import Path
from app.core.logger import logger


def parse_novel_metadata(content: str, filename: str) -> Dict[str, str]:
    """
    解析小说元数据（标题、作者）
    
    Args:
        content: 小说内容
        filename: 文件名
        
    Returns:
        包含 title 和 author 的字典
    """
    lines = content.split('\n')
    
    # 尝试从文件头部提取标题和作者
    title = None
    author = None
    
    # 检查前10行
    for i, line in enumerate(lines[:10]):
        line = line.strip()
        if not line:
            continue
            
        # 尝试匹配标题模式（必须包含书名号）
        if not title:
            # 匹配包含书名号的行（《》、【】、『』）
            book_quote_pattern = r'[《》【】『』]'
            if re.search(book_quote_pattern, line):
                # 提取书名号中的内容
                # 匹配《》、【】、『』中的内容
                title_match = re.search(r'[《【『]([^》】』]+)[》】』]', line)
                if title_match:
                    title = title_match.group(1).strip()
                    # 如果同一行包含作者信息，也提取出来
                    # 例如：《小说标题》作者：xxx
                    author_in_line = re.search(r'[》】』]\s*(?:作者|作者：|作者:|by|By)\s*[:：]?\s*(.+)', line, re.IGNORECASE)
                    if author_in_line and not author:
                        author = author_in_line.group(1).strip()
                    continue
        
        # 尝试匹配作者模式
        if not author:
            # 作者模式：作者：xxx 或 作者 xxx 或 by xxx
            author_match = re.search(r'(?:作者|作者：|作者:|by|By)\s*[:：]?\s*(.+)', line, re.IGNORECASE)
            if author_match:
                author = author_match.group(1).strip()
                continue
    
    # 如果无法提取标题，使用文件名（去除扩展名）
    if not title:
        title = Path(filename).stem
    
    # 如果无法提取作者，使用默认值
    if not author:
        author = "未知"
    
    return {
        "title": title,
        "author": author
    }


def split_chapters(content: str) -> List[Dict[str, str]]:
    """
    分割小说内容为章节
    
    Args:
        content: 小说完整内容
        
    Returns:
        章节列表，每个章节包含 title 和 content
    """
    # 章节匹配模式
    # 中文：第[一二三四五六七八九十百千万\d]+章、第[0-9]+章、第[0-9]+回
    # 英文：Chapter\s+[0-9]+、CHAPTER\s+[0-9]+
    chapter_patterns = [
        r'第[一二三四五六七八九十百千万\d]+章',
        r'第[0-9]+章',
        r'第[0-9]+回',
        r'Chapter\s+[0-9]+',
        r'CHAPTER\s+[0-9]+',
    ]
    
    # 组合所有模式
    pattern = '|'.join(f'({p})' for p in chapter_patterns)
    
    # 查找所有章节标题位置
    chapters = []
    lines = content.split('\n')
    current_chapter_title = None
    current_chapter_content = []
    
    for i, line in enumerate(lines):
        line_stripped = line.strip()
        
        # 检查是否是章节标题
        match = re.search(pattern, line_stripped, re.IGNORECASE)
        if match:
            # 如果之前有章节，先保存
            if current_chapter_title is not None:
                chapter_content = '\n'.join(current_chapter_content).strip()
                if chapter_content:  # 只保存非空章节
                    chapters.append({
                        "title": current_chapter_title,
                        "content": chapter_content
                    })
            
            # 开始新章节
            current_chapter_title = line_stripped
            current_chapter_content = []
        else:
            # 添加到当前章节内容
            if current_chapter_title is not None:
                current_chapter_content.append(line)
            elif line_stripped:  # 如果还没有章节标题，但内容不为空，可能是前言
                # 如果没有找到章节标题，将整个内容作为第一章
                if not chapters:
                    current_chapter_title = "第一章"
                    current_chapter_content = [line]
    
    # 保存最后一个章节
    if current_chapter_title is not None:
        chapter_content = '\n'.join(current_chapter_content).strip()
        if chapter_content:
            chapters.append({
                "title": current_chapter_title,
                "content": chapter_content
            })
    
    # 如果没有找到任何章节，将整个内容作为第一章
    if not chapters:
        content_stripped = content.strip()
        if content_stripped:
            chapters.append({
                "title": "第一章",
                "content": content_stripped
            })
    
    logger.info(f"解析得到 {len(chapters)} 个章节")
    return chapters


def read_novel_file(file_path: str) -> str:
    """
    读取小说文件，自动处理编码
    
    Args:
        file_path: 文件路径
        
    Returns:
        文件内容（字符串）
        
    Raises:
        UnicodeDecodeError: 如果无法解码文件
    """
    encodings = ['utf-8', 'gbk', 'gb2312', 'big5']
    
    for encoding in encodings:
        try:
            with open(file_path, 'r', encoding=encoding) as f:
                return f.read()
        except UnicodeDecodeError:
            continue
        except Exception as e:
            logger.error(f"读取文件失败: {str(e)}")
            raise
    
    raise UnicodeDecodeError(
        "无法解码文件",
        b"",
        0,
        len(encodings),
        f"尝试了以下编码: {', '.join(encodings)}"
    )

