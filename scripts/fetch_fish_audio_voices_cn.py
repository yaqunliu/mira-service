#!/usr/bin/env python
"""
获取 Fish Audio 中文音色列表，并按男女分类
"""

import sys
import os
import json

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.core.config import settings


FISH_AUDIO_API_BASE = "https://api.fish.audio"


def list_voices(page_size=200, page_number=1, sort_by="task_count"):
    """获取音色列表"""
    url = f"{FISH_AUDIO_API_BASE}/model"
    params = {
        "page_size": page_size,
        "page_number": page_number,
        "sort_by": sort_by
    }
    
    print(f"请求 URL: {url}")
    print(f"参数: {params}")
    
    api_key = settings.FISH_AUDIO_API_KEY
    headers = {"Authorization": f"Bearer {api_key}"}
    
    import requests
    response = requests.get(url, headers=headers, params=params)
    response.raise_for_status()
    
    data = response.json()
    items = data.get("items", data.get("data", []))
    
    print(f"获取到 {len(items)} 个音色")
    return items


def is_chinese_voice(voice):
    """判断是否为中文音色"""
    title = voice.get("title", "").lower()
    description = voice.get("description", "").lower()
    tags = voice.get("tags", [])
    language = voice.get("language", "").lower()
    
    # 中文关键词
    chinese_patterns = [
        "chinese", "mandarin", "中文", "普通话",
        "中国", "华人", "汉", "普通话"
    ]
    
    # 检查标题或描述是否包含中文
    for pattern in chinese_patterns:
        if pattern in title or pattern in description:
            return True
    
    # 检查标签
    for tag in tags:
        tag_lower = tag.lower()
        if tag_lower in ["chinese", "mandarin", "中文"]:
            return True
    
    # 检查语言字段
    if "zh" in language or "chinese" in language:
        return True
    
    # 检查是否包含中文字符（通过 Unicode 范围）
    title_chars = title + description
    for char in title_chars:
        if '\u4e00' <= char <= '\u9fff':
            return True
    
    return False


def get_gender(voice):
    """获取性别"""
    tags = voice.get("tags", [])
    
    # 中文女性关键词（优先级高）
    female_chinese = ["女", "女生", "女孩", "女性", "女神", "学姐", "御姐", "女王", "女生", "女友", "软妹", "萌妹", "甜美", "可爱", "少女", "妈妈", "阿姨", "姐姐", "妹妹", "娘子", "老婆"]
    # 中文男性关键词
    male_chinese = ["男", "男生", "男孩", "男性", "帅哥", "学长", "御弟", "少爷", "先生", "老公", "男友", "汉子", "猛男", "老爸", "叔叔", "哥哥", "弟弟", "老爷", "老爷们"]
    
    for tag in tags:
        if any(kw in tag for kw in female_chinese):
            return "female"
        if any(kw in tag for kw in male_chinese):
            return "male"
    
    # 检查英文标签
    tags_lower = [t.lower() for t in tags]
    
    if "female" in tags_lower:
        return "female"
    elif "male" in tags_lower:
        return "male"
    
    return "unknown"


def format_voice_info(voice, gender):
    """格式化音色信息"""
    voice_id = voice.get("id", "")
    title = voice.get("title", "未命名")
    description = voice.get("description", "")
    
    tags = voice.get("tags", [])
    if isinstance(tags, str):
        tags = [t.strip() for t in tags.split(",") if t.strip()]
    
    try:
        reference_audio = voice.get("reference_audio", [])
        if reference_audio and len(reference_audio) > 0:
            if isinstance(reference_audio[0], dict):
                audio_url = reference_audio[0].get("audio_url", "")
            else:
                audio_url = str(reference_audio[0])
        else:
            audio_url = ""
    except:
        audio_url = ""
    
    task_count = voice.get("task_count", 0)
    
    return {
        "voice_id": voice_id,
        "title": title,
        "description": description,
        "tags": tags,
        "gender": gender,
        "audio_url": audio_url,
        "task_count": task_count
    }


def generate_markdown(male_voices, female_voices, unknown_voices):
    """生成 Markdown 文档"""
    from datetime import datetime
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    total = len(male_voices) + len(female_voices) + len(unknown_voices)
    
    md_content = f"""# Fish Audio 中文音色列表

> 生成时间：{timestamp}
> 总计：{total} 个中文音色（男: {len(male_voices)} | 女: {len(female_voices)} | 其他: {len(unknown_voices)}）

---

## 简介

本文档列出 Fish Audio API 可用的中文音色，按性别分类。

## 使用方法

```python
from app.agent.tools.audio_tools import GenerateAudioWithEmotionTool

tool = GenerateAudioWithEmotionTool()
result = await tool.execute(
    state=state,
    text="你好，这是测试语音",
    voice_id="<voice_id>",
    emotion_tags=["happy"]
)
```

---

## 👨 男性音色 ({len(male_voices)})

| # | 名称 | ID | 描述 | 使用次数 |
|---|------|----|------|----------|

"""
    
    for i, voice in enumerate(male_voices, 1):
        voice_id = voice.get("voice_id", "")[:16] + "..." if len(voice.get("voice_id", "")) > 16 else voice.get("voice_id", "")
        title = voice.get("title", "未命名")
        description = voice.get("description", "")[:40] + "..." if len(voice.get("description", "")) > 40 else voice.get("description", "")
        task_count = voice.get("task_count", 0)
        
        title_escaped = title.replace("|", "\\|")
        description_escaped = description.replace("|", "\\|")
        
        md_content += f"| {i} | {title_escaped} | `{voice_id}` | {description_escaped} | {task_count:,} |\n"
    
    md_content += f"\n---\n\n## 👩 女性音色 ({len(female_voices)})\n\n"
    md_content += "| # | 名称 | ID | 描述 | 使用次数 |\n"
    md_content += "|---|------|----|------|----------|\n\n"
    
    for i, voice in enumerate(female_voices, 1):
        voice_id = voice.get("voice_id", "")[:16] + "..." if len(voice.get("voice_id", "")) > 16 else voice.get("voice_id", "")
        title = voice.get("title", "未命名")
        description = voice.get("description", "")[:40] + "..." if len(voice.get("description", "")) > 40 else voice.get("description", "")
        task_count = voice.get("task_count", 0)
        
        title_escaped = title.replace("|", "\\|")
        description_escaped = description.replace("|", "\\|")
        
        md_content += f"| {i} | {title_escaped} | `{voice_id}` | {description_escaped} | {task_count:,} |\n"
    
    md_content += f"\n---\n\n## ❓ 未分类音色 ({len(unknown_voices)})\n\n"
    md_content += "| # | 名称 | ID | 描述 | 使用次数 |\n"
    md_content += "|---|------|----|------|----------|\n\n"
    
    for i, voice in enumerate(unknown_voices, 1):
        voice_id = voice.get("voice_id", "")[:16] + "..." if len(voice.get("voice_id", "")) > 16 else voice.get("voice_id", "")
        title = voice.get("title", "未命名")
        description = voice.get("description", "")[:40] + "..." if len(voice.get("description", "")) > 40 else voice.get("description", "")
        task_count = voice.get("task_count", 0)
        
        title_escaped = title.replace("|", "\\|")
        description_escaped = description.replace("|", "\\|")
        
        md_content += f"| {i} | {title_escaped} | `{voice_id}` | {description_escaped} | {task_count:,} |\n"
    
    md_content += "\n---\n\n## 详细列表\n\n"
    
    def add_detail_section(voices, title):
        md = f"### {title}\n\n"
        for voice in voices:
            voice_id = voice.get("voice_id", "")
            title_name = voice.get("title", "未命名")
            description = voice.get("description", "")
            tags = voice.get("tags", [])
            audio_url = voice.get("audio_url", "")
            task_count = voice.get("task_count", 0)
            
            md += f"#### {title_name}\n\n"
            md += f"**Voice ID**: `{voice_id}`\n\n"
            if description:
                md += f"**描述**: {description}\n\n"
            if tags:
                md += f"**标签**: {' | '.join(tags)}\n\n"
            md += f"**使用次数**: {task_count:,}\n\n"
            if audio_url:
                md += f"**示例音频**: [播放]({audio_url})\n\n"
            md += "---\n\n"
        return md
    
    md_content += add_detail_section(male_voices, "👨 男性音色")
    md_content += add_detail_section(female_voices, "👩 女性音色")
    md_content += add_detail_section(unknown_voices, "❓ 未分类音色")
    
    return md_content


def save_to_json(data, filepath):
    """保存到 JSON 文件"""
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    
    print(f"JSON 文件已保存: {filepath}")


def main():
    """主函数"""
    
    print("=" * 50)
    print("Fish Audio 中文音色获取工具")
    print("=" * 50)
    
    print("\n正在获取音色列表...")
    try:
        voices_raw = list_voices(page_size=200, page_number=1)
    except Exception as e:
        print(f"获取音色列表失败: {e}")
        return
    
    if not voices_raw:
        print("未获取到任何音色")
        return
    
    print(f"\n筛选中文音色...")
    chinese_voices = [v for v in voices_raw if is_chinese_voice(v)]
    print(f"找到 {len(chinese_voices)} 个中文音色")
    
    male_voices = []
    female_voices = []
    unknown_voices = []
    
    for voice in chinese_voices:
        gender = get_gender(voice)
        info = format_voice_info(voice, gender)
        
        if gender == "male":
            male_voices.append(info)
        elif gender == "female":
            female_voices.append(info)
        else:
            unknown_voices.append(info)
    
    # 按使用次数排序
    male_voices.sort(key=lambda v: v.get("task_count", 0), reverse=True)
    female_voices.sort(key=lambda v: v.get("task_count", 0), reverse=True)
    unknown_voices.sort(key=lambda v: v.get("task_count", 0), reverse=True)
    
    print(f"\n分类结果:")
    print(f"  👨 男性: {len(male_voices)} 个")
    print(f"  👩 女性: {len(female_voices)} 个")
    print(f"  ❓ 其他: {len(unknown_voices)} 个")
    
    # 生成 Markdown
    md_content = generate_markdown(male_voices, female_voices, unknown_voices)
    
    # 保存文件
    docs_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "docs")
    os.makedirs(docs_dir, exist_ok=True)
    
    md_path = os.path.join(docs_dir, "FISH_AUDIO_VOICES_CN.md")
    json_path = os.path.join(docs_dir, "FISH_AUDIO_VOICES_CN.json")
    
    with open(md_path, "w", encoding="utf-8") as f:
        f.write(md_content)
    
    print(f"\nMarkdown 文档已保存: {md_path}")
    
    # 保存 JSON
    save_to_json({
        "male": male_voices,
        "female": female_voices,
        "unknown": unknown_voices
    }, json_path)
    
    # 打印预览
    print("\n" + "=" * 50)
    print("男性音色 Top 10")
    print("=" * 50)
    for i, voice in enumerate(male_voices[:10], 1):
        print(f"{i}. {voice.get('title', '未命名')} - {voice.get('task_count', 0):,} 次")
    
    print("\n" + "=" * 50)
    print("女性音色 Top 10")
    print("=" * 50)
    for i, voice in enumerate(female_voices[:10], 1):
        print(f"{i}. {voice.get('title', '未命名')} - {voice.get('task_count', 0):,} 次")
    
    print("\n完成！")


if __name__ == "__main__":
    main()
