"""
Agent 单元测试

测试 Agent 工作流的各个组件
"""

import pytest
import asyncio
from unittest.mock import Mock, AsyncMock, patch
from typing import Dict, Any

from app.agent.state.schemas import ComicDramaState
from app.agent.tools.base import BaseTool
from app.agent.tools.generation_tools import (
    GenerateCharacterImageTool,
    GenerateSceneImageTool,
    GenerateStoryboardImageTool,
    GenerateVideoTool,
    GenerateAudioTool,
    LLMAnalysisTool,
    GeneratePromptTool
)
from app.agent.tools.review_tools import (
    ReviewCharacterTool,
    ReviewSceneTool,
    ReviewStoryboardTool,
    BatchReviewTool,
    QualityCheckTool
)
from app.agent.tools.editing_tools import (
    ConcatenateVideoTool,
    AddAudioTrackTool,
    AddSubtitleTool,
    FinalRenderTool
)
from app.agent.agents.script_analysis_team import ScriptAnalysisTeam
from app.agent.agents.director import DirectorAgent
from app.agent.knowledge.base import KnowledgeBase, DirectorKnowledge, PromptKnowledge


class TestComicDramaState:
    """测试状态定义"""
    
    def test_state_creation(self):
        """测试状态创建"""
        state: ComicDramaState = {
            "creation_uuid": "test-uuid",
            "thread_id": "thread-123",
            "user_id": 1,
            "session_id": "session-123",
            "current_stage": "init",
            "script_text": "这是一个测试剧本",
            "characters": [],
            "scenes": [],
            "storyboards": [],
            "audio_segments": [],
            "video_segments": [],
            "final_video": None,
            "messages": [],
            "errors": [],
            "pending_checkpoint": None,
            "metadata": {}
        }
        
        assert state["current_stage"] == "init"
        assert state["creation_uuid"] == "test-uuid"
        assert len(state["characters"]) == 0
    
    def test_state_update(self):
        """测试状态更新"""
        state: ComicDramaState = {
            "current_stage": "init",
            "characters": [],
            "messages": []
        }
        
        state["current_stage"] = "script_analysis"
        state["characters"].append({"name": "测试角色"})
        state["messages"].append({"role": "system", "content": "测试消息"})
        
        assert state["current_stage"] == "script_analysis"
        assert len(state["characters"]) == 1
        assert len(state["messages"]) == 1


class TestBaseTool:
    """测试基础工具"""
    
    def test_tool_creation(self):
        """测试工具创建"""
        tool = BaseTool()
        assert tool.name == "base_tool"
        assert tool.description == "基础工具"
    
    @pytest.mark.asyncio
    async def test_tool_execute(self):
        """测试工具执行"""
        tool = BaseTool()
        
        result = await tool.execute(
            state={},
            test_param="value"
        )
        
        assert result == {}


class TestGenerationTools:
    """测试生成工具"""
    
    @pytest.mark.asyncio
    async def test_generate_character_image_tool_creation(self):
        """测试角色图片生成工具创建"""
        tool = GenerateCharacterImageTool()
        assert tool.name == "generate_character_image"
        assert "角色" in tool.description
    
    @pytest.mark.asyncio
    async def test_generate_scene_image_tool_creation(self):
        """测试场景图片生成工具创建"""
        tool = GenerateSceneImageTool()
        assert tool.name == "generate_scene_image"
        assert "场景" in tool.description
    
    @pytest.mark.asyncio
    async def test_generate_storyboard_image_tool_creation(self):
        """测试分镜图片生成工具创建"""
        tool = GenerateStoryboardImageTool()
        assert tool.name == "generate_storyboard_image"
        assert "分镜" in tool.description
    
    @pytest.mark.asyncio
    async def test_generate_video_tool_creation(self):
        """测试视频生成工具创建"""
        tool = GenerateVideoTool()
        assert tool.name == "generate_video"
        assert "视频" in tool.description
    
    @pytest.mark.asyncio
    async def test_generate_audio_tool_creation(self):
        """测试音频生成工具创建"""
        tool = GenerateAudioTool()
        assert tool.name == "generate_audio"
        assert "音频" in tool.description
    
    @pytest.mark.asyncio
    async def test_llm_analysis_tool_creation(self):
        """测试 LLM 分析工具创建"""
        tool = LLMAnalysisTool()
        assert tool.name == "llm_analysis"
        assert "LLM" in tool.description
    
    @pytest.mark.asyncio
    async def test_generate_prompt_tool_creation(self):
        """测试提示词生成工具创建"""
        tool = GeneratePromptTool()
        assert tool.name == "generate_prompt"
        assert "提示词" in tool.description


class TestReviewTools:
    """测试审核工具"""
    
    @pytest.mark.asyncio
    async def test_review_character_tool_creation(self):
        """测试角色审核工具创建"""
        tool = ReviewCharacterTool()
        assert tool.name == "review_character"
        assert "角色" in tool.description
    
    @pytest.mark.asyncio
    async def test_review_scene_tool_creation(self):
        """测试场景审核工具创建"""
        tool = ReviewSceneTool()
        assert tool.name == "review_scene"
        assert "场景" in tool.description
    
    @pytest.mark.asyncio
    async def test_review_storyboard_tool_creation(self):
        """测试分镜审核工具创建"""
        tool = ReviewStoryboardTool()
        assert tool.name == "review_storyboard"
        assert "分镜" in tool.description
    
    @pytest.mark.asyncio
    async def test_batch_review_tool_creation(self):
        """测试批量审核工具创建"""
        tool = BatchReviewTool()
        assert tool.name == "batch_review"
        assert "批量" in tool.description
    
    @pytest.mark.asyncio
    async def test_quality_check_tool_creation(self):
        """测试质量检查工具创建"""
        tool = QualityCheckTool()
        assert tool.name == "quality_check"
        assert "质量" in tool.description


class TestEditingTools:
    """测试剪辑工具"""
    
    @pytest.mark.asyncio
    async def test_concatenate_video_tool_creation(self):
        """测试视频拼接工具创建"""
        tool = ConcatenateVideoTool()
        assert tool.name == "concatenate_video"
        assert "拼接" in tool.description
    
    @pytest.mark.asyncio
    async def test_add_audio_track_tool_creation(self):
        """测试添加音轨工具创建"""
        tool = AddAudioTrackTool()
        assert tool.name == "add_audio_track"
        assert "音轨" in tool.description
    
    @pytest.mark.asyncio
    async def test_add_subtitle_tool_creation(self):
        """测试添加字幕工具创建"""
        tool = AddSubtitleTool()
        assert tool.name == "add_subtitle"
        assert "字幕" in tool.description
    
    @pytest.mark.asyncio
    async def test_final_render_tool_creation(self):
        """测试最终渲染工具创建"""
        tool = FinalRenderTool()
        assert tool.name == "final_render"
        assert "渲染" in tool.description


class TestScriptAnalysisTeam:
    """测试剧本分析团队"""
    
    def test_team_creation(self):
        """测试团队创建"""
        team = ScriptAnalysisTeam()
        assert team is not None
    
    @pytest.mark.asyncio
    async def test_analyze_script_with_empty_script(self):
        """测试分析空剧本"""
        team = ScriptAnalysisTeam()
        
        state: ComicDramaState = {
            "script_text": ""
        }
        
        result = await team.analyze_script(state)
        
        assert result["success"] is False
        assert "empty" in result.get("error", "").lower()


class TestDirectorAgent:
    """测试导演 Agent"""
    
    def test_agent_creation(self):
        """测试 Agent 创建"""
        agent = DirectorAgent()
        assert agent is not None
        assert len(agent.STAGES) > 0
    
    def test_determine_next_stage(self):
        """测试阶段决策"""
        agent = DirectorAgent()
        
        state: ComicDramaState = {
            "current_stage": "init",
            "errors": []
        }
        
        next_stage = agent.determine_next_stage(state)
        assert next_stage == "script_analysis"
    
    def test_is_recoverable_error(self):
        """测试错误恢复判断"""
        agent = DirectorAgent()
        
        assert agent._is_recoverable_error("timeout error") is True
        assert agent._is_recoverable_error("rate limit exceeded") is True
        assert agent._is_recoverable_error("syntax error") is False
    
    def test_should_pause_for_review(self):
        """测试是否应该暂停审核"""
        agent = DirectorAgent()
        
        state_no_review: ComicDramaState = {
            "current_stage": "init",
            "characters": []
        }
        
        assert agent.should_pause_for_review(state_no_review) is False
        
        state_with_review: ComicDramaState = {
            "current_stage": "asset_generation",
            "characters": [{"name": "测试", "image_url": "http://test.com/img.jpg"}]
        }
        
        assert agent.should_pause_for_review(state_with_review) is True


class TestKnowledgeBase:
    """测试知识库"""
    
    def test_knowledge_base_creation(self):
        """测试知识库创建"""
        kb = KnowledgeBase(collection_name="test_collection")
        assert kb is not None
    
    def test_add_documents(self):
        """测试添加文档"""
        kb = KnowledgeBase(collection_name="test_add_docs")
        
        documents = [
            {
                "id": "doc1",
                "content": "测试内容1",
                "metadata": {"topic": "test"}
            },
            {
                "id": "doc2",
                "content": "测试内容2",
                "metadata": {"topic": "test"}
            }
        ]
        
        result = kb.add_documents(documents, category="test")
        
        assert result["success"] is True
        assert result["count"] == 2
    
    def test_query(self):
        """测试查询"""
        kb = KnowledgeBase(collection_name="test_query")
        
        kb.add_documents([
            {
                "id": "q1",
                "content": "关于电影摄影的技巧",
                "metadata": {"topic": "cinematography"}
            }
        ], category="cinema")
        
        results = kb.query("摄影技术", k=5)
        
        assert isinstance(results, list)
    
    def test_get_collection_count(self):
        """测试获取文档数量"""
        kb = KnowledgeBase(collection_name="test_count")
        
        kb.add_documents([
            {"id": f"c{i}", "content": f"内容{i}", "metadata": {}}
            for i in range(5)
        ], category="test")
        
        count = kb.get_collection_count()
        assert count == 5


class TestDirectorKnowledge:
    """测试导演知识库"""
    
    def test_director_knowledge_creation(self):
        """测试导演知识库创建"""
        kb = DirectorKnowledge()
        assert kb is not None


class TestPromptKnowledge:
    """测试提示词知识库"""
    
    def test_prompt_knowledge_creation(self):
        """测试提示词知识库创建"""
        kb = PromptKnowledge()
        assert kb is not None


# 夹具
@pytest.fixture
def sample_state() -> ComicDramaState:
    """示例状态"""
    return {
        "creation_uuid": "test-creation-uuid",
        "thread_id": "thread-123",
        "user_id": 1,
        "session_id": "session-123",
        "current_stage": "init",
        "script_text": "这是一个测试剧本，讲述了一个勇敢的英雄冒险故事。",
        "characters": [
            {
                "name": "主角",
                "description": "勇敢的年轻人",
                "image_url": "http://example.com/hero.jpg",
                "generation_status": "completed"
            }
        ],
        "scenes": [
            {
                "name": "起始村庄",
                "description": "一个宁静的小村庄",
                "image_url": "http://example.com/village.jpg",
                "generation_status": "completed"
            }
        ],
        "storyboards": [],
        "audio_segments": [],
        "video_segments": [],
        "final_video": None,
        "messages": [],
        "errors": [],
        "pending_checkpoint": None,
        "metadata": {}
    }


# 运行测试
if __name__ == "__main__":
    pytest.main([__file__, "-v"])
