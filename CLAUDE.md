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
│   │   ├── pipeline/           # Unified message processing
│   │   │   ├── handler.py      # Entry point, batching
│   │   │   ├── processor.py    # Core processing logic
│   │   │   ├── normalizer.py   # Message normalization
│   │   │   ├── models.py       # ProcessedMessage, UploadedFile
│   │   │   ├── queue.py        # Message queue management
│   │   │   └── tracker.py      # Upload tracking
│   │   ├── middlewares/        # Logging, database, balance check
│   │   ├── keyboards/          # Inline/reply keyboards
│   │   └── loader.py           # Bot initialization
│   ├── core/
│   │   ├── claude/             # Claude API client, context manager
│   │   ├── tools/              # Tool implementations
│   │   ├── message_queue.py    # 200ms batching for split messages
│   │   └── pricing.py          # Cost calculation
│   ├── services/               # Payment, balance, topic naming services
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
- **Models:** Claude Haiku/Sonnet 4.5, Opus 4.6 (selectable via /model)
- **Streaming:** Real-time token streaming to Telegram
- **Context:** 200K token window with automatic management
- **Extended Thinking:** 16K budget tokens for complex reasoning
- **Prompt Caching:** 5-minute ephemeral cache (10x cost reduction)

### Tools (10 total)
| Tool | Purpose | Cost |
|------|---------|------|
| `analyze_image` | Vision analysis via Files API | Paid |
| `analyze_pdf` | PDF text + visual analysis | Paid |
| `execute_python` | E2B sandbox with file I/O | Paid |
| `generate_image` | Google Gemini image generation | Paid |
| `transcribe_audio` | Whisper speech-to-text | Paid |
| `web_search` | Internet search (server-side) | Paid |
| `web_fetch` | Fetch URL content (server-side) | Free |
| `render_latex` | LaTeX to PNG | Free |
| `preview_file` | Preview cached file before delivery | Free* |
| `deliver_file` | Send cached file to user | Free |

*`preview_file` is free for text/CSV, paid for images/PDFs (uses Vision API)

### File Handling
- **Input:** Any file type (images, PDFs, audio, video, documents)
- **Output:** Generated files via exec_cache → deliver_file pattern
- **Storage:** Files API (24h TTL) + Telegram file_id + Redis cache

### Payment System
- **Telegram Stars:** Native payment integration
- **Balance:** USD balance with soft-check (can go negative once)
- **Tool Cost Control:** Rejects paid tools when balance < 0
- **Generation Stop:** /stop or new message cancels, charges partial usage

### Topic Naming
- **Auto-naming:** Topics automatically named based on first user message
- **LLM-based:** Uses Claude Haiku for intelligent title generation (3-6 words)
- **Cost:** ~$0.0003 per title (500 input + 50 output tokens)

### Caching (Redis)
- **User data:** balance, model_id, custom_prompt (TTL 3600s)
- **Thread:** Active thread lookup (TTL 3600s)
- **Messages:** Thread history with atomic append (TTL 3600s)
- **Files:** Binary cache (TTL 3600s, max 20MB)
- **Write-behind:** Async Postgres writes (5s flush, batch 100, retry on failure)
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
| `telegram/handlers/claude.py` | ~1700 | Main message handler, streaming, tools |
| `telegram/pipeline/handler.py` | ~360 | Unified message processing entry point |
| `telegram/pipeline/normalizer.py` | ~700 | Message normalization, file downloads |
| `core/tools/registry.py` | ~330 | Tool definitions and dispatch |
| `cache/write_behind.py` | ~620 | Async DB write queue with retry |
| `core/tools/execute_python.py` | ~950 | E2B sandbox code execution |

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

Based on audit (2026-01-27):
- **Service initialization duplication** — Same repo/service setup in 5+ places
- **Singleton patterns inconsistent** — 3 different patterns across codebase
- **Streaming handler too large** — `_stream_with_unified_events` is 500+ lines
- **Balance check logic scattered** — Duplicated in middleware, handlers, tools

See `PLAN.md` for improvement roadmap.

---

## Documentation

See `docs/` for detailed architecture:
- `docs/database.md` - DB schema and repositories
- `docs/phase-*.md` - Feature implementation details
- `docs/README.md` - Documentation index
