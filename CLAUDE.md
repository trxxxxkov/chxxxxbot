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
│   │   └── logging.py          # structlog configuration
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

### Documentation-first

Before writing code — planning and documentation.

**Process:**
1. Discuss component architecture and structure
2. Document agreed plan in `docs/`
3. Implement code according to plan
4. On changes — update documentation

**`docs/` folder:**
- Stores plans for each component
- Source of truth for architectural decisions
- Optimized for LLM-agents (see `docs/README.md`)
- Always kept up to date

**Rule:** Any code change affecting architecture must be reflected in the corresponding document.

**README.md:** Contains project maintenance commands (start, logs, debug). Update when infrastructure changes.

---

## Current Status

**Phase 1.1:** Bot structure — agreed, created
