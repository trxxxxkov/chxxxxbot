# Telegram Bot API 9.3 → Database Mapping

Field-by-field mapping between Telegram Bot API entities and database models. Use this to correctly extract and store data from incoming Telegram updates.

## Status
**implemented** (Phase 1.2)

---

## Quick Reference

**Import aiogram types:**
```python
from aiogram.types import Message, User as TelegramUser, Chat as TelegramChat
```

**Import database models:**
```python
from db.models.user import User as DBUser
from db.models.chat import Chat as DBChat
from db.models.message import Message as DBMessage, MessageRole
```

---

## User Mapping

### Telegram → Database

**Source:** `aiogram.types.User` (from `message.from_user`)

| Telegram Field | Type | DB Model | DB Field | Notes |
|----------------|------|----------|----------|-------|
| `id` | int | User | `id` | **Primary key** - Telegram user_id |
| `is_bot` | bool | User | `is_bot` | Bot account flag |
| `first_name` | str | User | `first_name` | **Required** by Telegram |
| `last_name` | Optional[str] | User | `last_name` | Family name |
| `username` | Optional[str] | User | `username` | Without @ prefix, **unique** |
| `language_code` | Optional[str] | User | `language_code` | IETF tag (e.g., "en", "ru") |
| `is_premium` | Optional[bool] | User | `is_premium` | Telegram Premium status |
| `added_to_attachment_menu` | Optional[bool] | User | `added_to_attachment_menu` | Bot in attachment menu |
| - | - | User | `current_model` | Custom field (default: "claude") |
| - | - | User | `first_seen_at` | Auto-set on first creation |
| - | - | User | `last_seen_at` | Auto-updated |

### Extraction Code

```python
from aiogram.types import Message
from db.repositories.user_repository import UserRepository

async def extract_user(message: Message, session: AsyncSession):
    if not message.from_user:
        return None

    user_repo = UserRepository(session)

    user, was_created = await user_repo.get_or_create(
        telegram_id=message.from_user.id,
        is_bot=message.from_user.is_bot,
        first_name=message.from_user.first_name,
        last_name=message.from_user.last_name,
        username=message.from_user.username,
        language_code=message.from_user.language_code,
        is_premium=message.from_user.is_premium or False,
        added_to_attachment_menu=message.from_user.added_to_attachment_menu or False,
    )

    return user, was_created
```

**Important Notes:**
- `first_name` is **required** by Telegram (always present)
- `username` can be None (not all users have @username)
- `is_premium` and `added_to_attachment_menu` may be None in older API versions (default to False)
- `last_seen_at` is automatically updated by `get_or_create()`

---

## Chat Mapping

### Telegram → Database

**Source:** `aiogram.types.Chat` (from `message.chat`)

| Telegram Field | Type | DB Model | DB Field | Notes |
|----------------|------|----------|----------|-------|
| `id` | int | Chat | `id` | **Primary key** - Telegram chat_id |
| `type` | str | Chat | `type` | "private", "group", "supergroup", "channel" |
| `title` | Optional[str] | Chat | `title` | Groups/channels only |
| `username` | Optional[str] | Chat | `username` | Public @chatname |
| `first_name` | Optional[str] | Chat | `first_name` | Private chats only |
| `last_name` | Optional[str] | Chat | `last_name` | Private chats only |
| `is_forum` | Optional[bool] | Chat | `is_forum` | Supergroup has topics (Bot API 9.3) |

### Chat Type Values

| Telegram | Database | Description |
|----------|----------|-------------|
| "private" | "private" | 1-on-1 chat with user |
| "group" | "group" | Regular group chat |
| "supergroup" | "supergroup" | Supergroup (upgraded from group) |
| "channel" | "channel" | Broadcast channel |

### Extraction Code

```python
from aiogram.types import Message
from db.repositories.chat_repository import ChatRepository

async def extract_chat(message: Message, session: AsyncSession):
    chat_repo = ChatRepository(session)

    chat, was_created = await chat_repo.get_or_create(
        telegram_id=message.chat.id,
        chat_type=message.chat.type,
        title=message.chat.title,
        username=message.chat.username,
        first_name=message.chat.first_name,
        last_name=message.chat.last_name,
        is_forum=message.chat.is_forum or False,
    )

    return chat, was_created
```

**Important Notes:**
- Private chats have `first_name`/`last_name`
- Groups/channels have `title`
- `is_forum` = True means supergroup has forum topics enabled (Bot API 9.3)

---

## Thread Mapping

### Telegram → Database

**Source:** `aiogram.types.Message.message_thread_id` (Bot API 9.3)

| Telegram Field | Type | DB Model | DB Field | Notes |
|----------------|------|----------|----------|-------|
| `message_thread_id` | Optional[int] | Thread | `thread_id` | Forum topic ID, None = main chat |
| `chat.id` | int | Thread | `chat_id` | Which chat |
| `from_user.id` | int | Thread | `user_id` | Which user owns thread |
| - | - | Thread | `id` | Internal auto-increment ID |
| - | - | Thread | `title` | Custom field |
| - | - | Thread | `model_name` | Custom field (default: "claude") |
| - | - | Thread | `system_prompt` | Custom field |

### Thread Logic

**Forum Topics (Bot API 9.3):**
- `message.message_thread_id = None` → main chat (no topic)
- `message.message_thread_id = 123` → forum topic with ID 123
- Each user has **one thread per topic** in each chat

**Thread Identification:**
```python
thread_key = (chat_id, user_id, thread_id)
# Unique constraint: UNIQUE(chat_id, user_id, COALESCE(thread_id, 0))
```

### Extraction Code

```python
from aiogram.types import Message
from db.repositories.thread_repository import ThreadRepository

async def extract_thread(message: Message, session: AsyncSession):
    if not message.from_user:
        return None

    thread_repo = ThreadRepository(session)

    # Get thread_id from message (None for main chat)
    telegram_thread_id = message.message_thread_id  # Bot API 9.3

    thread, was_created = await thread_repo.get_or_create_thread(
        chat_id=message.chat.id,
        user_id=message.from_user.id,
        thread_id=telegram_thread_id,
        # Optional: set custom title, model, prompt
    )

    return thread, was_created
```

**Important Notes:**
- `message_thread_id` is available only in chats with `is_forum=True`
- For non-forum chats, `message_thread_id` is always None
- Thread determines **LLM conversation context** (all messages in thread)

---

## Message Mapping

### Telegram → Database

**Source:** `aiogram.types.Message`

| Telegram Field | Type | DB Model | DB Field | Notes |
|----------------|------|----------|----------|-------|
| `chat.id` | int | Message | `chat_id` | **Primary key part 1** |
| `message_id` | int | Message | `message_id` | **Primary key part 2** |
| `from_user.id` | Optional[int] | Message | `from_user_id` | NULL for channels |
| `date` | datetime | Message | `date` | Convert to Unix timestamp |
| `edit_date` | Optional[datetime] | Message | `edit_date` | Convert to Unix timestamp |
| `text` | Optional[str] | Message | `text_content` | Text content |
| `caption` | Optional[str] | Message | `caption` | Media caption |
| `reply_to_message.message_id` | Optional[int] | Message | `reply_to_message_id` | Replied message |
| `media_group_id` | Optional[str] | Message | `media_group_id` | Groups related media |
| - | - | Message | `thread_id` | FK to threads.id (lookup required) |
| - | - | Message | `role` | MessageRole enum (USER/ASSISTANT/SYSTEM) |
| - | - | Message | `has_photos` | Calculated from attachments |
| - | - | Message | `has_documents` | Calculated from attachments |
| - | - | Message | `has_voice` | Calculated from attachments |
| - | - | Message | `has_video` | Calculated from attachments |
| - | - | Message | `attachment_count` | Calculated from attachments |
| - | - | Message | `attachments` | JSONB array (see below) |
| - | - | Message | `input_tokens` | LLM billing (set after API call) |
| - | - | Message | `output_tokens` | LLM billing (set after API call) |

### MessageRole Assignment

| Source | Role | Usage |
|--------|------|-------|
| User message | `MessageRole.USER` | Incoming Telegram message |
| Bot response | `MessageRole.ASSISTANT` | LLM-generated response |
| System prompt | `MessageRole.SYSTEM` | Custom system prompts |

### Attachment Mapping

**Telegram provides multiple types of media:**

| Telegram Type | DB Type | Telegram Fields | DB JSONB Fields |
|---------------|---------|-----------------|-----------------|
| Photo | "photo" | `message.photo[-1]` (largest) | file_id, file_unique_id, width, height, file_size |
| Document | "document" | `message.document` | file_id, file_unique_id, file_name, mime_type, file_size |
| Voice | "voice" | `message.voice` | file_id, file_unique_id, duration, mime_type, file_size |
| Video | "video" | `message.video` | file_id, file_unique_id, width, height, duration, file_size |
| Audio | "audio" | `message.audio` | file_id, file_unique_id, duration, title, performer, mime_type, file_size |
| Video Note | "video_note" | `message.video_note` | file_id, file_unique_id, length, duration, file_size |
| Sticker | "sticker" | `message.sticker` | file_id, file_unique_id, width, height, is_animated, is_video |

**JSONB Schema:**
```json
[
  {
    "type": "photo",
    "file_id": "AgACAgIAAxkBAAI...",
    "file_unique_id": "AQADw...",
    "width": 1280,
    "height": 720,
    "file_size": 102400
  }
]
```

### Extraction Code

```python
from aiogram.types import Message as TelegramMessage
from db.repositories.message_repository import MessageRepository
from db.models.message import MessageRole

async def extract_message(
    telegram_msg: TelegramMessage,
    thread_id: int,
    session: AsyncSession,
):
    msg_repo = MessageRepository(session)

    # Extract attachments
    attachments = []

    # Photos (get largest)
    if telegram_msg.photo:
        photo = telegram_msg.photo[-1]
        attachments.append({
            "type": "photo",
            "file_id": photo.file_id,
            "file_unique_id": photo.file_unique_id,
            "width": photo.width,
            "height": photo.height,
            "file_size": photo.file_size,
        })

    # Documents
    if telegram_msg.document:
        doc = telegram_msg.document
        attachments.append({
            "type": "document",
            "file_id": doc.file_id,
            "file_unique_id": doc.file_unique_id,
            "file_name": doc.file_name,
            "mime_type": doc.mime_type,
            "file_size": doc.file_size,
        })

    # Voice messages
    if telegram_msg.voice:
        voice = telegram_msg.voice
        attachments.append({
            "type": "voice",
            "file_id": voice.file_id,
            "file_unique_id": voice.file_unique_id,
            "duration": voice.duration,
            "mime_type": voice.mime_type,
            "file_size": voice.file_size,
        })

    # Videos
    if telegram_msg.video:
        video = telegram_msg.video
        attachments.append({
            "type": "video",
            "file_id": video.file_id,
            "file_unique_id": video.file_unique_id,
            "width": video.width,
            "height": video.height,
            "duration": video.duration,
            "file_size": video.file_size,
        })

    # Create message in DB
    db_message = await msg_repo.create_message(
        chat_id=telegram_msg.chat.id,
        message_id=telegram_msg.message_id,
        thread_id=thread_id,
        from_user_id=telegram_msg.from_user.id if telegram_msg.from_user else None,
        date=int(telegram_msg.date.timestamp()),
        role=MessageRole.USER,
        text_content=telegram_msg.text,
        caption=telegram_msg.caption,
        reply_to_message_id=telegram_msg.reply_to_message.message_id if telegram_msg.reply_to_message else None,
        media_group_id=telegram_msg.media_group_id,
        attachments=attachments,
        edit_date=int(telegram_msg.edit_date.timestamp()) if telegram_msg.edit_date else None,
    )

    return db_message
```

**Important Notes:**
- **Photos:** Telegram sends array of sizes, use `photo[-1]` for largest
- **file_unique_id:** Persistent across bots, use for deduplication
- **file_id:** Bot-specific, use for file downloads
- **Timestamps:** Convert `datetime` to Unix timestamp with `int(dt.timestamp())`
- **Channel messages:** `from_user_id` is None for channel posts

---

## Complete Handler Example

```python
from aiogram import Router
from aiogram.types import Message
from sqlalchemy.ext.asyncio import AsyncSession

from db.repositories.user_repository import UserRepository
from db.repositories.chat_repository import ChatRepository
from db.repositories.thread_repository import ThreadRepository
from db.repositories.message_repository import MessageRepository
from db.models.message import MessageRole

router = Router(name="message_handler")


@router.message()
async def handle_user_message(message: Message, session: AsyncSession):
    """Complete example: save incoming message to database."""

    # 1. Extract and save user
    user_repo = UserRepository(session)
    user, user_created = await user_repo.get_or_create(
        telegram_id=message.from_user.id,
        is_bot=message.from_user.is_bot,
        first_name=message.from_user.first_name,
        last_name=message.from_user.last_name,
        username=message.from_user.username,
        language_code=message.from_user.language_code,
        is_premium=message.from_user.is_premium or False,
        added_to_attachment_menu=message.from_user.added_to_attachment_menu or False,
    )

    # 2. Extract and save chat
    chat_repo = ChatRepository(session)
    chat, chat_created = await chat_repo.get_or_create(
        telegram_id=message.chat.id,
        chat_type=message.chat.type,
        title=message.chat.title,
        username=message.chat.username,
        first_name=message.chat.first_name,
        last_name=message.chat.last_name,
        is_forum=message.chat.is_forum or False,
    )

    # 3. Find or create thread
    thread_repo = ThreadRepository(session)
    thread, thread_created = await thread_repo.get_or_create_thread(
        chat_id=message.chat.id,
        user_id=message.from_user.id,
        thread_id=message.message_thread_id,  # Bot API 9.3 forum topics
    )

    # 4. Extract attachments
    attachments = []
    if message.photo:
        photo = message.photo[-1]  # Largest photo
        attachments.append({
            "type": "photo",
            "file_id": photo.file_id,
            "file_unique_id": photo.file_unique_id,
            "width": photo.width,
            "height": photo.height,
            "file_size": photo.file_size,
        })

    # 5. Save message to DB
    msg_repo = MessageRepository(session)
    db_message = await msg_repo.create_message(
        chat_id=message.chat.id,
        message_id=message.message_id,
        thread_id=thread.id,
        from_user_id=message.from_user.id,
        date=int(message.date.timestamp()),
        role=MessageRole.USER,
        text_content=message.text,
        caption=message.caption,
        attachments=attachments,
    )

    # 6. Get conversation history for LLM context
    history = await msg_repo.get_thread_messages(thread.id, limit=100)

    # 7. Call LLM with history (Phase 1.3)
    # ...

    # No commit needed - DatabaseMiddleware handles it automatically
```

---

## Message Updates (Edits)

**Telegram sends `edited_message` update:**

```python
from aiogram import Router
from aiogram.types import Message
from sqlalchemy.ext.asyncio import AsyncSession

from db.repositories.message_repository import MessageRepository

router = Router(name="edit_handler")


@router.edited_message()
async def handle_edited_message(message: Message, session: AsyncSession):
    """Handle message edits."""
    msg_repo = MessageRepository(session)

    try:
        await msg_repo.update_message(
            chat_id=message.chat.id,
            message_id=message.message_id,
            text_content=message.text,
            caption=message.caption,
            edit_date=int(message.edit_date.timestamp()) if message.edit_date else None,
        )
    except ValueError:
        # Message not found in DB - might be old message
        # Decide: ignore or save as new?
        pass
```

---

## Special Cases

### Channel Posts

**Channel posts have no `from_user`:**
```python
if message.from_user:
    from_user_id = message.from_user.id
else:
    from_user_id = None  # Channel post
```

### Service Messages

**Service messages (user joined, chat created, etc.) have no text:**
```python
if message.text:
    text_content = message.text
else:
    # Service message or media-only
    text_content = None
```

### Media Groups

**Multiple media items sent together share `media_group_id`:**
```python
if message.media_group_id:
    # This message is part of media group
    # Save with media_group_id for grouping in queries
    pass
```

### Forward Information

**Forwarded messages have `forward_from` or `forward_from_chat`:**

| Telegram Field | Type | Meaning |
|----------------|------|---------|
| `forward_from` | User | Forwarded from user |
| `forward_from_chat` | Chat | Forwarded from channel |
| `forward_date` | datetime | When original was sent |

**Currently not stored in DB** - add fields if needed for your use case.

---

## Bot API 9.3 New Features

### Forum Topics Support

**New fields in Bot API 9.3:**
- `Chat.is_forum: bool` - Supergroup has topics enabled
- `Message.message_thread_id: Optional[int]` - Topic ID (None for main chat)

**Implementation:**
- `Chat.is_forum` → `chats.is_forum`
- `Message.message_thread_id` → `threads.thread_id`

**Usage:**
```python
if message.chat.is_forum:
    # Forum chat - use thread_id
    thread_id = message.message_thread_id
else:
    # Regular chat - no thread_id
    thread_id = None
```

### Message Reactions (Future)

**Bot API 9.3 also added reactions** - not yet implemented in our schema.

**To add support:**
1. Add `reactions` JSONB column to `messages` table
2. Add `has_reactions` boolean flag for fast queries
3. Handle `message_reaction` update type

---

## Validation Rules

### Required Fields

**Always present in valid Telegram messages:**
- `Message.message_id` - Always present
- `Message.date` - Always present
- `Message.chat` - Always present
- `User.id` - Always present (when user exists)
- `User.first_name` - Always present (when user exists)

**Can be None:**
- `Message.from_user` - None for channel posts
- `Message.text` - None for media-only or service messages
- `User.username` - Many users don't have @username
- `Chat.title` - None for private chats

### Field Constraints

**Username:**
- Must start with letter
- 5-32 characters
- Only a-z, 0-9, and underscores
- Store WITHOUT @ prefix

**Chat ID ranges:**
- Positive: users (1 to 1099511627775)
- Negative: groups/channels (-4000000000000 to -1)

---

## Related Documents

- [database.md](database.md) - Complete database architecture
- [bot-structure.md](bot-structure.md) - File structure overview
- [CLAUDE.md](../CLAUDE.md) - Project overview and status
