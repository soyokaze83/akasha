"""Background task processing for non-blocking webhook handling."""

import asyncio
import logging
import time
from typing import Optional

from src.core.gowa import gowa_client

logger = logging.getLogger(__name__)


async def process_text_reply_background(
    reply_agent,
    query: str,
    reply_jid: str,
    message_id: str,
    quoted_context: Optional[str],
    image_data: Optional[bytes],
    image_mime_type: Optional[str],
    akasha_message_ids: dict[str, float],
) -> None:
    """
    Process a text reply in the background and send the response.

    This allows the webhook handler to return immediately (within GoWA's timeout)
    while the LLM processing happens asynchronously.

    Args:
        reply_agent: The ReplyAgentService instance
        query: The user's query
        reply_jid: JID to send the response to
        message_id: Original message ID (for reply threading)
        quoted_context: Optional quoted message context
        image_data: Optional image bytes for multimodal queries
        image_mime_type: MIME type of the image
        akasha_message_ids: Dict to track Akasha's sent messages
    """
    processing_start = time.time()

    try:
        response_text, sources = await reply_agent.process_query(
            query=query,
            quoted_context=quoted_context,
            image_data=image_data,
            image_mime_type=image_mime_type,
        )

        result = await gowa_client.send_message(
            phone=reply_jid,
            message=response_text,
            reply_message_id=message_id,
        )

        # Track Akasha's sent message ID for reply detection
        sent_message_id = result.get("message_id")
        if sent_message_id:
            akasha_message_ids[sent_message_id] = time.time()
            logger.info(f"Tracked message ID: {sent_message_id}")
        else:
            logger.warning(f"No message_id in GoWA response: {result}")

        total_time = time.time() - processing_start
        logger.info(
            f"Reply Agent response sent to {reply_jid} "
            f"(total processing time: {total_time:.2f}s)"
        )

    except Exception as e:
        logger.exception(f"Reply Agent error: {e}")
        await _send_error_response(e, reply_jid, message_id, akasha_message_ids)


async def process_image_reply_background(
    reply_agent,
    query: str,
    reply_jid: str,
    message_id: str,
    image_data: bytes,
    image_mime_type: str,
    quoted_context: Optional[str],
    akasha_message_ids: dict[str, float],
) -> None:
    """
    Process an image reply in the background and send the response.

    Args:
        reply_agent: The ReplyAgentService instance
        query: The user's query (from caption)
        reply_jid: JID to send the response to
        message_id: Original message ID (for reply threading)
        image_data: Image bytes
        image_mime_type: MIME type of the image
        quoted_context: Optional quoted message context
        akasha_message_ids: Dict to track Akasha's sent messages
    """
    processing_start = time.time()

    try:
        response_text, sources = await reply_agent.process_query(
            query=query,
            quoted_context=quoted_context,
            image_data=image_data,
            image_mime_type=image_mime_type,
        )

        result = await gowa_client.send_message(
            phone=reply_jid,
            message=response_text,
            reply_message_id=message_id,
        )

        # Track Akasha's sent message ID
        sent_message_id = result.get("message_id")
        if sent_message_id:
            akasha_message_ids[sent_message_id] = time.time()
            logger.info(f"Tracked message ID: {sent_message_id}")

        total_time = time.time() - processing_start
        logger.info(
            f"Reply Agent (image) response sent to {reply_jid} "
            f"(total processing time: {total_time:.2f}s)"
        )

    except Exception as e:
        logger.exception(f"Reply Agent (image) error: {e}")
        await _send_image_error_response(e, reply_jid, message_id, akasha_message_ids)


async def _send_error_response(
    error: Exception,
    reply_jid: str,
    message_id: str,
    akasha_message_ids: dict[str, float],
) -> None:
    """Send a user-friendly error message based on error type."""
    error_str = str(error).lower()

    if "503" in str(error) or "unavailable" in error_str or "overload" in error_str:
        error_message = (
            "The AI service is temporarily overloaded. "
            "I tried all available API keys but couldn't connect. "
            "Please try again in a moment."
        )
    elif "429" in str(error) or "quota" in error_str or "rate" in error_str:
        error_message = (
            "I'm currently experiencing high demand and hit my rate limit. "
            "Please wait a moment and try again."
        )
    elif "exhausted" in error_str or "all api keys" in error_str:
        error_message = (
            "All my API resources are temporarily exhausted. "
            "Please try again in a few minutes."
        )
    elif "timeout" in error_str:
        error_message = (
            "The request took too long to process. "
            "Please try again with a simpler question."
        )
    elif "api" in error_str and "key" in error_str:
        error_message = (
            "I'm having trouble connecting to my AI service. "
            "Please notify the administrator."
        )
    else:
        error_message = (
            "Sorry, I encountered an error processing your request. "
            "Please try again."
        )

    try:
        error_result = await gowa_client.send_message(
            phone=reply_jid,
            message=error_message,
            reply_message_id=message_id,
        )
        # Also track error message IDs so user can reply to them
        sent_message_id = error_result.get("message_id")
        if sent_message_id:
            akasha_message_ids[sent_message_id] = time.time()
    except Exception as send_error:
        logger.error(f"Failed to send error message: {send_error}")


async def _send_image_error_response(
    error: Exception,
    reply_jid: str,
    message_id: str,
    akasha_message_ids: dict[str, float],
) -> None:
    """Send a user-friendly error message for image processing errors."""
    error_str = str(error).lower()

    if "download" in error_str or "media" in error_str:
        error_message = (
            "I couldn't download the image. "
            "Please try sending it again."
        )
    elif "503" in str(error) or "unavailable" in error_str or "overload" in error_str:
        error_message = (
            "The AI service is temporarily overloaded. "
            "I tried all available API keys but couldn't connect. "
            "Please try again in a moment."
        )
    elif "429" in str(error) or "quota" in error_str or "rate" in error_str:
        error_message = (
            "I'm currently experiencing high demand. "
            "Please wait a moment and try again."
        )
    elif "exhausted" in error_str or "all api keys" in error_str:
        error_message = (
            "All my API resources are temporarily exhausted. "
            "Please try again in a few minutes."
        )
    else:
        error_message = (
            "Sorry, I couldn't process the image. Please try again."
        )

    try:
        error_result = await gowa_client.send_message(
            phone=reply_jid,
            message=error_message,
            reply_message_id=message_id,
        )
        sent_message_id = error_result.get("message_id")
        if sent_message_id:
            akasha_message_ids[sent_message_id] = time.time()
    except Exception as send_error:
        logger.error(f"Failed to send error message: {send_error}")


async def process_chat_summary_background(
    chat_summarizer_service,
    chat_jid: str,
    message_count: int,
    reply_jid: str,
    message_id: str,
    akasha_message_ids: dict[str, float],
) -> None:
    """
    Process chat summary in background and send response.

    Args:
        chat_summarizer_service: The ChatSummarizerService instance
        chat_jid: JID of the chat to summarize
        message_count: Number of messages to summarize
        reply_jid: JID to send the response to
        message_id: Original message ID (for reply threading)
        akasha_message_ids: Dict to track Akasha's sent messages
    """
    start_time = time.time()

    try:
        # Fetch messages from GoWA
        messages = await gowa_client.get_chat_messages(
            chat_jid=chat_jid,
            limit=message_count,
        )

        if not messages:
            response_text = "I couldn't find any messages to summarize in this chat."
        else:
            # Generate summary
            summary, participants = await chat_summarizer_service.summarize_messages(
                messages
            )

            # Format response
            response_text = f"*Chat Summary* ({len(messages)} messages)\n\n{summary}"
            if participants:
                response_text += f"\n\n*Participants:* {', '.join(sorted(participants))}"

        # Send response
        result = await gowa_client.send_message(
            phone=reply_jid,
            message=response_text,
            reply_message_id=message_id,
        )

        # Track message ID for reply detection
        sent_message_id = result.get("message_id")
        if sent_message_id:
            akasha_message_ids[sent_message_id] = time.time()

        elapsed = time.time() - start_time
        logger.info(
            f"Chat summary sent to {reply_jid} "
            f"({len(messages)} messages, {elapsed:.2f}s)"
        )

    except Exception as e:
        logger.exception(f"Error processing chat summary: {e}")
        await _send_error_response(e, reply_jid, message_id, akasha_message_ids)
