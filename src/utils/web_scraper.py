"""Web scraping and external content fetching utilities."""

import asyncio
import logging
from typing import Optional

import httpx
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

HN_BASE_URL = "https://hacker-news.firebaseio.com/v0"


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


async def _fetch_hn_story(
    client: httpx.AsyncClient, item_id: int
) -> Optional[dict]:
    """Fetch a single HackerNews story by ID.

    Returns:
        Story dict with id, title, url, score, etc. or None on failure.
    """
    try:
        response = await client.get(f"{HN_BASE_URL}/item/{item_id}.json")
        response.raise_for_status()
        return response.json()
    except Exception as e:
        logger.debug(f"Failed to fetch HN item {item_id}: {e}")
        return None


async def fetch_hackernews_top_stories(count: int = 5) -> list[dict]:
    """Fetch top HackerNews stories that link to external URLs.

    Fetches the top story IDs, then retrieves details for a batch of them
    in parallel, filtering for stories with external URLs (skipping
    Ask HN, Show HN text-only posts, etc.).

    Args:
        count: Number of URL-bearing stories to return.

    Returns:
        List of story dicts with keys: id, title, url, score.
        Empty list on failure.
    """
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            # Get top story IDs
            response = await client.get(f"{HN_BASE_URL}/topstories.json")
            response.raise_for_status()
            story_ids: list[int] = response.json()

            if not story_ids:
                logger.warning("HackerNews returned empty top stories list")
                return []

            # Fetch details for count*3 stories in parallel to find enough with URLs
            batch_size = count * 3
            batch_ids = story_ids[:batch_size]

            stories_raw = await asyncio.gather(
                *[_fetch_hn_story(client, sid) for sid in batch_ids]
            )

            # Filter for stories with external URLs
            stories = []
            for story in stories_raw:
                if (
                    story
                    and story.get("type") == "story"
                    and story.get("url")
                ):
                    stories.append(
                        {
                            "id": story["id"],
                            "title": story.get("title", ""),
                            "url": story["url"],
                            "score": story.get("score", 0),
                        }
                    )
                    if len(stories) >= count:
                        break

            logger.info(
                f"Fetched {len(stories)} HN stories with URLs "
                f"(from {len(batch_ids)} candidates)"
            )
            return stories

    except httpx.HTTPStatusError as e:
        logger.error(f"HackerNews API error: {e.response.status_code}")
        return []
    except Exception as e:
        logger.error(f"Failed to fetch HackerNews stories: {e}")
        return []
