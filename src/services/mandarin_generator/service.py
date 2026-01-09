"""Mandarin passage generation service."""

import logging
import re
from datetime import date
from typing import Optional

from src.core.config import settings
from src.llm import get_configured_llm

logger = logging.getLogger(__name__)


# Shared constants for message formatting
MESSAGE_HEADER_TEMPLATE = "📚 每日中文阅读 - {date}"


def get_formatted_date() -> str:
    """Get today's date formatted for Mandarin passages (YYYY年MM月DD日)."""
    return date.today().strftime("%Y年%m月%d日")


def format_passage_message(passage: str) -> str:
    """Format a passage with the standard header."""
    date_str = get_formatted_date()
    header = MESSAGE_HEADER_TEMPLATE.format(date=date_str)
    return f"{header}\n\n{passage}"

SYSTEM_INSTRUCTION = """你是一位专业的中文教育专家, 专门为中级学习者 (HSK 3-4级) 编写阅读材料。

规则: 
1. 只使用HSK 3-4级的词汇和语法
2. 只输出汉字, 不要拼音, 不要英文翻译
3. 文章长度: 300-500个汉字 (这是硬性要求, 必须写完整)
4. 使用简体中文
5. 内容要有趣、实用、贴近生活
6. 文章结构清晰, 有开头、中间、结尾
7. 可以适当使用一些HSK 5级的简单词汇, 但要确保整体难度适中
8. 不要在文章末尾添加任何注释、词汇表或翻译
9. 不要添加标题
10. 必须写完整篇文章, 不要中途停止"""

WEB_SEARCH_SYSTEM_INSTRUCTION = """你是一位专业的中文教育专家, 专门为中级学习者 (HSK 3-4级) 编写阅读材料。

特别注意: 你将根据今天的新闻/时事热点来生成文章, 所以话题可能与日常生活不同, 但难度必须保持在HSK 3-4级。

规则: 
1. 只使用HSK 3-4级的词汇和语法
2. 只输出汉字, 不要拼音, 不要英文翻译
3. 文章长度: 300-500个汉字 (这是硬性要求, 必须写完整) 
4. 使用简体中文
5. 基于提供的新闻/时事热点内容选择有趣话题
6. 内容要有趣、实用、贴近生活
7. 文章结构清晰, 有开头、中间、结尾
8. 可以适当使用一些HSK 5级的简单词汇, 但要确保整体难度适中
9. 不要在文章末尾添加任何注释、词汇表或翻译
10. 不要添加标题
11. 必须写完整篇文章, 不要中途停止
12. 根据提供的新闻内容调整生成的文章, 不要抄袭原文"""


class PassageGeneratorService:
    """Service for generating HSK 3-4 Mandarin reading passages."""

    # Passage length constraints (in Chinese characters)
    MIN_LENGTH = 250
    MAX_LENGTH = 600

    # Temperature for passage generation (0.9 = more creative, varied writing)
    # Higher temperature produces more diverse and interesting passages,
    # which is desirable for educational content that should feel fresh each day
    GENERATION_TEMPERATURE = 0.9

    def _validate_and_fix_length(self, passage: str) -> tuple[str, bool]:
        """
        Validate passage length and truncate if too long.

        Args:
            passage: The generated passage

        Returns:
            Tuple of (fixed_passage, is_valid) where is_valid indicates
            if the passage meets minimum length requirement
        """
        # Count only Chinese characters for length validation
        chinese_chars = len([c for c in passage if "\u4e00" <= c <= "\u9fff"])

        if chinese_chars < self.MIN_LENGTH:
            logger.warning(
                f"Passage too short: {chinese_chars} Chinese chars (min: {self.MIN_LENGTH})"
            )
            return passage, False

        if chinese_chars > self.MAX_LENGTH:
            logger.warning(
                f"Passage too long: {chinese_chars} Chinese chars (max: {self.MAX_LENGTH}), truncating"
            )
            # Truncate at sentence boundary (。！？)
            passage = self._truncate_at_sentence(passage, self.MAX_LENGTH)

        return passage, True

    def _truncate_at_sentence(self, passage: str, max_chars: int) -> str:
        """Truncate passage at the nearest sentence boundary before max_chars."""
        # Find sentence endings (Chinese punctuation)
        sentence_endings = ["。", "！", "？"]

        # Count Chinese characters and find truncation point
        char_count = 0
        last_sentence_end = 0

        for i, char in enumerate(passage):
            if "\u4e00" <= char <= "\u9fff":
                char_count += 1
            if char in sentence_endings:
                if char_count <= max_chars:
                    last_sentence_end = i + 1

            if char_count > max_chars and last_sentence_end > 0:
                break

        if last_sentence_end > 0:
            return passage[:last_sentence_end]

        # Fallback: hard truncate if no sentence boundary found
        return passage[:max_chars]

    async def _fetch_web_content(self) -> tuple[Optional[str], Optional[str]]:
        """
        Fetch web content for topic selection.

        Returns:
            Tuple of (page_content, failure_reason) - one will be None
        """
        from src.services.reply_agent.tools import web_search_tool
        from src.utils.web_scraper import fetch_page_text

        # Search for today's news in Chinese
        search_query = "今日新闻 有趣的话题"
        logger.info(f"Searching for topics with query: {search_query}")

        results = await web_search_tool.search(search_query, num_results=3)

        if not results:
            return None, "No search results returned"

        # Fetch content from top result for LLM to analyze
        top_result = results[0]
        logger.info(f"Fetching content from: {top_result['title']}")

        page_content = await fetch_page_text(top_result["link"])

        # Limit to first 2000 characters to avoid overwhelming LLM
        if page_content and len(page_content) > 2000:
            page_content = page_content[:2000]
            logger.info("Limited page content to 2000 characters")

        if not page_content:
            logger.warning(
                f"Failed to fetch content from {top_result['link']}, using snippet instead"
            )
            page_content = top_result.get("snippet", "")

        if not page_content:
            return None, f"Failed to fetch content from {top_result['link']}"

        return page_content, None

    async def _generate_passage_from_web_content(
        self, page_content: str
    ) -> tuple[str, str]:
        """
        Generate passage and extract topic in a single LLM call.

        Args:
            page_content: Web content to base the passage on

        Returns:
            Tuple of (passage, topic)
        """
        # Combined prompt: select topic AND generate passage in one call
        combined_prompt = f"""基于以下新闻/网页内容, 选择一个有趣的话题并写一篇短文。

新闻内容:
{page_content}

要求:
1. 在文章开头用【话题：XXX】标注你选择的话题 (必须包含这个标记)
2. 话题要具体、有趣、来源于提供的新闻内容
3. 适合HSK 3-4级学习者阅读
4. 只用汉字, 不要拼音
5. 300-500个汉字 (必须写完整)
6. 内容有趣、实用
7. 文章要有完整的开头、中间和结尾

格式示例:
【话题：春节旅游】
春节快到了, 很多人都在计划去旅游...

直接输出【话题：XXX】和文章内容。"""

        llm_client = get_configured_llm()
        response = await llm_client.generate_content(
            prompt=combined_prompt,
            system_instruction=WEB_SEARCH_SYSTEM_INSTRUCTION,
            temperature=self.GENERATION_TEMPERATURE,
        )

        response = response.strip()

        # Extract topic from 【话题：XXX】 pattern
        topic_match = re.search(r"【话题[：:]\s*(.+?)】", response)
        if topic_match:
            topic = topic_match.group(1).strip()
            # Remove topic marker from passage
            passage = re.sub(r"【话题[：:].*?】\s*", "", response).strip()
            logger.info(f"Extracted topic from combined response: '{topic}'")
        else:
            # Fallback if pattern not found
            topic = "网络话题"
            passage = response
            logger.warning(
                "Could not extract topic from response, using default '网络话题'"
            )

        return passage, topic

    async def generate_passage(self, topic: Optional[str] = None) -> tuple[str, str]:
        """
        Generate a Mandarin reading passage.

        Args:
            topic: Optional specific topic for the passage

        Returns:
            Tuple of (passage text, topic used)
        """
        if topic:
            # Specific topic provided - use single LLM call
            prompt = f"""请写一篇关于"{topic}"的短文。

要求:
- 适合HSK 3-4级学习者阅读
- 只用汉字, 不要拼音
- 300-500个汉字 (必须写完整)
- 内容有趣、实用
- 文章要有完整的开头、中间和结尾

直接输出文章内容, 不要任何标题或额外说明。"""

            llm_client = get_configured_llm()
            passage = await llm_client.generate_content(
                prompt=prompt,
                system_instruction=SYSTEM_INSTRUCTION,
                temperature=self.GENERATION_TEMPERATURE,
            )
            passage = passage.strip()
            display_topic = topic

        elif settings.topic_selection_mode == "web_search":
            # Web search mode: fetch content and generate in single LLM call
            page_content, failure_reason = await self._fetch_web_content()

            if page_content:
                # Single LLM call for both topic selection and passage generation
                passage, extracted_topic = await self._generate_passage_from_web_content(
                    page_content
                )
                display_topic = f"网络话题: {extracted_topic}"
            else:
                # Fallback to free topic if web search fails
                logger.warning(f"Web search failed: {failure_reason}, falling back to free topic mode")
                passage, display_topic = await self._generate_free_topic_passage()
                display_topic = f"自由话题 (搜索失败: {failure_reason})"
        else:
            # Free topic mode
            passage, display_topic = await self._generate_free_topic_passage()

        # Validate and fix passage length
        passage, is_valid = self._validate_and_fix_length(passage)

        # Count Chinese characters for logging
        chinese_chars = len([c for c in passage if "\u4e00" <= c <= "\u9fff"])
        logger.info(
            f"Generated passage for topic '{display_topic}': {chinese_chars} Chinese chars "
            f"(total: {len(passage)} chars, mode: {settings.topic_selection_mode}, "
            f"valid_length: {is_valid})"
        )
        return passage, display_topic

    async def _generate_free_topic_passage(self) -> tuple[str, str]:
        """Generate a passage with a freely chosen topic."""
        prompt = """请自由选择一个有趣的话题, 写一篇短文。话题可以是任何内容, 比如: 日常生活、旅行经历、美食、科技、文化、自然、人际关系、工作学习、兴趣爱好等等。

要求:
- 适合HSK 3-4级学习者阅读
- 只用汉字, 不要拼音
- 300-500个汉字 (必须写完整)
- 内容有趣、实用
- 文章要有完整的开头、中间和结尾

直接输出文章内容, 不要任何标题或额外说明。"""

        llm_client = get_configured_llm()
        passage = await llm_client.generate_content(
            prompt=prompt,
            system_instruction=SYSTEM_INSTRUCTION,
            temperature=self.GENERATION_TEMPERATURE,
        )
        return passage.strip(), "自由话题"


# Singleton instance
passage_generator = PassageGeneratorService()
