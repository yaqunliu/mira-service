"""
角色状态识别工具
用于根据角色的外观、着装、状态等信息生成唯一的角色标识
"""
from typing import Dict, Any, Optional
import re


class CharacterStateIdentifier:
    """角色状态识别器"""

    # 关键状态词库
    STATE_KEYWORDS = {
        # 湿度状态
        'wet': ['湿透', '淋湿', '湿漉漉', '浑身湿', '全身湿', '雨水打湿', '被雨淋'],
        # 脏污状态
        'dirty': ['脏', '污渍', '泥泞', '灰尘', '弄脏', '沾满'],
        # 受伤状态
        'injured': ['受伤', '流血', '伤口', '包扎', '血迹', '挂彩'],
        # 情绪/精神状态
        'tired': ['疲惫', '憔悴', '疲惫不堪', '精疲力尽', '虚弱'],
        'angry': ['愤怒', '暴怒', '怒气冲冲'],
        # 特殊形态
        'transformed': ['变身', '变化', '变形', '化身', '形态'],
        'battle': ['战斗', '格斗', '战斗状态', '备战'],
        # 着装状态
        'formal': ['正装', '西装', '礼服', '正式'],
        'casual': ['休闲', '便装', '日常'],
        'work': ['工作服', '制服', '职业装'],
        'damaged_clothes': ['破损', '撕裂', '褴褛', '破烂', '衣衫不整'],
    }

    @classmethod
    def generate_character_identity(
        cls,
        name: str,
        age_group: str,
        appearance: str = "",
        clothing: str = "",
        description: str = "",
        extra_context: str = ""
    ) -> str:
        """
        生成角色标识

        Args:
            name: 角色名字
            age_group: 年龄段
            appearance: 外观描述
            clothing: 着装描述
            description: 分镜描述
            extra_context: 额外上下文

        Returns:
            角色标识，格式：角色名-年龄段-状态 (如 "张三-青年-雨天湿透")
        """
        # 合并所有描述文本
        full_text = f"{appearance} {clothing} {description} {extra_context}"

        # 检测特殊状态
        detected_states = cls._detect_states(full_text)

        # 构建角色标识
        if detected_states:
            # 有特殊状态
            state_suffix = "-".join(detected_states)
            identity = f"{name}-{age_group}-{state_suffix}"
        else:
            # 无特殊状态，只用年龄段
            identity = f"{name}-{age_group}"

        return identity

    @classmethod
    def _detect_states(cls, text: str) -> list:
        """
        检测文本中的状态关键词

        Args:
            text: 要检测的文本

        Returns:
            检测到的状态列表
        """
        detected = []

        # 按优先级检测状态
        priority_order = [
            'wet',           # 湿透状态
            'injured',       # 受伤状态
            'dirty',         # 脏污状态
            'transformed',   # 变身状态
            'battle',        # 战斗状态
            'tired',         # 疲惫状态
            'damaged_clothes', # 衣服破损
            'formal',        # 正装
            'work',          # 工作服
            'casual',        # 休闲装
        ]

        for state_key in priority_order:
            keywords = cls.STATE_KEYWORDS.get(state_key, [])
            for keyword in keywords:
                if keyword in text:
                    # 转换为中文描述
                    state_name = cls._get_state_chinese_name(state_key, keyword, text)
                    if state_name and state_name not in detected:
                        detected.append(state_name)
                    break  # 同一类状态只取第一个匹配

        return detected

    @classmethod
    def _get_state_chinese_name(cls, state_key: str, keyword: str, context: str) -> Optional[str]:
        """
        根据状态类型和关键词生成中文状态名

        Args:
            state_key: 状态键
            keyword: 匹配到的关键词
            context: 上下文

        Returns:
            中文状态名
        """
        # 状态映射
        state_mapping = {
            'wet': '湿透',
            'dirty': '脏污',
            'injured': '受伤',
            'tired': '疲惫',
            'angry': '愤怒',
            'transformed': '变身',
            'battle': '战斗状态',
            'formal': '正装',
            'casual': '休闲装',
            'work': '工作服',
            'damaged_clothes': '衣服破损',
        }

        # 特殊处理：如果关键词更具体，直接使用关键词
        if state_key == 'wet' and '雨' in context:
            return '雨天湿透'
        elif state_key == 'wet':
            return '湿透'

        return state_mapping.get(state_key, keyword)

    @classmethod
    def extract_appearance_details(cls, appearance: str, clothing: str) -> Dict[str, str]:
        """
        提取外观细节

        Args:
            appearance: 外观描述
            clothing: 着装描述

        Returns:
            外观细节字典
        """
        details = {}

        # 提取发型
        hair_keywords = ['短发', '长发', '卷发', '直发', '马尾', '辫子', '寸头', '光头']
        for keyword in hair_keywords:
            if keyword in appearance or keyword in clothing:
                details['hair'] = keyword
                break

        # 提取服装类型
        clothing_keywords = {
            '西装': 'formal',
            '礼服': 'formal',
            '唐装': 'traditional',
            '制服': 'uniform',
            'T恤': 'casual',
            '牛仔': 'casual',
            '运动服': 'sports',
        }
        for keyword, category in clothing_keywords.items():
            if keyword in clothing:
                details['clothing_category'] = category
                break

        return details


# 便捷函数
def generate_character_identity(
    name: str,
    age_group: str,
    appearance: str = "",
    clothing: str = "",
    shot_description: str = "",
    **kwargs
) -> str:
    """
    生成角色标识（便捷函数）

    示例:
        generate_character_identity("张三", "青年", "黑色短发", "改良唐装外套，全身湿透", "在雨中奔跑")
        # 返回: "张三-青年-雨天湿透"

        generate_character_identity("李四", "中年", "金丝眼镜", "深色商务西装", "")
        # 返回: "李四-中年-正装"
    """
    return CharacterStateIdentifier.generate_character_identity(
        name=name,
        age_group=age_group,
        appearance=appearance,
        clothing=clothing,
        description=shot_description,
        extra_context=kwargs.get('extra_context', '')
    )


if __name__ == "__main__":
    # 测试用例
    print("测试角色状态识别:")
    print()

    # 测试1: 雨天湿透
    identity1 = generate_character_identity(
        "张三",
        "青年",
        "黑色短发，面容憔悴",
        "改良唐装外套，全身湿透",
        "在暴雨中奔跑"
    )
    print(f"测试1 (雨天湿透): {identity1}")
    # 预期: 张三-青年-雨天湿透

    # 测试2: 正常着装
    identity2 = generate_character_identity(
        "张三",
        "青年",
        "黑色短发",
        "改良唐装外套",
        "站在办公室"
    )
    print(f"测试2 (正常着装): {identity2}")
    # 预期: 张三-青年

    # 测试3: 正装商务
    identity3 = generate_character_identity(
        "李总",
        "中年",
        "金丝眼镜，面容严肃",
        "深色商务西装和衬衫",
        "坐在办公桌后"
    )
    print(f"测试3 (正装): {identity3}")
    # 预期: 李总-中年-正装

    # 测试4: 受伤状态
    identity4 = generate_character_identity(
        "王五",
        "青年",
        "脸上有伤口，血迹",
        "破损的T恤",
        "刚经历战斗"
    )
    print(f"测试4 (受伤): {identity4}")
    # 预期: 王五-青年-受伤-衣服破损

    # 测试5: 变身状态
    identity5 = generate_character_identity(
        "小明",
        "少年",
        "发光的眼睛",
        "战斗形态",
        "变身后的形态"
    )
    print(f"测试5 (变身): {identity5}")
    # 预期: 小明-少年-变身-战斗状态
