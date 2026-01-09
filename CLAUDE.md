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
│   ├── config.py               # Constants, app settings
│   ├── telegram/               # Telegram API integration
│   │   ├── handlers/           # Message and command handlers
│   │   ├── middlewares/        # Middleware (logging, DI)
│   │   ├── keyboards/          # Inline and reply keyboards
│   │   └── loader.py           # Bot, Dispatcher initialization
│   ├── core/                   # LLM providers (core functionality)
│   │   ├── base.py             # Abstract provider interface
│   │   └── claude/             # Claude implementation
│   ├── db/                     # PostgreSQL integration
│   │   ├── engine.py           # Async engine, session
│   │   ├── models/             # SQLAlchemy models
│   │   └── repositories/       # CRUD operations
│   ├── utils/                  # Helper utilities
│   │   └── structured_logging.py  # structlog configuration
│   ├── Dockerfile
│   └── pyproject.toml
│
├── postgres/                   # Container: PostgreSQL
│   ├── alembic/                # Migrations
│   └── init.sql                # Initial schema
│
├── grafana/                    # Container: Grafana
│   └── provisioning/           # Dashboards, datasources
│
├── loki/                       # Container: Loki
│   └── loki-config.yaml
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
- ⏸️ Extended Thinking parameter DISABLED (requires Phase 1.5 DB schema)

**Phase 1.4.4 - Best Practices & Optimization:**
- ✅ System prompt rewritten for Claude 4 style
- ✅ Effort parameter for Opus 4.5 (`effort: "high"`)
- ✅ Token Counting API for large requests (>150K tokens)
- ✅ Stop reason handling (context overflow, refusal, max_tokens)

**Documentation:**
- ✅ 15 Claude API pages reviewed and documented
- ✅ Best practices adopted (explicit instructions, thinking vocabulary)
- ✅ See [docs/phase-1.4-claude-advanced-api.md](docs/phase-1.4-claude-advanced-api.md)

#### 1.5 Multimodal + Tools 📋 Planned
**Multimodal support:**
- Images (vision via Files API)
- Voice messages (transcription + processing)
- PDF documents (text + visual analysis)
- Arbitrary files (via tools)

**Tools framework:**
- Tool Runner (SDK beta) for all custom tools
- analyze_image, analyze_pdf (Claude Vision/PDF API)
- web_search, web_fetch (server-side tools)
- Code execution (external service: E2B/Modal/self-hosted)
- Modular tool architecture (easy to add new tools)

**Database schema:**
- user_files table (telegram_file_id, claude_file_id, metadata)
- thinking_blocks column in messages (for Extended Thinking)
- Files API lifecycle management (24h TTL)

**Out of scope:**
- Claude's code execution tool (no internet access)
- Citations feature (not critical for Phase 1.5)
- RAG with vector DB (Phase 1.6)

### Phase 2 — Telegram Features Expansion

#### 2.1 Payment System 📋 Planned
**User balance:**
- USD balance in database (User model)
- Pre-request validation (block if insufficient funds)
- Real-time cost calculation

**Telegram Stars integration:**
- Payment flow (deposit via Stars)
- Refund mechanism (by transaction_id)
- Invoice generation

**Admin features:**
- Privileged users list (in secrets)
- Manual balance adjustment commands
- Balance management by username/user_id

**Cost tracking:**
- All API calls tracked (LLM, tools, external APIs)
- Cost attribution per user
- Cost reporting and analytics

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

#### 3.1 Cache
| Component | Technology |
|-----------|------------|
| Cache | Redis 7 |
| Async client | redis-py (async) |

#### 3.2 Monitoring
| Component | Technology |
|-----------|------------|
| Dashboards | Grafana |
| Metrics | Prometheus |
| Logs | Loki |

#### 3.3 DB Admin
| Component | Technology |
|-----------|------------|
| Web interface | CloudBeaver |

#### 3.4 Other LLM Providers
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

**Current Test Coverage:** 201 tests across all components ✅

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
  - Extended Thinking parameter DISABLED until Phase 1.5 (requires DB schema)
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

**Next:** Phase 1.5 (Multimodal + Tools)
