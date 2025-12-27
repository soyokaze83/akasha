"""Tool implementations for Reply Agent."""

import logging
from typing import Optional

import httpx

from src.core.config import settings

logger = logging.getLogger(__name__)


class WebSearchTool:
    """Google Custom Search implementation."""

    SEARCH_URL = "https://www.googleapis.com/customsearch/v1"

    async def search(self, query: str, num_results: int = 5) -> list[dict[str, str]]:
        """
        Execute a web search using Google Custom Search API.

        Args:
            query: Search query string
            num_results: Number of results to return (max 10)

        Returns:
            List of search results with title, link, snippet
        """
        if not settings.google_search_api_key or not settings.google_search_engine_id:
            logger.warning("Google Search API not configured, returning empty results")
            return []

        try:
            async with httpx.AsyncClient() as client:
                params = {
                    "key": settings.google_search_api_key,
                    "cx": settings.google_search_engine_id,
                    "q": query,
                    "num": min(num_results, 10),
                }

                response = await client.get(self.SEARCH_URL, params=params, timeout=10.0)
                response.raise_for_status()
                data = response.json()

                results = []
                for item in data.get("items", []):
                    results.append({
                        "title": item.get("title", ""),
                        "link": item.get("link", ""),
                        "snippet": item.get("snippet", ""),
                    })

                logger.info(f"Search for '{query}' returned {len(results)} results")
                return results

        except httpx.HTTPStatusError as e:
            logger.error(f"Google Search API error: {e.response.status_code} - {e.response.text}")
            return []
        except Exception as e:
            logger.error(f"Web search failed: {e}")
            return []


# Tool definitions for LLM function calling
OPENAI_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "web_search",
            "description": "Search the web for current information. Use this when you need up-to-date information, recent news, or facts you're not certain about.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "The search query to look up",
                    }
                },
                "required": ["query"],
            },
        },
    }
]

GEMINI_TOOLS = [
    {
        "name": "web_search",
        "description": "Search the web for current information. Use this when you need up-to-date information, recent news, or facts you're not certain about.",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "The search query to look up",
                }
            },
            "required": ["query"],
        },
    }
]


# Singleton instance
web_search_tool = WebSearchTool()
