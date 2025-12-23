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
| `message.image` | Image received | `image_path`, `mime_type`, `caption` |
| `message.video` | Video received | `video_path`, `mime_type` |
| `message.audio` | Audio received | `audio_path`, `mime_type` |
| `message.document` | Document received | `document_path`, `filename` |
| `message.reaction` | Reaction to message | `reaction`, `message_id_reacted` |
| `message.revoked` | Message deleted | `message_id` |
| `group.participants` | Group membership change | `action`, `participants` |

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

router = APIRouter()

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

    # Process based on event type
    if payload.get("type") == "message.text":
        print(f"Message from {payload['pushname']}: {payload['message']['text']}")

    return {"status": "ok"}
```

---

## References

- **GitHub**: https://github.com/aldinokemal/go-whatsapp-web-multidevice
- **API Docs**: https://bump.sh/aldinokemal/doc/go-whatsapp-web-multidevice/
- **Docker Hub**: https://hub.docker.com/r/aldinokemal2104/go-whatsapp-web-multidevice
