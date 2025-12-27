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
| `GEMINI_API_KEY` | If using Gemini | - | Google Gemini API key |
| `GEMINI_MODEL` | No | `gemini-2.0-flash` | Gemini model to use |
| `OPENAI_API_KEY` | If using OpenAI | - | OpenAI API key |
| `OPENAI_MODEL` | No | `gpt-4o-mini` | OpenAI model to use |
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

### LLM rate limit errors (429)
If you see `RESOURCE_EXHAUSTED` or rate limit errors:
1. Switch to a different LLM provider in `.env`:
   ```bash
   LLM_PROVIDER=openai
   OPENAI_API_KEY=sk-your-key
   ```
2. Rebuild: `docker-compose up --build -d`

## License

MIT
