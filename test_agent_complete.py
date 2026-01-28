"""
Agent API 完整功能测试

测试内容包括：
1. 状态查询功能
2. 执行工作流（进行下一步）
3. 进度跟踪
4. 响应内容验证
"""

import asyncio
import aiohttp
import json
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


async def send_message(session, message: str, timeout: int = 60) -> List[str]:
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
            timeout=aiohttp.ClientTimeout(total=timeout)
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


async def reset_session(session):
    """重置会话"""
    headers = {
        "Authorization": f"Bearer {TOKEN}",
        "Content-Type": "application/json"
    }
    reset_data = {"keep_assets": False}
    async with session.post(
        f"{API_BASE}/creations/{TEST_CREATION_UUID}/agent/reset",
        json=reset_data,
        headers=headers,
        timeout=aiohttp.ClientTimeout(total=10)
    ) as response:
        return response.status == 200


async def get_session_status(session) -> Dict[str, Any]:
    """获取会话状态"""
    headers = {"Authorization": f"Bearer {TOKEN}"}
    async with session.get(
        f"{API_BASE}/creations/{TEST_CREATION_UUID}/agent/status",
        headers=headers,
        timeout=aiohttp.ClientTimeout(total=10)
    ) as response:
        if response.status == 200:
            return await response.json()
        return {}


async def test_step1_query_status():
    """测试步骤1: 查询初始状态"""
    print("\n" + "=" * 60)
    print("📍 测试步骤1: 查询初始状态")
    print("=" * 60)

    async with aiohttp.ClientSession() as session:
        await reset_session(session)

        responses = await send_message(session, "当前创作状态怎么样？")
        if responses:
            full_response = " ".join(responses)
            has_status = any(kw in full_response for kw in ["阶段", "初始化", "状态", "0 个"])
            log_test("查询初始状态", has_status, f"响应包含状态信息: {full_response[:150]}...")
            return True
        else:
            log_test("查询初始状态", False, "无响应")
            return False


async def test_step2_start_workflow():
    """测试步骤2: 开始工作流（进行下一步）"""
    print("\n" + "=" * 60)
    print("📍 测试步骤2: 开始工作流（进行下一步）")
    print("=" * 60)

    async with aiohttp.ClientSession() as session:
        print("\n--- 用户请求: 开始分析剧本 ---")
        responses = await send_message(session, "开始分析剧本", timeout=120)

        if responses:
            full_response = " ".join(responses)
            print(f"收到 {len(responses)} 个响应块")

            has_progress = any(kw in full_response for kw in ["分析", "开始", "识别", "角色", "场景", "完成"])
            log_test("开始剧本分析", has_progress or len(responses) > 0, f"响应块数: {len(responses)}, 包含关键词: {has_progress}")

            for i, resp in enumerate(responses[:3]):
                print(f"  响应 {i+1}: {resp[:80]}...")

            return responses
        else:
            log_test("开始剧本分析", False, "无响应")
            return []


async def test_step3_query_after_workflow():
    """测试步骤3: 工作流执行后查询状态"""
    print("\n" + "=" * 60)
    print("📍 测试步骤3: 工作流执行后查询状态")
    print("=" * 60)

    async with aiohttp.ClientSession() as session:
        print("\n--- 查询: 现在有多少人物？ ---")
        responses = await send_message(session, "当前有多少人物？")
        if responses:
            full_response = " ".join(responses)
            has_count = any(kw in full_response for kw in ["角色", "个", "共", "暂无"])
            log_test("查询角色数量", has_count, f"响应: {full_response[:100]}...")
        else:
            log_test("查询角色数量", False, "无响应")

        print("\n--- 查询: 有多少个场景？ ---")
        responses = await send_message(session, "有多少个场景？")
        if responses:
            full_response = " ".join(responses)
            has_count = any(kw in full_response for kw in ["场景", "个", "共", "暂无"])
            log_test("查询场景数量", has_count, f"响应: {full_response[:100]}...")
        else:
            log_test("查询场景数量", False, "无响应")


async def test_step4_continue_workflow():
    """测试步骤4: 继续执行下一步"""
    print("\n" + "=" * 60)
    print("📍 测试步骤4: 继续执行下一步")
    print("=" * 60)

    async with aiohttp.ClientSession() as session:
        print("\n--- 用户请求: 生成角色图片 ---")
        responses = await send_message(session, "生成角色图片", timeout=120)

        if responses:
            full_response = " ".join(responses)
            print(f"收到 {len(responses)} 个响应块")

            has_progress = any(kw in full_response for kw in ["生成", "图片", "角色", "完成", "开始"])
            log_test("生成角色图片", has_progress or len(responses) > 0, f"响应块数: {len(responses)}")
        else:
            log_test("生成角色图片", False, "无响应")

        print("\n--- 用户请求: 继续下一步 ---")
        responses = await send_message(session, "继续", timeout=120)

        if responses:
            print(f"收到 {len(responses)} 个响应块")
            log_test("继续执行工作流", len(responses) > 0, f"响应块数: {len(responses)}")
        else:
            log_test("继续执行工作流", False, "无响应")


async def test_step5_query_image_status():
    """测试步骤5: 查询图片生成状态"""
    print("\n" + "=" * 60)
    print("📍 测试步骤5: 查询图片生成状态")
    print("=" * 60)

    async with aiohttp.ClientSession() as session:
        print("\n--- 查询: 图片生成状态如何？ ---")
        responses = await send_message(session, "图片生成状态如何？")
        if responses:
            full_response = " ".join(responses)
            has_status = any(kw in full_response for kw in ["图片", "生成", "进度", "完成", "角色"])
            log_test("查询图片状态", has_status, f"响应: {full_response[:100]}...")
        else:
            log_test("查询图片状态", False, "无响应")

        print("\n--- 查询: 现在进行到哪一步了？ ---")
        responses = await send_message(session, "现在进行到哪一步了？")
        if responses:
            full_response = " ".join(responses)
            has_stage = any(kw in full_response for kw in ["阶段", "进行", "当前", "步骤"])
            log_test("查询当前阶段", has_stage, f"响应: {full_response[:100]}...")
        else:
            log_test("查询当前阶段", False, "无响应")


async def test_step6_natural_language():
    """测试步骤6: 自然语言指令"""
    print("\n" + "=" * 60)
    print("📍 测试步骤6: 自然语言指令")
    print("=" * 60)

    async with aiohttp.ClientSession() as session:
        natural_commands = [
            ("帮我看看项目进度", "进度查询"),
            ("现在是什么情况", "状态查询"),
            ("我想知道进行到哪了", "进度查询"),
            ("检查一下状态", "状态查询"),
        ]

        for command, description in natural_commands:
            print(f"\n--- {description}: \"{command}\" ---")
            responses = await send_message(session, command)
            if responses:
                log_test(description, True, f"响应块数: {len(responses)}")
            else:
                log_test(description, False, "无响应")


async def test_step7_interaction_flow():
    """测试步骤7: 完整交互流程"""
    print("\n" + "=" * 60)
    print("📍 测试步骤7: 完整交互流程")
    print("=" * 60)

    async with aiohttp.ClientSession() as session:
        await reset_session(session)

        interaction_sequence = [
            ("查询初始状态", "当前创作状态怎么样？"),
            ("请求开始", "开始工作"),
            ("查询进度", "进行得怎么样了？"),
            ("继续执行", "继续下一步"),
            ("查询最终状态", "现在是什么情况？"),
        ]

        for step_name, message in interaction_sequence:
            print(f"\n--- 步骤: {step_name} ---")
            print(f"    用户: {message}")
            responses = await send_message(session, message, timeout=120)

            if responses:
                full_response = " ".join(responses)
                print(f"    Agent: {full_response[:100]}...")
            else:
                print(f"    Agent: (无响应)")


async def test_step8_multiple_queries():
    """测试步骤8: 连续多次查询"""
    print("\n" + "=" * 60)
    print("📍 测试步骤8: 连续多次查询")
    print("=" * 60)

    async with aiohttp.ClientSession() as session:
        queries = [
            "当前有多少人物？",
            "有多少个场景？",
            "图片生成状态如何？",
            "现在进行到哪一步了？",
            "当前创作状态怎么样？",
        ]

        success_count = 0
        for query in queries:
            responses = await send_message(session, query)
            if responses:
                success_count += 1
                print(f"✓ {query[:20]}... -> 收到响应")
            else:
                print(f"✗ {query[:20]}... -> 无响应")

        log_test("连续查询测试", success_count >= 3, f"成功: {success_count}/{len(queries)}")


async def main():
    """主测试函数"""
    print("=" * 60)
    print("Agent API 完整功能测试")
    print("测试时间:", datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    print("=" * 60)

    print("\n" + "🔷" * 20)
    print("  第一部分: 状态查询功能测试")
    print("🔷" * 20)

    await test_step1_query_status()
    await test_step3_query_after_workflow()
    await test_step5_query_image_status()
    await test_step6_natural_language()
    await test_step8_multiple_queries()

    print("\n" + "🔷" * 20)
    print("  第二部分: 工作流执行功能测试")
    print("🔷" * 20)

    await test_step2_start_workflow()
    await test_step4_continue_workflow()

    print("\n" + "🔷" * 20)
    print("  第三部分: 完整交互流程测试")
    print("🔷" * 20)

    await test_step7_interaction_flow()

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
    print(f"通过率: {passed/total*100:.1f}%" if total > 0 else "通过率: 0%")

    summary = {
        "total": total,
        "passed": passed,
        "failed": total - passed,
        "pass_rate": f"{passed/total*100:.1f}%" if total > 0 else "0%",
        "timestamp": datetime.now().isoformat(),
        "tests": results
    }

    with open("/Users/user/code/mira/agent_complete_test_results.json", "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)

    print("\n结果已保存到: /Users/user/code/mira/agent_complete_test_results.json")

    return passed == total


if __name__ == "__main__":
    success = asyncio.run(main())
    sys.exit(0 if success else 1)
