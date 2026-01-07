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

#### 1. Minimal Bot
| Component | Technology |
|-----------|------------|
| Framework | aiogram 3.24 |
| Telegram API | Bot API 9.3 (polling) |
| Python | 3.12+ |
| Validation/models | Pydantic v2 |
| Containerization | Docker + Docker Compose |

#### 2. PostgreSQL
| Component | Technology |
|-----------|------------|
| Database | PostgreSQL 16 |
| Async driver | asyncpg |
| ORM | SQLAlchemy 2.0 (async) |
| Migrations | Alembic |

#### 3. Claude Integration
| Component | Technology |
|-----------|------------|
| SDK | anthropic (official) |

### Phase 2 — Telegram Features Expansion
- Threads (Bot API 9.3)
- Message streaming (Bot API 9.3)
- Payments (Telegram Stars)
- Keyboards (inline, reply)
- Modalities (text, photo, video, audio, files)
- Service messages
- Commands, menus

### Phase 3 — Infrastructure

#### Cache
| Component | Technology |
|-----------|------------|
| Cache | Redis 7 |
| Async client | redis-py (async) |

#### Monitoring
| Component | Technology |
|-----------|------------|
| Dashboards | Grafana |
| Metrics | Prometheus |
| Logs | Loki |

#### DB Admin
| Component | Technology |
|-----------|------------|
| Web interface | CloudBeaver |

#### Other LLM Providers
- OpenAI
- Google

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

**Next:** Phase 1.3 (Claude Integration)
