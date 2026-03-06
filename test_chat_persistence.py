#!/usr/bin/env python3
"""
测试 Chat 模式状态持久化
"""

import requests
import json
import time

BASE_URL = "http://localhost:8100"
TOKEN = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJodHRwOi8vMTI3LjAuMC4xOjU0MzIxL2F1dGgvdjEiLCJzdWIiOiJhODUxZmQyNy05OTU0LTQwZmItOWFmMS1mMjY0OWI0N2M3NGIiLCJhdWQiOiJhdXRoZW50aWNhdGVkIiwiZXhwIjoxNzcyNjEwMjk4LCJpYXQiOjE3NzI2MDY2OTgsImVtYWlsIjoiZmxvd2VyYmxpbmdzQGdtYWlsLmNvbSIsInBob25lIjoiIiwiYXBwX21ldGFkYXRhIjp7InByb3ZpZGVyIjoiZ29vZ2xlIiwicHJvdmlkZXJzIjpbImdvb2dsZSJdfSwidXNlcl9tZXRhZGF0YSI6eyJhdmF0YXJfdXJsIjoiaHR0cHM6Ly9saDMuZ29vZ2xldXNlcmNvbnRlbnQuY29tL2EvQUNnOG9jSW9ndVdpZUZfQVFwOWl6b1dubnFSRTBVb1BsNmxES3luMWJ4bVdJVnZQZ20zcWgzYz1zOTYtYyIsImVtYWlsIjoiZmxvd2VyYmxpbmdzQGdtYWlsLmNvbSIsImVtYWlsX3ZlcmlmaWVkIjp0cnVlLCJmdWxsX25hbWUiOiJ3YW5oZW5nIHpoYW5nIiwiaXNzIjoiaHR0cHM6Ly9hY2NvdW50cy5nb29nbGUuY29tIiwibmFtZSI6IndhbmhlbmcgemhhbmciLCJwaG9uZV92ZXJpZmllZCI6ZmFsc2UsInBpY3R1cmUiOiJodHRwczovL2xoMy5nb29nbGV1c2VyY29udGVudC5jb20vYS9BQ2c4b2NJb2d1V2llRl9BUXA5aXpvV25ucVJFMFVvUGw2bERLeW4xYnhtV0lWdlBnbTNxaDNjPXM5Ni1jIiwicHJvdmlkZXJfaWQiOiIxMDk1MzQzNTg1OTU1MjgzMjA3NzMiLCJzdWIiOiIxMDk1MzQzNTg1OTU1MjgzMjA3NzMifSwicm9sZSI6ImF1dGhlbnRpY2F0ZWQiLCJhYWwiOiJhYWwxIiwiYW1yIjpbeyJtZXRob2QiOiJvYXV0aCIsInRpbWVzdGFtcCI6MTc3MjQxODU2NH1dLCJzZXNzaW9uX2lkIjoiMmFhYWFiZjctMDIyNS00OTg5LTg2OWMtY2RmOTUwZjdhNzE3IiwiaXNfYW5vbnltb3VzIjpmYWxzZX0.npwwbT6Bav9g_jnYopImdSTVFbusFtqfpZIsHk1QP9Y"

# 创建项目 ID（从之前的测试获取）
CREATION_UUID = "613134b6-ee8a-4415-ab8c-a836a2adb780"

def send_message(message: str):
    """发送聊天消息"""
    headers = {
        "Authorization": f"Bearer {TOKEN}",
        "Content-Type": "application/json"
    }
    
    # 先获取 session
    session_resp = requests.get(
        f"{BASE_URL}/api/v1/creations/{CREATION_UUID}/agent/session",
        headers=headers
    )
    print(f"Session: {session_resp.status_code}")
    session_data = session_resp.json()
    thread_id = session_data.get("thread_id")
    print(f"Thread ID: {thread_id}")
    
    # 发送消息
    resp = requests.post(
        f"{BASE_URL}/api/v1/creations/{CREATION_UUID}/agent/chat",
        headers=headers,
        json={"message": message},
        stream=True
    )
    
    print(f"\n发送: {message}")
    print(f"状态: {resp.status_code}")
    
    # 读取响应
    for line in resp.iter_lines():
        if line:
            data = line.decode('utf-8')
            if data.startswith('data: '):
                try:
                    event_data = json.loads(data[6:])
                    event_type = event_data.get("event", "")
                    if event_type == "message.delta":
                        content = event_data.get("data", {}).get("content", "")
                        if content:
                            print(f"  回复: {content[:100]}...")
                    elif event_type == "message.end":
                        print("  消息结束")
                    elif event_type == "progress":
                        node = event_data.get("data", {}).get("node", "")
                        status = event_data.get("data", {}).get("status", "")
                        print(f"  进度: {node} - {status}")
                    elif event_type == "board_action":
                        action = event_data.get("data", {})
                        print(f"  卡片: {action.get('type')}")
                except:
                    pass
    print("-" * 50)


if __name__ == "__main__":
    print("=" * 50)
    print("测试 Chat 模式状态持久化")
    print("=" * 50)
    
    # 1. 发送问候
    send_message("你好")
    time.sleep(2)
    
    # 2. 选择视频类型
    send_message("我要创作英文单词视频")
    time.sleep(2)
    
    # 3. 填写参数
    send_message("单词列表: apple, banana，句子难度: 小学")
    time.sleep(2)
    
    # 4. 再次发送消息，测试状态是否保持
    send_message("再添加一个单词 cat")
    time.sleep(2)
    
    print("\n测试完成！")
    print("请查看日志，确认状态是否正确保存和加载")
