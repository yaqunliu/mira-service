"""
Vocab Tools - 单词视频创作相关的工具
"""

from typing import Dict, Any, List
from pydantic import BaseModel, Field


class SaveVocabParamsInput(BaseModel):
    """保存单词视频参数"""
    words: List[str] = Field(description="单词列表，1-5个")
    sentence_level: str = Field(default="primary", description="句子难度：kindergarten/primary/middle")
    word_repeat_count: int = Field(default=2, description="单词重复次数：1或2")
    translation_repeat_count: int = Field(default=1, description="翻译重复次数：1或2")
    voice_gender: str = Field(default="random", description="配音性别：female/male/random")


def get_vocab_tools():
    """获取单词视频相关的工具"""
    from langchain_core.tools import tool
    
    @tool(args_schema=SaveVocabParamsInput)
    def save_vocab_params(
        words: List[str],
        sentence_level: str = "primary",
        word_repeat_count: int = 2,
        translation_repeat_count: int = 1,
        voice_gender: str = "random"
    ) -> Dict[str, Any]:
        """
        保存单词视频创作参数。
        
        当用户提供了单词或配置信息时，调用此工具保存参数。
        
        参数：
        - words: 单词列表，最多5个
        - sentence_level: 句子难度（kindergarten/primary/middle）
        - word_repeat_count: 单词重复次数（1或2）
        - translation_repeat_count: 翻译重复次数（1或2）
        - voice_gender: 配音性别（female/male/random）
        
        返回保存结果和当前参数状态。
        """
        return {
            "success": True,
            "message": "参数已保存",
            "params": {
                "words": words,
                "sentence_level": sentence_level,
                "word_repeat_count": word_repeat_count,
                "translation_repeat_count": translation_repeat_count,
                "voice_gender": voice_gender,
            }
        }
    
    return [save_vocab_params]
