from typing import List, Literal, TypedDict, Optional, Dict, Any
from dataclasses import dataclass


class VocabConfig(TypedDict, total=False):
    """英语单词视频配置"""
    words: List[str]
    word_count: int
    word_repeat_count: int
    translation_repeat_count: int
    enable_sentence_video: bool
    voice_gender: Literal["female", "male", "random"]
    voice_age: Literal["child", "adult"]
    sentence_level: Literal["kindergarten", "primary", "middle"]
    style: str
    character_id: Optional[str]
    scene_id: Optional[str]


PREDEFINED_CHARACTERS: Dict[str, Dict[str, Any]] = {
    "char_001": {
        "id": "char_001",
        "name": "团子",
        "gender": "female",
        "age": "child",
        "description": "A cute 6-year-old Chinese girl with chubby round face, double ponytails, big sparkly eyes, wearing yellow kindergarten uniform with bear pattern, always giggling",
        "image_url": "https://novel-agent.cn-sh2.ufileos.com/test/custom_path/团子.png",
    },
    "char_002": {
        "id": "char_002",
        "name": "跳跳",
        "gender": "male",
        "age": "child",
        "description": "A lively 8-year-old Chinese boy with short messy hair, bright energetic eyes, wearing blue school uniform with superhero cape, always jumping around excitedly",
        "image_url": "https://novel-agent.cn-sh2.ufileos.com/test/custom_path/跳跳.png",
    },
    "char_003": {
        "id": "char_003",
        "name": "泡泡",
        "gender": "female",
        "age": "child",
        "description": "A gentle 10-year-old Chinese girl with long flowing hair, clear wise eyes, wearing a flowy pink dress, speaks softly and thoughtfully",
        "image_url": "https://novel-agent.cn-sh2.ufileos.com/test/custom_path/泡泡.png",
    },
    "char_004": {
        "id": "char_004",
        "name": "浩然",
        "gender": "male",
        "age": "adult",
        "description": "A handsome 22-year-old Chinese young man with neat short hair, bright confident eyes, wearing casual hoodie and jeans, warm friendly smile, speaks energetically",
        "image_url": "https://novel-agent.cn-sh2.ufileos.com/test/custom_path/浩然.png",
    },
    "char_005": {
        "id": "char_005",
        "name": "雅文",
        "gender": "female",
        "age": "adult",
        "description": "A beautiful 22-year-old Chinese young woman with long silky hair, gentle sparkling eyes, wearing casual elegant dress, warm approachable smile, speaks with a soft pleasant voice",
        "image_url": "https://novel-agent.cn-sh2.ufileos.com/test/custom_path/雅文.png",
    },
}


PREDEFINED_SCENES: Dict[str, Dict[str, Any]] = {
    "scene_001": {
        "id": "scene_001",
        "name": "彩虹极光",
        "description": "A vibrant swirling aurora borealis with colors blending from purple to blue to green to yellow to orange to red, like colorful curtains dancing in the night sky, dreamy and magical",
        "image_url": "https://novel-agent.cn-sh2.ufileos.com/test/custom_path/彩虹极光.png",
    },
    "scene_002": {
        "id": "scene_002",
        "name": "糖果漩涡",
        "description": "A colorful candy-like swirling pattern with bright pink, purple, blue, yellow, and green colors mixing together like a delicious cotton candy vortex, sweet and delightful",
        "image_url": "https://novel-agent.cn-sh2.ufileos.com/test/custom_path/糖果漩涡.png",
    },
    "scene_003": {
        "id": "scene_003",
        "name": "日出朝霞",
        "description": "A warm sunrise gradient blending from deep purple at top through pink and orange to golden yellow at bottom, with soft clouds floating, peaceful and beautiful",
        "image_url": "https://novel-agent.cn-sh2.ufileos.com/test/custom_path/日出朝霞.png",
    },
    "scene_004": {
        "id": "scene_004",
        "name": "泡泡星空",
        "description": "A dreamy background filled with countless colorful soap bubbles in various sizes, bubbles in pink, blue, purple, gold, and rainbow colors floating together, sparkling and magical",
        "image_url": "https://novel-agent.cn-sh2.ufileos.com/test/custom_path/泡泡星空.png",
    },
    "scene_005": {
        "id": "scene_005",
        "name": "热带日落",
        "description": "A vibrant sunset gradient with hot pink, orange, and yellow mixing together, warm and energetic atmosphere, like a tropical paradise",
        "image_url": "https://novel-agent.cn-sh2.ufileos.com/test/custom_path/热带日落.png",
    },
}


CHARACTER_BY_LEVEL = {
    "kindergarten": ["char_001", "char_002", "char_004", "char_005"],
    "primary": ["char_001", "char_002", "char_003", "char_004", "char_005"],
    "middle": ["char_002", "char_003", "char_004", "char_005"]
}


SCENE_BY_LEVEL = {
    "kindergarten": ["scene_001", "scene_002"],
    "primary": ["scene_002", "scene_003", "scene_004"],
    "middle": ["scene_003", "scene_004", "scene_005"]
}


def select_character(sentence_level: str, gender: str = None) -> Dict[str, Any]:
    """根据难度随机选择角色"""
    import random
    
    available = CHARACTER_BY_LEVEL.get(sentence_level, ["char_001", "char_002", "char_004"])
    
    # 随机选择一个角色
    char_id = random.choice(available)
    return PREDEFINED_CHARACTERS[char_id]


def select_scene(sentence_level: str) -> Dict[str, Any]:
    """根据难度选择场景"""
    available = SCENE_BY_LEVEL.get(sentence_level, ["scene_002"])
    import random
    scene_id = random.choice(available)
    return PREDEFINED_SCENES[scene_id]


@dataclass
class VocabConfigDefaults:
    word_repeat_count: int = 2
    translation_repeat_count: int = 1
    enable_sentence_video: bool = False
    voice_gender: Literal["female", "male"] = "female"
    voice_age: Literal["child", "adult"] = "child"
    sentence_level: Literal["kindergarten", "primary", "middle"] = "primary"
    style: str = "cartoon"

    def to_dict(self) -> dict:
        return {
            "word_repeat_count": self.word_repeat_count,
            "translation_repeat_count": self.translation_repeat_count,
            "enable_sentence_video": self.enable_sentence_video,
            "voice_gender": self.voice_gender,
            "voice_age": self.voice_age,
            "sentence_level": self.sentence_level,
            "style": self.style,
        }


def merge_vocab_config(user_config: Optional[dict]) -> VocabConfig:
    """合并用户配置和默认值"""
    defaults = VocabConfigDefaults()
    result = defaults.to_dict()
    
    if user_config:
        result.update(user_config)
    
    if "words" in result and result["words"]:
        result["word_count"] = len(result["words"])
    
    return result


def validate_vocab_config(config: VocabConfig) -> tuple[bool, str]:
    """验证配置有效性"""
    words = config.get("words", [])
    if not words:
        return False, "单词列表不能为空"
    
    if len(words) < 3 or len(words) > 5:
        return False, "单词数量必须是3-5个"
    
    for word in words:
        if not word or not word.strip():
            return False, "单词不能为空"
        if not word.replace(" ", "").isalpha():
            return False, f"单词 '{word}' 包含非法字符"
    
    word_repeat = config.get("word_repeat_count", 2)
    if word_repeat < 1 or word_repeat > 5:
        return False, "单词重复次数必须在1-5之间"
    
    trans_repeat = config.get("translation_repeat_count", 1)
    if trans_repeat < 1 or trans_repeat > 3:
        return False, "翻译重复次数必须在1-3之间"
    
    return True, ""
