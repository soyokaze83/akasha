# Akasha - Claude Code Context

## Project Overview

Multi-service WhatsApp automation platform built with FastAPI, integrating with [GoWA](https://github.com/aldinokemal/go-whatsapp-web-multidevice) (go-whatsapp-web-multidevice). Provides AI-powered services including Mandarin passage generation, conversational AI assistant, and chat summarization.

## Tech Stack

- **Framework**: FastAPI (async Python web framework)
- **Package Manager**: uv
- **Python Version**: 3.10+
- **LLM Providers**: Google Gemini (primary), OpenRouter (fallback)
- **Vector Store**: Qdrant (topic deduplication)
- **Scheduler**: APScheduler (daily tasks)
- **WhatsApp Integration**: GoWA (Docker container)

## Project Structure

```
src/
├── main.py                    # FastAPI entry point, webhook handling
├── core/                      # Shared infrastructure
│   ├── config.py              # Pydantic Settings (loads from .env)
│   ├── logging.py             # Structured logging setup
│   ├── scheduler.py           # APScheduler configuration
│   ├── rate_limiter.py        # Per-sender sliding window rate limiting
│   ├── vector_store.py        # Qdrant client for topic embeddings
│   ├── background_tasks.py    # Async webhook processing
│   └── gowa/                  # WhatsApp client
│       ├── client.py          # GoWA API wrapper with retry logic
│       └── models.py          # GoWA webhook payload models
├── llm/                       # LLM provider abstraction
│   ├── base.py                # LLMClient Protocol + factory
│   ├── gemini.py              # Gemini client (multimodal + key rotation)
│   ├── openai.py              # OpenAI client (multimodal)
│   ├── openrouter.py          # OpenRouter fallback (text-only)
│   └── key_rotator.py         # API key rotation for rate limits
├── utils/                     # Utility modules
│   └── web_scraper.py         # Web scraping utilities
└── services/                  # Business logic modules
    ├── mandarin_generator/    # Daily Mandarin passage service
    │   ├── service.py         # Passage generation logic
    │   ├── router.py          # API endpoints
    │   ├── models.py          # Pydantic models
    │   └── tasks.py           # Scheduled daily task
    ├── reply_agent/           # AI-powered WhatsApp replies
    │   ├── service.py         # Query processing with tool orchestration
    │   ├── router.py          # API endpoints
    │   ├── models.py          # Pydantic models
    │   └── tools.py           # Web search tool
    └── chat_summarizer/       # Chat history summarization
        ├── service.py         # Summarization logic
        ├── router.py          # API endpoints
        └── models.py          # Pydantic models
```

## Key Patterns

### 1. Service Module Structure
Each service follows this pattern:
- `service.py`: Core business logic as a class with singleton instance
- `router.py`: FastAPI APIRouter with endpoints (prefix = /service-name)
- `models.py`: Pydantic models for request/response
- `tasks.py`: (optional) Scheduled tasks for APScheduler

```python
# Singleton pattern in service.py
class MyService:
    def my_method(self): ...

my_service = MyService()  # Module-level singleton
```

### 2. Configuration
All configuration uses Pydantic Settings from `src/core/config.py`:
```python
from src.core.config import settings

api_key = settings.gemini_api_key
recipients = settings.recipients_list  # Parsed from comma-separated
```

### 3. LLM Provider Abstraction
Use the abstraction layer, not direct clients:
```python
from src.llm import get_configured_llm

llm_client = get_configured_llm()

# Text-only generation
response = await llm_client.generate_content(
    prompt="...",
    system_instruction="...",
    temperature=0.8,
)

# Multimodal generation with image (Gemini/OpenAI only, ignored by OpenRouter)
response = await llm_client.generate_content(
    prompt="What is in this image?",
    image_data=image_bytes,           # Optional: bytes
    image_mime_type="image/jpeg",     # Optional: MIME type
)
```

### 4. Background Task Pattern
Long-running webhook handlers use background tasks:
```python
import asyncio
asyncio.create_task(process_in_background(...))
return {"status": "ok"}  # Return immediately
```

### 5. Error Handling with Fallback
LLM calls include automatic fallback on 429/503 errors:
- Primary: Gemini with key rotation (supports multimodal/vision)
- Fallback: OpenRouter (text-only, image data ignored with warning)

## Development Commands

```bash
# Install dependencies
uv sync

# Run locally (requires GoWA running separately)
uv run uvicorn src.main:app --reload --port 8080

# Run tests
uv run pytest
uv run pytest -v  # Verbose

# Docker operations
docker-compose up -d              # Start all services
docker-compose logs -f akasha     # View Akasha logs
docker-compose logs -f whatsapp   # View GoWA logs
```

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | `/` | Service info |
| GET | `/health` | Health check (GoWA + scheduler) |
| POST | `/webhook` | GoWA webhook handler |
| POST | `/mandarin/generate` | Generate and send passage |
| POST | `/mandarin/trigger-daily` | Trigger daily job manually |
| POST | `/reply-agent/query` | Process AI query |
| GET | `/reply-agent/status` | Reply Agent configuration |
| POST | `/chat-summarizer/summarize` | Summarize chat messages |
| GET | `/chat-summarizer/status` | Chat Summarizer configuration |

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `APP_NAME` | `akasha` | Application name |
| `DEBUG` | `false` | Enable debug mode |
| `LOG_LEVEL` | `INFO` | Logging level |
| `LLM_PROVIDER` | `gemini` | Primary LLM: `gemini` or `openai` |
| `LLM_FALLBACK_ENABLED` | `true` | Enable fallback on errors |
| `GEMINI_API_KEY` | - | Comma-separated for rotation |
| `GEMINI_MODEL` | `gemini-2.0-flash` | Gemini model |
| `GEMINI_EMBEDDING_MODEL` | `gemini-embedding-001` | Gemini embedding model for topic dedup |
| `OPENAI_API_KEY` | - | OpenAI API key |
| `OPENAI_MODEL` | `gpt-4o-mini` | OpenAI model |
| `OPENROUTER_API_KEY` | - | Fallback provider |
| `OPENROUTER_MODEL` | `xiaomi/mimo-v2-flash:free` | Fallback model |
| `WHATSAPP_RECIPIENTS` | - | Comma-separated JIDs |
| `TOPIC_SELECTION_MODE` | `free` | `free` or `web_search` |
| `DAILY_PASSAGE_HOUR` | `7` | Hour to send (0-23) |
| `DAILY_PASSAGE_MINUTE` | `0` | Minute to send |
| `TIMEZONE` | `Asia/Jakarta` | Scheduler timezone |
| `RATE_LIMIT_REQUESTS` | `10` | Max per sender per window |
| `RATE_LIMIT_WINDOW_SECONDS` | `60` | Window size |
| `MAX_CONCURRENT_SENDS` | `5` | Parallel send limit |
| `GOWA_BASE_URL` | `http://whatsapp:3000` | GoWA service URL |
| `GOWA_USERNAME` | `user1` | GoWA auth |
| `GOWA_PASSWORD` | `pass1` | GoWA auth |
| `GOWA_WEBHOOK_SECRET` | `your-secret-key` | Webhook signature verification |
| `GOOGLE_SEARCH_API_KEY` | - | For Reply Agent web search |
| `GOOGLE_SEARCH_ENGINE_ID` | - | For Reply Agent web search |
| `REPLY_AGENT_ENABLED` | `true` | Enable Reply Agent |
| `CHAT_SUMMARIZER_ENABLED` | `true` | Enable Chat Summarizer |
| `CHAT_SUMMARIZER_MAX_MESSAGES` | `200` | Max messages to summarize |
| `QDRANT_URL` | `http://qdrant:6333` | Vector store URL |
| `TOPIC_SIMILARITY_THRESHOLD` | `0.85` | Similarity threshold for topic dedup |

## WhatsApp JID Formats

- **Individual**: `{country}{phone}@s.whatsapp.net` (e.g., `6281234567890@s.whatsapp.net`)
- **Group**: `{group_id}@g.us` (e.g., `120363024512399999@g.us`)

## Key Files to Understand

1. [main.py](src/main.py) - Entry point, webhook routing logic
2. [config.py](src/core/config.py) - All configuration options
3. [llm/base.py](src/llm/base.py) - LLMClient Protocol with multimodal support
4. [reply_agent/service.py](src/services/reply_agent/service.py) - Complex LLM orchestration with tool calling
5. [gowa/client.py](src/core/gowa/client.py) - WhatsApp API wrapper
6. [docs/GOWA_INTEGRATION.md](docs/GOWA_INTEGRATION.md) - GoWA API reference
