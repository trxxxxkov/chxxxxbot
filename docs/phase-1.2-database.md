# Database Architecture

PostgreSQL database layer with SQLAlchemy 2.0 async ORM, repository pattern, and automatic session management. Uses Telegram IDs as primary keys, JSONB for attachments, and ready for Redis caching.

## Status
**implemented** (Phase 1.2 complete)

---

## Quick Reference

**Files to import:**
```python
# Engine
from db.engine import init_db, dispose_db, get_session_factory

# Models (8 total)
from db.models.user import User
from db.models.chat import Chat
from db.models.thread import Thread
from db.models.message import Message, MessageRole
from db.models.user_file import UserFile
from db.models.payment import Payment
from db.models.balance_operation import BalanceOperation
from db.models.tool_call import ToolCall

# Repositories (8 total)
from db.repositories.user_repository import UserRepository
from db.repositories.chat_repository import ChatRepository
from db.repositories.thread_repository import ThreadRepository
from db.repositories.message_repository import MessageRepository
from db.repositories.user_file_repository import UserFileRepository
from db.repositories.payment_repository import PaymentRepository
from db.repositories.balance_operation_repository import BalanceOperationRepository
from db.repositories.tool_call_repository import ToolCallRepository
```

**NO __init__.py files** - Python 3.12+ namespace packages with direct imports.

---

## Architecture Overview

```
Handler (telegram/handlers/)
    ↓ receives session via middleware
Repository (db/repositories/)
    ↓ uses AsyncSession
Model (db/models/)
    ↓ SQLAlchemy ORM
PostgreSQL Database
```

**Key Design Decisions:**
1. **Telegram IDs as PKs** - No surrogate keys where Telegram provides globally unique IDs
2. **Composite Keys** - Messages use (chat_id, message_id) matching Telegram's identification
3. **JSONB + Denormalization** - Attachments in JSONB with boolean flags for fast queries
4. **Repository Pattern** - Abstraction layer ready for Redis caching (Phase 3)
5. **Async Everything** - asyncpg driver, async engine, async sessions

---

## Database Engine (bot/db/engine.py)

### Purpose
Manages database connection pool and session lifecycle.

### Configuration
```python
# Connection pool settings (optimized for long-running Telegram bot)
pool_size=5          # Base connections
max_overflow=10      # Additional connections during spikes
pool_pre_ping=True   # Auto-reconnect on stale connections
pool_recycle=3600    # Recycle every hour
```

### Usage in main.py
```python
from config import get_database_url
from db.engine import init_db, dispose_db

async def main():
    # Startup
    database_url = get_database_url()  # Reads /run/secrets/postgres_password
    init_db(database_url, echo=False)

    # ... bot polling ...

    # Shutdown
    finally:
        await dispose_db()
```

### Session Management
**Do NOT use get_session() directly in handlers!**
Session is injected by DatabaseMiddleware automatically.

```python
# ❌ WRONG - don't do this
async with get_session() as session:
    user_repo = UserRepository(session)

# ✅ CORRECT - session injected by middleware
async def handler(message: Message, session: AsyncSession):
    user_repo = UserRepository(session)
```

---

## Models (bot/db/models/)

All models inherit from `Base` (DeclarativeBase). Models with timestamps also use `TimestampMixin`.

### Base Classes (bot/db/models/base.py)

```python
from db.models.base import Base, TimestampMixin

# Base - required for all models
class MyModel(Base):
    __tablename__ = "my_table"

# TimestampMixin - adds created_at, updated_at
class MyModel(Base, TimestampMixin):
    __tablename__ = "my_table"
```

**TimestampMixin provides:**
- `created_at: datetime` - Auto-set on insert
- `updated_at: datetime` - Auto-updated on changes

---

### User Model (bot/db/models/user.py)

**Purpose:** Stores Telegram user information with full Bot API 9.3 field coverage.

**Primary Key:** `id` (Telegram user_id, globally unique)

**Key Fields:**
```python
id: int                          # Telegram user ID (PK)
is_bot: bool                     # Bot account flag
first_name: str                  # Required by Telegram
last_name: Optional[str]         # Family name
username: Optional[str]          # @username (unique)
language_code: Optional[str]     # IETF language tag (e.g., "en")
is_premium: bool                 # Telegram Premium status
added_to_attachment_menu: bool   # Bot in attachment menu

# Bot-specific fields
current_model: str               # Selected LLM model (default: "claude")
first_seen_at: datetime          # When user first used bot
last_seen_at: datetime           # Last activity timestamp
```

**Relationships:**
- `users.id` ← `threads.user_id` (one-to-many)
- `users.id` ← `messages.from_user_id` (one-to-many)

**Indexes:**
- `idx_users_username` on username (partial: WHERE username IS NOT NULL)
- `idx_users_last_seen` on last_seen_at

**Usage Example:**
```python
user = User(
    id=123456789,  # Telegram user_id
    first_name="John",
    username="john_doe",
    language_code="en",
    is_premium=True,
)
```

---

### Chat Model (bot/db/models/chat.py)

**Purpose:** Stores Telegram chat information (private/group/supergroup/channel).

**Primary Key:** `id` (Telegram chat_id, globally unique)

**Key Fields:**
```python
id: int                    # Telegram chat ID (PK)
type: str                  # "private", "group", "supergroup", "channel"
title: Optional[str]       # Chat title (groups/channels)
username: Optional[str]    # Public @chatname
first_name: Optional[str]  # First name (private chats only)
last_name: Optional[str]   # Last name (private chats only)
is_forum: bool             # Supergroup has topics enabled (Bot API 9.3)
```

**Chat ID Ranges (from Telegram API):**
- Users: 1 to 1099511627775 (positive)
- Groups: -1 to -999999999999 (negative)
- Supergroups/Channels: -1997852516352 to -1000000000001

**Relationships:**
- `chats.id` ← `threads.chat_id` (one-to-many)
- `chats.id` ← `messages.chat_id` (one-to-many)

**Indexes:**
- `idx_chats_type` on type
- `idx_chats_username` on username (partial)

---

### Thread Model (bot/db/models/thread.py)

**Purpose:** Conversation threads for LLM context management with Telegram thread_id support.

**Primary Key:** `id` (auto-increment BIGSERIAL, internal use only)

**Unique Constraint:** (chat_id, user_id, COALESCE(thread_id, 0))
- Each user has ONE thread per topic in each chat

**Key Fields:**
```python
id: int                       # Internal ID (auto-increment)
chat_id: int                  # FK → chats.id
user_id: int                  # FK → users.id
thread_id: Optional[int]      # Telegram thread/topic ID (NULL = main chat)
title: Optional[str]          # Thread title
model_name: str               # LLM model (default: "claude")
system_prompt: Optional[str]  # Custom system prompt
```

**Thread Logic:**
- `thread_id = NULL` → main chat (no forum topic)
- `thread_id = 123` → Telegram forum topic with ID 123
- Each user has separate threads per topic for personalized LLM context
- **LLM context = all messages in this thread**

**Foreign Keys:**
- `chat_id` → chats.id ON DELETE CASCADE
- `user_id` → users.id ON DELETE CASCADE

**Indexes:**
- `idx_threads_chat_user` on (chat_id, user_id)
- `idx_threads_thread_id` on thread_id (partial: WHERE thread_id IS NOT NULL)

**Usage Example:**
```python
# Main chat thread
thread = Thread(
    chat_id=123,
    user_id=456,
    thread_id=None,  # main chat
    model_name="claude",
)

# Forum topic thread
thread = Thread(
    chat_id=123,
    user_id=456,
    thread_id=789,  # forum topic ID
    title="General Discussion",
    model_name="claude",
)
```

---

### Message Model (bot/db/models/message.py)

**Purpose:** Stores all Telegram messages for conversation history and LLM context.

**Primary Key:** Composite (chat_id, message_id)
- Matches Telegram's identification scheme
- Message IDs are sequential per chat

**Key Fields:**
```python
# Primary key
chat_id: int                  # Telegram chat ID (PK part 1)
message_id: int               # Telegram message ID (PK part 2)

# Foreign keys
thread_id: Optional[int]      # FK → threads.id
from_user_id: Optional[int]   # FK → users.id (NULL for channels)

# Message metadata
date: int                     # Unix timestamp when sent
edit_date: Optional[int]      # Unix timestamp of last edit
role: MessageRole             # USER, ASSISTANT, or SYSTEM (for LLM API)

# Content
text_content: Optional[str]   # Text content
caption: Optional[str]        # Media caption

# Reply info
reply_to_message_id: Optional[int]  # Replied message ID
media_group_id: Optional[str]       # Groups related media

# Denormalized attachment flags (for FAST queries with B-tree indexes)
has_photos: bool              # Has photo attachments
has_documents: bool           # Has document attachments
has_voice: bool               # Has voice messages
has_video: bool               # Has video attachments
attachment_count: int         # Total attachments

# JSONB for full metadata (for COMPLEX queries with GIN index)
attachments: dict             # JSONB array with full attachment data

# Token tracking
input_tokens: Optional[int]   # LLM input tokens (for billing)
output_tokens: Optional[int]  # LLM output tokens (for billing)

created_at: int               # Record creation timestamp (Unix)
```

**MessageRole Enum:**
```python
class MessageRole(str, enum.Enum):
    USER = "user"           # Message from user
    ASSISTANT = "assistant" # Response from LLM
    SYSTEM = "system"       # System prompt
```

**Attachments JSONB Schema:**
```json
[
  {
    "type": "photo",
    "file_id": "AgACAgIAAxkBAAI...",
    "file_unique_id": "AQADw...",
    "width": 1280,
    "height": 720,
    "file_size": 102400
  },
  {
    "type": "document",
    "file_id": "BQACAgIAAxkBAAI...",
    "file_unique_id": "AQADx...",
    "file_name": "report.pdf",
    "mime_type": "application/pdf",
    "file_size": 512000
  }
]
```

**Why JSONB + Denormalization?**
- **Boolean flags** use B-tree indexes → FAST simple queries ("give me all messages with photos")
- **JSONB** uses GIN index → COMPLEX metadata queries ("find documents larger than 1MB")
- Best of both worlds for performance

**Foreign Keys:**
```sql
chat_id → chats.id ON DELETE CASCADE
from_user_id → users.id ON DELETE SET NULL
thread_id → threads.id ON DELETE SET NULL
(chat_id, reply_to_message_id) → messages(chat_id, message_id) ON DELETE SET NULL
```

**Indexes:**
- `idx_messages_thread` on thread_id (partial)
- `idx_messages_from_user` on from_user_id (partial)
- `idx_messages_date` on date
- `idx_messages_role` on role
- `idx_messages_media_group` on media_group_id (partial)
- `idx_messages_has_photos` on has_photos (partial: WHERE has_photos = TRUE)
- `idx_messages_has_documents` on has_documents (partial)
- `idx_messages_has_voice` on has_voice (partial)
- `idx_messages_attachments_gin` on attachments (GIN, jsonb_path_ops)

---

### UserFile Model (bot/db/models/user_file.py)

**Purpose:** Stores uploaded files via Claude Files API with Telegram file_id mapping.

**Primary Key:** `id` (auto-increment BIGSERIAL)

**Key Fields:**
```python
id: int                       # Internal ID (auto-increment)
thread_id: int                # FK → threads.id
filename: str                 # Original filename
file_type: str                # MIME type
file_size: int                # Size in bytes
telegram_file_id: str         # Telegram file_id for re-download
claude_file_id: Optional[str] # Claude Files API ID
content_hash: str             # SHA-256 hash for deduplication
is_available: bool            # Still available in Claude Files API
created_at: datetime          # Upload timestamp
expires_at: Optional[datetime] # Claude file expiration (24h TTL)
```

**Indexes:**
- `idx_user_files_thread` on thread_id
- `idx_user_files_claude_id` on claude_file_id (unique, partial)
- `idx_user_files_content_hash` on content_hash

---

### Payment Model (bot/db/models/payment.py)

**Purpose:** Records Telegram Stars payments for balance top-up.

**Primary Key:** `id` (auto-increment BIGSERIAL)

**Key Fields:**
```python
id: int                              # Internal ID
user_id: int                         # FK → users.id
telegram_payment_charge_id: str      # Telegram payment ID (unique)
provider_payment_charge_id: str      # Provider payment ID
total_amount: int                    # Amount in Stars
currency: str                        # "XTR" (Stars)
usd_amount: Decimal                  # Converted USD amount
status: PaymentStatus                # PENDING, COMPLETED, REFUNDED
created_at: datetime                 # Payment timestamp
```

**PaymentStatus Enum:**
```python
class PaymentStatus(str, enum.Enum):
    PENDING = "pending"
    COMPLETED = "completed"
    REFUNDED = "refunded"
```

**Indexes:**
- `idx_payments_user` on user_id
- `idx_payments_telegram_charge` on telegram_payment_charge_id (unique)

---

### BalanceOperation Model (bot/db/models/balance_operation.py)

**Purpose:** Audit trail for all balance changes (charges, payments, refunds, admin topups).

**Primary Key:** `id` (auto-increment BIGSERIAL)

**Key Fields:**
```python
id: int                      # Internal ID
user_id: int                 # FK → users.id
amount: Decimal              # Change amount (positive or negative)
balance_before: Decimal      # Balance before operation
balance_after: Decimal       # Balance after operation
operation_type: str          # "charge", "payment", "refund", "admin_topup"
description: str             # Human-readable description
reference_id: Optional[str]  # Related entity ID (payment_id, thread_id)
created_at: datetime         # Operation timestamp
```

**Indexes:**
- `idx_balance_ops_user` on user_id
- `idx_balance_ops_created` on created_at
- `idx_balance_ops_type` on operation_type

---

### ToolCall Model (bot/db/models/tool_call.py)

**Purpose:** Records tool executions for analytics and debugging.

**Primary Key:** `id` (auto-increment BIGSERIAL)

**Key Fields:**
```python
id: int                      # Internal ID
thread_id: int               # FK → threads.id
user_id: int                 # FK → users.id
tool_name: str               # Tool identifier (e.g., "execute_python")
tool_input: dict             # JSONB - input parameters
tool_output: Optional[dict]  # JSONB - output result
status: str                  # "success", "error", "timeout"
duration_ms: int             # Execution time in milliseconds
cost_usd: Optional[Decimal]  # Estimated cost
error_message: Optional[str] # Error details if failed
created_at: datetime         # Execution timestamp
```

**Indexes:**
- `idx_tool_calls_thread` on thread_id
- `idx_tool_calls_user` on user_id
- `idx_tool_calls_tool_name` on tool_name
- `idx_tool_calls_status` on status

---

## Repositories (bot/db/repositories/)

Repository pattern provides abstraction layer for database operations. Ready for Redis caching in Phase 3.

### BaseRepository (bot/db/repositories/base.py)

Generic base class with common CRUD operations.

```python
from db.repositories.base import BaseRepository

class MyRepository(BaseRepository[MyModel]):
    def __init__(self, session: AsyncSession):
        super().__init__(session, MyModel)

    # Now you have:
    # - get_by_id(id_value)
    # - get_all(limit, offset)
    # - create(entity)
    # - update(entity)
    # - delete(entity)
```

**Important:** Repository methods do NOT commit. Commit is handled by DatabaseMiddleware.

---

### UserRepository (bot/db/repositories/user_repository.py)

**Location:** `bot/db/repositories/user_repository.py`

**Key Methods:**

```python
from db.repositories.user_repository import UserRepository

user_repo = UserRepository(session)

# Get user by Telegram ID
user = await user_repo.get_by_telegram_id(123456789)

# Get or create user (returns tuple: (User, was_created))
user, was_created = await user_repo.get_or_create(
    telegram_id=123456789,
    first_name="John",
    username="john_doe",
    language_code="en",
    is_premium=True,
)

# Update last seen timestamp
await user_repo.update_last_seen(123456789)

# Get total user count
count = await user_repo.get_users_count()
```

**get_or_create() Behavior:**
- If user exists: **updates** all profile fields, sets last_seen_at, returns (user, False)
- If user doesn't exist: **creates** new user, returns (user, True)

**Usage in Handler:**
```python
async def start_handler(message: Message, session: AsyncSession):
    user_repo = UserRepository(session)

    user, was_created = await user_repo.get_or_create(
        telegram_id=message.from_user.id,
        first_name=message.from_user.first_name,
        # ... other fields
    )

    if was_created:
        await message.answer("Welcome!")
    else:
        await message.answer("Welcome back!")

    # No commit needed - middleware handles it
```

---

### ChatRepository (bot/db/repositories/chat_repository.py)

**Key Methods:**

```python
from db.repositories.chat_repository import ChatRepository

chat_repo = ChatRepository(session)

# Get or create chat
chat, was_created = await chat_repo.get_or_create(
    telegram_id=-123456789,
    chat_type="supergroup",
    title="My Group",
    is_forum=True,
)

# Get chat by username
chat = await chat_repo.get_by_username("my_channel")

# Get chats by type
chats = await chat_repo.get_by_type("supergroup", limit=50)

# Get forum chats only
forums = await chat_repo.get_forum_chats(limit=50)
```

---

### ThreadRepository (bot/db/repositories/thread_repository.py)

**Key Methods:**

```python
from db.repositories.thread_repository import ThreadRepository

thread_repo = ThreadRepository(session)

# Get or create thread (respects unique constraint)
thread, was_created = await thread_repo.get_or_create_thread(
    chat_id=123,
    user_id=456,
    thread_id=None,  # main chat, or 789 for forum topic
    model_name="claude",
)

# Get active thread for user in specific chat/topic
thread = await thread_repo.get_active_thread(
    chat_id=123,
    user_id=456,
    thread_id=None,  # or topic ID
)

# Get all threads for user
threads = await thread_repo.get_user_threads(user_id=456, limit=10)

# Get all threads in chat
threads = await thread_repo.get_chat_threads(chat_id=123, limit=10)

# Update thread model
await thread_repo.update_thread_model(thread_id=1, model_name="openai")

# Delete thread
await thread_repo.delete_thread(thread_id=1)
```

**Finding Thread for Current Message:**
```python
async def handle_message(message: Message, session: AsyncSession):
    thread_repo = ThreadRepository(session)

    # Get thread_id from message (Bot API 9.3)
    telegram_thread_id = message.message_thread_id  # None for main chat

    # Find or create thread
    thread, _ = await thread_repo.get_or_create_thread(
        chat_id=message.chat.id,
        user_id=message.from_user.id,
        thread_id=telegram_thread_id,
    )

    # Now load conversation history for LLM context
```

---

### MessageRepository (bot/db/repositories/message_repository.py)

**Key Methods:**

```python
from db.repositories.message_repository import MessageRepository
from db.models.message import MessageRole

msg_repo = MessageRepository(session)

# Get message by composite key
message = await msg_repo.get_message(chat_id=123, message_id=456)

# Create message with attachments
message = await msg_repo.create_message(
    chat_id=123,
    message_id=456,
    thread_id=1,
    from_user_id=789,
    date=1234567890,
    role=MessageRole.USER,
    text_content="Hello!",
    attachments=[
        {
            "type": "photo",
            "file_id": "AgACAgIAAxkBAAI...",
            "width": 1280,
            "height": 720,
        }
    ],
)
# Automatically sets has_photos=True, attachment_count=1

# Update message (for edits)
await msg_repo.update_message(
    chat_id=123,
    message_id=456,
    text_content="Updated text",
    edit_date=1234567900,
)

# Get conversation history for LLM (ordered by date ASC)
messages = await msg_repo.get_thread_messages(
    thread_id=1,
    limit=100,  # or None for all
)

# Get recent messages in chat (ordered by date DESC)
messages = await msg_repo.get_recent_messages(chat_id=123, limit=50)

# Track LLM token usage
await msg_repo.add_tokens(
    chat_id=123,
    message_id=456,
    input_tokens=150,
    output_tokens=200,
)

# Get messages with attachments
photos = await msg_repo.get_messages_with_attachments(
    thread_id=1,
    attachment_type="photo",  # or "document", "voice", "video", None
    limit=50,
)
```

**Saving Incoming Telegram Message:**
```python
async def save_telegram_message(
    telegram_msg: Message,  # aiogram Message
    session: AsyncSession,
    thread_id: int,
):
    msg_repo = MessageRepository(session)

    # Extract attachments
    attachments = []
    if telegram_msg.photo:
        # Get largest photo
        photo = telegram_msg.photo[-1]
        attachments.append({
            "type": "photo",
            "file_id": photo.file_id,
            "file_unique_id": photo.file_unique_id,
            "width": photo.width,
            "height": photo.height,
            "file_size": photo.file_size,
        })

    # Create message
    db_message = await msg_repo.create_message(
        chat_id=telegram_msg.chat.id,
        message_id=telegram_msg.message_id,
        thread_id=thread_id,
        from_user_id=telegram_msg.from_user.id,
        date=telegram_msg.date.timestamp(),
        role=MessageRole.USER,
        text_content=telegram_msg.text,
        attachments=attachments,
    )
```

---

### UserFileRepository (bot/db/repositories/user_file_repository.py)

**Key Methods:**

```python
from db.repositories.user_file_repository import UserFileRepository

file_repo = UserFileRepository(session)

# Create file record
file = await file_repo.create(
    thread_id=1,
    filename="image.png",
    file_type="image/png",
    file_size=102400,
    telegram_file_id="AgACAgIAAxkBAAI...",
    content_hash="sha256_hash",
)

# Get file by Claude ID
file = await file_repo.get_by_claude_id("file-abc123")

# Get files for thread
files = await file_repo.get_thread_files(thread_id=1, is_available=True)

# Mark file as expired
await file_repo.mark_expired(file_id=1)
```

---

### PaymentRepository (bot/db/repositories/payment_repository.py)

**Key Methods:**

```python
from db.repositories.payment_repository import PaymentRepository

payment_repo = PaymentRepository(session)

# Create payment record
payment = await payment_repo.create(
    user_id=123,
    telegram_payment_charge_id="charge_123",
    provider_payment_charge_id="provider_456",
    total_amount=100,  # Stars
    usd_amount=Decimal("2.00"),
)

# Get payment by Telegram charge ID
payment = await payment_repo.get_by_telegram_charge_id("charge_123")

# Get user payments
payments = await payment_repo.get_user_payments(user_id=123, limit=10)

# Mark as refunded
await payment_repo.mark_refunded(payment_id=1)
```

---

### BalanceOperationRepository (bot/db/repositories/balance_operation_repository.py)

**Key Methods:**

```python
from db.repositories.balance_operation_repository import BalanceOperationRepository

balance_op_repo = BalanceOperationRepository(session)

# Record balance operation
operation = await balance_op_repo.create(
    user_id=123,
    amount=Decimal("-0.05"),
    balance_before=Decimal("10.00"),
    balance_after=Decimal("9.95"),
    operation_type="charge",
    description="Claude API call",
    reference_id="thread_1",
)

# Get user's balance history
operations = await balance_op_repo.get_user_operations(
    user_id=123,
    limit=50,
    offset=0,
)

# Get operations by type
charges = await balance_op_repo.get_by_type(
    user_id=123,
    operation_type="charge",
    limit=100,
)
```

---

### ToolCallRepository (bot/db/repositories/tool_call_repository.py)

**Key Methods:**

```python
from db.repositories.tool_call_repository import ToolCallRepository

tool_repo = ToolCallRepository(session)

# Record tool call
tool_call = await tool_repo.create(
    thread_id=1,
    user_id=123,
    tool_name="execute_python",
    tool_input={"code": "print('hello')"},
    status="pending",
)

# Update with result
await tool_repo.update_result(
    tool_call_id=1,
    tool_output={"stdout": "hello"},
    status="success",
    duration_ms=1500,
    cost_usd=Decimal("0.001"),
)

# Get thread tool calls
calls = await tool_repo.get_thread_calls(thread_id=1, limit=50)

# Get tool usage stats
stats = await tool_repo.get_tool_stats(
    user_id=123,
    since=datetime.now() - timedelta(days=30),
)
```

---

## Database Middleware (bot/telegram/middlewares/database_middleware.py)

**Purpose:** Automatic session management for all handlers.

**How it works:**
1. Creates new AsyncSession for each update
2. Injects session into `data['session']`
3. Calls handler
4. **Auto-commits** on success
5. **Auto-rollbacks** on error
6. Ensures cleanup

**Registration (bot/telegram/loader.py):**
```python
from telegram.middlewares.database_middleware import DatabaseMiddleware

dispatcher.update.middleware(LoggingMiddleware())
dispatcher.update.middleware(DatabaseMiddleware())  # After logging
```

**Handler Receives Session:**
```python
async def my_handler(message: Message, session: AsyncSession):
    # session is injected by middleware
    user_repo = UserRepository(session)
    user = await user_repo.get_or_create(...)

    # No need to commit - middleware does it automatically
```

**Error Handling:**
```python
async def my_handler(message: Message, session: AsyncSession):
    user_repo = UserRepository(session)

    try:
        user = await user_repo.get_or_create(...)
        # ... some operation that might fail ...
    except Exception as e:
        # Middleware will auto-rollback
        logger.error("operation_failed", error=str(e))
        raise  # re-raise to trigger rollback
```

---

## Migrations (postgres/alembic/)

**Configuration Files:**
- `postgres/alembic.ini` - Alembic configuration
- `postgres/alembic/env.py` - Migration environment (async support)
- `postgres/alembic/script.py.mako` - Migration template
- `postgres/alembic/versions/` - Migration files

**Important:** env.py imports all models directly (NO __init__.py):
```python
from db.models.base import Base
from db.models.user import User
from db.models.chat import Chat
from db.models.thread import Thread
from db.models.message import Message
from db.models.user_file import UserFile
from db.models.payment import Payment
from db.models.balance_operation import BalanceOperation
from db.models.tool_call import ToolCall
```

**Commands (run from project root):**
```bash
# Generate migration from model changes
docker compose exec bot sh -c "cd /postgres && alembic revision --autogenerate -m 'description'"

# Apply migrations
docker compose exec bot sh -c "cd /postgres && alembic upgrade head"

# Rollback one migration
docker compose exec bot sh -c "cd /postgres && alembic downgrade -1"

# Show current revision
docker compose exec bot sh -c "cd /postgres && alembic current"

# Show migration history
docker compose exec bot sh -c "cd /postgres && alembic history"
```

**Migrations run automatically on bot startup** (see Dockerfile CMD).

---

## Docker Configuration

**compose.yaml:**
```yaml
services:
  postgres:
    image: postgres:16
    environment:
      POSTGRES_PASSWORD_FILE: /run/secrets/postgres_password
    volumes:
      - postgres_data:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U postgres"]
      interval: 10s

  bot:
    depends_on:
      postgres:
        condition: service_healthy  # Wait for DB
    environment:
      DATABASE_HOST: postgres
      DATABASE_PORT: 5432
```

**Secrets:**
- `/run/secrets/telegram_bot_token` - Bot token
- `/run/secrets/postgres_password` - Database password

**Database URL Construction (bot/config.py):**
```python
def get_database_url() -> str:
    password = Path("/run/secrets/postgres_password").read_text().strip()
    host = os.getenv("DATABASE_HOST", "postgres")
    port = os.getenv("DATABASE_PORT", "5432")
    user = os.getenv("DATABASE_USER", "postgres")
    database = os.getenv("DATABASE_NAME", "postgres")
    return f"postgresql+asyncpg://{user}:{password}@{host}:{port}/{database}"
```

---

## Future: Redis Caching (Phase 3)

Repository pattern is ready for Redis caching layer:

```python
# Future implementation
class CachedUserRepository(UserRepository):
    def __init__(self, session: AsyncSession, redis: Redis):
        super().__init__(session)
        self.redis = redis

    async def get_by_telegram_id(self, telegram_id: int):
        # Check cache first
        cached = await self.redis.get(f"user:{telegram_id}")
        if cached:
            return deserialize(cached)

        # Fallback to DB
        user = await super().get_by_telegram_id(telegram_id)

        # Cache result
        if user:
            await self.redis.setex(f"user:{telegram_id}", 3600, serialize(user))

        return user
```

**No handler changes needed** - just swap repository implementation.

---

## Common Patterns

### Pattern 1: Handle Incoming Message
```python
async def handle_user_message(message: Message, session: AsyncSession):
    # 1. Get or create user
    user_repo = UserRepository(session)
    user, _ = await user_repo.get_or_create(
        telegram_id=message.from_user.id,
        first_name=message.from_user.first_name,
        # ... other fields from message.from_user
    )

    # 2. Get or create chat
    chat_repo = ChatRepository(session)
    chat, _ = await chat_repo.get_or_create(
        telegram_id=message.chat.id,
        chat_type=message.chat.type,
        title=message.chat.title,
        is_forum=message.chat.is_forum or False,
    )

    # 3. Find or create thread
    thread_repo = ThreadRepository(session)
    thread, _ = await thread_repo.get_or_create_thread(
        chat_id=message.chat.id,
        user_id=message.from_user.id,
        thread_id=message.message_thread_id,  # Bot API 9.3
    )

    # 4. Save message to DB
    msg_repo = MessageRepository(session)
    db_message = await msg_repo.create_message(
        chat_id=message.chat.id,
        message_id=message.message_id,
        thread_id=thread.id,
        from_user_id=message.from_user.id,
        date=int(message.date.timestamp()),
        role=MessageRole.USER,
        text_content=message.text,
        # ... handle attachments
    )

    # 5. Get conversation history for LLM
    history = await msg_repo.get_thread_messages(thread.id, limit=100)

    # 6. Call LLM with history
    # ... (Phase 1.3)
```

### Pattern 2: Save LLM Response
```python
async def save_llm_response(
    chat_id: int,
    message_id: int,  # Response message ID from Telegram
    thread_id: int,
    response_text: str,
    input_tokens: int,
    output_tokens: int,
    session: AsyncSession,
):
    msg_repo = MessageRepository(session)

    # Save response as ASSISTANT message
    db_message = await msg_repo.create_message(
        chat_id=chat_id,
        message_id=message_id,
        thread_id=thread_id,
        from_user_id=None,  # Bot responses have no user
        date=int(datetime.now(timezone.utc).timestamp()),
        role=MessageRole.ASSISTANT,
        text_content=response_text,
    )

    # Track tokens for billing
    await msg_repo.add_tokens(
        chat_id=chat_id,
        message_id=message_id,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
    )
```

### Pattern 3: Switch LLM Model for Thread
```python
async def switch_model(
    chat_id: int,
    user_id: int,
    thread_id: Optional[int],
    new_model: str,
    session: AsyncSession,
):
    thread_repo = ThreadRepository(session)

    # Find thread
    thread = await thread_repo.get_active_thread(
        chat_id=chat_id,
        user_id=user_id,
        thread_id=thread_id,
    )

    if thread:
        await thread_repo.update_thread_model(thread.id, new_model)
```

---

## Troubleshooting

### Issue: "session is not available"
**Cause:** Handler doesn't have `session: AsyncSession` parameter.

**Fix:**
```python
# ❌ Missing session parameter
async def my_handler(message: Message):
    pass

# ✅ Correct
async def my_handler(message: Message, session: AsyncSession):
    pass
```

### Issue: "duplicate key value violates unique constraint"
**Cause:** Trying to create entity that already exists.

**Fix:** Use get_or_create methods:
```python
# ❌ Direct create might fail
user = User(id=123, ...)
await user_repo.create(user)

# ✅ Use get_or_create
user, _ = await user_repo.get_or_create(telegram_id=123, ...)
```

### Issue: Changes not persisting
**Cause:** Exception in handler triggers rollback.

**Fix:** Check logs for errors, fix the issue. Middleware auto-commits only on success.

### Issue: "foreign key constraint fails"
**Cause:** Referencing entity that doesn't exist.

**Fix:** Create referenced entities first:
```python
# ❌ Create message before thread exists
await msg_repo.create_message(thread_id=999, ...)

# ✅ Create thread first
thread, _ = await thread_repo.get_or_create_thread(...)
await msg_repo.create_message(thread_id=thread.id, ...)
```

---

## Related Documents

- [phase-1.2-telegram-api-mapping.md](phase-1.2-telegram-api-mapping.md) - Telegram API to database field mapping
- [phase-1.1-bot-structure.md](phase-1.1-bot-structure.md) - File structure overview
- [CLAUDE.md](../CLAUDE.md) - Project overview and current status
