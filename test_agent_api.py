#!/usr/bin/env python3
"""
Agent API 测试脚本
测试所有 Agent 相关的 API 端点
"""

import asyncio
import aiohttp
import json
import sys
from datetime import datetime
from pathlib import Path

BASE_URL = "http://localhost:8100"
API_BASE = f"{BASE_URL}/api/v1"

TOKEN = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJodHRwOi8vMTI3LjAuMC4xOjU0MzIxL2F1dGgvdjEiLCJzdWIiOiJhODUxZmQyNy05OTU0LTQwZmItOWFmMS1mMjY0OWI0N2M3NGIiLCJhdWQiOiJhdXRoZW50aWNhdGVkIiwiZXhwIjoxNzY5NjAwNDc1LCJpYXQiOjE3Njk1OTY4NzUsImVtYWlsIjoiZmxvd2VyYmxpbmdzQGdtYWlsLmNvbSIsInBob25lIjoiIiwiYXBwX21ldGFkYXRhIjp7InByb3ZpZGVyIjoiZ29vZ2xlIiwicHJvdmlkZXJzIjpbImdvb2dsZSJdfSwidXNlcl9tZXRhZGF0YSI6eyJhdmF0YXJfdXJsIjoiaHR0cHM6Ly9saDMuZ29vZ2xldXNlcmNvbnRlbnQuY29tL2EvQUNnOG9jSW9ndVdpZUZfQVFwOWl6b1dubnFSRTBVb1BsNmxES3luMWJ4bVdJVnZQZ20zcWgzYz1zOTYtYyIsImVtYWlsIjoiZmxvd2VyYmxpbmdzQGdtYWlsLmNvbSIsImVtYWlsX3ZlcmlmaWVkIjp0cnVlLCJmdWxsX25hbWUiOiJ3YW5oZW5nIHpoYW5nIiwiaXNzIjoiaHR0cHM6Ly9hY2NvdW50cy5nb29nbGUuY29tIiwibmFtZSI6IndhbmhlbmcgemhhbmciLCJwaG9uZV92ZXJpZmllZCI6ZmFsc2UsInBpY3R1cmUiOiJodHRwczovL2xoMy5nb29nbGV1c2VyY29udGVudC5jb20vYS9BQ2c4b2NJb2d1V2llRl9BUXA5aXpvV25ucVJFMFVvUGw2bERLeW4xYnhtV0lWdlBnbTNxaDNjPXM5Ni1jIiwicHJvdmlkZXJfaWQiOiIxMDk1MzQzNTg1OTU1MjgzMjA3NzMiLCJzdWIiOiIxMDk1MzQzNTg1OTU1MjgzMjA3NzMifSwicm9sZSI6ImF1dGhlbnRpY2F0ZWQiLCJhYWwiOiJhYWwxIiwiYW1yIjpbeyJtZXRob2QiOiJvYXV0aCIsInRpbWVzdGFtcCI6MTc2OTM5OTY2OH1dLCJzZXNzaW9uX2lkIjoiNTNhYmIwNDYtNDJiMy00ZTEzLTgyNmUtMjAxNGM5NmZlMmQ4IiwiaXNfYW5vbnltb3VzIjpmYWxzZX0.8y78SlNWT6UfUIqA_pdm70edtFdu5er6Hng-n37Tiog"
CREATION_UUID = "ca45f265-fe48-4dab-a8c8-a186e0803fa8"

HEADERS = {
    "Authorization": f"Bearer {TOKEN}",
    "Content-Type": "application/json"
}

test_results = []

def log_result(test_name, status, details=""):
    """记录测试结果"""
    result = {
        "timestamp": datetime.now().isoformat(),
        "test_name": test_name,
        "status": status,
        "details": details
    }
    test_results.append(result)
    status_symbol = "✓" if status == "PASS" else "✗" if status == "FAIL" else "⚠"
    print(f"{status_symbol} {test_name}: {status}")
    if details:
        print(f"   {details}")

async def test_get_session_status(session, creation_uuid):
    """测试获取会话状态"""
    url = f"{API_BASE}/creations/{creation_uuid}/agent/status"
    try:
        async with session.get(url, headers=HEADERS) as response:
            text = await response.text()
            if response.status == 200:
                log_result("GET /creations/{uuid}/agent/status", "PASS", f"状态码: {response.status}")
                return json.loads(text)
            else:
                log_result("GET /creations/{uuid}/agent/status", "FAIL", f"状态码: {response.status}, 响应: {text[:200]}")
                return None
    except Exception as e:
        log_result("GET /creations/{uuid}/agent/status", "FAIL", f"异常: {str(e)}")
        return None

async def test_get_message_history(session, creation_uuid):
    """测试获取消息历史"""
    url = f"{API_BASE}/creations/{creation_uuid}/agent/messages"
    try:
        async with session.get(url, headers=HEADERS) as response:
            text = await response.text()
            if response.status == 200:
                log_result("GET /creations/{uuid}/agent/messages", "PASS", f"状态码: {response.status}")
                return json.loads(text)
            else:
                log_result("GET /creations/{uuid}/agent/messages", "FAIL", f"状态码: {response.status}, 响应: {text[:200]}")
                return None
    except Exception as e:
        log_result("GET /creations/{uuid}/agent/messages", "FAIL", f"异常: {str(e)}")
        return None

async def test_reset_session(session, creation_uuid):
    """测试重置会话"""
    url = f"{API_BASE}/creations/{creation_uuid}/agent/reset"
    payload = {"confirm": True}
    try:
        async with session.post(url, json=payload, headers=HEADERS) as response:
            text = await response.text()
            if response.status in [200, 202]:
                log_result("POST /creations/{uuid}/agent/reset", "PASS", f"状态码: {response.status}")
                return json.loads(text) if text else {"success": True}
            else:
                log_result("POST /creations/{uuid}/agent/reset", "FAIL", f"状态码: {response.status}, 响应: {text[:200]}")
                return None
    except Exception as e:
        log_result("POST /creations/{uuid}/agent/reset", "FAIL", f"异常: {str(e)}")
        return None

async def test_interrupt_session(session, creation_uuid):
    """测试中断会话"""
    url = f"{API_BASE}/creations/{creation_uuid}/agent/interrupt"
    payload = {"reason": "测试中断", "message_id": "test-001"}
    try:
        async with session.post(url, json=payload, headers=HEADERS) as response:
            text = await response.text()
            if response.status in [200, 202]:
                log_result("POST /creations/{uuid}/agent/interrupt", "PASS", f"状态码: {response.status}")
                return json.loads(text) if text else {"success": True}
            else:
                log_result("POST /creations/{uuid}/agent/interrupt", "FAIL", f"状态码: {response.status}, 响应: {text[:200]}")
                return None
    except Exception as e:
        log_result("POST /creations/{uuid}/agent/interrupt", "FAIL", f"异常: {str(e)}")
        return None

async def test_agent_chat(session, creation_uuid):
    """测试 Agent 聊天（流式）"""
    url = f"{API_BASE}/creations/{creation_uuid}/agent/chat"
    
    script_content = """# 镜头1: 日内, 办公室

主角小明坐在办公桌前,看着电脑屏幕,表情焦虑。

小明: (自言自语) 这个项目又要延期了,该怎么办?

# 镜头2: 日内, 会议室

经理走进会议室,大家都很紧张。

经理: 各位,我有一个好消息要宣布。

# 镜头3: 日内, 办公室

小明接到电话,脸上露出惊喜的表情。

小明: 真的吗?太好了!"""
    
    payload = {
        "message": "请根据上面的剧本开始工作",
        "context": {
            "script_text": script_content
        },
        "stream": True
    }
    
    try:
        async with session.post(url, json=payload, headers=HEADERS) as response:
            if response.status == 200:
                log_result("POST /agent/chat (流式)", "PASS", f"状态码: {response.status}, 开始接收流式响应")
                
                chunk_count = 0
                message_count = 0
                async for chunk in response.content:
                    chunk_str = chunk.decode('utf-8')
                    if chunk_str.startswith('data: '):
                        try:
                            data = json.loads(chunk_str[6:])
                            if data.get('event') == 'message':
                                message_count += 1
                        except:
                            pass
                    chunk_count += 1
                    
                    if chunk_count > 100:
                        break
                
                log_result("流式响应统计", "INFO", f"收到 {chunk_count} 个数据块, {message_count} 条消息")
                return True
            else:
                text = await response.text()
                log_result("POST /agent/chat", "FAIL", f"状态码: {response.status}, 响应: {text[:300]}")
                return False
    except asyncio.TimeoutError:
        log_result("POST /agent/chat", "FAIL", "请求超时")
        return False
    except Exception as e:
        log_result("POST /agent/chat", "FAIL", f"异常: {str(e)}")
        return False

async def test_health_check(session):
    """测试健康检查"""
    url = f"{BASE_URL}/health"
    try:
        async with session.get(url) as response:
            if response.status == 200:
                log_result("GET /health", "PASS", f"服务健康")
                return True
            else:
                log_result("GET /health", "FAIL", f"状态码: {response.status}")
                return False
    except Exception as e:
        log_result("GET /health", "FAIL", f"异常: {str(e)}")
        return False

async def run_all_tests():
    """运行所有测试"""
    print("=" * 60)
    print("Agent API 测试开始")
    print("=" * 60)
    print(f"测试时间: {datetime.now().isoformat()}")
    print(f"Base URL: {BASE_URL}")
    print(f"Creation UUID: {CREATION_UUID}")
    print("=" * 60)
    print()
    
    connector = aiohttp.TCPConnector(limit=10)
    timeout = aiohttp.ClientTimeout(total=300)
    async with aiohttp.ClientSession(connector=connector, timeout=timeout) as session:
        print("1. 测试健康检查...")
        await test_health_check(session)
        print()
        
        print("2. 测试获取会话状态...")
        status = await test_get_session_status(session, CREATION_UUID)
        print()
        
        print("3. 测试获取消息历史...")
        messages = await test_get_message_history(session, CREATION_UUID)
        print()
        
        print("4. 测试重置会话...")
        await test_reset_session(session, CREATION_UUID)
        print()
        
        print("5. 测试获取消息历史（重置后）...")
        messages_after_reset = await test_get_message_history(session, CREATION_UUID)
        print()
        
        print("6. 测试 Agent 聊天（流式）...")
        chat_success = await test_agent_chat(session, CREATION_UUID)
        print()
        
        print("7. 测试获取消息历史（聊天后）...")
        messages_after_chat = await test_get_message_history(session, CREATION_UUID)
        print()
        
        print("8. 测试中断会话...")
        await test_interrupt_session(session, CREATION_UUID)
        print()
        
        print("9. 最终检查会话状态...")
        final_status = await test_get_session_status(session, CREATION_UUID)
        print()
    
    print("=" * 60)
    print("测试完成!")
    print("=" * 60)
    
    passed = sum(1 for r in test_results if r["status"] == "PASS")
    failed = sum(1 for r in test_results if r["status"] == "FAIL")
    total = len(test_results)
    
    summary = f"""
测试结果汇总:
--------------
总测试数: {total}
通过: {passed}
失败: {failed}
通过率: {passed/total*100:.1f}%

测试时间: {datetime.now().isoformat()}
"""
    print(summary)
    
    return test_results

def save_results(results):
    """保存测试结果到文件"""
    output_file = Path("/Users/user/code/mira/agent_test_results.txt")
    
    passed = sum(1 for r in results if r["status"] == "PASS")
    failed = sum(1 for r in results if r["status"] == "FAIL")
    total = len(results)
    
    with open(output_file, 'w', encoding='utf-8') as f:
        f.write("=" * 60 + "\n")
        f.write("Agent API 测试结果报告\n")
        f.write("=" * 60 + "\n\n")
        
        f.write(f"测试时间: {datetime.now().isoformat()}\n")
        f.write(f"Base URL: {BASE_URL}\n")
        f.write(f"Creation UUID: {CREATION_UUID}\n\n")
        
        f.write("-" * 60 + "\n")
        f.write("测试结果汇总\n")
        f.write("-" * 60 + "\n")
        f.write(f"总测试数: {total}\n")
        f.write(f"通过: {passed}\n")
        f.write(f"失败: {failed}\n")
        f.write(f"通过率: {passed/total*100:.1f}%\n\n")
        
        f.write("-" * 60 + "\n")
        f.write("详细测试结果\n")
        f.write("-" * 60 + "\n\n")
        
        for i, result in enumerate(results, 1):
            status_symbol = "✓" if result["status"] == "PASS" else "✗" if result["status"] == "FAIL" else "⚠"
            f.write(f"{i}. [{result['status']}] {result['test_name']}\n")
            f.write(f"   时间: {result['timestamp']}\n")
            if result['details']:
                f.write(f"   详情: {result['details']}\n")
            f.write("\n")
        
        f.write("=" * 60 + "\n")
        f.write("测试结束\n")
        f.write("=" * 60 + "\n")
    
    print(f"\n结果已保存到: {output_file}")
    return output_file

if __name__ == "__main__":
    results = asyncio.run(run_all_tests())
    save_results(results)
