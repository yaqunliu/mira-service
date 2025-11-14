"""
小说解析工具单元测试
"""
import pytest
import tempfile
import os
from pathlib import Path
from app.utils.novel_parser import (
    read_novel_file,
    parse_novel_metadata,
    split_chapters
)


class TestReadNovelFile:
    """测试 read_novel_file 函数"""
    
    def test_read_utf8_file(self):
        """测试读取 UTF-8 编码文件"""
        content = "这是测试内容\n包含中文"
        with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', suffix='.txt', delete=False) as f:
            f.write(content)
            temp_path = f.name
        
        try:
            result = read_novel_file(temp_path)
            assert result == content
        finally:
            os.unlink(temp_path)
    
    def test_read_gbk_file(self):
        """测试读取 GBK 编码文件"""
        content = "这是GBK编码的测试内容"
        with tempfile.NamedTemporaryFile(mode='w', encoding='gbk', suffix='.txt', delete=False) as f:
            f.write(content)
            temp_path = f.name
        
        try:
            result = read_novel_file(temp_path)
            assert result == content
        finally:
            os.unlink(temp_path)
    
    def test_file_not_found(self):
        """测试文件不存在的情况"""
        with pytest.raises(FileNotFoundError):
            read_novel_file("/nonexistent/file.txt")
    
    def test_invalid_encoding(self):
        """测试无法解码的文件（使用二进制数据）"""
        # 创建一个无法用常见编码解码的文件
        with tempfile.NamedTemporaryFile(mode='wb', suffix='.txt', delete=False) as f:
            f.write(b'\xff\xfe\x00\x00')  # 无效的UTF-8序列
            temp_path = f.name
        
        try:
            with pytest.raises(UnicodeDecodeError):
                read_novel_file(temp_path)
        finally:
            os.unlink(temp_path)


class TestParseNovelMetadata:
    """测试 parse_novel_metadata 函数"""
    
    def test_extract_title_and_author(self):
        """测试提取标题和作者"""
        content = """测试小说标题
作者：测试作者
这是正文内容"""
        result = parse_novel_metadata(content, "test.txt")
        assert result["title"] == "测试小说标题"
        assert result["author"] == "测试作者"
    
    def test_extract_title_only(self):
        """测试只提取标题，无作者"""
        content = """测试小说标题
这是正文内容"""
        result = parse_novel_metadata(content, "test.txt")
        assert result["title"] == "测试小说标题"
        assert result["author"] == "未知"
    
    def test_extract_author_variations(self):
        """测试不同作者格式"""
        test_cases = [
            ("作者：张三", "张三"),
            ("作者: 李四", "李四"),
            ("作者 王五", "王五"),
            ("by John Doe", "John Doe"),
            ("By Jane Smith", "Jane Smith"),
        ]
        
        for author_line, expected_author in test_cases:
            content = f"小说标题\n{author_line}\n正文"
            result = parse_novel_metadata(content, "test.txt")
            assert result["author"] == expected_author, f"Failed for: {author_line}"
    
    def test_use_filename_as_title(self):
        """测试使用文件名作为标题（当第一行不符合标题条件时）"""
        # 第一行太长，不会被识别为标题，应该使用文件名
        content = "这是一个非常非常非常非常非常非常非常非常非常非常非常长的第一行，超过50个字符，不应该被识别为标题"
        result = parse_novel_metadata(content, "我的小说.txt")
        assert result["title"] == "我的小说"
        assert result["author"] == "未知"
    
    def test_empty_content(self):
        """测试空内容"""
        result = parse_novel_metadata("", "test.txt")
        assert result["title"] == "test"
        assert result["author"] == "未知"
    
    def test_title_with_chapter_keyword(self):
        """测试标题包含章节关键字的情况"""
        # 如果第一行包含章节关键字，应该跳过，使用文件名
        content = """第一章 开始
这是正文"""
        result = parse_novel_metadata(content, "test.txt")
        # 包含"第"和"章"的行不应该被识别为标题，应该使用文件名
        assert result["title"] == "test"  # 应该使用文件名
    
    def test_long_title_line(self):
        """测试过长的行不应该被识别为标题"""
        # 第一行超过50字符，不应该被识别为标题
        long_line = "这是一个非常非常非常非常非常非常非常非常非常非常非常长的标题行，超过50个字符，不应该被识别"
        content = f"{long_line}\n作者：测试作者"
        result = parse_novel_metadata(content, "test.txt")
        assert result["title"] == "test"  # 长行不应该被识别为标题，应该使用文件名
    
    def test_title_with_book_quotes(self):
        """测试书名号格式的标题（如《魔魂启临》）"""
        content = """《魔魂启临》
这是正文内容"""
        result = parse_novel_metadata(content, "test.txt")
        assert result["title"] == "魔魂启临"
        assert result["author"] == "未知"
    
    def test_title_and_author_in_same_line_with_quotes(self):
        """测试书名号和作者在同一行（如《魔魂启临》 作者：先飞看刀）"""
        content = """《魔魂启临》 作者：先飞看刀
这是正文内容"""
        result = parse_novel_metadata(content, "test.txt")
        assert result["title"] == "魔魂启临"
        assert result["author"] == "先飞看刀"
    
    def test_title_and_author_in_same_line_without_quotes(self):
        """测试标题和作者在同一行（无书名号）"""
        content = """魔魂启临 作者：先飞看刀
这是正文内容"""
        result = parse_novel_metadata(content, "test.txt")
        assert result["title"] == "魔魂启临"
        assert result["author"] == "先飞看刀"
    
    def test_different_book_quote_types(self):
        """测试不同类型的书名号"""
        test_cases = [
            ("《三体》", "三体"),
            ("【斗破苍穹】", "斗破苍穹"),
            ("『全职高手』", "全职高手"),
        ]
        
        for title_line, expected_title in test_cases:
            content = f"{title_line}\n正文内容"
            result = parse_novel_metadata(content, "test.txt")
            assert result["title"] == expected_title, f"Failed for: {title_line}"
    
    def test_book_quote_with_author_variations(self):
        """测试书名号与不同作者格式的组合"""
        test_cases = [
            ("《魔魂启临》 作者：先飞看刀", "魔魂启临", "先飞看刀"),
            ("《三体》 作者: 刘慈欣", "三体", "刘慈欣"),
            ("【斗破苍穹】 作者 天蚕土豆", "斗破苍穹", "天蚕土豆"),
            ("《全职高手》 by 蝴蝶蓝", "全职高手", "蝴蝶蓝"),
        ]
        
        for title_author_line, expected_title, expected_author in test_cases:
            content = f"{title_author_line}\n正文内容"
            result = parse_novel_metadata(content, "test.txt")
            assert result["title"] == expected_title, f"Title failed for: {title_author_line}"
            assert result["author"] == expected_author, f"Author failed for: {title_author_line}"


class TestSplitChapters:
    """测试 split_chapters 函数"""
    
    def test_split_chinese_chapters(self):
        """测试分割中文章节"""
        # 注意：章节标题必须单独一行，不能与其他内容在同一行
        content = """第一章 开始
这是第一章的内容。

第二章 继续
这是第二章的内容。

第三章 结束
这是第三章的内容。"""
        chapters = split_chapters(content)
        # 应该正确识别3个章节
        assert len(chapters) == 3, f"期望3个章节，实际得到{len(chapters)}个: {[ch['title'] for ch in chapters]}"
        assert chapters[0]["title"] == "第一章 开始"
        assert "第一章的内容" in chapters[0]["content"]
        assert chapters[1]["title"] == "第二章 继续"
        assert chapters[2]["title"] == "第三章 结束"
    
    def test_split_chinese_numeric_chapters(self):
        """测试分割中文数字章节"""
        content = """第一章 开始
内容1

第2章 继续
内容2

第3章 结束
内容3"""
        chapters = split_chapters(content)
        assert len(chapters) == 3
        assert chapters[0]["title"] == "第一章 开始"
        assert chapters[1]["title"] == "第2章 继续"
    
    def test_split_english_chapters(self):
        """测试分割英文章节"""
        content = """Chapter 1 Beginning
This is chapter 1 content.

Chapter 2 Middle
This is chapter 2 content.

CHAPTER 3 End
This is chapter 3 content."""
        chapters = split_chapters(content)
        assert len(chapters) == 3
        assert chapters[0]["title"] == "Chapter 1 Beginning"
        assert chapters[1]["title"] == "Chapter 2 Middle"
        assert chapters[2]["title"] == "CHAPTER 3 End"
    
    def test_split_chinese_hui_chapters(self):
        """测试分割中文'回'格式章节"""
        content = """第一回 开始
内容1

第二回 继续
内容2"""
        chapters = split_chapters(content)
        assert len(chapters) == 2
        assert chapters[0]["title"] == "第一回 开始"
        assert chapters[1]["title"] == "第二回 继续"
    
    def test_no_chapters_fallback(self):
        """测试没有章节标题时，将整个内容作为第一章"""
        content = "这是没有章节标题的内容，应该被作为第一章处理。"
        chapters = split_chapters(content)
        assert len(chapters) == 1
        assert chapters[0]["title"] == "第一章"
        assert chapters[0]["content"] == content
    
    def test_empty_content(self):
        """测试空内容"""
        chapters = split_chapters("")
        assert len(chapters) == 0
    
    def test_whitespace_only(self):
        """测试只有空白字符的内容"""
        chapters = split_chapters("   \n\n   ")
        assert len(chapters) == 0
    
    def test_chapter_with_empty_content(self):
        """测试章节标题后没有内容的情况"""
        content = """第一章 开始
第二章 继续
这是第二章的内容"""
        chapters = split_chapters(content)
        # 第一章没有内容，应该被跳过或包含空内容
        assert len(chapters) >= 1
        assert chapters[-1]["title"] == "第二章 继续"
    
    def test_mixed_chapter_formats(self):
        """测试混合章节格式"""
        content = """第一章 开始
内容1

Chapter 2 Middle
Content 2

第3回 结束
内容3"""
        chapters = split_chapters(content)
        assert len(chapters) == 3
        assert chapters[0]["title"] == "第一章 开始"
        assert chapters[1]["title"] == "Chapter 2 Middle"
        assert chapters[2]["title"] == "第3回 结束"
    
    def test_chapter_title_with_extra_text(self):
        """测试章节标题包含额外文本"""
        content = """第一章 这是章节标题 额外信息
这是第一章的内容。

第二章 另一个标题
这是第二章的内容。"""
        chapters = split_chapters(content)
        assert len(chapters) == 2
        assert chapters[0]["title"] == "第一章 这是章节标题 额外信息"
        assert "第一章的内容" in chapters[0]["content"]
    
    def test_multiple_chapters_same_line(self):
        """测试同一行有多个章节标题的情况（应该匹配第一个）"""
        content = """第一章 开始 第二章 继续
这是内容"""
        chapters = split_chapters(content)
        # 应该识别第一个章节标题
        assert len(chapters) >= 1


class TestIntegration:
    """集成测试：测试完整流程"""
    
    def test_full_parse_workflow(self):
        """测试完整的解析流程"""
        content = """我的小说标题
作者：张三

第一章 开始
这是第一章的内容，包含很多文字。

第二章 继续
这是第二章的内容。

第三章 结束
这是最后一章的内容。"""
        
        # 测试元数据解析
        metadata = parse_novel_metadata(content, "我的小说.txt")
        assert metadata["title"] == "我的小说标题"
        assert metadata["author"] == "张三"
        
        # 测试章节分割
        chapters = split_chapters(content)
        assert len(chapters) == 3
        assert chapters[0]["title"] == "第一章 开始"
        assert chapters[1]["title"] == "第二章 继续"
        assert chapters[2]["title"] == "第三章 结束"
        
        # 验证章节内容
        assert "第一章的内容" in chapters[0]["content"]
        assert "第二章的内容" in chapters[1]["content"]
        assert "最后一章的内容" in chapters[2]["content"]
    
    def test_real_world_example(self):
        """测试真实世界的小说格式"""
        content = """《三体》
作者：刘慈欣

第一部 地球往事

第一章 科学边界
这是第一章的内容...

第二章 台球
这是第二章的内容...

第二部 黑暗森林

第一章 面壁者
这是第二部的第一章..."""
        
        metadata = parse_novel_metadata(content, "三体.txt")
        # 标题可能被识别为"《三体》"或使用文件名
        assert metadata["author"] == "刘慈欣"
        
        chapters = split_chapters(content)
        # 应该识别出所有章节
        assert len(chapters) >= 3
        assert any("第一章 科学边界" in ch["title"] for ch in chapters)
        assert any("第二章 台球" in ch["title"] for ch in chapters)

