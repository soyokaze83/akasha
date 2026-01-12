"""Chat summarization service."""

import logging
import re
from typing import Optional

from src.core.config import settings
from src.core.gowa import gowa_client
from src.llm import get_configured_llm

logger = logging.getLogger(__name__)


class ChatSummarizerService:
    """Service for summarizing WhatsApp chat history."""

    # Case-insensitive trigger pattern
    # Matches: "akasha, summarize the previous 50 messages"
    # Also allows trailing whitespace and punctuation (.!?)
    TRIGGER_PATTERN = re.compile(
        r"^akasha,\s*summarize\s+the\s+previous\s+(\d+)\s+messages?\s*[.!?]*\s*$",
        re.IGNORECASE,
    )

    def should_trigger(self, message: str) -> bool:
        """Check if message matches the summarize command."""
        return bool(self.TRIGGER_PATTERN.match(message.strip()))

    def extract_message_count(self, message: str) -> Optional[int]:
        """Extract the requested number of messages from command."""
        match = self.TRIGGER_PATTERN.match(message.strip())
        if match:
            count = int(match.group(1))
            # Enforce maximum limit
            return min(count, settings.chat_summarizer_max_messages)
        return None

    async def _resolve_display_name(
        self,
        sender_jid: str,
        name_cache: dict[str, str],
    ) -> str:
        """
        Resolve a JID to a display name, using cache to avoid redundant API calls.

        Args:
            sender_jid: The sender's JID
            name_cache: Cache dict mapping JID -> display name

        Returns:
            Display name or phone number as fallback
        """
        if sender_jid in name_cache:
            return name_cache[sender_jid]

        # Extract phone number as fallback (also strip device ID if present)
        phone_number = sender_jid.split("@")[0].split(":")[0] if sender_jid else "Unknown"

        try:
            # Normalize JID (remove device ID if present)
            normalized_jid = phone_number + "@s.whatsapp.net"
            user_info = await gowa_client.get_user_info(normalized_jid)
            display_name = user_info.get("verified_name") or phone_number
            name_cache[sender_jid] = display_name
            return display_name
        except Exception as e:
            logger.debug(f"Could not resolve name for {sender_jid}: {e}")
            name_cache[sender_jid] = phone_number
            return phone_number

    async def summarize_messages(
        self,
        messages: list[dict],
    ) -> tuple[str, list[str]]:
        """
        Generate summary of chat messages.

        Args:
            messages: List of message dicts from GoWA

        Returns:
            Tuple of (summary_text, list_of_participants)
        """
        if not messages:
            return "No messages to summarize.", []

        # Cache for name lookups to avoid redundant API calls
        name_cache: dict[str, str] = {}

        # Extract participants and format messages
        participants = set()
        formatted_messages = []

        for msg in messages:
            sender_jid = msg.get("sender_jid", "")
            text = msg.get("content", "")

            if text:  # Only include text messages
                # Resolve display name (uses cache)
                sender_name = await self._resolve_display_name(sender_jid, name_cache)
                participants.add(sender_name)
                formatted_messages.append(f"[{sender_name}]: {text}")

        if not formatted_messages:
            return "No text messages found to summarize.", []

        # Build prompt for LLM
        messages_text = "\n".join(formatted_messages)

        prompt = f"""Summarize the following chat conversation. Include who said what and the main topics discussed.

Chat messages:
{messages_text}

Requirements:
- Write the summary in the same language as the messages
- Mention key participants and their contributions
- Highlight main topics and any decisions or conclusions
- Keep it concise but comprehensive
- Format as a readable summary paragraph or bullet points"""

        system_instruction = """You are a helpful assistant that summarizes chat conversations.
Your summaries should:
- Be in the same language as the original messages
- Attribute statements to specific participants
- Capture the essence of the discussion
- Be neutral and factual"""

        llm_client = get_configured_llm()
        summary = await llm_client.generate_content(
            prompt=prompt,
            system_instruction=system_instruction,
            temperature=0.3,  # Lower temperature for factual summarization
        )

        return summary.strip(), list(participants)


# Singleton instance
chat_summarizer = ChatSummarizerService()
