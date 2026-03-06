"""
超时与重试机制单元测试

测试 LLM 和 Tool 调用的重试逻辑
"""

import pytest
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch


class TestRetryConfig:
    """测试重试配置"""

    def test_timeout_config_defined(self):
        """验证超时配置完整"""
        from app.agent.utils.retry import TIMEOUT_CONFIG
        
        assert 'llm' in TIMEOUT_CONFIG
        assert 'db_tool' in TIMEOUT_CONFIG
        assert 'generation_tool' in TIMEOUT_CONFIG
        
        # 验证合理的超时值
        assert TIMEOUT_CONFIG['llm'] >= 30
        assert TIMEOUT_CONFIG['db_tool'] >= 5
        assert TIMEOUT_CONFIG['generation_tool'] >= 60

    def test_retry_config_defined(self):
        """验证重试配置完整"""
        from app.agent.utils.retry import RETRY_CONFIG
        
        assert 'max_attempts' in RETRY_CONFIG
        assert 'base_delay' in RETRY_CONFIG
        assert 'max_delay' in RETRY_CONFIG
        assert 'exponential_base' in RETRY_CONFIG
        
        # 验证合理的重试值
        assert RETRY_CONFIG['max_attempts'] >= 2
        assert RETRY_CONFIG['base_delay'] > 0
        assert RETRY_CONFIG['max_delay'] > RETRY_CONFIG['base_delay']


class TestLLMRetry:
    """测试 LLM 调用重试"""

    @pytest.mark.asyncio
    async def test_llm_retry_success(self):
        """测试 LLM 重试成功场景"""
        from app.agent.utils.retry import call_llm_with_retry
        
        # 模拟成功的 LLM 调用
        mock_llm = AsyncMock(return_value="success response")
        
        result = await call_llm_with_retry(mock_llm, "test prompt")
        
        assert result == "success response"
        assert mock_llm.call_count == 1

    @pytest.mark.asyncio
    async def test_llm_retry_on_failure(self):
        """测试 LLM 失败后重试"""
        from app.agent.utils.retry import call_llm_with_retry, RetryError
        
        # 模拟一直失败的 LLM 调用
        mock_llm = AsyncMock(side_effect=Exception("LLM error"))
        
        with pytest.raises(RetryError) as exc_info:
            await call_llm_with_retry(mock_llm, "test prompt", max_attempts=2, timeout=1)
        
        assert exc_info.value.attempts == 2
        assert mock_llm.call_count == 2

    @pytest.mark.asyncio
    async def test_llm_retry_eventual_success(self):
        """测试 LLM 失败一次后成功"""
        from app.agent.utils.retry import call_llm_with_retry
        
        # 第一次失败，第二次成功
        mock_llm = AsyncMock(side_effect=[Exception("first fail"), "success"])
        
        result = await call_llm_with_retry(mock_llm, "test prompt", max_attempts=3, timeout=10)
        
        assert result == "success"
        assert mock_llm.call_count == 2


class TestToolRetry:
    """测试 Tool 调用重试"""

    @pytest.mark.asyncio
    async def test_tool_retry_success(self):
        """测试 Tool 重试成功场景"""
        from app.agent.utils.retry import execute_tool_with_retry
        
        mock_tool = AsyncMock(return_value={"status": "success"})
        
        result = await execute_tool_with_retry(mock_tool, tool_type="db_tool")
        
        assert result["status"] == "success"
        assert mock_tool.call_count == 1

    @pytest.mark.asyncio
    async def test_tool_retry_on_timeout(self):
        """测试 Tool 超时后重试"""
        from app.agent.utils.retry import execute_tool_with_retry, RetryError
        
        async def slow_tool():
            await asyncio.sleep(10)  # 超时
            return {"status": "success"}
        
        with pytest.raises(RetryError):
            await execute_tool_with_retry(
                slow_tool,
                tool_type="db_tool",
                max_attempts=2,
                timeout=0.1,
            )


class TestRetryDecorator:
    """测试重试装饰器"""

    @pytest.mark.asyncio
    async def test_with_retry_decorator(self):
        """测试 @with_retry 装饰器"""
        from app.agent.utils.retry import with_retry
        
        call_count = 0
        
        @with_retry(max_attempts=3, timeout=10)
        async def my_tool():
            nonlocal call_count
            call_count += 1
            if call_count < 2:
                raise Exception("fail")
            return "success"
        
        result = await my_tool()
        
        assert result == "success"
        assert call_count == 2


class TestTimeoutManager:
    """测试超时管理器"""

    def test_timeout_manager_get(self):
        """测试获取超时时间"""
        from app.agent.utils.retry import TimeoutManager
        
        manager = TimeoutManager()
        
        assert manager.get_timeout("llm") > 0
        assert manager.get_timeout("db_tool") > 0
        assert manager.get_timeout("unknown") > 0  # 返回默认值

    def test_timeout_manager_update(self):
        """测试更新超时配置"""
        from app.agent.utils.retry import TimeoutManager
        
        manager = TimeoutManager()
        original = manager.get_timeout("llm")
        
        manager.update_timeout("llm", 120)
        
        assert manager.get_timeout("llm") == 120

    def test_timeout_manager_custom_config(self):
        """测试自定义配置"""
        from app.agent.utils.retry import TimeoutManager
        
        custom = {"custom_tool": 999}
        manager = TimeoutManager(custom_config=custom)
        
        assert manager.get_timeout("custom_tool") == 999
