# CLAUDE.md

Guidance for Claude Code when working with this repository.

## Project Overview

Telegram bot with LLM integration (Claude, planned: OpenAI, Gemini). Microservices architecture with Docker Compose.

**Stack:** Python 3.12+, aiogram 3.24, PostgreSQL 16, Redis 7, Anthropic SDK

---

## File Structure

```
chxxxxbot/
├── bot/                        # Main application container
│   ├── main.py                 # Entry point
│   ├── config.py               # Settings, model registry, system prompt
│   ├── telegram/
│   │   ├── handlers/           # Message handlers (claude.py is main)
│   │   ├── middlewares/        # Logging, database, balance check
│   │   ├── keyboards/          # Inline/reply keyboards
│   │   └── loader.py           # Bot initialization
│   ├── core/
│   │   ├── claude/             # Claude API client, context manager
│   │   ├── tools/              # Tool implementations
│   │   ├── message_queue.py    # 200ms batching for split messages
│   │   └── pricing.py          # Cost calculation
│   ├── services/               # Payment, balance services
│   ├── db/
│   │   ├── models/             # User, Chat, Thread, Message, Payment, etc.
│   │   └── repositories/       # CRUD operations
│   ├── cache/                  # Redis caching layer
│   └── tests/                  # 1300+ tests
├── postgres/                   # PostgreSQL + Alembic migrations
├── redis/                      # Redis cache
├── grafana/                    # Monitoring dashboards + alerts
├── prometheus/                 # Metrics collection
├── loki/ + promtail/           # Log aggregation
├── secrets/                    # Docker secrets (.gitignore)
└── docs/                       # Architecture documentation
```

**Principle:** One top-level folder = one Docker container.

---

## Current Capabilities

### LLM Integration
- **Models:** Claude Haiku/Sonnet/Opus 4.5 (selectable via /model)
- **Streaming:** Real-time token streaming to Telegram
- **Context:** 200K token window with automatic management
- **Extended Thinking:** 16K budget tokens for complex reasoning
- **Prompt Caching:** 5-minute ephemeral cache (10x cost reduction)

### Tools (9 total)
| Tool | Purpose | Cost |
|------|---------|------|
| `analyze_image` | Vision analysis via Files API | Paid |
| `analyze_pdf` | PDF text + visual analysis | Paid |
| `execute_python` | E2B sandbox with file I/O | Paid |
| `generate_image` | Google Gemini image generation | Paid |
| `transcribe_audio` | Whisper speech-to-text | Paid |
| `web_search` | Internet search | Paid |
| `web_fetch` | Fetch URL content | Free |
| `render_latex` | LaTeX to PNG | Free |
| `deliver_file` / `preview_file` | File delivery control | Free |

### File Handling
- **Input:** Any file type (images, PDFs, audio, video, documents)
- **Output:** Generated files via exec_cache → deliver_file pattern
- **Storage:** Files API (24h TTL) + Telegram file_id + Redis cache

### Payment System
- **Telegram Stars:** Native payment integration
- **Balance:** USD balance with soft-check (can go negative once)
- **Tool Cost Control:** Rejects paid tools when balance < 0
- **Generation Stop:** /stop or new message cancels, charges partial usage

### Caching (Redis)
- **User data:** balance, model_id, custom_prompt (TTL 60s)
- **Messages:** Thread history (TTL 300s)
- **Files:** Binary cache (TTL 3600s, max 20MB)
- **Write-behind:** Async Postgres writes (5s flush, batch 100)
- **Circuit breaker:** 3 failures → 30s timeout

### Monitoring
- **Grafana:** :3000 - dashboards, alerts
- **Prometheus:** Metrics (cache hits, queue depth, latency)
- **Loki:** Centralized logs (30 days retention)

---

## Architectural Principles

### Modularity
- Universal interfaces over ad-hoc solutions
- Each function does one thing
- Dependency injection where possible
- Repository pattern for DB access

### Logging-first
- Structured JSON logs via structlog
- Context in every log: user_id, message_id, request_id
- All API calls, errors, and key operations logged

### Code Style
- **Google Python Style Guide**
- Pre-commit hooks: yapf, isort, pylint, mypy
- Type hints required
- Docstrings in Google format

### Documentation-first
- Plan → Document → Implement → Update docs
- Architecture decisions in docs/
- Ask user about trade-offs, don't assume

### Test-first
- Tests alongside implementation
- Bug fix = regression test mandatory
- 80%+ coverage target
- Run: `docker compose exec bot pytest`

---

## Key Files

| File | Lines | Purpose |
|------|-------|---------|
| `telegram/handlers/claude.py` | ~2000 | Main message handler, streaming, tools |
| `telegram/handlers/files.py` | ~700 | File upload processing |
| `telegram/handlers/media_handlers.py` | ~600 | Voice/audio/video handlers |
| `core/tools/registry.py` | ~400 | Tool definitions and dispatch |
| `cache/write_behind.py` | ~200 | Async DB write queue |

---

## Commands

```bash
# Start
docker compose up -d

# Logs
docker compose logs bot -f

# Tests
docker compose exec bot pytest
docker compose exec bot pytest -x  # stop on first failure

# Rebuild
docker compose build bot && docker compose up -d bot
```

---

## Known Architecture Issues

> To be filled after audit

---

## Documentation

See `docs/` for detailed architecture:
- `docs/database.md` - DB schema and repositories
- `docs/phase-*.md` - Feature implementation details
- `docs/README.md` - Documentation index
