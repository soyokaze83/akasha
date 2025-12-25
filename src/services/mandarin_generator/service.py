"""Mandarin passage generation service."""

import logging
import random
from typing import Optional

from src.llm import get_configured_llm

logger = logging.getLogger(__name__)

# Topic categories for variety in daily passages
PASSAGE_TOPICS = [
    "日常生活",  # Daily life
    "工作和学习",  # Work and study
    "旅游和交通",  # Travel and transportation
    "购物和饮食",  # Shopping and food
    "健康和运动",  # Health and exercise
    "天气和季节",  # Weather and seasons
    "家庭和朋友",  # Family and friends
    "兴趣爱好",  # Hobbies
    "文化和节日",  # Culture and festivals
    "科技和生活",  # Technology and life
]

SYSTEM_INSTRUCTION = """你是一位专业的中文教育专家, 专门为中级学习者 (HSK 3-4级) 编写阅读材料。

规则：
1. 只使用HSK 3-4级的词汇和语法
2. 只输出汉字，不要拼音，不要英文翻译
3. 文章长度300-500字
4. 使用简体中文
5. 内容要有趣、实用、贴近生活
6. 文章结构清晰，有开头、中间、结尾
7. 可以适当使用一些HSK 5级的简单词汇, 但要确保整体难度适中
8. 不要在文章末尾添加任何注释、词汇表或翻译
9. 不要添加标题"""


class PassageGeneratorService:
    """Service for generating HSK 3-4 Mandarin reading passages."""

    async def generate_passage(self, topic: Optional[str] = None) -> tuple[str, str]:
        """
        Generate a Mandarin reading passage.

        Args:
            topic: Optional specific topic, otherwise randomly selected

        Returns:
            Tuple of (passage text, topic used)
        """
        if topic is None:
            topic = random.choice(PASSAGE_TOPICS)

        prompt = f"""请写一篇关于"{topic}"的短文。

要求：
- 适合HSK 3-4级学习者阅读
- 只用汉字，不要拼音
- 150-250字
- 内容有趣、实用

直接输出文章内容，不要任何标题或额外说明。"""

        llm_client = get_configured_llm()
        passage = await llm_client.generate_content(
            prompt=prompt,
            system_instruction=SYSTEM_INSTRUCTION,
            temperature=0.8,
        )

        # Clean up any potential artifacts
        passage = passage.strip()

        logger.info(f"Generated passage for topic '{topic}': {len(passage)} characters")
        return passage, topic


# Singleton instance
passage_generator = PassageGeneratorService()
