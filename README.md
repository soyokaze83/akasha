# Akasha

A multi-service WhatsApp platform built with FastAPI that integrates with [GoWA](https://github.com/aldinokemal/go-whatsapp-web-multidevice) (go-whatsapp-web-multidevice).

Mostly for my personal needs but feel free to setup for personal usage as well.

## Services

### Mandarin Generator
Daily HSK 3-4 level Mandarin reading passages sent automatically via WhatsApp. Perfect for language learners practicing with friends.

- Generates 150-250 character passages using LLMs (Gemini or OpenAI)
- Hanzi only format (no pinyin, no English)
- Automatic daily scheduling with configurable time
- Manual trigger via API

### Reply Agent
AI-powered WhatsApp assistant that responds to messages with web search capabilities.

- Trigger with "hey akasha, <your question>" in any chat
- Reply directly to Akasha's messages without trigger phrase to continue conversation
- Web search integration for current information
- Automatic LLM provider fallback (Gemini ↔ OpenAI) on rate limits
- Supports multiple rotating API keys for high availability

### Chat Summarizer (Coming Soon)
Summarize WhatsApp chat history using LLMs.

## Quick Start

### Prerequisites

- Docker and Docker Compose
- LLM API key (choose one):
  - Google Gemini API key ([Get one here](https://makersuite.google.com/app/apikey))
  - OpenAI API key ([Get one here](https://platform.openai.com/api-keys))
- WhatsApp account (personal or business)

### Setup

1. **Clone and configure**
   ```bash
   cd akasha
   cp .env.example .env
   ```

2. **Edit `.env` with your values**
   ```bash
   # LLM Provider - choose "gemini" or "openai"
   LLM_PROVIDER=openai

   # If using Gemini
   GEMINI_API_KEY=your-gemini-api-key

   # If using OpenAI
   OPENAI_API_KEY=sk-your-openai-api-key
   OPENAI_MODEL=gpt-4o-mini

   # Required
   WHATSAPP_RECIPIENTS=6281234567890@s.whatsapp.net

   # Optional - adjust schedule
   DAILY_PASSAGE_HOUR=7
   DAILY_PASSAGE_MINUTE=0
   TIMEZONE=Asia/Jakarta
   ```

3. **Start services**
   ```bash
   docker-compose up -d
   ```

4. **Link WhatsApp account**
   - Open http://localhost:3000/app/login in your browser
   - Scan the QR code with WhatsApp mobile app
   - Go to Settings > Linked Devices > Link a Device

5. **Verify setup**
   ```bash
   # Check health
   curl http://localhost:8080/health

   # Test by triggering a passage manually
   curl -X POST http://localhost:8080/mandarin/trigger-daily
   ```

## Environment Variables

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `LLM_PROVIDER` | No | `gemini` | LLM provider: `gemini` or `openai` |
| `LLM_FALLBACK_ENABLED` | No | `true` | Enable fallback to other provider on errors |
| `GEMINI_API_KEY` | If using Gemini | - | Gemini API key (comma-separated for rotation) |
| `GEMINI_MODEL` | No | `gemini-2.0-flash` | Gemini model to use |
| `OPENAI_API_KEY` | If using OpenAI | - | OpenAI API key |
| `OPENAI_MODEL` | No | `gpt-4o-mini` | OpenAI model to use |
| `REPLY_AGENT_ENABLED` | No | `true` | Enable/disable the Reply Agent |
| `GOOGLE_SEARCH_API_KEY` | For Reply Agent | - | Google Custom Search API key |
| `GOOGLE_SEARCH_ENGINE_ID` | For Reply Agent | - | Google Custom Search Engine ID |
| `WHATSAPP_RECIPIENTS` | Yes | - | Comma-separated recipient JIDs |
| `DAILY_PASSAGE_HOUR` | No | `7` | Hour to send (0-23) |
| `DAILY_PASSAGE_MINUTE` | No | `0` | Minute to send (0-59) |
| `TIMEZONE` | No | `Asia/Jakarta` | Scheduler timezone |
| `GOWA_BASE_URL` | No | `http://whatsapp:3000` | GoWA service URL |
| `GOWA_USERNAME` | No | `user1` | GoWA basic auth username |
| `GOWA_PASSWORD` | No | `pass1` | GoWA basic auth password |
| `LOG_LEVEL` | No | `INFO` | Logging level |

## WhatsApp JID Formats

- **Individual**: `{country_code}{phone}@s.whatsapp.net`
  - Example: `6281234567890@s.whatsapp.net` (Indonesia)

- **Group**: `{group_id}@g.us`
  - Example: `120363024512399999@g.us`
  - To find group JID: `curl -u user1:pass1 http://localhost:3000/user/my/groups`

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | `/` | Service info |
| GET | `/health` | Health check (GoWA + scheduler) |
| POST | `/webhook` | GoWA webhook handler |
| POST | `/mandarin/generate` | Generate and send passage |
| POST | `/mandarin/trigger-daily` | Trigger daily job manually |
| POST | `/reply-agent/query` | Process a query with the Reply Agent |
| GET | `/reply-agent/status` | Get Reply Agent configuration status |

### Generate Passage

```bash
# Generate and send to all configured recipients
curl -X POST http://localhost:8080/mandarin/generate

# Generate with specific topic
curl -X POST http://localhost:8080/mandarin/generate \
  -H "Content-Type: application/json" \
  -d '{"topic": "旅游和交通"}'

# Send to specific recipient
curl -X POST http://localhost:8080/mandarin/generate \
  -H "Content-Type: application/json" \
  -d '{"recipient": "6281234567890@s.whatsapp.net"}'
```

### Reply Agent Query

```bash
# Simple query (response returned but not sent via WhatsApp)
curl -X POST http://localhost:8080/reply-agent/query \
  -H "Content-Type: application/json" \
  -d '{"query": "What is the capital of France?"}'

# Query with quoted context (simulating a reply to a message)
curl -X POST http://localhost:8080/reply-agent/query \
  -H "Content-Type: application/json" \
  -d '{"query": "Can you explain this?", "quoted_context": "The mitochondria is the powerhouse of the cell."}'

# Query and send response to WhatsApp
curl -X POST http://localhost:8080/reply-agent/query \
  -H "Content-Type: application/json" \
  -d '{"query": "What time is it in Tokyo?", "recipient": "6281234567890@s.whatsapp.net"}'

# Check Reply Agent status
curl http://localhost:8080/reply-agent/status
```

## Project Structure

```
akasha/
├── docs/
│   └── GOWA_INTEGRATION.md      # GoWA knowledge base
├── src/
│   ├── main.py                   # FastAPI entry point
│   ├── core/                     # Shared utilities
│   │   ├── config.py             # Pydantic settings
│   │   ├── logging.py            # Logging setup
│   │   ├── scheduler.py          # APScheduler
│   │   └── gowa/                 # GoWA client
│   ├── llm/
│   │   ├── base.py               # LLM provider abstraction
│   │   ├── gemini.py             # Gemini LLM client
│   │   └── openai.py             # OpenAI LLM client
│   └── services/
│       ├── mandarin_generator/   # Mandarin passage service
│       ├── reply_agent/          # AI-powered reply assistant
│       └── chat_summarizer/      # Chat summarization (future)
├── docker-compose.yml
├── Dockerfile
└── pyproject.toml
```

## Local Development

```bash
# Install dependencies with uv
uv sync

# Run locally (requires GoWA running separately)
uv run uvicorn src.main:app --reload --port 8080
```

## Logs

```bash
# View all logs
docker-compose logs -f

# View only Akasha logs
docker-compose logs -f akasha

# View only GoWA logs
docker-compose logs -f whatsapp
```

## VPS Deployment

### Minimum Requirements

| Resource | Minimum | Recommended |
|----------|---------|-------------|
| RAM | 1 GB | 2 GB |
| Storage | 5 GB | 10 GB |
| CPU | 1 vCPU | 2 vCPU |

**Notes:**
- GoWA (WhatsApp service) uses ~200-400 MB RAM
- Akasha (FastAPI app) uses ~100-200 MB RAM
- Storage includes Docker images (~2-3 GB) and WhatsApp session data
- A basic 1 GB VPS can run both services, but 2 GB provides headroom for logs and future services

### Recommended VPS Providers

| Provider | Plan | Price/Month |
|----------|------|-------------|
| [Hetzner](https://www.hetzner.com/cloud) | CX22 (2 vCPU, 4 GB) | ~$4-5 |
| [DigitalOcean](https://www.digitalocean.com/) | Basic Droplet (1 vCPU, 1 GB) | $6 |
| [Vultr](https://www.vultr.com/) | Cloud Compute (1 vCPU, 1 GB) | $6 |
| [Linode](https://www.linode.com/) | Nanode (1 vCPU, 1 GB) | $5 |

### Deployment Steps

1. **Provision VPS** with Ubuntu 22.04+ or Debian 12+

2. **Install Docker**
   ```bash
   curl -fsSL https://get.docker.com | sh
   sudo usermod -aG docker $USER
   # Log out and back in
   ```

3. **Clone and configure**
   ```bash
   git clone https://github.com/yourusername/akasha.git
   cd akasha
   cp .env.example .env
   nano .env  # Edit with your values
   ```

4. **Start services**
   ```bash
   docker-compose up -d
   ```

5. **Link WhatsApp** - Access `http://your-vps-ip:3000/app/login` to scan QR code

6. **Optional: Set up reverse proxy** with nginx/Caddy for HTTPS

## Troubleshooting

### "you are not logged in" error
Re-scan QR code at http://localhost:3000/app/login

### Messages not sending
1. Check health: `curl http://localhost:8080/health`
2. Verify recipient JID format
3. Check logs: `docker-compose logs -f akasha`

### QR code not loading
1. Check GoWA is running: `docker-compose ps`
2. View logs: `docker-compose logs whatsapp`

### Environment variables not updating
If changes to `.env` aren't reflected after restarting:
```bash
# Rebuild and restart containers
docker-compose up --build -d
```

### LLM rate limit or server errors (429, 503)
If you see rate limit or server unavailable errors:
1. Enable automatic fallback (enabled by default):
   ```bash
   LLM_FALLBACK_ENABLED=true
   GEMINI_API_KEY=key1,key2,key3
   OPENAI_API_KEY=sk-your-key
   ```
2. The system will:
   - Rotate through all Gemini API keys on 503 errors
   - Fallback to OpenAI if all Gemini keys are exhausted
   - Provide clear error messages to users
3. Or switch to a different LLM provider in `.env`:
   ```bash
   LLM_PROVIDER=openai
   OPENAI_API_KEY=sk-your-key
   ```
4. Rebuild: `docker-compose up --build -d`

### Reply Agent not responding
1. Check if enabled: `curl http://localhost:8080/reply-agent/status`
2. Verify trigger phrase: Messages must start with "hey akasha, "
3. Check web search is configured (for current information queries):
   ```bash
   GOOGLE_SEARCH_API_KEY=your-key
   GOOGLE_SEARCH_ENGINE_ID=your-cx-id
   ```

## License

MIT
