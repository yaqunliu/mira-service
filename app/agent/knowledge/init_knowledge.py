"""
知识库初始化脚本

将知识文档解析并写入 ChromaDB 向量数据库
每个知识点作为独立文档存储，便于精确检索
"""

import os
import hashlib
import re
from typing import Dict, List, Any
from pathlib import Path

from app.core.logger import logger
from app.agent.knowledge.base import KnowledgeBase


class KnowledgeInitializer:
    """知识库初始化器"""

    def __init__(self, knowledge_dir: str = None):
        """
        初始化

        Args:
            knowledge_dir: 知识库文档目录，默认为 app/agent/knowledge/
        """
        if knowledge_dir is None:
            current_dir = Path(__file__).parent
            self.knowledge_dir = current_dir
        else:
            self.knowledge_dir = Path(knowledge_dir)

        # 各类知识库
        self.style_kb = KnowledgeBase(collection_name="style_knowledge")
        self.director_kb = KnowledgeBase(collection_name="director_knowledge")
        self.prompt_kb = KnowledgeBase(collection_name="prompt_knowledge")
        self.storyboard_kb = KnowledgeBase(collection_name="storyboard_knowledge")

    def _compute_hash(self, text: str) -> str:
        """计算文本哈希值"""
        return hashlib.md5(text.encode()).hexdigest()[:8]

    def _parse_markdown_sections(self, file_path: str) -> List[Dict[str, Any]]:
        """
        解析 Markdown 文件，按 ## 标题分割为独立文档
        """
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()

        documents = []
        file_name = Path(file_path).stem

        # 按 ## 分割（二级标题）
        sections = re.split(r'\n## ', content)

        for i, section in enumerate(sections):
            if not section.strip():
                continue

            # 处理第一个section可能包含# 一级标题
            if i == 0 and section.startswith('#'):
                # 跳过文件标题部分，或者提取文件描述
                lines = section.split('\n', 2)
                if len(lines) > 2:
                    section = lines[2]
                else:
                    continue

            # 获取标题和内容
            lines = section.split('\n', 1)
            title = lines[0].strip().lstrip('#').strip()
            body = lines[1].strip() if len(lines) > 1 else ""

            if body and len(body) > 50:  # 过滤太短的内容
                doc_id = f"{file_name}_{self._compute_hash(title)}"
                documents.append({
                    "id": doc_id,
                    "content": f"{title}\n\n{body}",
                    "metadata": {
                        "source_file": file_name,
                        "title": title,
                        "type": "section"
                    }
                })

        return documents

    def _parse_style_document(self, file_path: str) -> List[Dict[str, Any]]:
        """
        专门解析风格文档，每种风格作为独立文档
        """
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()

        documents = []

        # 按 ## 分割风格
        sections = re.split(r'\n## ', content)

        for section in sections:
            if not section.strip():
                continue

            # 跳过文件标题
            if section.startswith('#'):
                continue

            lines = section.split('\n', 1)
            title = lines[0].strip()
            body = lines[1].strip() if len(lines) > 1 else ""

            if not body:
                continue

            # 提取风格名称（如 "日漫风格 (Anime Style)" -> "anime"）
            style_match = re.search(r'\(([^)]+)\)', title)
            style_key = ""
            if style_match:
                style_key = style_match.group(1).lower().split()[0]
            else:
                style_key = title.split()[0].lower()

            doc_id = f"style_{style_key}_{self._compute_hash(title)}"
            documents.append({
                "id": doc_id,
                "content": f"{title}\n\n{body}",
                "metadata": {
                    "source_file": Path(file_path).stem,
                    "title": title,
                    "style_key": style_key,
                    "type": "visual_style"
                }
            })

        return documents

    def _parse_color_document(self, file_path: str) -> List[Dict[str, Any]]:
        """解析色彩心理文档"""
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()

        documents = []
        sections = re.split(r'\n## ', content)

        for section in sections:
            if not section.strip() or section.startswith('#'):
                continue

            lines = section.split('\n', 1)
            title = lines[0].strip()
            body = lines[1].strip() if len(lines) > 1 else ""

            if not body:
                continue

            # 提取色彩类型
            color_match = re.search(r'\(([^)]+)\)', title)
            color_key = color_match.group(1).lower().replace(' ', '_') if color_match else title.split()[0].lower()

            doc_id = f"color_{color_key}_{self._compute_hash(title)}"
            documents.append({
                "id": doc_id,
                "content": f"{title}\n\n{body}",
                "metadata": {
                    "source_file": Path(file_path).stem,
                    "title": title,
                    "color_type": color_key,
                    "type": "color_psychology"
                }
            })

        return documents

    def _parse_camera_document(self, file_path: str) -> List[Dict[str, Any]]:
        """解析镜头技巧文档，每种镜头类型独立"""
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()

        documents = []
        sections = re.split(r'\n## ', content)

        for section in sections:
            if not section.strip() or section.startswith('#'):
                continue

            lines = section.split('\n', 1)
            title = lines[0].strip()
            body = lines[1].strip() if len(lines) > 1 else ""

            if not body:
                continue

            # 提取镜头类型
            shot_match = re.search(r'\(([^)]+)\)', title)
            shot_key = ""
            if shot_match:
                shot_key = shot_match.group(1).lower().replace(' ', '_').replace('-', '_')
            else:
                shot_key = title.split()[0].lower()

            doc_id = f"camera_{shot_key}_{self._compute_hash(title)}"
            documents.append({
                "id": doc_id,
                "content": f"{title}\n\n{body}",
                "metadata": {
                    "source_file": Path(file_path).stem,
                    "title": title,
                    "shot_type": shot_key,
                    "type": "camera_technique"
                }
            })

        return documents

    def init_style_knowledge(self) -> Dict[str, Any]:
        """初始化风格知识库"""
        styles_dir = self.knowledge_dir / "styles"
        total_docs = 0
        all_documents = []

        try:
            # 解析 visual_styles.md
            visual_styles_path = styles_dir / "visual_styles.md"
            if visual_styles_path.exists():
                docs = self._parse_style_document(str(visual_styles_path))
                all_documents.extend(docs)
                logger.info(f"解析 visual_styles.md: {len(docs)} 个风格")

            # 解析 color_psychology.md
            color_path = styles_dir / "color_psychology.md"
            if color_path.exists():
                docs = self._parse_color_document(str(color_path))
                all_documents.extend(docs)
                logger.info(f"解析 color_psychology.md: {len(docs)} 个色彩类型")

            # 写入向量数据库
            if all_documents:
                self.style_kb.add_documents(all_documents, category="style")
                total_docs = len(all_documents)

            return {"success": True, "count": total_docs, "documents": [d["metadata"]["title"] for d in all_documents]}

        except Exception as e:
            logger.error(f"初始化风格知识库失败: {e}")
            return {"success": False, "error": str(e)}

    def init_director_knowledge(self) -> Dict[str, Any]:
        """初始化导演知识库"""
        director_dir = self.knowledge_dir / "director"
        total_docs = 0
        all_documents = []

        try:
            # 镜头技巧
            camera_path = director_dir / "camera_techniques.md"
            if camera_path.exists():
                docs = self._parse_camera_document(str(camera_path))
                all_documents.extend(docs)
                logger.info(f"解析 camera_techniques.md: {len(docs)} 个镜头类型")

            # 构图法则
            composition_path = director_dir / "composition.md"
            if composition_path.exists():
                docs = self._parse_markdown_sections(str(composition_path))
                for doc in docs:
                    doc["metadata"]["type"] = "composition"
                all_documents.extend(docs)
                logger.info(f"解析 composition.md: {len(docs)} 个构图技巧")

            # 光线与氛围
            lighting_path = director_dir / "lighting_mood.md"
            if lighting_path.exists():
                docs = self._parse_markdown_sections(str(lighting_path))
                for doc in docs:
                    doc["metadata"]["type"] = "lighting"
                all_documents.extend(docs)
                logger.info(f"解析 lighting_mood.md: {len(docs)} 个光线技巧")

            # 节奏与剪辑
            pacing_path = director_dir / "pacing_editing.md"
            if pacing_path.exists():
                docs = self._parse_markdown_sections(str(pacing_path))
                for doc in docs:
                    doc["metadata"]["type"] = "pacing"
                all_documents.extend(docs)
                logger.info(f"解析 pacing_editing.md: {len(docs)} 个剪辑技巧")

            # 分镜技巧
            storyboard_path = director_dir / "storyboard_techniques.md"
            if storyboard_path.exists():
                docs = self._parse_markdown_sections(str(storyboard_path))
                for doc in docs:
                    doc["metadata"]["type"] = "storyboard"
                all_documents.extend(docs)
                logger.info(f"解析 storyboard_techniques.md: {len(docs)} 个分镜技巧")

            # 写入向量数据库
            if all_documents:
                self.director_kb.add_documents(all_documents, category="director")
                total_docs = len(all_documents)

            return {"success": True, "count": total_docs}

        except Exception as e:
            logger.error(f"初始化导演知识库失败: {e}")
            return {"success": False, "error": str(e)}

    def init_prompt_knowledge(self) -> Dict[str, Any]:
        """初始化提示词知识库"""
        prompts_dir = self.knowledge_dir / "prompts"
        total_docs = 0
        all_documents = []

        try:
            # 角色提示词
            char_path = prompts_dir / "character_prompts.md"
            if char_path.exists():
                docs = self._parse_markdown_sections(str(char_path))
                for doc in docs:
                    doc["metadata"]["type"] = "character_prompt"
                all_documents.extend(docs)
                logger.info(f"解析 character_prompts.md: {len(docs)} 个模板")

            # 场景提示词
            scene_path = prompts_dir / "scene_prompts.md"
            if scene_path.exists():
                docs = self._parse_markdown_sections(str(scene_path))
                for doc in docs:
                    doc["metadata"]["type"] = "scene_prompt"
                all_documents.extend(docs)
                logger.info(f"解析 scene_prompts.md: {len(docs)} 个模板")

            # 分镜提示词
            storyboard_path = prompts_dir / "storyboard_prompts.md"
            if storyboard_path.exists():
                docs = self._parse_markdown_sections(str(storyboard_path))
                for doc in docs:
                    doc["metadata"]["type"] = "storyboard_prompt"
                all_documents.extend(docs)
                logger.info(f"解析 storyboard_prompts.md: {len(docs)} 个模板")

            # 写入向量数据库
            if all_documents:
                self.prompt_kb.add_documents(all_documents, category="prompt")
                total_docs = len(all_documents)

            return {"success": True, "count": total_docs}

        except Exception as e:
            logger.error(f"初始化提示词知识库失败: {e}")
            return {"success": False, "error": str(e)}

    def init_storyboard_knowledge(self) -> Dict[str, Any]:
        """初始化分镜知识库（从导演知识中复制分镜相关内容）"""
        director_dir = self.knowledge_dir / "director"
        total_docs = 0
        all_documents = []

        try:
            # 分镜技巧
            storyboard_path = director_dir / "storyboard_techniques.md"
            if storyboard_path.exists():
                docs = self._parse_markdown_sections(str(storyboard_path))
                for doc in docs:
                    doc["metadata"]["type"] = "storyboard_technique"
                all_documents.extend(docs)

            # 写入向量数据库
            if all_documents:
                self.storyboard_kb.add_documents(all_documents, category="storyboard")
                total_docs = len(all_documents)

            return {"success": True, "count": total_docs}

        except Exception as e:
            logger.error(f"初始化分镜知识库失败: {e}")
            return {"success": False, "error": str(e)}

    def clear_all_knowledge(self) -> Dict[str, Any]:
        """清空所有知识库（用于重新初始化）"""
        results = {}

        try:
            # 删除并重新创建集合
            collections = ["style_knowledge", "director_knowledge", "prompt_knowledge", "storyboard_knowledge"]
            for coll_name in collections:
                try:
                    self.style_kb.client.delete_collection(coll_name)
                    logger.info(f"已删除集合: {coll_name}")
                except:
                    pass
            results["success"] = True
        except Exception as e:
            results["success"] = False
            results["error"] = str(e)

        return results

    def init_all(self, clear_first: bool = True) -> Dict[str, Any]:
        """初始化所有知识库"""
        results = {}

        if clear_first:
            logger.info("清空现有知识库...")
            self.clear_all_knowledge()
            # 重新创建知识库实例
            self.style_kb = KnowledgeBase(collection_name="style_knowledge")
            self.director_kb = KnowledgeBase(collection_name="director_knowledge")
            self.prompt_kb = KnowledgeBase(collection_name="prompt_knowledge")
            self.storyboard_kb = KnowledgeBase(collection_name="storyboard_knowledge")

        logger.info("开始初始化知识库...")

        results["style"] = self.init_style_knowledge()
        results["director"] = self.init_director_knowledge()
        results["prompt"] = self.init_prompt_knowledge()
        results["storyboard"] = self.init_storyboard_knowledge()

        # 统计总数
        total = sum(r.get("count", 0) for r in results.values() if r.get("success"))
        results["total"] = total

        return results


def init_knowledge(clear_first: bool = True) -> Dict[str, Any]:
    """初始化知识库的入口函数"""
    initializer = KnowledgeInitializer()
    results = initializer.init_all(clear_first=clear_first)

    logger.info("=" * 50)
    logger.info("知识库初始化完成:")
    for kb_name, result in results.items():
        if kb_name == "total":
            continue
        if result.get("success"):
            count = result.get("count", 0)
            logger.info(f"  ✓ {kb_name}: {count} 个文档")
        else:
            logger.error(f"  ✗ {kb_name}: 失败 - {result.get('error')}")

    logger.info(f"  总计: {results.get('total', 0)} 个文档")
    logger.info("=" * 50)

    return results


async def test_knowledge_query():
    """测试知识库查询"""
    from app.agent.knowledge.base import (
        get_style_knowledge,
        get_director_knowledge,
        get_prompt_knowledge,
        get_storyboard_knowledge
    )

    print("\n" + "=" * 50)
    print("测试知识库查询")
    print("=" * 50)

    # 测试风格知识库
    print("\n【风格知识库测试】")
    style_kb = get_style_knowledge()
    results = await style_kb.query("日漫风格", k=2)
    print(f"查询 '日漫风格': 找到 {len(results)} 条结果")
    for r in results:
        print(f"  - {r['metadata'].get('title', 'N/A')}: {r['content'][:100]}...")

    # 测试导演知识库
    print("\n【导演知识库测试】")
    director_kb = get_director_knowledge()
    results = await director_kb.query("特写镜头", k=2)
    print(f"查询 '特写镜头': 找到 {len(results)} 条结果")
    for r in results:
        print(f"  - {r['metadata'].get('title', 'N/A')}")

    # 测试提示词知识库
    print("\n【提示词知识库测试】")
    prompt_kb = get_prompt_knowledge()
    results = await prompt_kb.query("角色图片", k=2)
    print(f"查询 '角色图片': 找到 {len(results)} 条结果")
    for r in results:
        print(f"  - {r['metadata'].get('title', 'N/A')}")

    # 测试分镜知识库
    print("\n【分镜知识库测试】")
    storyboard_kb = get_storyboard_knowledge()
    results = await storyboard_kb.query("动作镜头", k=2)
    print(f"查询 '动作镜头': 找到 {len(results)} 条结果")
    for r in results:
        print(f"  - {r['metadata'].get('title', 'N/A')}")

    print("\n" + "=" * 50)
    print("测试完成")
    print("=" * 50)


if __name__ == "__main__":
    import asyncio

    # 初始化知识库
    results = init_knowledge(clear_first=True)

    # 测试查询
    asyncio.run(test_knowledge_query())
