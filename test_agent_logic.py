"""
Agent API 逻辑测试

测试 Agent 的逻辑功能，包括：
- 状态查询功能（人物数量、场景数量、图片生成状态等）
- 响应内容是否合理
- 各种边界情况
"""

import asyncio
import json
import aiohttp
import sys
from datetime import datetime
from typing import List, Dict, Any, Optional

API_BASE = "http://localhost:8100/api/v1"
TEST_CREATION_UUID = "ca45f265-fe48-4dab-a8c8-a186e0803fa8"

TOKEN = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJodHRwOi8vMTI3LjAuMC4xOjU0MzIxL2F1dGgvdjEiLCJzdWIiOiJhODUxZmQyNy05OTU0LTQwZmItOWFmMS1mMjY0OWI0N2M3NGIiLCJhdWQiOiJhdXRoZW50aWNhdGVkIiwiZXhwIjoxNzY5NjAzOTg1LCJpYXQiOjE3Njk2MDAzODUsImVtYWlsIjoiZmxvd2VyYmxpbmdzQGdtYWlsLmNvbSIsInBob25lIjoiIiwiYXBwX21ldGFkYXRhIjp7InByb3ZpZGVyIjoiZ29vZ2xlIiwicHJvdmlkZXJzIjpbImdvb2dsZSJdfSwidXNlcl9tZXRhZGF0YSI6eyJhdmF0YXJfdXJsIjoiaHR0cHM6Ly9saDMuZ29vZ2xldXNlcmNvbnRlbnQuY29tL2EvQUNnOG9jSW9ndVdpZUZfQVFwOWl6b1dubnFSRTBVb1BsNmxES3luMWJ4bVdJVnZQZ20zcWgzYz1zOTYtYyIsImVtYWlsIjoiZmxvd2VyYmxpbmdzQGdtYWlsLmNvbSIsImVtYWlsX3ZlcmlmaWVkIjp0cnVlLCJmdWxsX25hbWUiOiJ3YW5oZW5nIHpoYW5nIiwiaXNzIjoiaHR0cHM6Ly9hY2NvdW50cy5nb29nbGUuY29tIiwibmFtZSI6IndhbmhlbmcgemhhbmciLCJwaG9uZV92ZXJpZmllZCI6ZmFsc2UsInBpY3R1cmUiOiJodHRwczovL2xoMy5nb29nbGV1c2VyY29udGVudC5jb20vYS9BQ2c4b2NJb2d1V2llRl9BUXA5aXpvV25ucVJFMFVvUGw2bERLeW4xYnhtV0lWdlBnbTNxaDNjPXM5Ni1jIiwicHJvdmlkZXJfaWQiOiIxMDk1MzQzNTg1OTU1MjgzMjA3NzMiLCJzdWIiOiIxMDk1MzQzNTg1OTU1MjgzMjA3NzMifSwicm9sZSI6ImF1dGhlbnRpY2F0ZWQiLCJhYWwiOiJhYWwxIiwiYW1yIjpbeyJtZXRob2QiOiJvYXV0aCIsInRpbWVzdGFtcCI6MTc2OTM5OTY2OH1dLCJzZXNzaW9uX2lkIjoiNTNhYmIwNDYtNDJiMy00ZTEzLTgyNmUtMjAxNGM5NmZlMmQ4IiwiaXNfYW5vbnltb3VzIjpmYWxzZX0.6g88V1f1dM7Ltb97GwGZTqBC-oeNfQx-aZiep3fA81c"

results: List[Dict[str, Any]] = []


def log_test(name: str, passed: bool, details: str = ""):
    """记录测试结果"""
    status = "✓ PASS" if passed else "✗ FAIL"
    print(f"{status} {name}")
    if details:
        print(f"   {details}")
    results.append({
        "test": name,
        "passed": passed,
        "details": details,
        "timestamp": datetime.now().isoformat()
    })


async def test_health_check():
    """测试健康检查"""
    print("\n" + "=" * 60)
    print("健康检查")
    print("=" * 60)

    async with aiohttp.ClientSession() as session:
        try:
            async with session.get(
                f"{API_BASE}/creations/{TEST_CREATION_UUID}/agent/status",
                headers={"Authorization": f"Bearer {TOKEN}"},
                timeout=aiohttp.ClientTimeout(total=5)
            ) as response:
                text = await response.text()
                if response.status == 200:
                    log_test("健康检查", True, "Agent 服务正常运行")
                    return True
                else:
                    log_test("健康检查", False, f"状态码: {response.status}")
                    return False
        except Exception as e:
            log_test("健康检查", False, f"连接失败: {str(e)}")
            return False


async def get_session_status(session, token: str) -> Dict[str, Any]:
    """获取会话状态"""
    headers = {"Authorization": f"Bearer {token}"}
    async with session.get(
        f"{API_BASE}/creations/{TEST_CREATION_UUID}/agent/status",
        headers=headers,
        timeout=aiohttp.ClientTimeout(total=10)
    ) as response:
        text = await response.text()
        if response.status == 200:
            return json.loads(text)
        return {}


async def reset_session(session, token: str):
    """重置会话"""
    headers = {"Authorization": f"Bearer {token}"}
    reset_data = {"keep_assets": False}
    async with session.post(
        f"{API_BASE}/creations/{TEST_CREATION_UUID}/agent/reset",
        json=reset_data,
        headers=headers,
        timeout=aiohttp.ClientTimeout(total=10)
    ) as response:
        return response.status == 200


async def send_message(session, message: str) -> List[str]:
    """发送消息并收集响应"""
    headers = {
        "Authorization": f"Bearer {TOKEN}",
        "Content-Type": "application/json"
    }
    chat_data = {
        "message": message,
        "stream": True
    }

    responses = []
    try:
        async with session.post(
            f"{API_BASE}/creations/{TEST_CREATION_UUID}/agent/chat",
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
                log_test(f"发送消息: {message[:30]}...", False, f"状态码: {response.status}, 响应: {text[:200]}")
    except Exception as e:
        log_test(f"发送消息: {message[:30]}...", False, f"异常: {str(e)}")

    return responses


async def test_status_queries():
    """测试状态查询功能"""
    print("\n" + "=" * 60)
    print("状态查询功能测试")
    print("=" * 60)

    headers = {"Authorization": f"Bearer {TOKEN}"}

    async with aiohttp.ClientSession() as session:
        await reset_session(session, TOKEN)

        print("\n--- 测试 1: 查询总体状态 ---")
        responses = await send_message(session, "当前创作状态怎么样？")
        if responses:
            full_response = " ".join(responses)
            has_status_info = any(keyword in full_response for keyword in ["阶段", "角色", "场景", "状态", "进度"])
            log_test("查询总体状态", has_status_info, f"响应包含状态信息: {has_status_info}\n响应: {full_response[:200]}...")
        else:
            log_test("查询总体状态", False, "无响应")

        print("\n--- 测试 2: 查询角色数量 ---")
        responses = await send_message(session, "当前有多少人物？")
        if responses:
            full_response = " ".join(responses)
            has_count = any(keyword in full_response for keyword in ["角色", "共", "个", "0"])
            log_test("查询角色数量", has_count, f"响应包含角色信息: {full_response[:200]}")
        else:
            log_test("查询角色数量", False, "无响应")

        print("\n--- 测试 3: 查询场景数量 ---")
        responses = await send_message(session, "有多少个场景？")
        if responses:
            full_response = " ".join(responses)
            has_count = any(keyword in full_response for keyword in ["场景", "共", "个", "0"])
            log_test("查询场景数量", has_count, f"响应包含场景信息: {full_response[:200]}")
        else:
            log_test("查询场景数量", False, "无响应")

        print("\n--- 测试 4: 查询图片生成状态 ---")
        responses = await send_message(session, "图片生成状态如何？")
        if responses:
            full_response = " ".join(responses)
            has_image_status = any(keyword in full_response for keyword in ["图片", "生成", "进度", "完成"])
            log_test("查询图片状态", has_image_status, f"响应包含图片信息: {full_response[:200]}")
        else:
            log_test("查询图片状态", False, "无响应")

        print("\n--- 测试 5: 查询当前阶段 ---")
        responses = await send_message(session, "现在进行到哪一步了？")
        if responses:
            full_response = " ".join(responses)
            has_stage = any(keyword in full_response for keyword in ["阶段", "步骤", "进行", "当前"])
            log_test("查询当前阶段", has_stage, f"响应包含阶段信息: {full_response[:200]}")
        else:
            log_test("查询当前阶段", False, "无响应")


async def test_natural_language_queries():
    """测试自然语言查询"""
    print("\n" + "=" * 60)
    print("自然语言查询测试")
    print("=" * 60)

    async with aiohttp.ClientSession() as session:
        await reset_session(session, TOKEN)

        natural_queries = [
            ("我想知道现在的情况", "模糊查询"),
            ("帮我看看项目进度", "进度查询"),
            ("现在有几个角色了", "角色数量查询"),
            ("场景生成了多少", "场景数量查询"),
            ("图片生成完了吗", "图片状态查询"),
        ]

        for query, description in natural_queries:
            print(f"\n--- 测试: {description} ---")
            responses = await send_message(session, query)
            if responses:
                full_response = " ".join(responses)
                log_test(description, True, f"响应: {full_response[:150]}...")
            else:
                log_test(description, False, "无响应")


async def test_logic合理性():
    """测试响应逻辑的合理性"""
    print("\n" + "=" * 60)
    print("响应逻辑合理性测试")
    print("=" * 60)

    async with aiohttp.ClientSession() as session:
        await reset_session(session, TOKEN)

        print("\n--- 测试: 空状态下的响应 ---")
        responses = await send_message(session, "当前有多少人物？")
        if responses:
            full_response = " ".join(responses)
            is_reasonable = "暂无" in full_response or "0" in full_response or "没有" in full_response
            log_test("空状态响应合理", is_reasonable, f"响应: {full_response[:150]}")
        else:
            log_test("空状态响应合理", False, "无响应")

        print("\n--- 测试: 状态查询应该立即返回 ---")
        import time
        start = time.time()
        responses = await send_message(session, "查询状态")
        elapsed = time.time() - start

        is_fast = elapsed < 5
        log_test("状态查询响应速度快", is_fast, f"耗时: {elapsed:.2f}秒")


async def test_edge_cases():
    """测试边界情况"""
    print("\n" + "=" * 60)
    print("边界情况测试")
    print("=" * 60)

    async with aiohttp.ClientSession() as session:
        print("\n--- 测试: 非常短的消息 ---")
        responses = await send_message(session, "状态")
        log_test("短消息查询", len(responses) > 0, f"响应数: {len(responses)}")

        print("\n--- 测试: 混合消息 ---")
        responses = await send_message(session, "状态查询，有多少人物和场景？")
        if responses:
            full_response = " ".join(responses)
            has_multiple = "角色" in full_response and "场景" in full_response
            log_test("混合消息查询", has_multiple, f"响应包含多个信息: {full_response[:150]}")
        else:
            log_test("混合消息查询", False, "无响应")


async def main():
    """主测试函数"""
    print("=" * 60)
    print("Agent API 逻辑测试")
    print("测试时间:", datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    print("=" * 60)

    await test_health_check()

    await test_status_queries()

    await test_natural_language_queries()

    await test_logic合理性()

    await test_edge_cases()

    print("\n" + "=" * 60)
    print("测试结果汇总")
    print("=" * 60)

    passed = sum(1 for r in results if r["passed"])
    total = len(results)

    for result in results:
        status = "✓" if result["passed"] else "✗"
        print(f"{status} {result['test']}")

    print(f"\n总测试数: {total}")
    print(f"通过: {passed}")
    print(f"失败: {total - passed}")
    print(f"通过率: {passed/total*100:.1f}%")

    summary = {
        "total": total,
        "passed": passed,
        "failed": total - passed,
        "pass_rate": f"{passed/total*100:.1f}%",
        "timestamp": datetime.now().isoformat(),
        "tests": results
    }

    with open("/Users/user/code/mira/agent_logic_test_results.json", "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)

    print("\n结果已保存到: /Users/user/code/mira/agent_logic_test_results.json")

    return passed == total


if __name__ == "__main__":
    success = asyncio.run(main())
    sys.exit(0 if success else 1)
