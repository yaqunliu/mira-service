"""
知识库管理 - Knowledge Base Management

提供知识检索和向量存储功能
使用 OpenAI text-embedding-ada-002 模型进行向量化
"""

from typing import Dict, Any, List, Optional
from app.core.logger import logger
from app.core.config import settings
import chromadb
from chromadb.config import Settings
from chromadb.utils.embedding_functions import OpenAIEmbeddingFunction
import os


class KnowledgeBase:
    """知识库管理类

    使用 ChromaDB 存储向量，通过 OpenAI text-embedding-ada-002 进行 embedding
    """

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

        # 使用 OpenAI embedding 函数
        self.embedding_function = OpenAIEmbeddingFunction(
            api_key=settings.OPENAI_API_KEY,
            api_base=str(settings.OPENAI_BASE_URL) if settings.OPENAI_BASE_URL else None,
            model_name="text-embedding-ada-002"
        )

        self.collection = self.client.get_or_create_collection(
            name=collection_name,
            metadata={"description": "Agent 知识库"},
            embedding_function=self.embedding_function
        )
        self._embeddings = None  # LangChain embeddings 延迟初始化
        logger.info(f"知识库初始化完成: {collection_name} (embedding: text-embedding-ada-002)")

    def _get_langchain_embeddings(self):
        """获取 LangChain OpenAI Embeddings（延迟初始化）"""
        if self._embeddings is None:
            from langchain_openai import OpenAIEmbeddings
            self._embeddings = OpenAIEmbeddings(
                model="text-embedding-ada-002",
                api_key=settings.OPENAI_API_KEY,
                base_url=str(settings.OPENAI_BASE_URL) if settings.OPENAI_BASE_URL else None,
            )
        return self._embeddings
    
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
        查询知识库（同步版本）

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

    async def aquery(
        self,
        query_text: str,
        category: Optional[str] = None,
        k: int = 5
    ) -> List[Dict[str, Any]]:
        """
        异步查询知识库

        使用 LangChain OpenAI Embeddings 进行异步向量化查询

        Args:
            query_text: 查询文本
            category: 类别筛选（可选）
            k: 返回结果数量

        Returns:
            查询结果
        """
        try:
            # 使用 LangChain 异步生成 embedding
            embeddings = self._get_langchain_embeddings()
            query_embedding = await embeddings.aembed_query(query_text)

            where_filter = {"category": category} if category else None

            # ChromaDB 查询（使用预计算的 embedding）
            results = self.collection.query(
                query_embeddings=[query_embedding],
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
            logger.error(f"异步查询知识库失败: {e}")
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
        """异步查询导演知识"""
        return await self.kb.aquery(question, category="director", k=k)


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
        """异步查询提示词知识"""
        return await self.kb.aquery(question, category="prompt", k=k)


class StyleKnowledge:
    """风格模板知识库"""

    def __init__(self):
        self.kb = KnowledgeBase(collection_name="style_knowledge")
        self._init_knowledge()

    def _init_knowledge(self):
        """初始化风格知识"""
        # 检查是否已初始化
        if self.kb.get_collection_count() > 0:
            return

        documents = [
            {
                "id": "style_anime",
                "content": """日漫风格 (Anime Style)

视觉特点：
- 大眼睛、夸张的表情
- 鲜艳的色彩和清晰的轮廓线
- 简化的面部特征
- 动态的姿势和动作线

提示词关键词：
anime style, japanese animation, cel shading, vibrant colors, clean lines, expressive eyes

适用场景：
- 青春校园题材
- 奇幻冒险故事
- 轻松喜剧""",
                "metadata": {"style": "anime", "type": "visual"}
            },
            {
                "id": "style_realistic",
                "content": """写实摄影风格 (Realistic/Photorealistic)

视觉特点：
- 真实的光影效果
- 自然的肤色和材质
- 高细节度
- 真实的比例和解剖结构

提示词关键词：
photorealistic, realistic, natural lighting, detailed textures, professional photography, 8k, high detail

适用场景：
- 现代都市剧
- 历史题材
- 纪实风格""",
                "metadata": {"style": "realism", "type": "visual"}
            },
            {
                "id": "style_watercolor",
                "content": """水彩画风格 (Watercolor)

视觉特点：
- 柔和的色彩过渡
- 透明感和流动感
- 自然的笔触纹理
- 淡雅的色调

提示词关键词：
watercolor painting, soft colors, translucent, flowing brushstrokes, delicate, artistic

适用场景：
- 抒情爱情故事
- 回忆场景
- 梦幻氛围""",
                "metadata": {"style": "watercolor", "type": "visual"}
            },
            {
                "id": "style_cyberpunk",
                "content": """赛博朋克风格 (Cyberpunk)

视觉特点：
- 霓虹灯效果
- 高科技与低生活的对比
- 雨夜和反光表面
- 蓝紫粉色调为主

提示词关键词：
cyberpunk, neon lights, futuristic, rain, reflections, high tech low life, blade runner style, dystopian

适用场景：
- 科幻悬疑
- 未来都市
- 黑客题材""",
                "metadata": {"style": "cyberpunk", "type": "visual"}
            },
            {
                "id": "style_ukiyoe",
                "content": """浮世绘风格 (Ukiyo-e)

视觉特点：
- 平面化的构图
- 鲜明的色块
- 传统日本美学
- 特殊的波浪和云纹

提示词关键词：
ukiyo-e style, japanese woodblock print, flat colors, traditional japanese art, bold outlines, Hokusai style

适用场景：
- 古代东方题材
- 神话传说
- 艺术感强的作品""",
                "metadata": {"style": "ukiyoe", "type": "visual"}
            }
        ]

        self.kb.add_documents(documents, category="style")

    async def query(self, question: str, k: int = 3) -> List[Dict[str, Any]]:
        """异步查询风格知识"""
        return await self.kb.aquery(question, category="style", k=k)

    def get_style_prompt(self, style_name: str) -> str:
        """获取特定风格的提示词关键词"""
        style_map = {
            "anime": "anime style, japanese animation, cel shading, vibrant colors, clean lines",
            "realism": "photorealistic, realistic, natural lighting, detailed textures, professional photography",
            "watercolor": "watercolor painting, soft colors, translucent, flowing brushstrokes, delicate",
            "cyberpunk": "cyberpunk, neon lights, futuristic, rain, reflections, high tech low life",
            "ukiyoe": "ukiyo-e style, japanese woodblock print, flat colors, traditional japanese art"
        }
        return style_map.get(style_name, style_map["anime"])


class StoryboardKnowledge:
    """分镜技巧知识库"""

    def __init__(self):
        self.kb = KnowledgeBase(collection_name="storyboard_knowledge")
        self._init_knowledge()

    def _init_knowledge(self):
        """初始化分镜知识"""
        if self.kb.get_collection_count() > 0:
            return

        documents = [
            {
                "id": "shot_establishing",
                "content": """建立镜头 (Establishing Shot)

用途：介绍场景、时间、地点
构图：超广角，展示环境全貌
时长建议：3-5秒

提示词模板：
"Establishing shot of [location], [time of day], [weather], wide angle, cinematic, [style]"

示例：
"Establishing shot of a traditional Chinese village, early morning, misty mountains in background, wide angle, cinematic lighting, anime style"
""",
                "metadata": {"shot_type": "establishing", "category": "composition"}
            },
            {
                "id": "shot_medium",
                "content": """中景镜头 (Medium Shot)

用途：对话场景、角色互动
构图：角色腰部以上，可容纳2-3人
时长建议：2-4秒

提示词模板：
"Medium shot of [character] [action], [expression], [background], [lighting], [style]"

示例：
"Medium shot of two friends talking in a cafe, warm expressions, bokeh background, soft natural lighting, realistic style"
""",
                "metadata": {"shot_type": "medium", "category": "composition"}
            },
            {
                "id": "shot_closeup",
                "content": """特写镜头 (Close-up Shot)

用途：展示情感、重要细节
构图：面部或物体特写，背景模糊
时长建议：1-3秒

提示词模板：
"Close-up of [subject], [emotion/detail], [lighting], shallow depth of field, [style]"

示例：
"Close-up of a young woman's face, tears in her eyes, dramatic side lighting, shallow depth of field, cinematic"
""",
                "metadata": {"shot_type": "closeup", "category": "composition"}
            },
            {
                "id": "shot_action",
                "content": """动作镜头 (Action Shot)

用途：打斗、追逐、动态场景
构图：动态角度、运动模糊、冲击线
时长建议：1-2秒

提示词模板：
"Dynamic action shot of [character] [action], motion blur, [angle], dramatic composition, [style]"

示例：
"Dynamic action shot of a warrior leaping through the air, sword raised, motion blur, low angle, dramatic lighting, anime style"
""",
                "metadata": {"shot_type": "action", "category": "composition"}
            },
            {
                "id": "shot_transition",
                "content": """过渡镜头 (Transition Shot)

用途：场景转换、时间流逝
构图：象征性元素、自然景观
时长建议：2-3秒

提示词模板：
"[Symbolic element] transitioning from [state A] to [state B], [atmosphere], [style]"

示例：
"Cherry blossoms falling from a tree, transitioning from spring to summer, peaceful atmosphere, watercolor style"
""",
                "metadata": {"shot_type": "transition", "category": "composition"}
            },
            {
                "id": "video_prompt_guide",
                "content": """视频提示词指南

视频运动类型：
- camera pan left/right: 镜头左右平移
- camera zoom in/out: 镜头推拉
- camera tilt up/down: 镜头上下倾斜
- dolly forward/backward: 镜头前进后退
- orbit around subject: 环绕主体

运动描述关键词：
- slow motion, fast motion
- smooth camera movement
- dynamic camera shake
- static shot, locked camera

示例：
"Camera slowly zooms in on character's face, subtle expression change, soft lighting remains constant"
""",
                "metadata": {"shot_type": "video", "category": "motion"}
            }
        ]

        self.kb.add_documents(documents, category="storyboard")

    async def query(self, question: str, k: int = 3) -> List[Dict[str, Any]]:
        """异步查询分镜知识"""
        return await self.kb.aquery(question, category="storyboard", k=k)

    def get_shot_template(self, shot_type: str) -> str:
        """获取特定镜头类型的提示词模板"""
        templates = {
            "establishing": "Establishing shot of {location}, {time}, wide angle, cinematic, {style}",
            "medium": "Medium shot of {character} {action}, {background}, {style}",
            "closeup": "Close-up of {subject}, {emotion}, shallow depth of field, {style}",
            "action": "Dynamic action shot of {character} {action}, motion blur, dramatic, {style}",
            "transition": "{element} transitioning, {atmosphere}, {style}"
        }
        return templates.get(shot_type, templates["medium"])


# 全局知识库实例
_director_kb = None
_prompt_kb = None
_style_kb = None
_storyboard_kb = None


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


def get_style_knowledge() -> StyleKnowledge:
    """获取风格知识库"""
    global _style_kb
    if _style_kb is None:
        _style_kb = StyleKnowledge()
    return _style_kb


def get_storyboard_knowledge() -> StoryboardKnowledge:
    """获取分镜知识库"""
    global _storyboard_kb
    if _storyboard_kb is None:
        _storyboard_kb = StoryboardKnowledge()
    return _storyboard_kb
