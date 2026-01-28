"""
知识库管理 - Knowledge Base Management

提供知识检索和向量存储功能
"""

from typing import Dict, Any, List, Optional
from app.core.logger import logger
from app.core.config import settings
import chromadb
from chromadb.config import Settings
import os


class KnowledgeBase:
    """知识库管理类"""
    
    def __init__(self, collection_name: str = "agent_knowledge"):
        """
        初始化知识库
        
        Args:
            collection_name: 集合名称
        """
        self.client = chromadb.PersistentClient(
            path=settings.CHROMADB_PATH or "./chroma_db",
            settings=Settings(anonymized_telemetry=False)
        )
        self.collection = self.client.get_or_create_collection(
            name=collection_name,
            metadata={"description": "Agent 知识库"}
        )
        logger.info(f"知识库初始化完成: {collection_name}")
    
    def add_documents(
        self,
        documents: List[Dict[str, str]],
        category: str = "general"
    ) -> Dict[str, Any]:
        """
        添加文档到知识库
        
        Args:
            documents: 文档列表，每个包含 id, content, metadata
            category: 文档类别
            
        Returns:
            添加结果
        """
        try:
            ids = [doc["id"] for doc in documents]
            contents = [doc["content"] for doc in documents]
            metadatas = [
                {**doc.get("metadata", {}), "category": category}
                for doc in documents
            ]
            
            self.collection.add(
                documents=contents,
                ids=ids,
                metadatas=metadatas
            )
            
            logger.info(f"添加 {len(documents)} 个文档到知识库")
            
            return {
                "success": True,
                "count": len(documents)
            }
            
        except Exception as e:
            logger.error(f"添加文档失败: {e}")
            return {"success": False, "error": str(e)}
    
    def query(
        self,
        query_text: str,
        category: Optional[str] = None,
        k: int = 5
    ) -> List[Dict[str, Any]]:
        """
        查询知识库
        
        Args:
            query_text: 查询文本
            category: 类别筛选（可选）
            k: 返回结果数量
            
        Returns:
            查询结果
        """
        try:
            where_filter = {"category": category} if category else None
            
            results = self.collection.query(
                query_texts=[query_text],
                n_results=k,
                where=where_filter
            )
            
            output = []
            for i in range(len(results["ids"][0])):
                output.append({
                    "id": results["ids"][0][i],
                    "content": results["documents"][0][i],
                    "metadata": results["metadatas"][0][i],
                    "distance": results["distances"][0][i] if "distances" in results else None
                })
            
            return output
            
        except Exception as e:
            logger.error(f"查询知识库失败: {e}")
            return []
    
    def delete_documents(self, ids: List[str]) -> Dict[str, Any]:
        """删除文档"""
        try:
            self.collection.delete(ids=ids)
            return {"success": True, "count": len(ids)}
        except Exception as e:
            logger.error(f"删除文档失败: {e}")
            return {"success": False, "error": str(e)}
    
    def get_collection_count(self) -> int:
        """获取文档数量"""
        return self.collection.count()


class DirectorKnowledge:
    """导演知识库"""
    
    def __init__(self):
        self.kb = KnowledgeBase(collection_name="director_knowledge")
        self._init_knowledge()
    
    def _init_knowledge(self):
        """初始化导演知识"""
        documents = [
            {
                "id": "camera_wide",
                "content": """广角镜头（Wide Shot）
用于展示场景全貌，建立空间感。
适用于：开场场景、角色介绍、动作场景开始。

构图要点：
- 保持地平线平衡
- 角色占据画面的适当比例
- 注意前景元素的运用""",
                "metadata": {"topic": "camera", "subtopic": "wide_shot"}
            },
            {
                "id": "camera_close",
                "content": """特写镜头（Close-up）
用于展示角色情感和重要细节。
适用于：情感高潮、关键道具展示、对话重点。

构图要点：
- 眼睛位于画面上三分之一
- 留出头部上方的空间
- 背景虚化""",
                "metadata": {"topic": "camera", "subtopic": "close_up"}
            },
            {
                "id": "pacing_action",
                "content": """动作场景节奏指南

快节奏剪辑：
- 镜头时长：2-4秒
- 频繁切换角度
- 使用跳切增强冲击感

慢节奏剪辑：
- 镜头时长：8-15秒
- 稳定的镜头运动
- 强调氛围而非动作""",
                "metadata": {"topic": "pacing", "subtopic": "action"}
            },
            {
                "id": "composition_rule_thirds",
                "content": """三分法则（Rule of Thirds）
将画面分成九宫格，关键元素放置在交叉点或线上。

应用场景：
- 人物视线方向留白
- 平衡画面元素
- 创造视觉引导线""",
                "metadata": {"topic": "composition", "subtopic": "rule_of_thirds"}
            }
        ]
        
        self.kb.add_documents(documents, category="director")
    
    async def query(self, question: str, k: int = 3) -> List[Dict[str, Any]]:
        """查询导演知识"""
        return self.kb.query(question, category="director", k=k)


class PromptKnowledge:
    """提示词知识库"""
    
    def __init__(self):
        self.kb = KnowledgeBase(collection_name="prompt_knowledge")
        self._init_knowledge()
    
    def _init_knowledge(self):
        """初始化提示词知识"""
        documents = [
            {
                "id": "character_prompt",
                "content": """角色图片提示词模板

基础结构：[身份描述] + [外貌特征] + [服装] + [姿态] + [风格]

示例：
"A young woman with long flowing hair, wearing a traditional Chinese dress, standing in a garden, watercolor style"

质量提升技巧：
- 添加光照描述：soft natural lighting, dramatic backlight
- 指定艺术风格：anime style, realistic, oil painting
- 强调关键特征：intense eyes, determined expression""",
                "metadata": {"topic": "prompt", "subtopic": "character"}
            },
            {
                "id": "scene_prompt",
                "content": """场景图片提示词模板

基础结构：[地点] + [时间] + [氛围] + [构图] + [风格]

示例：
"Ancient Chinese palace courtyard, twilight, mysterious atmosphere, wide angle shot, cinematic lighting"

场景元素：
- 天空：clear blue sky, stormy clouds, sunset
- 建筑：traditional architecture, modern building
- 自然：cherry blossoms, autumn leaves, snow""",
                "metadata": {"topic": "prompt", "subtopic": "scene"}
            },
            {
                "id": "storyboard_prompt",
                "content": """分镜图片提示词模板

基础结构：[镜头类型] + [画面描述] + [角色动作] + [构图] + [风格]

示例：
"Wide shot, a lone warrior standing on a cliff overlooking a vast valley, strong wind blowing cape, dramatic composition, anime style"

镜头类型：
- Wide/Establishing: 建立场景
- Medium: 中景对话
- Close-up: 情感特写
- Extreme Close-up: 细节展示""",
                "metadata": {"topic": "prompt", "subtopic": "storyboard"}
            }
        ]
        
        self.kb.add_documents(documents, category="prompt")
    
    async def query(self, question: str, k: int = 3) -> List[Dict[str, Any]]:
        """查询提示词知识"""
        return self.kb.query(question, category="prompt", k=k)


# 全局知识库实例
_director_kb = None
_prompt_kb = None


def get_director_knowledge() -> DirectorKnowledge:
    """获取导演知识库"""
    global _director_kb
    if _director_kb is None:
        _director_kb = DirectorKnowledge()
    return _director_kb


def get_prompt_knowledge() -> PromptKnowledge:
    """获取提示词知识库"""
    global _prompt_kb
    if _prompt_kb is None:
        _prompt_kb = PromptKnowledge()
    return _prompt_kb
