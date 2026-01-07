# GoWA Integration Guide

This document serves as a knowledge base for Claude and developers working on the Akasha project. It documents the GoWA (go-whatsapp-web-multidevice) service integration.

## Project Overview

**Akasha** is a modular FastAPI platform that integrates with WhatsApp via GoWA. Each service (e.g., Mandarin Generator, Chat Summarizer) lives in its own directory under `src/services/`.

### Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                     Akasha (FastAPI)                        │
│  ┌─────────────────┐  ┌─────────────────┐  ┌────────────┐  │
│  │ Mandarin Gen.   │  │ Chat Summarizer │  │ Future...  │  │
│  │ /mandarin/*     │  │ /summarize/*    │  │            │  │
│  └────────┬────────┘  └────────┬────────┘  └─────┬──────┘  │
│           │                    │                 │          │
│  ┌────────┴────────────────────┴─────────────────┴──────┐  │
│  │              Shared Core (src/core/)                 │  │
│  │  • GoWA Client  • Config  • Logging  • Scheduler     │  │
│  └──────────────────────────┬───────────────────────────┘  │
└─────────────────────────────┼───────────────────────────────┘
                              │ HTTP (port 3000)
                              ▼
┌─────────────────────────────────────────────────────────────┐
│                  GoWA Service (Docker)                      │
│         aldinokemal2104/go-whatsapp-web-multidevice         │
│                                                             │
│  • REST API with Basic Auth                                 │
│  • WhatsApp Web Protocol                                    │
│  • Webhook callbacks to Akasha                              │
└─────────────────────────────────────────────────────────────┘
```

---

## GoWA Service Summary

**GoWA** (go-whatsapp-web-multidevice) is a Go-based WhatsApp automation tool that provides:
- REST API for programmatic WhatsApp interaction
- Web UI for manual operations
- Webhook support for incoming message notifications
- Multi-device support with QR code authentication

### Docker Image

```yaml
image: aldinokemal2104/go-whatsapp-web-multidevice
```

### Default Configuration

| Setting | Value |
|---------|-------|
| Port | 3000 |
| Auth | Basic Auth (username:password) |
| Database | SQLite at `/app/storages/whatsapp.db` |

---

## Key API Endpoints

All endpoints require Basic Authentication header:
```
Authorization: Basic base64(username:password)
```

### Authentication & Device Management

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/app/login` | Get QR code image for device pairing |
| GET | `/app/login-with-code?phone_number={number}` | Get pairing code (alternative to QR) |
| GET | `/app/devices` | List all connected devices |
| GET | `/app/reconnect` | Reconnect to WhatsApp servers |
| GET | `/app/logout` | Logout and clear session |

### Sending Messages

**Send Text Message**
```http
POST /send/message
Content-Type: application/json

{
  "phone": "6289685028129@s.whatsapp.net",
  "message": "Hello from Akasha!",
  "reply_message_id": "optional_message_id"
}
```

**Response:**
```json
{
  "code": "SUCCESS",
  "message": "Success",
  "results": {
    "message_id": "3EB0B430B6F8F1D0E053AC120E0A9E5C",
    "status": "success"
  }
}
```

**Send Image**
```http
POST /send/image
Content-Type: multipart/form-data

phone: 6289685028129@s.whatsapp.net
caption: Optional caption
image: <binary file> OR image_url: https://example.com/image.jpg
compress: true
view_once: false
```

**Send File/Document**
```http
POST /send/file
Content-Type: multipart/form-data

phone: 6289685028129@s.whatsapp.net
file: <binary file>
caption: Optional caption
```

### Media Operations

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/message/{message_id}/download` | Download media from a message on-demand |

**Download Media Example:**
```http
GET /message/3EB0C127D7BACC83D6A3/download?phone=6289685028129@s.whatsapp.net
```

**Response:** Binary media content with `Content-Type` header indicating MIME type.

> **Note:** This endpoint is used when `WHATSAPP_AUTO_DOWNLOAD_MEDIA=false` is set. The webhook provides the message ID, and media is fetched on-demand.

### Chat Operations

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/chats` | List all conversations (paginated) |
| GET | `/chat/{chat_jid}/messages` | Get messages from specific chat |

**Get Chat Messages Example:**
```http
GET /chat/6289685028129@s.whatsapp.net/messages?limit=50
```

### Group Management

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/group` | Create new group |
| GET | `/user/my/groups` | List user's groups |
| GET | `/group/participants?group_id={id}` | Get group participants |
| POST | `/group/participants` | Add participants to group |

---

## Phone Number Formats (JID)

WhatsApp uses JID (Jabber ID) format for identifying chats:

### Individual Chats
```
{country_code}{phone_number}@s.whatsapp.net
```
Examples:
- Indonesia: `6289685028129@s.whatsapp.net`
- USA: `14155552671@s.whatsapp.net`

### Group Chats
```
{group_id}@g.us
```
Example: `120363024512399999@g.us`

### How to Get Group JID
1. Call `GET /user/my/groups` to list all groups
2. Find the group and use the `id` field

---

## Webhook Integration

GoWA can send HTTP callbacks to your application when events occur.

### Configuration

In docker-compose.yml:
```yaml
environment:
  - WHATSAPP_WEBHOOK=http://akasha:8080/webhook
  - WHATSAPP_WEBHOOK_SECRET=your-secret-key
```

### Webhook Payload Structure

Every webhook includes these common fields:
```json
{
  "sender_id": "6289685028129",
  "chat_id": "6289685028129",
  "from": "6289685028129@s.whatsapp.net",
  "timestamp": "2025-12-23T10:30:00Z",
  "pushname": "John Doe",
  "type": "message.text",
  ...event-specific fields
}
```

### Event Types

| Type | Description | Additional Fields |
|------|-------------|-------------------|
| `message.text` | Text message received | `message`, `message_id`, `from_me` |
| `message.image` | Image received | `image` (object), `id`, `caption` |
| `message.video` | Video received | `video_path`, `mime_type` |
| `message.audio` | Audio received | `audio_path`, `mime_type` |
| `message.document` | Document received | `document_path`, `filename` |
| `message.reaction` | Reaction to message | `reaction`, `message_id_reacted` |
| `message.revoked` | Message deleted | `message_id` |
| `group.participants` | Group membership change | `action`, `participants` |

### Image Message Webhook (Auto-Download Disabled)

When `WHATSAPP_AUTO_DOWNLOAD_MEDIA=false` is set, image messages arrive with metadata only (no file path). The image must be downloaded on-demand via the `/message/{id}/download` API.

**Webhook Payload:**
```json
{
  "id": "3EB0C127D7BACC83D6A3",
  "chat_id": "6289685028129@s.whatsapp.net",
  "from": "6289685028129@s.whatsapp.net",
  "pushname": "John Doe",
  "image": {
    "url": "https://mmg.whatsapp.net/...",
    "caption": "hey akasha, what is this?",
    "mime_type": "image/jpeg"
  }
}
```

**Processing Flow:**
1. Receive webhook with `image` object (not a file path string)
2. Extract `id` from payload for download
3. Call `GET /message/{id}/download?phone={chat_id}` to fetch binary data
4. Process image with LLM or other service
5. No permanent storage required

### Signature Verification

Webhooks include HMAC-SHA256 signature in header:
```
X-Hub-Signature-256: sha256=<signature>
```

**Python Verification:**
```python
import hmac
import hashlib

def verify_webhook(payload: bytes, signature: str, secret: str) -> bool:
    expected = hmac.new(
        secret.encode(),
        payload,
        hashlib.sha256
    ).hexdigest()
    return hmac.compare_digest(signature.replace("sha256=", ""), expected)
```

---

## Authentication Flow

### Step 1: Start Services
```bash
docker-compose up -d
```

### Step 2: Get QR Code
Open browser to `http://localhost:3000/app/login`

### Step 3: Scan QR Code
1. Open WhatsApp on your phone
2. Go to Settings > Linked Devices > Link a Device
3. Scan the QR code

### Step 4: Verify Connection
```bash
curl -u user1:pass1 http://localhost:3000/app/devices
```

### Session Persistence
- Session data stored in Docker volume `whatsapp_data`
- Persists across container restarts
- No need to re-scan QR after restart

---

## Important Notes

### WhatsApp Web Protocol
- GoWA uses WhatsApp Web protocol (not official WhatsApp Business API)
- Works with personal WhatsApp accounts
- Also compatible with WhatsApp Business app

### Session Maintenance
- Primary phone must come online **every 14 days** to keep linked devices active
- If session expires, you'll need to re-scan QR code

### Rate Limiting
- WhatsApp enforces rate limits on message sending
- No documented limits in GoWA itself
- Recommended: Add delays between bulk messages

### Webhook Timeout for Image Processing
- **Default timeout**: 10 seconds (insufficient for images)
- **Recommended**: 60 seconds minimum
- **Reason**: LLM vision analysis typically takes 15-30+ seconds
- **Configuration**: Set `WHATSAPP_WEBHOOK_TIMEOUT=60` in docker-compose.yml
- **Impact**: Without sufficient timeout, GoWA will resend duplicate webhooks, causing duplicate processing attempts

### Duplicate Webhook Handling
- GoWA retries webhooks on timeout
- Always mark messages as processed **immediately** after ID extraction
- Use in-memory cache to skip duplicate processing
- Example: `processed_messages[message_id] = time.time()`

### Terms of Service
- Automated messaging via WhatsApp Web may violate WhatsApp's ToS
- Use with awareness of potential account restrictions
- Consider using official WhatsApp Business API for production

### Error Handling
Common error responses:
```json
{
  "code": "ERROR",
  "message": "you are not logged in",
  "results": null
}
```

Solution: Re-authenticate via `/app/login`

---

## Code Examples

### Send Message (Python)

```python
import httpx

async def send_whatsapp_message(phone: str, message: str):
    async with httpx.AsyncClient() as client:
        response = await client.post(
            "http://localhost:3000/send/message",
            auth=("user1", "pass1"),
            json={"phone": phone, "message": message},
            timeout=30.0
        )
        response.raise_for_status()
        data = response.json()

        if data["code"] != "SUCCESS":
            raise Exception(f"Failed: {data['message']}")

        return data["results"]["message_id"]
```

### Handle Webhook (FastAPI)

```python
from fastapi import APIRouter, Request, HTTPException
import hmac
import hashlib
import time

router = APIRouter()

# In-memory cache to prevent duplicate processing
processed_messages: dict[str, float] = {}

@router.post("/webhook")
async def handle_webhook(request: Request):
    body = await request.body()
    signature = request.headers.get("X-Hub-Signature-256", "")

    # Verify signature
    secret = "your-secret-key"
    expected = "sha256=" + hmac.new(
        secret.encode(), body, hashlib.sha256
    ).hexdigest()

    if not hmac.compare_digest(signature, expected):
        raise HTTPException(401, "Invalid signature")

    payload = await request.json()

    # Unified message ID extraction - check both locations
    # Media messages have ID at top level, text messages inside message object
    image_info = payload.get("image")
    video_info = payload.get("video")
    audio_info = payload.get("audio")
    is_media_message = any([isinstance(image_info, dict), 
                           isinstance(video_info, dict), 
                           isinstance(audio_info, dict)])
    
    if is_media_message:
        message_id = payload.get("id") or payload.get("message", {}).get("id", "")
    else:
        message_id = payload.get("message", {}).get("id", "")

    # Skip duplicates immediately after ID extraction
    if message_id and message_id in processed_messages:
        logger.debug(f"Skipping already processed message: {message_id}")
        return {"status": "ok"}

    # Mark as processed to prevent retry duplicates
    if message_id:
        processed_messages[message_id] = time.time()

    # Process based on event type
    if payload.get("type") == "message.text":
        message_text = payload.get("message", {}).get("text", "")
        logger.info(f"Message from {payload['pushname']}: {message_text}")
    elif payload.get("image"):
        logger.info(f"Image received from {payload['pushname']}")

    return {"status": "ok"}
```

### Download Media On-Demand (Python)

```python
import httpx

async def download_media(message_id: str, phone: str) -> tuple[bytes, str]:
    """
    Download media from a message on-demand.

    Args:
        message_id: The message ID containing media
        phone: The phone/chat JID

    Returns:
        Tuple of (media_bytes, mime_type)
    """
    async with httpx.AsyncClient() as client:
        response = await client.get(
            f"http://localhost:3000/message/{message_id}/download",
            params={"phone": phone},
            auth=("user1", "pass1"),
            timeout=60.0,  # 60s timeout for large files/slow connections
        )
        response.raise_for_status()

        mime_type = response.headers.get("Content-Type", "application/octet-stream")
        return response.content, mime_type

# Usage in webhook handler
async def handle_image_webhook(payload: dict):
    image_info = payload.get("image")
    if isinstance(image_info, dict):
        message_id = payload.get("id")
        chat_id = payload.get("chat_id")
        caption = image_info.get("caption", "")

        # Download image on-demand
        image_bytes, mime_type = await download_media(message_id, chat_id)

        # Process with your service (e.g., LLM vision)
        print(f"Downloaded {len(image_bytes)} bytes of {mime_type}")
```

---

## Troubleshooting

### Image Not Responding

**Symptoms:**
- Image sent with caption "hey akasha, ..." receives no response
- Logs show webhook received but no LLM processing
- Duplicate webhook messages appearing in logs

**Common Causes:**

1. **Message ID extraction failed**
   - Logs show: `message_id=` (empty string)
   - Cause: Payload structure mismatch, ID in unexpected location

2. **Webhook timeout before LLM completes**
   - Logs show: `context deadline exceeded` or GoWA retry attempts
   - Cause: Default 10s timeout insufficient for image processing

3. **Duplicate webhook processing**
   - Logs show: Multiple webhooks with same message_id
   - Cause: Message not marked processed immediately after extraction

**Solutions:**

1. Verify webhook timeout configuration:
   ```yaml
   # docker-compose.yml
   environment:
     - WHATSAPP_WEBHOOK_TIMEOUT=60  # Minimum 60s for images
   ```

2. Check for successful message ID extraction:
   - Look for: `Found message_id in message object for media message`
   - Or: `Found message_id at top level for media message`
   - If missing, payload structure needs investigation

3. Ensure immediate message marking:
   - Messages should be marked processed immediately after ID extraction
   - Look for: `Marked message {message_id} as processed`
   - This prevents duplicate processing on webhook retries

4. Verify LLM API timeouts:
   - OpenAI: `timeout=45.0` in chat.completions.create()
   - Gemini: Set appropriate timeout in generate_content()

**Expected Logging Patterns:**

When image processing works correctly, you should see these log entries in order:

1. Message ID extraction:
   ```
   Found message_id in message object for media message
   ```
   OR
   ```
   Found message_id at top level for media message
   ```

2. Trigger detection:
   ```
   Reply Agent (image) triggered by {sender}: query='...', 
   message_id=3EB0B14F97D0CD32235B0C, 
   from_jid=6289608842518:40@s.whatsapp.net in 6289608842518@s.whatsapp.net, 
   caption=hey akasha, what is this...
   ```

3. Download attempt:
   ```
   Attempting image download via API: message_id=3EB0B14F97D0CD32235B0C, 
   phone=6289608842518@s.whatsapp.net
   ```

4. Download success:
   ```
   Image downloaded successfully: image/jpeg, 41291 bytes
   ```

5. LLM processing:
   ```
   Gemini processing multimodal query with image (image/jpeg)
   ```
   OR
   ```
   OpenAI processing multimodal query with image (image/jpeg)
   ```

6. Response sent:
   ```
   Reply Agent (image) response sent to 6289608842518@s.whatsapp.net 
   (total processing time: 16.23s)
   ```

**Diagnosis Checklist:**

If images aren't responding, verify the following logs appear:

- [ ] Message ID found (not empty)
- [ ] Trigger detected (not skipping due to duplicate)
- [ ] Download attempted (not failing at API call)
- [ ] Download successful (not media download error)
- [ ] LLM processing started (not hanging)
- [ ] Response sent (not error thrown)
- [ ] Total time under 60s (not webhook timeout)

---

## References

- **GitHub**: https://github.com/aldinokemal/go-whatsapp-web-multidevice
- **API Docs**: https://bump.sh/aldinokemal/doc/go-whatsapp-web-multidevice/
- **Docker Hub**: https://hub.docker.com/r/aldinokemal2104/go-whatsapp-web-multidevice
