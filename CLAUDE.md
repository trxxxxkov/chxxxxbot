# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Telegram bot with access to LLM models (Claude, OpenAI, Google) and tools via agents. Microservices architecture.

---

## File Structure

```
chxxxxbot/
├── bot/                        # Container: Telegram bot
│   ├── main.py                 # Entry point: secrets, logger, startup
│   ├── config.py               # Constants, app settings, system prompt
│   ├── telegram/               # Telegram API integration
│   │   ├── handlers/           # Message and command handlers
│   │   │   ├── start.py        # /start, /help
│   │   │   ├── claude.py       # Claude message handler (catch-all)
│   │   │   ├── model.py        # /model command
│   │   │   ├── personality.py  # /personality command
│   │   │   ├── payment.py      # /pay, /balance, /refund
│   │   │   ├── admin.py        # /topup, /set_margin
│   │   │   ├── files.py        # File attachments
│   │   │   └── media_handlers.py  # Voice/audio/video
│   │   ├── middlewares/        # Middleware
│   │   │   ├── logging_middleware.py
│   │   │   ├── database_middleware.py
│   │   │   └── balance_middleware.py
│   │   ├── keyboards/          # Inline and reply keyboards
│   │   │   ├── model_selector.py
│   │   │   └── personality_selector.py
│   │   ├── media_processor.py  # Universal media processing
│   │   └── loader.py           # Bot, Dispatcher initialization
│   ├── core/                   # LLM providers (core functionality)
│   │   ├── base.py             # Abstract provider interface
│   │   ├── claude/             # Claude implementation
│   │   │   ├── client.py       # Claude API client
│   │   │   ├── context.py      # Context window manager
│   │   │   └── files_api.py    # Files API wrapper
│   │   ├── tools/              # Tool implementations
│   │   │   ├── registry.py     # Tool definitions and dispatch
│   │   │   ├── analyze_image.py
│   │   │   ├── analyze_pdf.py
│   │   │   ├── execute_python.py
│   │   │   ├── transcribe_audio.py
│   │   │   └── generate_image.py
│   │   ├── message_queue.py    # Message batching (200ms)
│   │   ├── pricing.py          # Cost calculation
│   │   └── clients.py          # Shared API clients
│   ├── services/               # Business logic
│   │   ├── payment_service.py  # Stars payment processing
│   │   └── balance_service.py  # User balance operations
│   ├── db/                     # PostgreSQL integration
│   │   ├── engine.py           # Async engine, session
│   │   ├── models/             # SQLAlchemy models
│   │   │   ├── user.py         # User (with balance)
│   │   │   ├── chat.py         # Chat/group/channel
│   │   │   ├── thread.py       # Conversation thread
│   │   │   ├── message.py      # Message (with tokens)
│   │   │   ├── user_file.py    # Files API references
│   │   │   ├── payment.py      # Stars payments
│   │   │   └── balance_operation.py  # Balance audit
│   │   └── repositories/       # CRUD operations
│   ├── cache/                  # Redis caching (Phase 3.2)
│   │   ├── client.py           # Redis client singleton
│   │   ├── keys.py             # Key generation, TTL constants
│   │   ├── user_cache.py       # User data caching
│   │   ├── thread_cache.py     # Thread/messages caching
│   │   └── file_cache.py       # Binary file caching
│   ├── utils/                  # Helper utilities
│   │   ├── structured_logging.py  # structlog configuration
│   │   └── metrics.py          # Prometheus metrics
│   ├── tests/                  # Test suite (580+ tests)
│   ├── Dockerfile
│   └── pyproject.toml
│
├── postgres/                   # Container: PostgreSQL
│   ├── alembic/                # Migrations
│   └── init.sql                # Initial schema
│
├── redis/                      # Container: Redis (Phase 3.2)
│                               # (data in redis_data volume)
│
├── grafana/                    # Container: Grafana
│   └── provisioning/           # Dashboards, datasources
│
├── loki/                       # Container: Loki
│   └── loki-config.yaml
│
├── promtail/                   # Container: Promtail (log collector)
│   └── promtail-config.yaml
│
├── prometheus/                 # Container: Prometheus (metrics)
│   └── prometheus.yml
│
├── secrets/                    # Docker secrets (in .gitignore)
├── docs/                       # Documentation (see docs/README.md)
├── compose.yaml
├── .gitignore
└── CLAUDE.md
```

**Principle:** One top-level folder = one Docker container.

---

## Development Phases

### Phase 1 — Working Prototype

#### 1.1 Minimal Bot ✅ Complete
| Component | Technology |
|-----------|------------|
| Framework | aiogram 3.24 |
| Telegram API | Bot API 9.3 (polling) |
| Python | 3.12+ |
| Validation/models | Pydantic v2 |
| Containerization | Docker + Docker Compose |

#### 1.2 PostgreSQL ✅ Complete
| Component | Technology |
|-----------|------------|
| Database | PostgreSQL 16 |
| Async driver | asyncpg |
| ORM | SQLAlchemy 2.0 (async) |
| Migrations | Alembic |

#### 1.3 Claude Integration (Core) ✅ Complete
| Component | Technology |
|-----------|------------|
| SDK | anthropic>=0.40.0 (official) |
| Model | Claude Sonnet 4.5 (claude-sonnet-4-5-20250929) |
| Streaming | Real-time token streaming (no buffering) |
| Context | Token-based window management (200K tokens) |
| Error handling | Rate limits, timeouts, API errors |

**Implemented Features:**
- ✅ Text-only conversations with streaming responses
- ✅ No buffering - each Claude chunk sent immediately to Telegram
- ✅ Thread-based context (all messages that fit in token window)
- ✅ Global system prompt (same for all users)
- ✅ Basic cost tracking (input/output tokens per message)
- ✅ Comprehensive structured logging
- ✅ Regression tests for all bugs encountered

**Bugs Fixed During Implementation:**
1. ✅ User.telegram_id AttributeError → changed to user.id
2. ✅ ChatRepository type parameter → changed to chat_type
3. ✅ Missing role parameter in MessageRepository.create_message
4. ✅ Wrong execution order (thread must be created before message)
5. ✅ Incorrect model name (claude-sonnet-4-5-20250514 → claude-sonnet-4-5-20250929)

**Test Coverage:**
- 4 regression tests in tests/core/test_claude_handler_integration.py
- All tests passing ✅

**Out of scope for 1.3:**
- Multimodal (images, voice, files)
- Tools (code execution, image generation)
- Payment system (balance blocking)
- Prompt caching

#### 1.4 Claude Advanced API ✅ Complete
**Status:** Complete (2026-01-09)

**Phase 1.4.1 - Model Registry:**
- ✅ 3 Claude 4.5 models (Haiku, Sonnet, Opus)
- ✅ Capability flags for feature detection
- ✅ Cache pricing in model registry
- ✅ `/model` command for model selection
- ✅ Cost tracking with model-specific pricing

**Phase 1.4.2 - Prompt Caching:**
- ✅ Conditional system prompt caching (≥1024 tokens)
- ✅ 5-minute ephemeral cache (10x cost reduction)
- ✅ Cache hit rate monitoring in logs
- ✅ 3-level prompt composition (GLOBAL + User + Thread)

**Phase 1.4.3 - Extended Thinking & Message Batching:**
- ✅ Interleaved thinking beta header
- ✅ `thinking_delta` streaming support
- ✅ Thinking token tracking
- ✅ Time-based message batching (200ms window)
- ✅ Extended Thinking ENABLED (budget_tokens: 16000)

**Phase 1.4.4 - Best Practices & Optimization:**
- ✅ System prompt rewritten for Claude 4 style
- ✅ Effort parameter for Opus 4.5 (`effort: "high"`)
- ✅ Token Counting API for large requests (>150K tokens)
- ✅ Stop reason handling (context overflow, refusal, max_tokens)

**Documentation:**
- ✅ 15 Claude API pages reviewed and documented
- ✅ Best practices adopted (explicit instructions, thinking vocabulary)
- ✅ See [docs/phase-1.4-claude-advanced-api.md](docs/phase-1.4-claude-advanced-api.md)

#### 1.5 Multimodal + Tools ✅ Complete
**Status:** Complete (2026-01-10)

**Multimodal support:**
- ✅ Images (vision via Files API - analyze_image)
- ✅ PDF documents (text + visual via Files API - analyze_pdf)
- ✅ Voice messages (via Phase 1.6)
- ✅ Audio/video files (via Phase 1.6)

**Tools framework:**
- ✅ Tool Runner (SDK beta) for all custom tools
- ✅ analyze_image (Claude Vision API with Files API)
- ✅ analyze_pdf (Claude PDF API with Files API)
- ✅ web_search, web_fetch (server-side tools)
- ✅ execute_python (E2B Code Interpreter with file I/O)
- ✅ Modular tool architecture

**Database schema:**
- ✅ user_files table (telegram_file_id, claude_file_id, metadata)
- ✅ thinking_blocks column in messages
- ✅ Files API lifecycle management (24h TTL)
- ✅ FileSource enum (USER/ASSISTANT)
- ✅ FileType enum (IMAGE/PDF/DOCUMENT/GENERATED)

**Stage 6 Complete:**
- ✅ File I/O for execute_python (upload inputs, download outputs)
- ✅ Hybrid storage (Files API for analyze_*, Telegram for execute_python)
- ✅ User files download from Telegram (Files API limitation workaround)
- ✅ Assistant files download from Files API

**See:** [docs/phase-1.5-multimodal-tools.md](docs/phase-1.5-multimodal-tools.md)

#### 1.6 Multimodal Support (All File Types) ✅ Complete
**Status:** Complete (2026-01-10)

**Universal Media Architecture:**
- ✅ `MediaType` enum: VOICE, AUDIO, VIDEO, VIDEO_NOTE, IMAGE, DOCUMENT
- ✅ `MediaContent` dataclass: universal container for all media types
- ✅ `MediaProcessor` class: single interface for all processing
- ✅ Unified flow: Download → Process → Queue → Claude handler

**Whisper Integration:**
- ✅ OpenAI Whisper API for speech-to-text transcription
- ✅ Automatic language detection
- ✅ Cost tracking (~$0.006 per minute)
- ✅ Supported formats: OGG, MP3, M4A, WAV, FLAC, MP4, MOV, AVI

**Implemented Handlers:**
- ✅ `handle_voice()` - voice messages (OGG/OPUS)
- ✅ `handle_audio()` - audio files (MP3, FLAC, WAV, etc)
- ✅ `handle_video()` - video files (audio track extraction)
- ✅ `handle_video_note()` - round video messages

**Integration:**
- ✅ Message Queue supports optional `MediaContent` parameter
- ✅ Claude handler extracts `text_content` (transcripts) or `file_id` (vision)
- ✅ Full backward compatibility with text-only messages
- ✅ Immediate processing for media (no 200ms delay)

**Files:**
- telegram/media_processor.py - MediaProcessor, MediaType, MediaContent
- telegram/handlers/media_handlers.py - Voice/Audio/Video handlers
- telegram/loader.py - Router registration
- core/message_queue.py - MediaContent support

**Testing:**
- ✅ Voice message download and transcription verified
- ✅ MediaContent queue integration working
- ✅ Cost tracking confirmed ($0.0014 for 14-second voice message)

**See:** [docs/phase-1.6-multimodal-support.md](docs/phase-1.6-multimodal-support.md)

#### 1.7 Image Generation (Nano Banana Pro) ✅ Complete
**Status:** Complete (2026-01-10)

**Tool:**
- ✅ `generate_image` - High-quality image generation up to 4K
- ✅ Google Nano Banana Pro (gemini-3-pro-image-preview)
- ✅ Google Search grounding for reference images
- ✅ Flexible parameters (aspect ratio, resolution, content policy)

**Integration:**
- ✅ Automatic delivery via `_file_contents` pattern
- ✅ Upload to Files API (24h TTL)
- ✅ Save to database (source=ASSISTANT, type=GENERATED)
- ✅ Send to Telegram as photo
- ✅ Added to context ("Available files")

**Pricing:**
- ✅ $0.134 per image (1K/2K resolution)
- ✅ $0.240 per image (4K resolution)
- ✅ Cost tracking in logs and tool results

**Files:**
- core/tools/generate_image.py - Tool implementation
- core/tools/registry.py - Tool registration
- config.py - System prompt update
- pyproject.toml, Dockerfile - Dependencies (google-genai, pillow)
- compose.yaml - Google API key secret

**Testing:**
- ✅ Comprehensive test suite: 15 tests (all passing)
- ✅ Success scenarios (default and custom parameters)
- ✅ Error handling (empty prompt, no image, content policy, API errors)
- ✅ Cost calculation verification (1K, 2K, 4K)
- ✅ Client singleton pattern validation
- ✅ Production testing verified ($0.134 for 2K images)

**See:** [docs/phase-1.7-image-generation.md](docs/phase-1.7-image-generation.md)

### Phase 2 — Telegram Features Expansion

#### 2.1 Payment System ✅ Complete
**Status:** Complete (2026-01-10)

**User balance system:**
- ✅ USD balance per user (starter balance: $0.10)
- ✅ Soft balance check (allow requests while balance > 0, can go negative once)
- ✅ Balance operations tracking (PAYMENT, USAGE, REFUND, ADMIN_TOPUP)
- ✅ Full audit trail in balance_operations table

**Telegram Stars integration:**
- ✅ Native payment flow via sendInvoice
- ✅ Pre-checkout query validation
- ✅ Successful payment handler with balance crediting
- ✅ Predefined packages (10/50/100/250/500 Stars) + custom amount (1-2500)
- ✅ Commission formula: y = x * (1 - k1 - k2 - k3)
  - k1 = 0.35 (Telegram withdrawal fee)
  - k2 = 0.15 (Topics in private chats fee)
  - k3 = 0.0+ (Owner margin, configurable)
- ✅ Refund support within 30 days (refundStarPayment)
- ✅ Transaction ID tracking for refunds
- ✅ Duplicate payment protection

**User commands:**
- ✅ `/pay` - Purchase balance with Stars (packages or custom)
- ✅ `/balance` - View current balance and transaction history
- ✅ `/refund <transaction_id>` - Request refund (30-day window)
- ✅ `/paysupport` - Payment support information (Telegram requirement)

**Admin features:**
- ✅ Privileged users list in secrets/privileged_users.txt
- ✅ `/topup <user_id|@username> <amount>` - Manual balance adjustment
- ✅ `/set_margin <margin>` - Configure owner margin (k3)
- ✅ Privilege verification for all admin commands

**Cost tracking integration:**
- ✅ Claude API costs tracked (input/output/cache tokens, thinking tokens)
- ✅ Tool execution costs tracked (Whisper, E2B, Google Gemini)
- ✅ Automatic charging after each API call
- ✅ Cost attribution per user
- ✅ Balance operations logged for every charge

**Balance middleware:**
- ✅ Pre-request balance check (blocks if balance ≤ 0)
- ✅ Free commands bypass (start, help, buy, balance, refund, paysupport, model, etc.)
- ✅ Fail-open on errors (allows request if balance check fails)

**Database schema:**
- ✅ payments table (Stars transactions, commission breakdown, refund tracking)
- ✅ balance_operations table (audit trail for all balance changes)
- ✅ User.balance field with relationships
- ✅ Alembic migration (007) applied

**Testing:**
- ✅ 46 integration tests (payment flow, refunds, middleware, admin commands)
- ✅ Unit tests for all models, repositories, services
- ✅ 566 total tests passing (100% pass rate)
- ✅ Edge case coverage (duplicates, expiry, insufficient balance, soft check)

**Files created:**
- Models: payment.py, balance_operation.py
- Repositories: payment_repository.py, balance_operation_repository.py
- Services: payment_service.py, balance_service.py
- Handlers: payment.py, admin.py
- Middleware: balance_middleware.py
- Tests: 8 test files (models, repos, services, integration, middleware)
- Migration: 007_add_payment_system_tables.py
- Secrets: privileged_users.txt

**See:** [docs/phase-2.1-payment-system.md](docs/phase-2.1-payment-system.md)

#### 2.2 DevOps Agent 📋 Planned

**Self-healing bot with autonomous code editing via Agent SDK.**

**Core capabilities:**
- 🔧 Auto-fix errors detected in production logs
- 🚀 Implement features on owner's request via Telegram
- 📊 Code review and suggestions
- 🔄 Create GitHub PRs with fixes/features
- ⚙️ Deploy changes after owner approval

**Architecture:**
- Agent Service container (Claude Agent SDK + FastAPI)
- Full filesystem access to bot code (shared volume)
- GitHub API integration (branches, PRs, merge)
- Docker socket access (restart containers)
- Loki alert webhook (auto-fix trigger)

**Telegram commands:**
- `/agent <task>` - Owner requests feature/fix/refactor
- `/approve_pr <number>` - Approve and deploy PR
- `/agent_status` - Check agent service health

**Security:**
- Owner-only access (OWNER_TELEGRAM_ID validation)
- Protected files (secrets/, .env, compose.yaml)
- Review before merge (always creates PRs, never direct commits)
- Audit logging (all operations logged)
- Rate limiting (prevent abuse)

**Use cases:**
1. Self-healing: Error in logs → Agent fixes → PR → Owner approves → Deployed
2. Feature dev: `/agent add /stats command` → Agent implements → PR → Review → Merged
3. Code review: `/agent review last commit` → Agent analyzes → Suggestions PR

**Cost:** ~$3-40/month depending on usage (Agent SDK operations)

See [docs/phase-2.2-devops-agent.md](docs/phase-2.2-devops-agent.md) for full architecture.

#### 2.3 Additional Telegram Features 📋 Planned
- Draft messages (Bot API 9.3)
- Threads/topics (Bot API 9.3)
- Keyboards (inline, reply)
- Service messages
- Commands, menus
- Media handling improvements

### Phase 3 — Infrastructure

#### 3.1 Monitoring ✅ Complete
**Status:** Complete (2026-01-11)

| Component | Port | Purpose |
|-----------|------|---------|
| Loki | :3100 (internal) | Log aggregation (30 days retention) |
| Promtail | internal | Log collector from Docker containers |
| Prometheus | :9090 (internal) | Metrics storage (30 days retention) |
| Grafana | :3000 (external) | Web UI for logs & metrics |
| CloudBeaver | :8978 (external) | Web UI for PostgreSQL |

**Access:**
- Grafana: `http://88.218.68.98:3000` (admin / secrets/grafana_password.txt)
- CloudBeaver: `http://88.218.68.98:8978` (create account on first access)

**Files:**
- loki/loki-config.yaml - Loki configuration
- promtail/promtail-config.yaml - Log collection config
- prometheus/prometheus.yml - Metrics scraping config
- grafana/provisioning/ - Datasources and dashboards

**See:** [docs/phase-3-infrastructure.md](docs/phase-3-infrastructure.md)

#### 3.2 Redis Cache ✅ Complete
**Status:** Complete (2026-01-21)

| Component | Technology |
|-----------|------------|
| Cache | Redis 7 (alpine) |
| Async client | redis-py 5.0+ with hiredis |
| Memory limit | 512MB |
| Eviction | allkeys-lru |
| Persistence | AOF (appendonly) |

**Cache Types:**
- ✅ User cache (balance, model_id) - TTL 60s
- ✅ Thread cache - TTL 600s (10 min)
- ✅ Messages cache - TTL 300s (5 min)
- ✅ File bytes cache - TTL 3600s (1 hour), max 20MB

**Cache Pattern:** Cache-aside with graceful degradation (falls back to DB if Redis unavailable)

**Metrics:**
- `bot_redis_cache_hits_total{cache_type}` - Cache hits
- `bot_redis_cache_misses_total{cache_type}` - Cache misses
- `bot_redis_operation_seconds{operation}` - Operation latency
- `bot_redis_connected_clients` - Connected clients
- `bot_redis_memory_bytes` - Memory usage

**Files:**
- cache/client.py - Redis client singleton
- cache/keys.py - Key generation and TTL constants
- cache/user_cache.py - User data caching
- cache/thread_cache.py - Thread and messages caching
- cache/file_cache.py - Binary file caching

**See:** [docs/phase-3.2-redis-cache.md](docs/phase-3.2-redis-cache.md)

#### 3.3 Other LLM Providers 📋 Planned
- OpenAI (latest models)
- Google Gemini (latest models)
- Unified provider interface
- Per-provider pricing
- Model selection per thread

---

## Architectural Principles

### Maximum Modularity

All code must be modular at every level, so any part of functionality can be updated independently.

**At file structure level:**
- Each module/component in separate directory
- Clear separation of concerns
- Minimal dependencies between modules

**At code level:**
- Universal interfaces instead of ad-hoc solutions
- Dependency injection where possible
- Each function does one thing
- Easily replaceable components

**Examples:**
- LLM providers — common interface, separate implementations
- Telegram handlers — independent modules by functionality
- DB — repository abstraction, no direct queries in handlers

### Logging-first

All code is written with logging in mind from the first line.

**What we log:**
- Incoming messages/updates from Telegram
- Claude API requests (without sensitive data)
- Database queries
- Errors and exceptions (with full traceback)
- Execution time of key operations
- User actions (commands, callbacks)

**How:**
- Structured logs (JSON) — for Loki
- Levels: DEBUG, INFO, WARNING, ERROR
- Context (user_id, message_id, request_id) in every log
- Library: `structlog`

### LLM Provider Modularity

Common interface for all providers (Claude, OpenAI, Google) to easily add new ones.

### Code Style

All Python code must follow **Google Python Style Guide**.

**Key requirements:**
- Docstrings in Google format (Args:, Returns:, Raises:, Examples:)
- Type hints for function parameters and returns
- 4 spaces for indentation
- Maximum line length: 80 characters (docstrings, comments), 100 characters (code)
- Imports organized: standard library, third-party, local
- Descriptive variable names (avoid abbreviations)

**Reference:** https://google.github.io/styleguide/pyguide.html

**Automated enforcement:**
- Pre-commit hooks configured in `.pre-commit-config.yaml`
- Runs automatically on every commit
- Tools: yapf (formatting), isort (imports), pylint (linting), pydocstyle (docstrings), mypy (types)
- Install: `pipx install pre-commit && pre-commit install`

### Documentation-first

Before writing code — planning and documentation.

**Development Process (MANDATORY):**

1. **Create Plan** - Discuss and agree on component architecture
   - What needs to be implemented
   - What files will be created/modified
   - What design decisions need to be made
   - What dependencies exist

2. **Document Plan in `docs/`** - BEFORE writing any code
   - Create or update relevant documentation
   - Include file paths, imports, usage examples
   - Document architectural decisions and rationale
   - Optimize for LLM agent comprehension

3. **Implement Code** - Follow the documented plan
   - Write code according to documentation
   - Ensure all design decisions from docs are reflected
   - Follow Google Python Style Guide

4. **Update Documentation** - If anything changes during implementation
   - Update docs to reflect actual implementation
   - Document any deviations from original plan
   - Keep docs and code in sync

**Golden Rule:**
```
Plan → Documentation in docs/ → Implementation → Update docs if needed
```

**Never:** Implementation first, then documentation. Always document BEFORE coding.

**`docs/` folder:**
- Stores plans and architecture for each component
- Source of truth for architectural decisions
- Optimized for LLM-agents (see `docs/README.md`)
- Always kept up to date with code

**Documentation must include:**
- Specific file paths and imports
- Code examples for common operations
- Relationships between components
- Architectural decisions with justification
- Troubleshooting common issues

**Rule:** Any code change affecting architecture must be reflected in the corresponding document in the same commit.

**README.md:** Contains project maintenance commands (start, logs, debug). Update when infrastructure changes.

### Test-First Development

**Policy:** All new functionality MUST have tests written alongside implementation.

**Process:**
1. Write tests first (TDD) or immediately after implementation
2. Ensure tests pass before committing
3. Maintain minimum 80% code coverage
4. Run tests locally before pushing

**CRITICAL: Bug Fix Policy:**
- **After fixing ANY production bug, IMMEDIATELY write a test** that would have caught it
- This test MUST be added BEFORE considering the bug fixed
- The test ensures the bug never happens again
- No exceptions - every bug fix must include a test

**Test Types:**
- **Unit tests**: Fast, isolated, in-memory SQLite
- **Integration tests**: Docker PostgreSQL, full stack
- **End-to-end tests**: Full application flow

**Test Structure:**

```
bot/tests/
├── conftest.py                           # Shared fixtures, mocks
├── db/                                   # Database layer tests
│   ├── repositories/
│   │   ├── test_user_repository.py       # UserRepository tests
│   │   ├── test_chat_repository.py       # ChatRepository tests
│   │   ├── test_thread_repository.py     # ThreadRepository tests
│   │   ├── test_message_repository.py    # MessageRepository tests
│   │   └── test_base_repository.py       # BaseRepository tests
│   ├── models/
│   │   └── test_base.py                  # Base and TimestampMixin tests
│   ├── test_engine.py                    # Connection pool, session tests
│   └── test_integration_db.py            # Full workflow tests
├── telegram/                              # Telegram bot layer tests
│   ├── handlers/
│   │   ├── test_start.py                 # /start and /help handlers
│   │   └── test_echo.py                  # Echo handler tests
│   ├── middlewares/
│   │   ├── test_logging_middleware.py    # Logging middleware tests
│   │   └── test_database_middleware.py   # Database middleware tests
│   └── test_loader.py                    # Bot and Dispatcher tests
├── utils/
│   └── test_structured_logging.py        # Logging configuration tests
├── test_config.py                        # Configuration tests
├── test_main.py                          # Application startup tests
└── manual_test_script.py                 # Manual PostgreSQL validation
```

**Important:** NO `__init__.py` files - use namespace packages (Python 3.12+)

**Running Tests:**

```bash
# All tests
docker compose exec bot pytest

# Specific test file
docker compose exec bot pytest tests/db/repositories/test_user_repository.py

# Specific test
docker compose exec bot pytest tests/db/test_engine.py::test_init_db_creates_engine

# With coverage report
docker compose exec bot pytest --cov=bot --cov-report=html
docker compose exec bot pytest --cov=bot --cov-report=term-missing

# Fast (unit tests only, skip integration)
docker compose exec bot pytest -m "not integration"

# Verbose output
docker compose exec bot pytest -v

# Stop on first failure
docker compose exec bot pytest -x

# Show print statements
docker compose exec bot pytest -s
```

**Test Naming Convention:**
- Test files: `test_*.py`
- Test functions: `test_<what_is_being_tested>`
- Fixtures: `mock_<object>` or `sample_<object>`

**Test Guidelines:**
- Clear test names describing what is tested
- Google-style docstrings with Args, Returns
- One assertion per test (when possible)
- Use fixtures for common setup
- Mock external dependencies (API calls, file I/O)
- Verify both success and failure paths

**Coverage Targets:**
- Database repositories: 90%+
- Infrastructure (engine, config): 85%+
- Telegram handlers: 80%+
- Middlewares: 90%+
- Overall project: 80%+

**Current Test Coverage:** 566 tests across all components ✅

**Manual Testing:**

For live PostgreSQL validation:
```bash
docker compose exec bot python tests/manual_test_script.py
```

This script:
- Tests all CRUD operations
- Verifies constraints and indexes
- Cleans up test data automatically
- Provides colored output for debugging

---

## Current Status

**Phase 1.1 (Minimal Bot):** ✅ Complete
- Bot structure created and running
- Echo handler working
- Structured logging with structlog
- Pre-commit hooks for Google Code Style
- Docker containerization working

**Phase 1.2 (PostgreSQL Integration):** ✅ Complete
- PostgreSQL 16 with SQLAlchemy 2.0 async ORM
- 4 models: User, Chat, Thread, Message
  - Telegram IDs as primary keys
  - Composite key (chat_id, message_id) for messages
  - JSONB attachments with denormalized flags
  - Bot API 9.3 support (thread_id, is_forum)
- Repository pattern with BaseRepository[T]
  - UserRepository, ChatRepository, ThreadRepository, MessageRepository
  - Enhanced structured logging in repositories
  - Ready for Redis caching (Phase 3)
- DatabaseMiddleware for automatic session management
  - Auto-commit on success, auto-rollback on error
- Alembic async migrations configuration
- Docker Compose with PostgreSQL service
- /start handler with database integration
- **Comprehensive test coverage: 201 tests**
  - Database layer: 69 tests (repositories, models, integration)
  - Infrastructure: 57 tests (engine, config, logging, base)
  - Telegram bot: 59 tests (handlers, middlewares, loader)
  - Application: 16 tests (startup, secrets, error handling)
  - Manual validation script for live PostgreSQL testing
- Comprehensive documentation in docs/:
  - database.md (98KB) - complete architecture
  - telegram-api-mapping.md (25KB) - API to DB mapping
  - bot-structure.md (updated) - structure with db/

**Phase 1.3 (Claude Integration - Core):** ✅ Complete
- Claude Sonnet 4.5 integration (claude-sonnet-4-5-20250929)
- Real-time streaming responses (no buffering)
- Token-based context management (200K context window)
- Thread-based conversation history
- Global system prompt
- Cost tracking (input/output tokens)
- Comprehensive structured logging
- **Regression tests: 4 tests** in tests/core/test_claude_handler_integration.py
  - Bug fix tests for all issues encountered during development
  - All tests passing ✅
- Files created:
  - bot/core/base.py - LLM provider interface
  - bot/core/models.py - Pydantic models
  - bot/core/exceptions.py - Custom exceptions
  - bot/core/claude/client.py - Claude API client
  - bot/core/claude/context.py - Context manager
  - bot/telegram/handlers/claude.py - Main handler
  - docs/claude-integration.md - Comprehensive architecture doc

**Phase 1.4 (Claude Advanced API):** ✅ Complete (2026-01-09)
- **Documentation review**: 15 Claude API pages reviewed and decisions documented
- **Phase 1.4.1 - Model Registry**:
  - 3 Claude 4.5 models (Haiku, Sonnet, Opus) with characteristics
  - Capability flags and cache pricing in registry
  - `/model` command for model selection
- **Phase 1.4.2 - Prompt Caching**:
  - Conditional system prompt caching (≥1024 tokens, 5-minute TTL)
  - 10x cost reduction on cache reads
  - Cache hit rate monitoring
  - 3-level prompt composition (GLOBAL + User + Thread)
- **Phase 1.4.3 - Extended Thinking & Message Batching**:
  - Interleaved thinking beta header
  - `thinking_delta` streaming support
  - Time-based message batching (200ms window for split messages)
  - Extended Thinking ENABLED (budget_tokens: 16000)
- **Phase 1.4.4 - Best Practices & Optimization**:
  - System prompt rewritten for Claude 4 style (explicit, concise)
  - Effort parameter for Opus 4.5 (`effort: "high"`)
  - Token Counting API for large requests (>150K tokens)
  - Stop reason handling (context overflow, refusal, max_tokens)
- **Files modified**:
  - bot/core/claude/client.py - beta headers, effort, token counting, stop reasons
  - bot/config.py - model registry, system prompt rewrite
  - bot/telegram/handlers/claude.py - stop reason handling, 3-level prompts
  - bot/core/message_queue.py - time-based batching
  - bot/core/base.py - get_stop_reason() method
- **Documentation**: docs/phase-1.4-claude-advanced-api.md (comprehensive guide)

**Phase 1.5 (Multimodal + Tools):** ✅ Complete (Partial)
- **Status**: Core tools and vision complete (2026-01-10)
- **Multimodal support (Stage 1-5)**:
  - Images (vision via Files API - analyze_image)
  - PDF documents (text + visual via Files API - analyze_pdf)
  - Voice/audio/video deferred to Phase 1.6
- **Tools framework**:
  - Tool Runner (SDK beta) for all custom tools
  - analyze_image, analyze_pdf (Claude Vision + Files API)
  - web_search, web_fetch (server-side tools)
  - execute_python (E2B Code Interpreter with file I/O)
  - Modular tool architecture
- **Database schema**:
  - user_files table (telegram_file_id, claude_file_id, metadata)
  - thinking_blocks column in messages
  - Files API lifecycle management (24h TTL)
  - FileSource enum (USER/ASSISTANT)
  - FileType enum (IMAGE/PDF/DOCUMENT/GENERATED)
- **Stage 6 Complete**:
  - File I/O for execute_python (upload inputs, download outputs)
  - Hybrid storage (Files API for analyze_*, Telegram for execute_python)
  - User files download from Telegram (Files API limitation workaround)
  - Assistant files download from Files API
- **Documentation**: docs/phase-1.5-multimodal-tools.md

**Phase 1.6 (Multimodal - All File Types):** ✅ Complete (2026-01-10)
- **Universal Media Architecture** (Stage 2-4):
  - MediaType enum (VOICE, AUDIO, VIDEO, VIDEO_NOTE, IMAGE, DOCUMENT)
  - MediaContent dataclass (universal container)
  - MediaProcessor class (single interface for all processing)
  - Unified flow: Download → Process → Queue → Claude handler
  - Transcript prefix: [VOICE MESSAGE - 12s]: transcript...
- **Whisper Integration** (Stage 2):
  - OpenAI Whisper API for speech-to-text ($0.006/minute)
  - Automatic language detection
  - Supported formats: OGG, MP3, M4A, WAV, FLAC, MP4, MOV, AVI
- **Implemented Handlers** (Stage 2-4):
  - handle_voice() - voice messages (OGG/OPUS)
  - handle_audio() - audio files (MP3, FLAC, WAV)
  - handle_video() - video files (audio track extraction)
  - handle_video_note() - round video messages
- **transcribe_audio Tool** (Stage 1):
  - Claude can transcribe any audio/video file on demand
  - Tool definition with detailed description
  - Registered in TOOL_DEFINITIONS
  - Download from Telegram storage
- **Database Schema** (Stage 5):
  - FileType enum extended: AUDIO, VOICE, VIDEO
  - Migration 006 applied
  - All 7 enum values in PostgreSQL
- **System Prompt** (Stage 6):
  - Added "Available Tools" section
  - Tool descriptions for all 6 tools
  - Tool Selection Guidelines
  - Updated "Working with Files" section
- **Integration**:
  - Message Queue supports optional MediaContent parameter
  - Claude handler extracts text_content or file_id with prefix
  - Full backward compatibility with text-only messages
  - Immediate processing for media (no delay)
- **Testing**: Voice transcription verified ($0.0012 for 12s message)
- **Files**:
  - core/tools/transcribe_audio.py - Tool implementation
  - telegram/media_processor.py - Core architecture
  - telegram/handlers/media_handlers.py - Media handlers
  - db/models/user_file.py - Extended FileType enum
  - postgres/alembic/versions/006_*.py - Migration
  - config.py - Updated GLOBAL_SYSTEM_PROMPT
- **Documentation**: docs/phase-1.6-multimodal-support.md

**Phase 1.7 (Image Generation - Nano Banana Pro):** ✅ Complete (2026-01-10)
- Google Nano Banana Pro integration (gemini-3-pro-image-preview)
- generate_image tool with flexible parameters (aspect ratio, resolution)
- Automatic delivery via _file_contents pattern
- Cost tracking ($0.134 for 1K/2K, $0.240 for 4K)
- Documentation: docs/phase-1.7-image-generation.md
- **Testing**: 15 comprehensive tests (all passing), production verified
- **Files**: core/tools/generate_image.py, tests/core/tools/test_generate_image.py, updated registry, system prompt, dependencies

**Phase 2.1 (Payment System):** ✅ Complete (2026-01-10)
- Telegram Stars payment integration with commission handling
- User balance system ($0.10 starter, soft balance check)
- Payment handlers (/pay with packages, /refund, /balance, /paysupport)
- Admin commands (/topup, /set_margin for privileged users)
- Balance middleware (blocks requests when balance ≤ 0)
- Cost tracking integration (Claude API, tools, external APIs)
- Full audit trail (payments, balance_operations tables)
- Refund support (30-day window with validation)
- Commission formula: y = x * (1 - 0.35 - 0.15 - k3)
- **Database**: 2 new models (Payment, BalanceOperation), migration 007
- **Testing**: 46 integration tests, 566 total tests passing (100% pass rate)
- **Files**: 17 new files (models, repos, services, handlers, middleware, tests)
- Documentation: docs/phase-2.1-payment-system.md

**Phase 3.1 (Monitoring):** ✅ Complete (2026-01-11)
- Loki + Promtail for centralized logging (30 days retention)
- Prometheus for metrics collection
- Grafana at :3000 (unified UI for logs & metrics)
- CloudBeaver at :8978 (PostgreSQL web admin)
- Pre-configured dashboards and datasources
- Documentation: docs/phase-3-infrastructure.md

**Next:** Phase 2.2 (DevOps Agent)
