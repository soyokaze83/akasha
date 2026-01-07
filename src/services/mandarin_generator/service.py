"""Mandarin passage generation service."""

import logging
from typing import Optional

from src.core.config import settings
from src.llm import get_configured_llm

logger = logging.getLogger(__name__)

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

    async def _select_topic_via_web_search(self) -> Optional[str]:
        """
        Use web search to find today's interesting topics and select one.

        Returns:
            Selected topic string, or None if web search fails
        """
        from src.services.reply_agent.tools import web_search_tool
        from src.utils.web_scraper import fetch_page_text

        # Search for today's news in Chinese
        search_query = "今日新闻 有趣的话题"
        logger.info(f"Searching for topics with query: {search_query}")

        results = await web_search_tool.search(search_query, num_results=3)

        if not results:
            logger.warning(
                "Web search returned no results, will fall back to free topic"
            )
            return None

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
            page_content = top_result["snippet"]

        # Use LLM to select and refine a topic based on web content
        topic_selection_prompt = f"""基于以下新闻/网页内容, 选择一个适合HSK 3-4级学习者阅读的有趣话题。

内容: 
{page_content}

要求: 
1. 只输出话题名称, 不要其他文字
2. 话题要具体、有趣
3. 话题要适合用300-500个汉字写短文
4. 话题应该来源于提供的新闻内容

直接输出话题名称。"""

        llm_client = get_configured_llm()
        topic = await llm_client.generate_content(
            prompt=topic_selection_prompt,
            temperature=0.7,
        )

        topic = topic.strip()
        logger.info(f"Selected topic via web search: '{topic}'")
        return topic

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
            system_instruction = SYSTEM_INSTRUCTION
        else:
            # Check topic selection mode configuration
            if settings.topic_selection_mode == "web_search":
                selected_topic = await self._select_topic_via_web_search()

                if selected_topic:
                    prompt = f"""请写一篇关于"{selected_topic}"的短文。"""
                    display_topic = f"网络话题: {selected_topic}"
                    system_instruction = WEB_SEARCH_SYSTEM_INSTRUCTION
                else:
                    # Fallback to free topic if web search fails
                    prompt = """请自由选择一个有趣的话题, 写一篇短文。话题可以是任何内容, 比如: 日常生活、旅行经历、美食、科技、文化、自然、人际关系、工作学习、兴趣爱好等等。"""
                    display_topic = "自由话题 (搜索失败) "
                    system_instruction = SYSTEM_INSTRUCTION
                    logger.warning("Web search failed, falling back to free topic mode")
            else:
                # Original free topic behavior
                prompt = """请自由选择一个有趣的话题, 写一篇短文。话题可以是任何内容, 比如: 日常生活、旅行经历、美食、科技、文化、自然、人际关系、工作学习、兴趣爱好等等。"""
                display_topic = "自由话题"
                system_instruction = SYSTEM_INSTRUCTION

        prompt += """

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
            system_instruction=system_instruction,
            temperature=0.9,
        )

        # Clean up any potential artifacts
        passage = passage.strip()

        logger.info(
            f"Generated passage for topic '{display_topic}': {len(passage)} characters "
            f"(mode: {settings.topic_selection_mode})"
        )
        return passage, display_topic


# Singleton instance
passage_generator = PassageGeneratorService()
