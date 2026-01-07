"""Web scraping utilities for content extraction."""

import logging
from typing import Optional

import httpx
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)


async def fetch_page_text(url: str) -> Optional[str]:
    """
    Fetch and extract text content from a web page.

    Args:
        url: URL of the web page to fetch

    Returns:
        Cleaned text content, or None if fetching fails
    """
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(url, follow_redirects=True)
            response.raise_for_status()

            # Parse HTML and extract text
            soup = BeautifulSoup(response.text, "lxml")

            # Remove script and style elements
            for script in soup(["script", "style"]):
                script.decompose()

            # Get text content
            text = soup.get_text(separator="\n", strip=True)

            # Clean up extra whitespace
            lines = [line.strip() for line in text.split("\n") if line.strip()]
            cleaned_text = "\n".join(lines)

            logger.info(f"Fetched {len(cleaned_text)} characters from {url}")
            return cleaned_text

    except httpx.HTTPStatusError as e:
        logger.error(f"HTTP error fetching {url}: {e.response.status_code}")
        return None
    except Exception as e:
        logger.error(f"Failed to fetch page {url}: {e}")
        return None
