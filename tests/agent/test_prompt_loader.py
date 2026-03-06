"""
Agent 提示词加载器测试
"""

import pytest
from pathlib import Path


class TestPromptLoader:
    """提示词加载器测试"""
    
    def test_load_prompt_intent_detection(self):
        """测试加载意图识别提示词"""
        from app.agent.prompts import load_prompt
        
        prompt = load_prompt("intent_detection")
        
        assert "metadata" in prompt
        assert "template" in prompt
        assert prompt["metadata"]["name"] == "intent_detection"
        assert prompt["metadata"]["model"] == "gpt-4o-mini"
        assert "意图识别" in prompt["template"]
    
    def test_load_prompt_status_response(self):
        """测试加载状态回复提示词"""
        from app.agent.prompts import load_prompt
        
        prompt = load_prompt("status_response")
        
        assert prompt["metadata"]["name"] == "status_response"
        assert "状态回复" in prompt["template"]
    
    def test_load_prompt_clarify_response(self):
        """测试加载引导回复提示词"""
        from app.agent.prompts import load_prompt
        
        prompt = load_prompt("clarify_response")
        
        assert prompt["metadata"]["name"] == "clarify_response"
        assert "引导" in prompt["template"]
    
    def test_load_prompt_task_confirmation(self):
        """测试加载任务确认提示词"""
        from app.agent.prompts import load_prompt
        
        prompt = load_prompt("task_confirmation")
        
        assert prompt["metadata"]["name"] == "task_confirmation"
    
    def test_load_prompt_not_found(self):
        """测试加载不存在的提示词"""
        from app.agent.prompts import load_prompt
        
        with pytest.raises(FileNotFoundError):
            load_prompt("not_exist_prompt")
    
    def test_format_prompt(self):
        """测试提示词渲染"""
        from app.agent.prompts import load_prompt, format_prompt
        
        prompt = load_prompt("intent_detection")
        
        context = {
            "user_message": "帮我生成角色图片",
            "chat_history": [
                {"role": "user", "content": "你好"},
                {"role": "assistant", "content": "你好！有什么可以帮助你的？"},
            ],
            "current_stage": "asset_generation",
        }
        
        filled = format_prompt(prompt, context)
        
        assert "帮我生成角色图片" in filled
        assert "asset_generation" in filled
        assert "你好" in filled
    
    def test_get_prompt_config(self):
        """测试获取提示词配置"""
        from app.agent.prompts import load_prompt, get_prompt_config
        
        prompt = load_prompt("intent_detection")
        
        model = get_prompt_config(prompt, "model", "default")
        temperature = get_prompt_config(prompt, "temperature", 0.5)
        not_exist = get_prompt_config(prompt, "not_exist", "default_value")
        
        assert model == "gpt-4o-mini"
        assert temperature == 0.3
        assert not_exist == "default_value"
    
    def test_load_and_format(self):
        """测试便捷函数"""
        from app.agent.prompts import load_and_format
        
        filled = load_and_format("intent_detection", {
            "user_message": "查看当前进度",
            "chat_history": [],
            "current_stage": "init",
        })
        
        assert isinstance(filled, str)
        assert "查看当前进度" in filled
