#!/usr/bin/env python3
"""
添加积分脚本
"""

import requests

# 配置
API_URL = "http://localhost:8100/api/v1/points/test/add-points"
TOKEN = "eyJhbGciOiJFUzI1NiIsImtpZCI6ImI4MTI2OWYxLTIxZDgtNGYyZS1iNzE5LWMyMjQwYTg0MGQ5MCIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJodHRwOi8vMTI3LjAuMC4xOjU0MzIxL2F1dGgvdjEiLCJzdWIiOiJmMmM4OGYwZS00ZWI0LTRhZmItYTZlZi04NTU3N2IyZGFlZjYiLCJhdWQiOiJhdXRoZW50aWNhdGVkIiwiZXhwIjoxNzY5OTA3ODMzLCJpYXQiOjE3Njk5MDQyMzMsImVtYWlsIjoiZmxvd2VyYmxpbmdzQGdtYWlsLmNvbSIsInBob25lIjoiIiwiYXBwX21ldGFkYXRhIjp7InByb3ZpZGVyIjoiZ29vZ2xlIiwicHJvdmlkZXJzIjpbImdvb2dsZSJdfSwidXNlcl9tZXRhZGF0YSI6eyJhdmF0YXJfdXJsIjoiaHR0cHM6Ly9saDMuZ29vZ2xldXNlcmNvbnRlbnQuY29tL2EvQUNnOG9jSW9ndVdpZUZfQVFwOWl6b1dubnFSRTBVb1BsNmxES3luMWJ4bVdJVnZQZ20zcWgzYz1zOTYtYyIsImVtYWlsIjoiZmxvd2VyYmxpbmdzQGdtYWlsLmNvbSIsImVtYWlsX3ZlcmlmaWVkIjp0cnVlLCJmdWxsX25hbWUiOiJ3YW5oZW5nIHpoYW5nIiwiaXNzIjoiaHR0cHM6Ly9hY2NvdW50cy5nb29nbGUuY29tIiwibmFtZSI6IndhbmhlbmcgemhhbmciLCJwaG9uZV92ZXJpZmllZCI6ZmFsc2UsInBpY3R1cmUiOiJodHRwczovL2xoMy5nb29nbGV1c2VyY29udGVudC5jb20vYS9BQ2c4b2NJb2d1V2llRl9BUXA5aXpvV25ucVJFMFVvUGw2bERLeW4xYnhtV0lWdlBnbTNxaDNjPXM5Ni1jIiwicHJvdmlkZXJfaWQiOiIxMDk1MzQzNTg1OTU1MjgzMjA3NzMiLCJzdWIiOiIxMDk1MzQzNTg1OTU1MjgzMjA3NzMifSwicm9sZSI6ImF1dGhlbnRpY2F0ZWQiLCJhYWwiOiJhYWwxIiwiYW1yIjpbeyJtZXRob2QiOiJvYXV0aCIsInRpbWVzdGFtcCI6MTc2OTg1MjkyMH1dLCJzZXNzaW9uX2lkIjoiNWJjYWU0MjYtMDJiOS00OTJmLWI2ZDUtYjJjNmZiYjMyZGRlIiwiaXNfYW5vbnltb3VzIjpmYWxzZX0.k1w2jlCC31COZpmARbYGCc-yYCnUZ6P-U9M6web7qqyUyLNNpgeVzfrgl6W5pFzs8p_vjy2UbmN-YgfiFlb9Kg"
USER_ID = 2
POINTS = 10000000

# 请求头
headers = {
    "Authorization": f"Bearer {TOKEN}",
    "Content-Type": "application/json"
}

# 请求体
data = {
    "user_id": USER_ID,
    "points": POINTS
}

try:
    print(f"正在为用户 {USER_ID} 添加 {POINTS} 积分...")
    response = requests.post(API_URL, headers=headers, json=data)
    
    print(f"状态码: {response.status_code}")
    print(f"响应: {response.text}")
    
    if response.status_code == 200:
        result = response.json()
        if result.get("success"):
            print("\n✅ 积分添加成功!")
            print(f"添加积分: {result['data']['points_added']}")
            print(f"当前可用积分: {result['data']['balance']['available_points']}")
        else:
            print(f"\n❌ 添加失败: {result.get('message', '未知错误')}")
    else:
        print(f"\n❌ 请求失败: HTTP {response.status_code}")
        
except Exception as e:
    print(f"\n❌ 发生错误: {e}")
