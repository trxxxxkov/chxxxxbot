# Bot Structure

File structure of the Telegram bot and purpose of each module.

## Status
implemented (Phase 1.2 - PostgreSQL integration complete)

---

## Overview

The bot is a Python application on aiogram 3.24, running in a Docker container. Uses polling to receive updates from Telegram.

```
bot/
├── main.py                       # Entry point
├── config.py                     # Constants and settings
├── telegram/                     # Telegram API
│   ├── handlers/                 # Command and message handlers
│   │   ├── start.py              # /start, /help commands
│   │   ├── claude.py             # Claude handler (catch-all) - Phase 1.3
│   │   ├── model.py              # /model command - Phase 1.4
│   │   ├── personality.py        # /personality command - Phase 1.4
│   │   ├── files.py              # File attachments - Phase 1.5
│   │   ├── media_handlers.py     # Voice/audio/video - Phase 1.6
│   │   ├── payment.py            # /pay, /balance, /refund - Phase 2.1
│   │   └── admin.py              # /topup, /set_margin - Phase 2.1
│   ├── middlewares/              # Middleware
│   │   ├── logging_middleware.py     # Request logging
│   │   ├── database_middleware.py    # Session management
│   │   └── balance_middleware.py     # Balance check - Phase 2.1
│   ├── keyboards/                # Keyboards (inline, reply)
│   └── loader.py                 # Bot, Dispatcher setup
├── core/                         # LLM providers
│   ├── base.py                   # Abstract interface
│   └── claude/                   # Claude implementation (Phase 1.3)
├── db/                           # PostgreSQL (Phase 1.2)
│   ├── engine.py                 # Async engine, connection pool
│   ├── models/                   # SQLAlchemy ORM models
│   │   ├── base.py               # Base, TimestampMixin
│   │   ├── user.py               # User model (Telegram users)
│   │   ├── chat.py               # Chat model (chats/groups/channels)
│   │   ├── thread.py             # Thread model (conversation threads)
│   │   └── message.py            # Message model (with JSONB attachments)
│   └── repositories/             # Repository pattern (CRUD)
│       ├── base.py               # BaseRepository[T] generic
│       ├── user_repository.py    # User operations
│       ├── chat_repository.py    # Chat operations
│       ├── thread_repository.py  # Thread operations
│       └── message_repository.py # Message operations
├── utils/                        # Utilities
│   └── structured_logging.py     # structlog configuration
├── Dockerfile
└── pyproject.toml

postgres/                         # Alembic migrations
├── alembic.ini                   # Alembic config
└── alembic/
    ├── env.py                    # Migration environment (async)
    ├── script.py.mako            # Migration template
    └── versions/                 # Migration files
```

**Important:** NO __init__.py files - Python 3.12+ namespace packages with direct imports.

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

**Location:** `bot/telegram/`

| File/folder | Description |
|-------------|-------------|
| `loader.py` | Creating Bot and Dispatcher objects, registering middleware and handlers |
| `handlers/` | Command and message handlers |
| `middlewares/` | Request processing middleware |
| `keyboards/` | Inline and reply keyboards |

#### telegram/loader.py
**Purpose:** Bot and Dispatcher initialization.

**Responsibilities:**
- Create Bot instance with default properties (HTML parse mode)
- Create Dispatcher and register middleware
- Register all routers (handlers)

**Middleware Order (first registered = first executed):**
1. LoggingMiddleware - Request logging
2. DatabaseMiddleware - Session injection
3. BalanceMiddleware - Balance check (Phase 2.1)

#### telegram/handlers/
**Purpose:** Command and message handlers.

| File | Description | Phase |
|------|-------------|-------|
| `start.py` | /start and /help commands with database integration | 1.1 |
| `claude.py` | Claude handler (catch-all for text messages) | 1.3 |
| `model.py` | /model command for model selection | 1.4 |
| `personality.py` | /personality command for custom prompts | 1.4 |
| `files.py` | File attachment handling (images, PDFs) | 1.5 |
| `media_handlers.py` | Voice, audio, video message handlers | 1.6 |
| `payment.py` | /pay, /balance, /refund commands | 2.1 |
| `admin.py` | /topup, /set_margin (privileged users) | 2.1 |

**Note:** The original echo.py handler was replaced by claude.py in Phase 1.3.

**Handler Signature:**
```python
async def handler(message: Message, session: AsyncSession):
    # session is injected by DatabaseMiddleware
    user_repo = UserRepository(session)
    # ... use repositories ...
    # No commit needed - middleware handles it
```

#### telegram/middlewares/
**Purpose:** Request processing middleware.

| File | Middleware | Description | Phase |
|------|------------|-------------|-------|
| `logging_middleware.py` | LoggingMiddleware | Logs all updates with context (user_id, message_id, execution time) | 1.1 |
| `database_middleware.py` | DatabaseMiddleware | Injects AsyncSession, auto-commits on success, auto-rollbacks on error | 1.2 |
| `balance_middleware.py` | BalanceMiddleware | Checks user balance before processing paid requests | 2.1 |

**DatabaseMiddleware Flow:**
1. Create AsyncSession for update
2. Inject into `data['session']`
3. Call handler
4. **Auto-commit** on success
5. **Auto-rollback** on exception
6. Ensure cleanup

**Principle:** Handlers do not contain business logic — they call methods from `core/` and `db/repositories/`.

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
**Purpose:** PostgreSQL database layer with SQLAlchemy 2.0 async ORM.

**Location:** `bot/db/`

**Imports (NO __init__.py):**
```python
# Engine
from db.engine import init_db, dispose_db, get_session_factory

# Models
from db.models.user import User
from db.models.chat import Chat
from db.models.thread import Thread
from db.models.message import Message, MessageRole

# Repositories
from db.repositories.user_repository import UserRepository
from db.repositories.chat_repository import ChatRepository
from db.repositories.thread_repository import ThreadRepository
from db.repositories.message_repository import MessageRepository
```

#### db/engine.py
**Purpose:** Database connection pool management.

**Provides:**
- `init_db(database_url, echo)` - Initialize engine and session factory
- `dispose_db()` - Close all connections on shutdown
- `get_session()` - Context manager for manual session creation
- `get_session_factory()` - Get session factory for middleware

**Configuration:**
```python
# Connection pool (optimized for long-running bot)
pool_size=5          # Base connections
max_overflow=10      # Additional during spikes
pool_pre_ping=True   # Auto-reconnect on stale connections
pool_recycle=3600    # Recycle every hour
```

**Usage in main.py:**
```python
from config import get_database_url
from db.engine import init_db, dispose_db

async def main():
    database_url = get_database_url()  # Reads /run/secrets/postgres_password
    init_db(database_url, echo=False)
    # ... bot polling ...
    finally:
        await dispose_db()
```

#### db/models/
**Purpose:** SQLAlchemy ORM models (database schema).

| File | Model | Description |
|------|-------|-------------|
| `base.py` | Base, TimestampMixin | Base class for all models |
| `user.py` | User | Telegram users (PK: Telegram user_id) |
| `chat.py` | Chat | Chats/groups/channels (PK: Telegram chat_id) |
| `thread.py` | Thread | Conversation threads with Bot API 9.3 support |
| `message.py` | Message | Messages with JSONB attachments (composite PK) |

**Key Design Decisions:**
- **Telegram IDs as PKs** - No surrogate keys where Telegram provides globally unique IDs
- **Composite Keys** - Messages use (chat_id, message_id)
- **JSONB + Denormalization** - Attachments in JSONB with boolean flags for fast queries
- **Bot API 9.3** - Full field coverage including forum topics (thread_id, is_forum)

**Schema Overview:**
```
users (id=telegram_user_id)
  ↓ 1:N
threads (id, user_id, chat_id, thread_id)
  ↓ 1:N
messages (chat_id, message_id) ← composite PK
  ↓ N:1
chats (id=telegram_chat_id)
```

**See:** [phase-1.2-database.md](phase-1.2-database.md) for complete schema documentation.

#### db/repositories/
**Purpose:** Repository pattern for database operations (abstraction layer).

| File | Repository | Description |
|------|------------|-------------|
| `base.py` | BaseRepository[T] | Generic CRUD operations |
| `user_repository.py` | UserRepository | User-specific operations |
| `chat_repository.py` | ChatRepository | Chat-specific operations |
| `thread_repository.py` | ThreadRepository | Thread management |
| `message_repository.py` | MessageRepository | Message and attachment handling |

**Key Methods:**
```python
# UserRepository
await user_repo.get_or_create(telegram_id, first_name, ...)
await user_repo.update_last_seen(telegram_id)

# ThreadRepository
await thread_repo.get_or_create_thread(chat_id, user_id, thread_id)
await thread_repo.get_active_thread(chat_id, user_id, thread_id)

# MessageRepository
await msg_repo.create_message(chat_id, message_id, thread_id, ...)
await msg_repo.get_thread_messages(thread_id, limit=100)
await msg_repo.add_tokens(chat_id, message_id, input_tokens, output_tokens)
```

**Principle:**
- Handlers work only through repositories, not directly with models
- Repositories do NOT commit - DatabaseMiddleware handles commit/rollback
- Ready for Redis caching (Phase 3)

**See:** [phase-1.2-database.md](phase-1.2-database.md) for usage examples.

---

### utils/
**Purpose:** Helper utilities.

| File | Description |
|------|-------------|
| `structured_logging.py` | structlog configuration for JSON logs |

**Extension:** When common functions appear — add them here.

---

### postgres/
**Purpose:** Alembic database migrations.

**Location:** `postgres/` (separate from bot code)

| File/folder | Description |
|-------------|-------------|
| `alembic.ini` | Alembic configuration |
| `alembic/env.py` | Migration environment (async support) |
| `alembic/script.py.mako` | Migration template |
| `alembic/versions/` | Migration files |

**Key Features:**
- Async migration support
- Direct model imports (NO __init__.py)
- Auto-run on bot startup (see Dockerfile CMD)

**Commands:**
```bash
# Generate migration from model changes
docker compose exec bot sh -c "cd /postgres && alembic revision --autogenerate -m 'description'"

# Apply migrations
docker compose exec bot sh -c "cd /postgres && alembic upgrade head"

# Show current version
docker compose exec bot sh -c "cd /postgres && alembic current"
```

---

## Data Flow

```
Telegram
  ↓
main.py (polling)
  ↓
telegram/middlewares/
  ├── LoggingMiddleware (logging)
  └── DatabaseMiddleware (session injection)
        ↓
telegram/handlers/ (receives: message, session)
        ↓
db/repositories/ (use session)
        ↓
db/models/ (SQLAlchemy ORM)
        ↓
PostgreSQL
        ↓
core/ (LLM) - Phase 1.3
        ↓
telegram/handlers/ (send response)
        ↓
DatabaseMiddleware (auto-commit)
        ↓
Telegram
```

**Session Lifecycle:**
1. DatabaseMiddleware creates AsyncSession
2. Session injected into handler via `data['session']`
3. Handler uses repositories with session
4. On success: middleware commits transaction
5. On error: middleware rollbacks transaction
6. Session cleaned up automatically

---

## Module Dependencies

```
main.py
  ├── config.py (get_database_url)
  ├── utils/structured_logging.py
  ├── db/engine.py (init_db, dispose_db)
  └── telegram/loader.py
        ├── telegram/middlewares/
        │   ├── logging_middleware.py
        │   └── database_middleware.py
        │         └── db/engine.py (get_session_factory)
        └── telegram/handlers/*
              ├── db/repositories/*
              │     ├── db/models/*
              │     └── sqlalchemy (AsyncSession)
              └── core/* (Phase 1.3)
```

**Dependency Rules:**
1. Dependencies only go down the hierarchy
2. Lower-level modules do not import upper-level modules
3. Handlers do NOT import models directly - only repositories
4. Repositories do NOT import handlers - only models
5. Models do NOT import anything from bot code - only SQLAlchemy

**Import Examples:**
```python
# ✅ CORRECT
from db.repositories.user_repository import UserRepository
from db.models.message import MessageRole

# ❌ WRONG - don't import models in handlers
from db.models.user import User  # Use UserRepository instead

# ❌ WRONG - don't create sessions manually
async with get_session() as session:  # Use middleware-injected session
```
