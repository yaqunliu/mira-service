"""
Agent 对话模拟器

模拟用户与 Agent 的完整交互流程，展示各种功能
"""

import asyncio
import aiohttp
import json
import sys
from datetime import datetime
from typing import List

API_BASE = "http://localhost:8100/api/v1"
CREATION_UUID = "ca45f265-fe48-4dab-a8c8-a186e0803fa8"

TOKEN = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJodHRwOi8vMTI3LjAuMC4xOjU0MzIxL2F1dGgvdjEiLCJzdWIiOiJhODUxZmQyNy05OTU0LTQwZmItOWFmMS1mMjY0OWI0N2M3NGIiLCJhdWQiOiJhdXRoZW50aWNhdGVkIiwiZXhwIjoxNzY5NjAwNDc1LCJpYXQiOjE3Njk1OTY4NzUsImVtYWlsIjoiZmxvd2VyYmxpbmdzQGdtYWlsLmNvbSIsInBob25lIjoiIiwiYXBwX21ldGFkYXRhIjp7InByb3ZpZGVyIjoiZ29vZ2xlIiwicHJvdmlkZXJzIjpbImdvb2dsZSJdfSwidXNlcl9tZXRhZGF0YSI6eyJhdmF0YXJfdXJsIjoiaHR0cHM6Ly9saDMuZ29vZ2xldXNlcmNvbnRlbnQuY29tL2EvQUNnOG9jSW9ndVdpZUZfQVFwOWl6b1dubnFSRTBVb1BsNmxES3luMWJ4bVdJVnZQZ20zcWgzYz1zOTYtYyIsImVtYWlsIjoiZmxvd2VyYmxpbmdzQGdtYWlsLmNvbSIsImVtYWlsX3ZlcmlmaWVkIjp0cnVlLCJmdWxsX25hbWUiOiJ3YW5oZW5nIHpoYW5nIiwiaXNzIjoiaHR0cHM6Ly9hY2NvdW50cy5nb29nbGUuY29tIiwibmFtZSI6IndhbmhlbmcgemhhbmciLCJwaG9uZV92ZXJpZmllZCI6ZmFsc2UsInBpY3R1cmUiOiJodHRwczovL2xoMy5nb29nbGV1c2VyY29udGVudC5jb20vYS9BQ2c4b2NJb2d1V2llRl9BUXA5aXpvV25ucVJFMFVvUGw2bERLeW4xYnhtV0lWdlBnbTNxaDNjPXM5Ni1jIiwicHJvdmlkZXJfaWQiOiIxMDk1MzQzNTg1OTU1MjgzMjA3NzMiLCJzdWIiOiIxMDk1MzQzNTg1OTU1MjgzMjA3NzMifSwicm9sZSI6ImF1dGhlbnRpY2F0ZWQiLCJhYWwiOiJhYWwxIiwiYW1yIjpbeyJtZXRob2QiOiJvYXV0aCIsInRpbWVzdGFtcCI6MTc2OTM5OTY2OH1dLCJzZXNzaW9uX2lkIjoiNTNhYmIwNDYtNDJiMy00ZTEzLTgyNmUtMjAxNGM5NmZlMmQ4IiwiaXNfYW5vbnltb3VzIjpmYWxzZX0.8y78SlNWT6UfUIqA_pdm70edtFdu5er6Hng-n37Tiog"


async def send_message(message: str, description: str = "") -> str:
    """发送消息并获取响应"""
    headers = {
        "Authorization": f"Bearer {TOKEN}",
        "Content-Type": "application/json"
    }
    chat_data = {
        "message": message,
        "stream": True
    }

    print(f"\n{'='*60}")
    print(f"👤 用户: {message}")
    if description:
        print(f"   ({description})")
    print("="*60)

    responses = []
    async with aiohttp.ClientSession() as session:
        try:
            async with session.post(
                f"{API_BASE}/creations/{CREATION_UUID}/agent/chat",
                json=chat_data,
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=30)
            ) as response:
                if response.status == 200:
                    async for line in response.content:
                        line = line.decode("utf-8").strip()
                        if line.startswith("data:"):
                            try:
                                data = json.loads(line[5:])
                                content = data.get("content", "")
                                if content:
                                    responses.append(content)
                            except json.JSONDecodeError:
                                pass
                else:
                    text = await response.text()
                    return f"❌ 错误: {response.status} - {text[:200]}"
        except Exception as e:
            return f"❌ 异常: {str(e)}"

    full_response = "".join(responses)
    print(f"\n🤖 Agent 回复:")
    print("-"*60)
    print(full_response)
    print("-"*60)

    return full_response


async def get_session_status() -> dict:
    """获取会话状态"""
    headers = {"Authorization": f"Bearer {TOKEN}"}
    async with aiohttp.ClientSession() as session:
        async with session.get(
            f"{API_BASE}/creations/{CREATION_UUID}/agent/status",
            headers=headers,
            timeout=aiohttp.ClientTimeout(total=10)
        ) as response:
            if response.status == 200:
                return await response.json()
            return {}


async def reset_session():
    """重置会话"""
    headers = {
        "Authorization": f"Bearer {TOKEN}",
        "Content-Type": "application/json"
    }
    reset_data = {"keep_assets": False}
    async with aiohttp.ClientSession() as session:
        async with session.post(
            f"{API_BASE}/creations/{CREATION_UUID}/agent/reset",
            json=reset_data,
            headers=headers,
            timeout=aiohttp.ClientTimeout(total=10)
        ) as response:
            return response.status == 200


async def main():
    """主函数 - 模拟完整对话流程"""
    print("="*60)
    print("🎬 Agent 对话模拟器")
    print("="*60)
    print(f"时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"创作 UUID: {CREATION_UUID}")
    print("="*60)

    print("\n📍 第一阶段: 初始状态查询")
    print("-"*60)

    await send_message(
        "当前创作状态怎么样？",
        "用户想了解项目的整体状态"
    )

    await send_message(
        "当前有多少人物和场景？",
        "用户想了解已识别的角色和场景数量"
    )

    print("\n📍 第二阶段: 图片生成状态查询")
    print("-"*60)

    await send_message(
        "图片生成完了吗？",
        "用户想了解图片生成进度"
    )

    await send_message(
        "帮我看看项目进度",
        "使用自然语言查询进度"
    )

    print("\n📍 第三阶段: 详细状态查询")
    print("-"*60)

    await send_message(
        "现在进行到哪一步了？",
        "用户想了解当前制作阶段"
    )

    await send_message(
        "有多少个场景？",
        "用户想了解场景详情"
    )

    print("\n📍 第四阶段: 混合查询测试")
    print("-"*60)

    await send_message(
        "状态查询，有多少人物和场景？",
        "混合查询角色和场景"
    )

    await send_message(
        "帮我看看",
        "模糊查询"
    )

    print("\n📍 第五阶段: 短消息测试")
    print("-"*60)

    await send_message(
        "状态",
        "极短消息测试"
    )

    await send_message(
        "人物",
        "查询角色"
    )

    print("\n" + "="*60)
    print("📊 对话模拟完成")
    print("="*60)
    print("\n✅ 已测试的功能:")
    print("  1. 总体状态查询")
    print("  2. 角色数量查询")
    print("  3. 场景数量查询")
    print("  4. 图片生成状态查询")
    print("  5. 当前阶段查询")
    print("  6. 自然语言混合查询")
    print("  7. 模糊查询")
    print("  8. 短消息查询")
    print("="*60)


if __name__ == "__main__":
    asyncio.run(main())
