#!/usr/bin/env python3
"""
获取 Fish Audio 音色列表并保存为 JSON
按 task_count 排序，保存前 5000 个

使用方法:
    uv run python fetch_fish_voices.py

环境变量:
    FISH_AUDIO_API_KEY - Fish Audio API Key
"""

import os
import json
import asyncio
from pathlib import Path

# 设置 Python 路径
import sys
sys.path.insert(0, str(Path(__file__).parent))

from fishaudio import FishAudio
from app.core.config import settings


def sample_to_dict(sample):
    """将 Sample 对象转换为字典"""
    if hasattr(sample, '__dict__'):
        return {
            "id": getattr(sample, 'id', ''),
            "title": getattr(sample, 'title', ''),
            "text": getattr(sample, 'text', ''),
            "task_id": getattr(sample, 'task_id', ''),
            "audio_url": getattr(sample, 'audio', ''),  # API 返回的字段是 audio 不是 audio_url
        }
    return str(sample)


def infer_gender_from_tags(tags):
    """从 tags 中推断性别"""
    if not tags:
        return "unknown"
    
    tags_lower = [str(t).lower() for t in tags]
    
    # 男性标识
    male_indicators = ["male", "man", "boy", "男", "男生", "男孩", "男声"]
    # 女性标识
    female_indicators = ["female", "woman", "girl", "女", "女生", "女孩", "女声"]
    
    for tag in tags_lower:
        if any(ind in tag for ind in male_indicators):
            return "male"
        if any(ind in tag for ind in female_indicators):
            return "female"
    
    return "unknown"


async def fetch_all_voices():
    """获取所有音色并保存"""
    
    # 直接从环境变量或配置获取 API Key
    api_key = settings.FISH_AUDIO_API_KEY
    if not api_key:
        print("错误: 未设置 FISH_AUDIO_API_KEY")
        return
    
    # 初始化 Fish Audio 客户端
    client = FishAudio(api_key=api_key)
    
    all_voices = []
    page_number = 1
    page_size = 100
    max_pages = 100  # 最多获取 100 页，确保能获取足够多的音色
    
    print("开始获取 Fish Audio 音色列表...")
    print(f"API Key: {api_key[:10]}...")
    print("按 task_count 排序获取...")
    
    while page_number <= max_pages:
        try:
            print(f"\n获取第 {page_number} 页...")
            
            # 调用 API 获取音色列表，按 task_count 排序
            response = client.voices.list(
                language="zh",
                page_size=page_size,
                page_number=page_number,
                sort_by="task_count"  # 按使用次数排序
            )
            
            # 从 PaginatedResponse 中获取 items
            voices = list(response.items) if hasattr(response, 'items') else list(response)
            
            print(f"  获取到 {len(voices)} 个音色")
            
            if not voices:
                print(f"  第 {page_number} 页没有数据，停止获取")
                break
            
            # 处理每个音色的数据
            for voice in voices:
                # 获取 voice 的属性
                tags = list(getattr(voice, 'tags', [])) if hasattr(voice, 'tags') else []
                
                # 从 API 获取 gender，如果没有则从 tags 推断
                gender = getattr(voice, 'gender', 'unknown')
                if not gender or gender == 'unknown':
                    gender = infer_gender_from_tags(tags)
                
                # 处理 samples 字段
                samples = []
                if hasattr(voice, 'samples'):
                    for sample in voice.samples:
                        samples.append(sample_to_dict(sample))
                
                # 只保留需要的字段
                voice_data = {
                    "id": getattr(voice, 'id', str(voice)),
                    "title": getattr(voice, 'title', 'Unknown'),
                    "description": getattr(voice, 'description', ''),
                    "gender": gender,
                    "task_count": getattr(voice, 'task_count', 0),
                    "samples": samples,
                }
                all_voices.append(voice_data)
                print(f"  ✓ {voice_data['title']}: task_count={voice_data['task_count']}, gender={gender}")
            
            # 如果获取的数量小于 page_size，说明已经到最后一页
            if len(voices) < page_size:
                print(f"\n已获取所有音色，共 {len(all_voices)} 个")
                break
            
            page_number += 1
            
        except Exception as e:
            print(f"\n获取第 {page_number} 页失败: {e}")
            import traceback
            traceback.print_exc()
            break
    
    if not all_voices:
        print("\n没有获取到任何音色")
        return
    
    # 按 task_count 排序（从高到低）
    all_voices.sort(key=lambda x: x.get('task_count', 0), reverse=True)
    
    # 只保留前 5000 个
    top_voices = all_voices[:5000]
    
    # 按性别分类
    categorized = {
        "male": [],
        "female": [],
        "unknown": []
    }
    
    for voice in top_voices:
        gender = voice.get("gender", "unknown")
        if gender in categorized:
            categorized[gender].append(voice)
        else:
            categorized["unknown"].append(voice)
    
    # 保存到文件
    output_file = Path(__file__).parent / "docs" / "FISH_AUDIO_VOICES_REAL.json"
    output_file.parent.mkdir(parents=True, exist_ok=True)
    
    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(categorized, f, ensure_ascii=False, indent=2)
    
    print(f"\n{'='*60}")
    print(f"音色列表已保存到: {output_file}")
    print(f"原始获取: {len(all_voices)} 个音色")
    print(f"保留前 5000 个")
    print(f"  - 男声: {len(categorized['male'])} 个")
    print(f"  - 女声: {len(categorized['female'])} 个")
    print(f"  - 未知: {len(categorized['unknown'])} 个")
    print(f"{'='*60}")
    
    # 打印前 20 个音色的详细信息
    print("\n前 20 个音色详情（按 task_count 排序）:")
    for i, voice in enumerate(top_voices[:20], 1):
        print(f"\n{i}. {voice['title']}")
        print(f"   id: {voice['id']}")
        print(f"   task_count: {voice['task_count']}")
        desc = voice['description']
        if len(desc) > 80:
            desc = desc[:80] + "..."
        print(f"   description: {desc}")
        print(f"   gender: {voice['gender']}")


if __name__ == "__main__":
    asyncio.run(fetch_all_voices())
