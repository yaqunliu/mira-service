#!/usr/bin/env python3
"""
Vocab 英文单词视频Agent调试脚本

直接在文件开头配置参数后运行:
    python test_vocab.py
"""

import requests
import time


# ============== 配置参数 ==============
TOKEN = """
eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJodHRwOi8vMTI3LjAuMC4xOjU0MzIxL2F1dGgvdjEiLCJzdWIiOiJhODUxZmQyNy05OTU0LTQwZmItOWFmMS1mMjY0OWI0N2M3NGIiLCJhdWQiOiJhdXRoZW50aWNhdGVkIiwiZXhwIjoxNzcyNTA2MzQyLCJpYXQiOjE3NzI1MDI3NDIsImVtYWlsIjoiZmxvd2VyYmxpbmdzQGdtYWlsLmNvbSIsInBob25lIjoiIiwiYXBwX21ldGFkYXRhIjp7InByb3ZpZGVyIjoiZ29vZ2xlIiwicHJvdmlkZXJzIjpbImdvb2dsZSJdfSwidXNlcl9tZXRhZGF0YSI6eyJhdmF0YXJfdXJsIjoiaHR0cHM6Ly9saDMuZ29vZ2xldXNlcmNvbnRlbnQuY29tL2EvQUNnOG9jSW9ndVdpZUZfQVFwOWl6b1dubnFSRTBVb1BsNmxES3luMWJ4bVdJVnZQZ20zcWgzYz1zOTYtYyIsImVtYWlsIjoiZmxvd2VyYmxpbmdzQGdtYWlsLmNvbSIsImVtYWlsX3ZlcmlmaWVkIjp0cnVlLCJmdWxsX25hbWUiOiJ3YW5oZW5nIHpoYW5nIiwiaXNzIjoiaHR0cHM6Ly9hY2NvdW50cy5nb29nbGUuY29tIiwibmFtZSI6IndhbmhlbmcgemhhbmciLCJwaG9uZV92ZXJpZmllZCI6ZmFsc2UsInBpY3R1cmUiOiJodHRwczovL2xoMy5nb29nbGV1c2VyY29udGVudC5jb20vYS9BQ2c4b2NJb2d1V2llRl9BUXA5aXpvV25ucVJFMFVvUGw2bERLeW4xYnhtV0lWdlBnbTNxaDNjPXM5Ni1jIiwicHJvdmlkZXJfaWQiOiIxMDk1MzQzNTg1OTU1MjgzMjA3NzMiLCJzdWIiOiIxMDk1MzQzNTg1OTU1MjgzMjA3NzMifSwicm9sZSI6ImF1dGhlbnRpY2F0ZWQiLCJhYWwiOiJhYWwxIiwiYW1yIjpbeyJtZXRob2QiOiJvYXV0aCIsInRpbWVzdGFtcCI6MTc3MjQxODU2NH1dLCJzZXNzaW9uX2lkIjoiMmFhYWFiZjctMDIyNS00OTg5LTg2OWMtY2RmOTUwZjdhNzE3IiwiaXNfYW5vbnltb3VzIjpmYWxzZX0.SRW8U7qfkBKYbrgGDqvHyz8sEFpXpT6rWzK1sNV0Jfw
""".strip()

# 单词列表（支持格式：["apple"] 或 ["bus(公交车)"]）
# WORDS = ["monday", "tuesday", "wednesday"]
WORDS = ["apple", "bicycle"]
# ========== 单词视频参数 ==========
# 单词重复次数（1-5），默认2
WORD_REPEAT_COUNT = 2

# 翻译重复次数（1-3），默认1
TRANSLATION_REPEAT_COUNT = 1

# 声音性别: female, male
VOICE_GENDER = "female"

# 声音年龄: child, adult
VOICE_AGE = "child"

# 句子难度: kindergarten, primary, middle
SENTENCE_LEVEL = "primary"

# 视频生成模型: sora-2, viduq2, viduq2-pro, viduq2-turbo, doubao-seedance-1-5-pro-251215
VIDEO_MODEL = "sora-2"

# ========== API 配置 ==========
BASE_URL = "http://localhost:8100"

# 轮询间隔（秒）
POLL_INTERVAL = 5  # 轮询间隔（秒）

# 最大等待时间（秒）
MAX_WAIT = 2400
# ============== 配置结束 ==============


def create_task(
    words: list,
    word_repeat_count: int,
    translation_repeat_count: int,
    voice_gender: str,
    voice_age: str,
    sentence_level: str,
    video_model: str,
    token: str,
    base_url: str
) -> str:
    url = f"{base_url}/api/v1/vocab/create"
    
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {token}"
    }
    
    data = {
        "words": words,
        "word_repeat_count": word_repeat_count,
        "translation_repeat_count": translation_repeat_count,
        "voice_gender": voice_gender,
        "voice_age": voice_age,
        "sentence_level": sentence_level,
        "video_model": video_model
    }
    
    print(f"\n创建任务:")
    print(f"  单词: {words}")
    print(f"  单词重复次数: {word_repeat_count}")
    print(f"  翻译重复次数: {translation_repeat_count}")
    print(f"  声音性别: {voice_gender} (female=女, male=男)")
    print(f"  声音年龄: {voice_age} (child=小孩, adult=成人)")
    print(f"  句子难度: {sentence_level} (primary=小学, junior=初中, senior=高中)")
    # print(f"  视频模型: {video_model}")
    
    response = requests.post(url, json=data, headers=headers)
    
    if response.status_code != 200:
        print(f"创建任务失败: {response.status_code} - {response.text}")
        exit(1)
    
    result = response.json()
    task_uuid = result.get("task_uuid")
    
    print(f"\n任务创建成功: task_uuid={task_uuid}")
    
    return task_uuid


def poll_status(task_uuid: str, token: str, base_url: str, interval: int, max_wait: int):
    url = f"{base_url}/api/v1/vocab/uuid/{task_uuid}/status"
    
    headers = {
        "Authorization": f"Bearer {token}"
    }
    
    print(f"\n开始轮询任务状态 (间隔 {interval} 秒, 最多 {max_wait} 秒)...")
    print("-" * 50)
    
    waited = 0
    last_status = None
    last_progress = None
    last_step = None
    same_count = 0
    
    while waited < max_wait:
        time.sleep(interval)
        waited += interval
        
        try:
            response = requests.get(url, headers=headers)
            
            if response.status_code != 200:
                print(f"查询状态失败: {response.status_code}")
                continue
            
            result = response.json()
            status = result.get("status")
            progress = result.get("progress", 0)
            current_step = result.get("current_step", "")
            video_url = result.get("video_url")
            error_message = result.get("error_message")
            step_status = result.get("step_status", "")
            
            has_changed = status != last_status or progress != last_progress or current_step != last_step
            
            if has_changed or same_count >= 10:
                step_info = f", step_status={step_status}" if step_status else ""
                print(f"[{waited}s] status={status}, progress={progress}%, step={current_step}\n{step_info}")
                last_status = status
                last_progress = progress
                last_step = current_step
                same_count = 0
            else:
                same_count += 1
            
            if status == "completed":
                print("-" * 50)
                print(f"✅ 任务完成!")
                print(f"视频URL: {video_url}")
                print(f"step_status: {step_status}")
                return result
            
            if video_url:
                print("-" * 50)
                print(f"✅ 任务完成（有视频URL）!")
                print(f"视频URL: {video_url}")
                print(f"step_status: {step_status}")
                return result
            
            if status == "failed":
                print("-" * 50)
                print(f"❌ 任务失败!")
                print(f"错误信息: {error_message}")
                print(f"step_status: {step_status}")
                return result
                
        except Exception as e:
            print(f"查询异常: {e}")
    
    print("-" * 50)
    print(f"⏰ 等待超时 ({max_wait}秒)")
    return None


def main():
    print("=" * 50)
    print("Vocab 视频Agent调用")
    print("=" * 50)
    print(f"单词: {WORDS}")
    # print(f"模型: {VIDEO_MODEL}")
    # print(f"URL: {BASE_URL}")
    print("=" * 50)
    
    task_uuid = create_task(
        words=WORDS,
        word_repeat_count=WORD_REPEAT_COUNT,
        translation_repeat_count=TRANSLATION_REPEAT_COUNT,
        voice_gender=VOICE_GENDER,
        voice_age=VOICE_AGE,
        sentence_level=SENTENCE_LEVEL,
        video_model=VIDEO_MODEL,
        token=TOKEN,
        base_url=BASE_URL
    )
    
    result = poll_status(task_uuid, TOKEN, BASE_URL, POLL_INTERVAL, MAX_WAIT)
    
    if result:
        print("\n最终结果:")
        print(f"  status: {result.get('status')}")
        print(f"  progress: {result.get('progress')}%")
        print(f"  current_step: {result.get('current_step')}")
        print(f"  step_status: {result.get('step_status', '')}")
        print(f"  video_url: {result.get('video_url')}")
    else:
        exit(1)


if __name__ == "__main__":
    main()
