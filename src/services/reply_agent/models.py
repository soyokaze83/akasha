"""Pydantic models for Reply Agent service."""

from pydantic import BaseModel


class SearchResult(BaseModel):
    """Individual search result from web search tool."""

    title: str
    link: str
    snippet: str


class AgentResponse(BaseModel):
    """Final response from the Reply Agent."""

    response: str
    sources_used: list[str] = []
