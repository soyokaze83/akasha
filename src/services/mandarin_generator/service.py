"""Mandarin passage generation service."""

import logging
from typing import Optional

from src.llm import get_configured_llm

logger = logging.getLogger(__name__)

SYSTEM_INSTRUCTION = """你是一位专业的中文教育专家，专门为中级学习者（HSK 3-4级）编写阅读材料。

规则：
1. 只使用HSK 3-4级的词汇和语法
2. 只输出汉字，不要拼音，不要英文翻译
3. 文章长度：300-500个汉字（这是硬性要求，必须写完整）
4. 使用简体中文
5. 内容要有趣、实用、贴近生活
6. 文章结构清晰，有开头、中间、结尾
7. 可以适当使用一些HSK 5级的简单词汇，但要确保整体难度适中
8. 不要在文章末尾添加任何注释、词汇表或翻译
9. 不要添加标题
10. 必须写完整篇文章，不要中途停止"""


class PassageGeneratorService:
    """Service for generating HSK 3-4 Mandarin reading passages."""

    async def generate_passage(self, topic: Optional[str] = None) -> tuple[str, str]:
        """
        Generate a Mandarin reading passage.

        Args:
            topic: Optional specific topic for the passage

        Returns:
            Tuple of (passage text, topic used)
        """
        if topic:
            prompt = f"""请写一篇关于"{topic}"的短文。"""
            display_topic = topic
        else:
            prompt = """请自由选择一个有趣的话题，写一篇短文。话题可以是任何内容，比如：日常生活、旅行经历、美食、科技、文化、自然、人际关系、工作学习、兴趣爱好等等。"""
            display_topic = "自由话题"

        prompt += """

要求：
- 适合HSK 3-4级学习者阅读
- 只用汉字，不要拼音
- 300-500个汉字（必须写完整）
- 内容有趣、实用
- 文章要有完整的开头、中间和结尾

直接输出文章内容，不要任何标题或额外说明。"""

        llm_client = get_configured_llm()
        passage = await llm_client.generate_content(
            prompt=prompt,
            system_instruction=SYSTEM_INSTRUCTION,
            temperature=0.9,
        )

        # Clean up any potential artifacts
        passage = passage.strip()

        logger.info(f"Generated passage for topic '{display_topic}': {len(passage)} characters")
        return passage, display_topic


# Singleton instance
passage_generator = PassageGeneratorService()
