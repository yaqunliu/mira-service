"""
小说解析工具
用于解析小说文件，提取元数据和分割章节
"""
import re
from typing import List, Dict, Tuple, Optional
from pathlib import Path

try:
    from app.core.logger import logger
except ImportError:
    # 如果logger不可用，使用简单的print作为fallback
    class SimpleLogger:
        def info(self, msg):
            pass
        def error(self, msg):
            pass
    logger = SimpleLogger()


# 英文数字单词（one ~ nine hundred ninety-nine），用于识别 "Chapter One" 这类英文章节标题
_EN_ONES = (
    r'(?:one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|'
    r'thirteen|fourteen|fifteen|sixteen|seventeen|eighteen|nineteen)'
)
_EN_TENS = r'(?:twenty|thirty|forty|fifty|sixty|seventy|eighty|ninety)'
_EN_TWO_DIGIT = rf'(?:{_EN_TENS}(?:[\s-]+{_EN_ONES})?|{_EN_ONES})'
_EN_NUMBER_WORD = (
    rf'(?:{_EN_ONES}[\s-]+hundred(?:[\s-]+(?:and[\s-]+)?{_EN_TWO_DIGIT})?|{_EN_TWO_DIGIT})'
)
# 罗马数字（I、IV、XIII 等），前瞻确保非空匹配
_ROMAN_NUMBER = r'(?=[MDCLXVI])M{0,3}(?:CM|CD|D?C{0,3})(?:XC|XL|L?X{0,3})(?:IX|IV|V?I{0,3})'
# 章节序号：阿拉伯数字 / 英文单词 / 罗马数字
_EN_CHAPTER_NUMBER = rf'(?:[0-9]+|{_EN_NUMBER_WORD}|{_ROMAN_NUMBER})'
# 行首可能出现的 Markdown 标记，如 "## Chapter Two"、"**Chapter Two**"
_MD_PREFIX = r'(?:#{1,6}\s*)?(?:\*{1,3})?\s*'
# 英文章节标题（锚定行首，避免正文中提到 "chapter one" 时被误切分）
_EN_CHAPTER_HEADING = rf'^{_MD_PREFIX}(?:chapter|chap\.?|part)\s+{_EN_CHAPTER_NUMBER}\b'
# 用于 clean_chapter_title：提取英文章节号部分
_EN_CHAPTER_PREFIX = rf'^(?:chapter|chap\.?|part)\s+{_EN_CHAPTER_NUMBER}\b'


def _is_latin_dominant(text: str) -> bool:
    """
    判断正文是否以拉丁字母（英文等）为主。

    用于按语种调整解析阈值：中文一个字的信息量约等于英文一个单词，
    两者共用同一套字符数/标点阈值会误判。

    Args:
        text: 正文内容（只取前 5000 字符做采样，避免长文件开销）

    Returns:
        True 表示拉丁字母为主，False 表示中日韩文字为主
    """
    sample = text[:5000]
    cjk_count = len(re.findall(r'[一-鿿]', sample))
    latin_count = len(re.findall(r'[A-Za-z]', sample))
    return latin_count > cjk_count


def _looks_like_title(line: str, is_latin: bool) -> bool:
    """
    判断首行是否像书名（而不是正文的第一句）。

    中文与英文用不同的阈值：
    - 中文：不超过 50 字，且标点不超过 2 个
    - 英文：不超过 120 字符且不超过 15 个单词，且不以句末标点结尾
      （英文书名普遍比中文长，如 "The Evening Breeze Through the Classroom" 已 40 字符；
       但英文正文首句几乎总以 . ! ? 结尾，用这一点排除正文比数标点更可靠，
       同时不会误伤 "Dr. Jekyll and Mr. Hyde" 这类含缩写点的书名）

    Args:
        line: 已 strip 的首行
        is_latin: 正文是否以拉丁字母为主

    Returns:
        True 表示看起来像书名
    """
    if is_latin:
        if len(line) > 120 or len(line.split()) > 15:
            return False
        return not line.rstrip().endswith(('.', '!', '?', '。', '！', '？'))

    if len(line) > 50:
        return False
    # 标点符号不超过2个，可能是标题
    return len(re.findall(r'[。！？，、：；]', line)) <= 2


def clean_chapter_title(title: str, max_length: int = 200) -> str:
    """
    清理章节标题
    
    处理规则：
    1. 从句号、感叹号、问号等标点符号截断
    2. 去除重复内容
    3. 清理常见的垃圾内容（如"牢记本站网址"、"七更求花"等）
    4. 限制长度
    5. 去除多余的空格和换行
    
    Args:
        title: 原始章节标题
        max_length: 最大长度，默认200
        
    Returns:
        清理后的章节标题
    """
    if not title:
        return title
    
    # 去除首尾空白和换行
    title = title.strip().replace('\n', ' ').replace('\r', ' ')
    
    # 去除多余的空格（多个空格替换为单个空格）
    title = re.sub(r'\s+', ' ', title)

    # 去除 Markdown 标记：行首的 #、首尾的 * / _（如 "## Chapter Two"、"**第一章**"）
    title = re.sub(r'^#{1,6}\s*', '', title)
    title = re.sub(r'^[*_]{1,3}\s*|\s*[*_]{1,3}$', '', title).strip()

    # 清理常见的垃圾内容模式
    # 1. 牢记本站网址相关（包括后面的所有内容）
    title = re.sub(r'牢记本站网址[：:].*', '', title, flags=re.IGNORECASE)
    title = re.sub(r'牢记本站网址.*', '', title, flags=re.IGNORECASE)
    
    # 2. 更求xxx相关（包括各种变体）
    # 先匹配带括号的：【七更求花】、【六更求花】等
    title = re.sub(r'[【\[]+[零一二三四五六七八九十百千万]*[更求]+[花票收藏订阅月票推荐打赏支持点击鲜花钻石红包礼物评价评论点赞分享转发关注]+[】\]]+', '', title, flags=re.IGNORECASE)
    # 再匹配不带括号的：七更求花、六更求花等（数字+更求+内容）
    title = re.sub(r'[零一二三四五六七八九十百千万\d]+[更求]+[花票收藏订阅月票推荐打赏支持点击鲜花钻石红包礼物评价评论点赞分享转发关注]+', '', title, flags=re.IGNORECASE)
    # 匹配：更求花、更求票等（没有数字前缀的）
    title = re.sub(r'[更求]+[花票收藏订阅月票推荐打赏支持点击鲜花钻石红包礼物评价评论点赞分享转发关注]+', '', title, flags=re.IGNORECASE)
    
    # 从句号、感叹号、问号等标点符号截断（保留章节号部分）
    # 匹配章节号后的内容，如果遇到句号等标点，截断
    # 先找到章节号的位置
    chapter_match = re.search(r'(第[^章回]*[章回])', title)
    if not chapter_match:
        # 英文章节标题，如 "Chapter One — Deskmates"、"Chapter 1. Beginning"
        chapter_match = re.match(_EN_CHAPTER_PREFIX, title, re.IGNORECASE)
    if chapter_match:
        chapter_part = chapter_match.group(0)
        rest_part = title[chapter_match.end():].strip()
        # 去掉紧跟章节号的句点（"Chapter 1. Beginning" 中的 "."），避免被当成截断点
        rest_part = re.sub(r'^[.。]+\s*', '', rest_part)

        # 在剩余部分中查找截断点
        # 优先在句号、感叹号、问号处截断
        truncate_chars = ['。', '！', '？', '.', '!', '?']
        truncate_pos = len(rest_part)
        for char in truncate_chars:
            pos = rest_part.find(char)
            if pos != -1 and pos < truncate_pos:
                truncate_pos = pos + 1
        
        # 如果找到截断点，截断
        if truncate_pos < len(rest_part):
            rest_part = rest_part[:truncate_pos].strip()
        
        title = (chapter_part + ' ' + rest_part).strip()
    else:
        # 如果没有找到章节号，直接查找截断点
        truncate_chars = ['。', '！', '？', '.', '!', '?']
        for char in truncate_chars:
            pos = title.find(char)
            if pos != -1:
                title = title[:pos + 1].strip()
                break
    
    # 去除重复内容（如果标题重复出现，只保留第一次）
    # 简单的重复检测：如果标题的前半部分和后半部分相同
    title_len = len(title)
    if title_len > 10:
        half_len = title_len // 2
        first_half = title[:half_len]
        second_half = title[half_len:half_len * 2]
        # 如果前半部分和后半部分相似度很高（去除空格后相似），只保留前半部分
        if first_half.replace(' ', '') == second_half.replace(' ', ''):
            title = first_half.strip()
    
    # 去除多余的空格
    title = re.sub(r'\s+', ' ', title).strip()
    
    # 限制长度
    if len(title) > max_length:
        title = title[:max_length].strip()
        # 如果截断后最后一个字符不是标点，尝试在最后一个标点处截断
        last_punct = max(
            title.rfind('。'), title.rfind('！'), title.rfind('？'),
            title.rfind('.'), title.rfind('!'), title.rfind('?'),
            title.rfind('，'), title.rfind(','), title.rfind('：'),
            title.rfind(':'), title.rfind('；'), title.rfind(';')
        )
        if last_punct > max_length * 0.7:  # 如果标点在70%位置之后，使用标点位置
            title = title[:last_punct + 1].strip()
    
    return title


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
    
    # 章节关键字模式，用于判断是否是章节标题
    chapter_keyword_pattern = (
        rf'第\s*[零一二三四五六七八九十百千万\d]+\s*[章回话卷]|{_EN_CHAPTER_HEADING}'
    )

    # 首行是否像书名，阈值按正文语种区分
    is_latin = _is_latin_dominant(content)

    # 检查前10行
    for i, line in enumerate(lines[:10]):
        line = line.strip()
        if not line:
            continue
            
        # 尝试匹配标题模式
        if not title:
            # 1. 优先匹配包含书名号的行（《》、【】、『』）
            book_quote_pattern = r'[《》【】『』]'
            if re.search(book_quote_pattern, line):
                # 提取书名号中的内容
                title_match = re.search(r'[《【『]([^》】』]+)[》】』]', line)
                if title_match:
                    title = title_match.group(1).strip()
                    # 如果同一行包含作者信息，也提取出来
                    author_in_line = re.search(r'[》】』]\s*(?:作者|作者：|作者:|by|By)\s*[:：]?\s*(.+)', line, re.IGNORECASE)
                    if author_in_line and not author:
                        author = author_in_line.group(1).strip()
                    continue
            
            # 2. 如果没有书名号，第一行看起来像书名且不包含章节关键字，则作为标题
            #    长度/标点阈值按语种区分，见 _looks_like_title
            if i == 0 and _looks_like_title(line, is_latin):
                # 检查是否包含章节关键字（如 "第一章"、"Chapter One" 开头的小说没有单独书名行）
                if not re.search(chapter_keyword_pattern, line, re.IGNORECASE):
                    title = line
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


def _default_chapter_title(content: str) -> str:
    """
    没有识别到章节标题时的兜底章节名。

    按正文语种返回，避免英文小说出现中文的"第一章"。
    """
    return "Chapter 1" if _is_latin_dominant(content) else "第一章"


def split_chapters(content: str) -> List[Dict[str, str]]:
    """
    分割小说内容为章节
    
    Args:
        content: 小说完整内容
        
    Returns:
        章节列表，每个章节包含 title 和 content
    """
    # 章节匹配模式
    # 中文数字：支持完整的中文数字格式，包括零一二三四五六七八九十百千万
    # 例如：第一章、第一千九百九十章、第一万章等
    # 支持带空格的格式：第 一 章、第 一 回、第 1999 章、第 一 百 章等
    # 阿拉伯数字：第[0-9]+章、第[0-9]+回、第[0-9]+话、第[0-9]+卷
    # 英文：Chapter\s+[0-9]+、CHAPTER\s+[0-9]+
    # 注意：\s* 表示零个或多个空白字符（空格、制表符等）
    # 对于中文数字，允许数字字符之间有空格，使用 ([零一二三四五六七八九十百千万]\s*)+ 模式
    chapter_patterns = [
        # 章
        r'第\s*([零一二三四五六七八九十百千万]\s*)+\s*章',  # 纯中文数字，支持数字字符间空格
        r'第\s*[零一二三四五六七八九十百千万]+\s*章',  # 纯中文数字，无空格（向后兼容）
        r'第\s*[零一二三四五六七八九十百千万\d]+\s*章',  # 中文数字和阿拉伯数字混合，支持空格
        r'第\s*[0-9]+\s*章',  # 纯阿拉伯数字，支持空格
        # 回
        r'第\s*([零一二三四五六七八九十百千万]\s*)+\s*回',  # 纯中文数字的回，支持数字字符间空格
        r'第\s*[零一二三四五六七八九十百千万]+\s*回',  # 纯中文数字的回，无空格（向后兼容）
        r'第\s*[零一二三四五六七八九十百千万\d]+\s*回',  # 中文数字和阿拉伯数字混合的回，支持空格
        r'第\s*[0-9]+\s*回',  # 纯阿拉伯数字的回，支持空格
        # 话
        r'第\s*([零一二三四五六七八九十百千万]\s*)+\s*话',  # 纯中文数字的话，支持数字字符间空格
        r'第\s*[零一二三四五六七八九十百千万]+\s*话',  # 纯中文数字的话，无空格
        r'第\s*[零一二三四五六七八九十百千万\d]+\s*话',  # 中文数字和阿拉伯数字混合的话，支持空格
        r'第\s*[0-9]+\s*话',  # 纯阿拉伯数字的话，支持空格
        # 卷
        r'第\s*([零一二三四五六七八九十百千万]\s*)+\s*卷',  # 纯中文数字的卷，支持数字字符间空格
        r'第\s*[零一二三四五六七八九十百千万]+\s*卷',  # 纯中文数字的卷，无空格
        r'第\s*[零一二三四五六七八九十百千万\d]+\s*卷',  # 中文数字和阿拉伯数字混合的卷，支持空格
        r'第\s*[0-9]+\s*卷',  # 纯阿拉伯数字的卷，支持空格
        # 英文
        r'Chapter\s+[0-9]+',
        r'CHAPTER\s+[0-9]+',
        # 英文数字单词与罗马数字，如 Chapter One / Chapter Twenty-Three / Chapter IV / Part Two
        # 锚定行首（允许 Markdown 的 # 与 * 前缀），避免正文中提到章节名时被误切分
        _EN_CHAPTER_HEADING,
    ]
    
    # 组合所有模式
    pattern = '|'.join(f'({p})' for p in chapter_patterns)
    
    # 书名和分隔符模式，用于过滤
    book_title_pattern = r'^[《【『][^》】』]+[》】』]\s*$'  # 匹配单独一行的书名
    separator_pattern = r'^[-=*_]{3,}\s*$'  # 匹配分隔符：---、===、***、___等
    
    # 兜底章节名跟随正文语种：英文小说不应该出现"第一章"
    default_title = _default_chapter_title(content)

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
                # 过滤掉内容不足50字的章节
                if chapter_content and len(chapter_content) >= 50:
                    chapters.append({
                        "title": current_chapter_title,
                        "content": chapter_content
                    })
            
            # 开始新章节，清理标题
            current_chapter_title = clean_chapter_title(line_stripped)
            current_chapter_content = []
        else:
            # 过滤掉书名和分隔符
            if re.match(book_title_pattern, line_stripped) or re.match(separator_pattern, line_stripped):
                # 如果是书名或分隔符，跳过这一行
                continue
            
            # 添加到当前章节内容
            if current_chapter_title is not None:
                current_chapter_content.append(line)
            elif line_stripped:  # 如果还没有章节标题，但内容不为空，可能是前言
                # 如果没有找到章节标题，将整个内容作为第一章
                if not chapters:
                    current_chapter_title = clean_chapter_title(default_title)
                    current_chapter_content = [line]
    
    # 保存最后一个章节
    if current_chapter_title is not None:
        chapter_content = '\n'.join(current_chapter_content).strip()
        # 过滤掉内容不足50字的章节
        if chapter_content and len(chapter_content) >= 50:
            chapters.append({
                "title": current_chapter_title,
                "content": chapter_content
            })
    
    # 如果没有找到任何章节，将整个内容作为第一章
    if not chapters:
        content_stripped = content.strip()
        # 过滤掉书名和分隔符
        filtered_lines = []
        for line in content_stripped.split('\n'):
            line_stripped = line.strip()
            if not (re.match(book_title_pattern, line_stripped) or re.match(separator_pattern, line_stripped)):
                filtered_lines.append(line)
        filtered_content = '\n'.join(filtered_lines).strip()
        if filtered_content and len(filtered_content) >= 20:
            chapters.append({
                "title": clean_chapter_title(default_title),
                "content": filtered_content
            })
    
    # 对所有章节标题进行最终清理（防止遗漏）
    for chapter in chapters:
        chapter['title'] = clean_chapter_title(chapter['title'])
    
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

