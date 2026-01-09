"""GoWA HTTP client for WhatsApp messaging."""

import logging
from typing import Optional

import httpx
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
    wait_fixed,
)

from src.core.config import settings

logger = logging.getLogger(__name__)


class GowaClientError(Exception):
    """Exception raised when GoWA API call fails."""

    pass


class GowaClient:
    """HTTP client for GoWA WhatsApp service."""

    def __init__(
        self,
        base_url: Optional[str] = None,
        username: Optional[str] = None,
        password: Optional[str] = None,
    ):
        self.base_url = base_url or settings.gowa_base_url
        self.auth = (
            username or settings.gowa_username,
            password or settings.gowa_password,
        )

    def _get_client(self) -> httpx.AsyncClient:
        """Create an async HTTP client with authentication."""
        return httpx.AsyncClient(
            base_url=self.base_url,
            auth=self.auth,
            timeout=30.0,
        )

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        retry=retry_if_exception_type((httpx.HTTPStatusError, httpx.ConnectError)),
    )
    async def send_message(
        self,
        phone: str,
        message: str,
        reply_message_id: Optional[str] = None,
    ) -> dict:
        """
        Send a text message via WhatsApp.

        Args:
            phone: Recipient JID (e.g., "6289685028129@s.whatsapp.net")
            message: Message content
            reply_message_id: Optional message ID to reply to

        Returns:
            Response dict with message_id and status

        Raises:
            GowaClientError: If the message fails to send
        """
        payload = {
            "phone": phone,
            "message": message,
        }
        if reply_message_id:
            payload["reply_message_id"] = reply_message_id

        async with self._get_client() as client:
            response = await client.post("/send/message", json=payload)
            response.raise_for_status()
            data = response.json()

            if data.get("code") != "SUCCESS":
                raise GowaClientError(f"Failed to send message: {data}")

            logger.info(
                f"Message sent successfully to {phone}: {data['results']['message_id']}"
            )
            return data["results"]

    async def check_health(self) -> bool:
        """
        Check if GoWA service is healthy and logged in.

        Returns:
            True if service is healthy, False otherwise
        """
        try:
            async with self._get_client() as client:
                response = await client.get("/app/devices")
                return response.status_code == 200
        except Exception as e:
            logger.error(f"GoWA health check failed: {e}")
            return False

    async def get_devices(self) -> list[dict]:
        """
        Get list of connected devices.

        Returns:
            List of device information dicts
        """
        async with self._get_client() as client:
            response = await client.get("/app/devices")
            response.raise_for_status()
            data = response.json()
            return data.get("results", [])

    @retry(
        stop=stop_after_attempt(2),
        wait=wait_fixed(1),
        retry=retry_if_exception_type((httpx.HTTPStatusError, httpx.ConnectError)),
    )
    async def download_media(self, message_id: str, phone: str) -> tuple[bytes, str]:
        """
        Download media from a message on-demand.

        This is used when WHATSAPP_AUTO_DOWNLOAD_MEDIA=false in GoWA.
        The webhook provides a message ID, and we fetch the media via API.

        Args:
            message_id: The message ID containing media
            phone: The phone/chat JID (e.g., "6289685028129@s.whatsapp.net")

        Returns:
            Tuple of (media_bytes, mime_type)

        Raises:
            GowaClientError: If media download fails or message has no media
        """
        async with self._get_client() as client:
            response = await client.get(
                f"/message/{message_id}/download",
                params={"phone": phone},
            )
            response.raise_for_status()

            # Get MIME type from Content-Type header
            content_type = response.headers.get("Content-Type", "application/octet-stream")
            # Strip any charset or parameters (e.g., "image/jpeg; charset=utf-8" -> "image/jpeg")
            mime_type = content_type.split(";")[0].strip()

            # GoWA returns JSON instead of binary in two cases:
            # 1. Error - no downloadable media
            # 2. Success - media was auto-downloaded to disk, returns file path
            if mime_type == "application/json":
                try:
                    json_data = response.json()
                    message = json_data.get("message", "")

                    # Check if it's a success response with file path
                    # Format: "Media downloaded successfully to statics/media/..."
                    if "downloaded successfully to" in message:
                        # Extract file path from message
                        file_path = message.split("downloaded successfully to ")[-1].strip()
                        logger.info(f"Media was auto-downloaded, fetching from path: {file_path}")
                        # Fetch the file from the static path
                        return await self.download_media_from_path(file_path)

                    # Otherwise it's an error
                    raise GowaClientError(f"No downloadable media: {message}")
                except (ValueError, KeyError) as e:
                    raise GowaClientError(f"No downloadable media in message: {e}")

            logger.info(f"Downloaded media from message {message_id}: {mime_type}, {len(response.content)} bytes")
            return response.content, mime_type

    @retry(
        stop=stop_after_attempt(2),
        wait=wait_fixed(1),
        retry=retry_if_exception_type((httpx.HTTPStatusError, httpx.ConnectError)),
    )
    async def download_media_from_path(self, file_path: str) -> tuple[bytes, str]:
        """
        Download media from a static file path (when auto-download is enabled).

        When GoWA auto-downloads media, the webhook includes a file_path.
        This method fetches the file from GoWA's static file server.

        Args:
            file_path: The file path from webhook (e.g., "statics/media/...")

        Returns:
            Tuple of (media_bytes, mime_type)

        Raises:
            GowaClientError: If media download fails
        """
        async with self._get_client() as client:
            # GoWA serves static files at the root path
            response = await client.get(f"/{file_path}")
            response.raise_for_status()

            content_type = response.headers.get("Content-Type", "application/octet-stream")
            mime_type = content_type.split(";")[0].strip()

            if mime_type == "application/json":
                raise GowaClientError(f"Failed to download media from path: {file_path}")

            logger.info(f"Downloaded media from path {file_path}: {mime_type}, {len(response.content)} bytes")
            return response.content, mime_type

    @retry(
        stop=stop_after_attempt(2),
        wait=wait_fixed(1),
        retry=retry_if_exception_type((httpx.HTTPStatusError, httpx.ConnectError)),
    )
    async def get_chat_messages(
        self, chat_jid: str, limit: int = 50
    ) -> list[dict]:
        """
        Fetch message history from a specific chat.

        Args:
            chat_jid: The chat JID (individual or group)
            limit: Maximum number of messages to fetch

        Returns:
            List of message dicts with sender, text, timestamp

        Raises:
            GowaClientError: If fetch fails
        """
        async with self._get_client() as client:
            response = await client.get(
                f"/chat/{chat_jid}/messages",
                params={"limit": limit},
            )
            response.raise_for_status()
            data = response.json()

            if data.get("code") != "SUCCESS":
                raise GowaClientError(f"Failed to fetch messages: {data}")

            messages = data.get("results", [])
            logger.info(f"Fetched {len(messages)} messages from {chat_jid}")
            return messages


# Singleton instance for dependency injection
gowa_client = GowaClient()
