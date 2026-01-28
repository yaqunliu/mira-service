"""
同步/异步混用问题检测工具

帮助检测代码中可能存在的同步阻塞异步问题
"""

import asyncio
import time
from contextlib import asynccontextmanager
from typing import AsyncGenerator


class SyncBlockDetector:
    """
    同步阻塞检测器

    用于检测代码中是否会阻塞 event loop
    """

    def __init__(self, threshold_ms: float = 10):
        """
        初始化

        Args:
            threshold_ms: 阻塞阈值（毫秒），超过此值的操作视为阻塞
        """
        self.threshold = threshold_ms / 1000
        self.blocked_operations = []

    def simulate_sync_call(self, duration_ms: float = 100):
        """
        模拟同步阻塞调用

        Args:
            duration_ms: 阻塞时长（毫秒）
        """
        start = time.time()
        time.sleep(duration_ms / 1000)
        elapsed = time.time() - start

        if elapsed > self.threshold:
            self.blocked_operations.append({
                "type": "time.sleep",
                "duration_ms": elapsed * 1000,
                "warning": "time.sleep() 会阻塞整个 event loop"
            })

        return elapsed

    async def async_sleep(self, duration_ms: float = 100):
        """异步睡眠 - 不会阻塞"""
        await asyncio.sleep(duration_ms / 1000)


class AsyncSafetyChecker:
    """
    异步安全检查器

    提供安全的异步上下文管理器
    """

    def __init__(self):
        self.is_async = True

    @staticmethod
    @asynccontextmanager
    async def safe_async_session(session_factory):
        """
        安全的异步会话上下文

        确保在异步上下文中正确管理数据库会话
        """
        async with session_factory() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise
            finally:
                await session.close()

    @staticmethod
    async def run_sync_in_executor(sync_func, *args, **kwargs):
        """
        在线程池中运行同步函数

        避免阻塞 event loop
        """
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, sync_func, *args, **kwargs)


class ConcurrencyTest:
    """
    并发测试工具

    测试异步代码的并发处理能力
    """

    @staticmethod
    async def test_async_concurrency(task_count: int = 100):
        """
        测试异步并发能力

        Args:
            task_count: 并发任务数量

        Returns:
            测试结果
        """
        async def mock_async_task(task_id: int):
            await asyncio.sleep(0.01)  # 模拟异步 I/O
            return {"task_id": task_id, "status": "done"}

        start = time.time()
        tasks = [mock_async_task(i) for i in range(task_count)]
        results = await asyncio.gather(*tasks)
        elapsed = time.time() - start

        return {
            "task_count": task_count,
            "elapsed_seconds": elapsed,
            "tasks_per_second": task_count / elapsed,
            "all_succeeded": all(r["status"] == "done" for r in results)
        }

    @staticmethod
    async def test_mixed_concurrency(sync_count: int = 10, async_count: int = 90):
        """
        测试混合并发（同步 + 异步）

        对比纯异步和混合场景的性能
        """
        async def async_task(task_id: int):
            await asyncio.sleep(0.01)
            return {"task_id": task_id}

        # 纯异步
        start = time.time()
        async_tasks = [async_task(i) for i in range(async_count)]
        await asyncio.gather(*async_tasks)
        pure_async_time = time.time() - start

        # 混合（同步任务会阻塞）
        start = time.time()
        for i in range(sync_count):
            time.sleep(0.01)  # 模拟同步阻塞
        mixed_time = time.time() - start

        return {
            "pure_async_time": pure_async_time,
            "mixed_time": mixed_time,
            "slowdown_factor": mixed_time / pure_async_time if pure_async_time > 0 else 1,
            "recommendation": "使用纯异步以获得最佳性能"
        }


async def demonstrate_blocking_problem():
    """
    演示同步阻塞问题
    """
    print("=" * 60)
    print("同步阻塞问题演示")
    print("=" * 60)

    detector = SyncBlockDetector(threshold_ms=5)

    # 场景1：同步 sleep - 会阻塞
    print("\n场景1：time.sleep(100ms)")
    start = time.time()
    detector.simulate_sync_call(100)
    elapsed = time.time() - start
    print(f"  实际耗时: {elapsed*1000:.2f}ms")
    print(f"  问题: 阻塞了整个 event loop 100ms")

    # 场景2：异步 sleep - 不会阻塞
    print("\n场景2：asyncio.sleep(100ms)")
    start = time.time()
    await detector.async_sleep(100)
    elapsed = time.time() - start
    print(f"  实际耗时: {elapsed*1000:.2f}ms")
    print(f"  优点: event loop 在等待期间可以处理其他任务")

    print("\n" + "=" * 60)
    print("结论: 在 async 函数中必须避免使用 time.sleep()")
    print("=" * 60)


async def demonstrate_concurrency():
    """
    演示并发性能差异
    """
    print("\n" + "=" * 60)
    print("并发性能测试")
    print("=" * 60)

    result = await ConcurrencyTest.test_async_concurrency(100)
    print(f"\n100 个异步任务:")
    print(f"  耗时: {result['elapsed_seconds']:.3f}s")
    print(f"  吞吐: {result['tasks_per_second']:.1f} 任务/秒")

    mixed = await ConcurrencyTest.test_mixed_concurrency(10, 90)
    print(f"\n混合场景 (10同步 + 90异步):")
    print(f"  纯异步时间: {mixed['pure_async_time']:.3f}s")
    print(f"  混合时间: {mixed['mixed_time']:.3f}s")
    print(f"  性能下降: {mixed['slowdown_factor']:.1f}x")
    print(f"  建议: {mixed['recommendation']}")


async def main():
    """主测试函数"""
    await demonstrate_blocking_problem()
    await demonstrate_concurrency()

    print("\n" + "=" * 60)
    print("安全编码建议")
    print("=" * 60)
    print("""
1. ✅ 在 async 函数中使用 asyncio.sleep() 而非 time.sleep()
2. ✅ 使用 aiofiles 进行异步文件 I/O
3. ✅ 使用 httpx 而非 requests 进行 HTTP 调用
4. ✅ 使用 asyncpg 而非 psycopg2 进行数据库操作
5. ❌ 避免在 async 函数中调用同步 ORM 操作
6. ❌ 避免使用 requests.get/post 而不使用 await
    """)


if __name__ == "__main__":
    asyncio.run(main())
