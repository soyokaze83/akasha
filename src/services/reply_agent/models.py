"""Pydantic models for Reply Agent service."""

from typing import Optional

from pydantic import BaseModel, Field


class SearchResult(BaseModel):
    """Individual search result from web search tool."""

    title: str
    link: str
    snippet: str


class AgentResponse(BaseModel):
    """Final response from the Reply Agent."""

    response: str
    sources_used: list[str] = []


# API Request/Response models
class QueryRequest(BaseModel):
    """Request model for processing a query."""

    query: str = Field(..., description="The question or request to process")
    quoted_context: Optional[str] = Field(
        None, description="Optional context from a quoted/replied message"
    )
    recipient: Optional[str] = Field(
        None,
        description="WhatsApp JID to send the response to. If not provided, response is returned but not sent.",
    )
    image_base64: Optional[str] = Field(
        None, description="Base64-encoded image data for multimodal queries"
    )
    image_mime_type: Optional[str] = Field(
        None,
        description="MIME type of the image (e.g., image/jpeg, image/png, image/webp)",
    )


class QueryResponse(BaseModel):
    """Response model for a processed query."""

    response: str
    sources_used: list[str] = []
    sent_to: Optional[str] = None
    provider_used: Optional[str] = None
