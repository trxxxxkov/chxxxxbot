# Bot Structure

File structure of the Telegram bot and purpose of each module.

## Status
agreed

---

## Overview

The bot is a Python application on aiogram 3.24, running in a Docker container. Uses polling to receive updates from Telegram.

```
bot/
├── main.py                 # Entry point
├── config.py               # Constants and settings
├── telegram/               # Telegram API
│   ├── handlers/           # Handlers
│   ├── middlewares/        # Middleware
│   ├── keyboards/          # Keyboards
│   └── loader.py           # Bot, Dispatcher
├── core/                   # LLM providers
│   ├── base.py             # Abstract interface
│   └── claude/             # Claude implementation
├── db/                     # PostgreSQL
│   ├── engine.py           # Connection
│   ├── models/             # SQLAlchemy models
│   └── repositories/       # CRUD
├── utils/                  # Utilities
│   └── logging.py          # structlog
├── Dockerfile
└── pyproject.toml
```

---

## Modules

### main.py
**Purpose:** Application entry point.

**Responsibilities:**
- Reading secrets from `/run/secrets/`
- Initializing logger (calling `utils/logging.py`)
- Starting polling

**Depends on:** config.py, utils/logging.py, telegram/loader.py

---

### config.py
**Purpose:** Centralized storage for constants and settings.

**Contains:**
- Timeouts, limits, default values
- Settings that are not secrets

**Does not contain:** Secrets (tokens, passwords) — they are read in main.py

---

### telegram/
**Purpose:** Everything related to Telegram Bot API.

| File/folder | Description |
|-------------|-------------|
| `loader.py` | Creating Bot and Dispatcher objects |
| `handlers/` | Command and message handlers |
| `middlewares/` | Request logging, dependency injection |
| `keyboards/` | Inline and reply keyboards |

**Principle:** Handlers do not contain business logic — they call methods from `core/` and `db/`.

---

### core/
**Purpose:** LLM providers — core functionality of the bot.

| File/folder | Description |
|-------------|-------------|
| `base.py` | Abstract `LLMProvider` interface |
| `claude/` | Claude API implementation |

**Extension:** To add a new provider (OpenAI, Google), create a folder with implementation of the interface from `base.py`.

---

### db/
**Purpose:** Working with PostgreSQL.

| File/folder | Description |
|-------------|-------------|
| `engine.py` | Async engine, session factory |
| `models/` | SQLAlchemy models (tables) |
| `repositories/` | CRUD operations for each model |

**Principle:** Handlers work only through repositories, not directly with models.

---

### utils/
**Purpose:** Helper utilities.

| File | Description |
|------|-------------|
| `logging.py` | structlog configuration for JSON logs |

**Extension:** When common functions appear — add them here.

---

## Data Flow

```
Telegram → main.py (polling) → telegram/handlers/
                                    ↓
                              core/ (LLM)
                                    ↓
                              db/ (persistence)
                                    ↓
                              telegram/handlers/ → Telegram
```

---

## Module Dependencies

```
main.py
  ├── config.py
  ├── utils/logging.py
  └── telegram/loader.py
        └── telegram/handlers/*
              ├── core/*
              └── db/repositories/*
                    └── db/models/*
```

**Rule:** Dependencies only go down the hierarchy. Lower-level modules do not import upper-level modules.
