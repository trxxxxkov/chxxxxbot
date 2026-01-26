# Phase 3.3: Cache-First Architecture

## Цель

Полная cache-first архитектура: во время обработки запроса НЕ ходить в Postgres.
Все данные читаются из Redis, записи накапливаются и пишутся в Postgres асинхронно.

**Ожидаемое ускорение:** 100-200ms на запрос (убираем все DB queries из hot path).

---

## Фаза A: TTFT Optimization (Time To First Token)

### Цель
Отправить первый токен пользователю сразу после получения от модели.
Остальные токены — через throttle interval.

### Текущее поведение
- DraftManager обновляет draft с throttle interval
- Первый токен ждёт того же интервала

### Изменения

**Файл: `bot/telegram/streaming.py`**
```python
class StreamingSession:
    def __init__(self, ...):
        self.first_update_sent = False  # Новый флаг

    async def handle_text_delta(self, delta: str) -> None:
        self.text_buffer += delta
        self.display.add_text(delta)

        # TTFT: первое обновление сразу
        if not self.first_update_sent:
            await self.update_display(force=True)
            self.first_update_sent = True
```

**Файл: `bot/telegram/draft_streaming.py`**
```python
class Draft:
    async def update(self, text: str, force: bool = False) -> None:
        # force=True пропускает throttle
        if force or self._should_update():
            await self._send_draft(text)
```

### Метрики
- `bot_ttft_seconds` — время до первого токена

---

## Фаза B: Write-Behind Pattern

### Цель
Накапливать записи в Redis, писать в Postgres батчами в фоне.

### Архитектура
```
                    Hot Path (sync)
[Request] ──────────────────────────────────────▶ [Response]
    │                                                  ▲
    ▼                                                  │
┌─────────────────────────────────────────────────────────┐
│                        REDIS                            │
│  ┌─────────┐  ┌─────────┐  ┌─────────┐  ┌───────────┐  │
│  │  User   │  │ Thread  │  │ Messages│  │  Files    │  │
│  │  Cache  │  │  Cache  │  │  Cache  │  │  Cache    │  │
│  └─────────┘  └─────────┘  └─────────┘  └───────────┘  │
│                                                         │
│  ┌─────────────────────────────────────────────────┐   │
│  │            Write Queue (LIST)                   │   │
│  │  [msg1, msg2, stats1, file1, balance1, ...]    │   │
│  └─────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────┘
                         │
                         │ Background Task (async)
                         ▼
┌─────────────────────────────────────────────────────────┐
│                      POSTGRES                           │
│  users │ threads │ messages │ user_files │ balance_ops  │
└─────────────────────────────────────────────────────────┘
```

### Новые файлы

**Файл: `bot/cache/write_behind.py`**
```python
"""Write-behind queue for async Postgres writes."""

import json
import asyncio
from typing import Any, Dict, List
from enum import Enum

from cache.client import get_redis
from utils.structured_logging import get_logger

logger = get_logger(__name__)

WRITE_QUEUE_KEY = "write:queue"
FLUSH_INTERVAL = 5  # seconds
BATCH_SIZE = 100


class WriteType(str, Enum):
    """Type of write operation."""
    MESSAGE = "message"
    USER_STATS = "user_stats"
    FILE = "file"
    BALANCE_OP = "balance_op"


async def queue_write(write_type: WriteType, data: Dict[str, Any]) -> bool:
    """Queue a write operation for background processing.

    Args:
        write_type: Type of write operation.
        data: Data to write.

    Returns:
        True if queued successfully.
    """
    redis = await get_redis()
    if redis is None:
        return False

    payload = json.dumps({
        "type": write_type.value,
        "data": data,
        "queued_at": time.time(),
    })

    await redis.rpush(WRITE_QUEUE_KEY, payload)
    return True


async def flush_writes(session) -> int:
    """Flush queued writes to Postgres.

    Called by background task periodically.

    Returns:
        Number of writes flushed.
    """
    redis = await get_redis()
    if redis is None:
        return 0

    # Get batch of writes
    writes = []
    for _ in range(BATCH_SIZE):
        data = await redis.lpop(WRITE_QUEUE_KEY)
        if data is None:
            break
        writes.append(json.loads(data))

    if not writes:
        return 0

    # Group by type and batch insert
    messages = [w for w in writes if w["type"] == WriteType.MESSAGE.value]
    stats = [w for w in writes if w["type"] == WriteType.USER_STATS.value]
    files = [w for w in writes if w["type"] == WriteType.FILE.value]
    balance_ops = [w for w in writes if w["type"] == WriteType.BALANCE_OP.value]

    # Batch insert each type
    if messages:
        await _batch_insert_messages(session, messages)
    if stats:
        await _batch_update_stats(session, stats)
    if files:
        await _batch_insert_files(session, files)
    if balance_ops:
        await _batch_insert_balance_ops(session, balance_ops)

    await session.commit()

    logger.info(
        "write_behind.flushed",
        total=len(writes),
        messages=len(messages),
        stats=len(stats),
        files=len(files),
        balance_ops=len(balance_ops),
    )

    return len(writes)


async def write_behind_task(logger) -> None:
    """Background task to flush writes periodically."""
    from db.engine import get_session

    while True:
        try:
            await asyncio.sleep(FLUSH_INTERVAL)

            async with get_session() as session:
                flushed = await flush_writes(session)

                if flushed > 0:
                    logger.debug(
                        "write_behind.task_complete",
                        flushed=flushed,
                    )

        except asyncio.CancelledError:
            # Final flush on shutdown
            logger.info("write_behind.shutdown_flush")
            async with get_session() as session:
                await flush_writes(session)
            break
        except Exception as e:
            logger.error(
                "write_behind.task_error",
                error=str(e),
                exc_info=True,
            )
```

### Изменения в существующих файлах

**Файл: `bot/telegram/handlers/claude.py`**

Заменить прямые записи на queue_write:

```python
# BEFORE:
await msg_repo.create_message(...)

# AFTER:
from cache.write_behind import queue_write, WriteType

await queue_write(WriteType.MESSAGE, {
    "chat_id": chat_id,
    "message_id": message_id,
    "thread_id": thread_id,
    "from_user_id": from_user_id,
    "date": date,
    "role": role.value,
    "text_content": text_content,
    ...
})

# Также обновить кэш сообщений
await update_cached_messages(thread_id, new_message)
```

**Файл: `bot/main.py`**

Добавить background task:

```python
# Start write-behind task
write_behind_task_handle = asyncio.create_task(
    write_behind_task(logger)
)
logger.info("write_behind_task_started")

# В finally:
write_behind_task_handle.cancel()
try:
    await write_behind_task_handle
except asyncio.CancelledError:
    pass
```

### Данные для write-behind

| Тип | Write-Behind | Причина |
|-----|--------------|---------|
| Messages (user) | ✅ Да | Некритично, можно восстановить |
| Messages (assistant) | ✅ Да | Некритично |
| User stats | ✅ Да | Агрегаты, потеря некритична |
| Files metadata | ✅ Да | Можно переиндексировать |
| Balance operations | ⚠️ Осторожно | Критично для аудита |
| User balance | ❌ Нет | Синхронно, атомарно |

### Гарантии

1. **AOF Persistence**: Redis с `appendfsync everysec`
2. **Graceful Shutdown**: Flush всех записей при остановке
3. **Retry Logic**: При ошибке записи — retry с backoff

---

## Фаза C: Files Visibility (ВСЕ типы файлов)

### Проблема
1. `files_delivered` не попадал в tool result (✅ ИСПРАВЛЕНО)
2. Инструкции только для images/PDFs

### Изменения

**Файл: `bot/core/tools/helpers.py`**

Улучшить `format_files_section()`:

```python
def format_files_section(files: List[Any]) -> str:
    """Format available files list for system prompt."""
    if not files:
        return ""

    lines = ["Available files in this conversation:"]

    # Group by type for clarity
    by_type = {}
    for file in files:
        file_type = file.file_type.value
        if file_type not in by_type:
            by_type[file_type] = []
        by_type[file_type].append(file)

    for file_type, type_files in by_type.items():
        lines.append(f"\n{file_type.upper()} files:")
        for file in type_files:
            file_info = (f"  - {file.filename} "
                        f"({format_size(file.file_size)}, "
                        f"{format_time_ago(file.uploaded_at)})")
            lines.append(file_info)
            lines.append(f"    claude_file_id: {file.claude_file_id}")

    lines.append("")
    lines.append(f"Total files available: {len(files)}")
    lines.append("")

    # Tool guidance for ALL file types
    lines.append("To work with these files:")
    lines.append("- Images: use analyze_image tool")
    lines.append("- PDFs: use analyze_pdf tool")
    lines.append("- Audio/Voice/Video: use transcribe_audio tool")
    lines.append("- Documents/Code: use execute_python with file_inputs")
    lines.append("- Generated files: download with deliver_file if needed")
    lines.append("")
    lines.append(
        "IMPORTANT: These files are ALREADY AVAILABLE. "
        "Do NOT regenerate files that are in this list. "
        "If user asks about files in this list, analyze them directly."
    )

    return "\n".join(lines)
```

### Проверка: какие файлы сохраняются

| Источник | Тип | Сохраняется? | Где |
|----------|-----|--------------|-----|
| User → Image | IMAGE | ✅ | pipeline/processor.py |
| User → PDF | PDF | ✅ | pipeline/processor.py |
| User → Document | DOCUMENT | ✅ | pipeline/processor.py |
| User → Voice | VOICE | ✅ | pipeline/processor.py |
| User → Audio | AUDIO | ✅ | pipeline/processor.py |
| User → Video | VIDEO | ✅ | pipeline/processor.py |
| Bot → generate_image | IMAGE | ✅ | claude_files.py |
| Bot → execute_python output | DOCUMENT | ✅ | claude_files.py |

---

## Фаза D: Full Cache-First

### Цель
Полностью убрать Postgres из hot path.

### Текущий hot path (что читается из DB)

1. **Balance check** (middleware) → User.balance
2. **Thread lookup** → Thread (get_or_create)
3. **Message history** → Messages[]
4. **Available files** → UserFiles[]
5. **User config** → User.model_id, User.custom_prompt

### Целевой hot path (всё из Redis)

```
[Request]
    │
    ▼
┌─────────────────────────────────────────────────────────┐
│ Balance Middleware                                       │
│   └─► get_cached_user(user_id) → balance, model_id      │
│       (cache miss → DB → cache)                          │
└─────────────────────────────────────────────────────────┘
    │
    ▼
┌─────────────────────────────────────────────────────────┐
│ Pipeline Handler                                         │
│   └─► get_cached_thread(chat_id, user_id)               │
│       (cache miss → DB → cache)                          │
└─────────────────────────────────────────────────────────┘
    │
    ▼
┌─────────────────────────────────────────────────────────┐
│ Claude Handler                                           │
│   ├─► get_cached_messages(thread_id)                    │
│   ├─► get_cached_files(thread_id)                       │
│   └─► Claude API call                                    │
└─────────────────────────────────────────────────────────┘
    │
    ▼
┌─────────────────────────────────────────────────────────┐
│ Response Processing                                      │
│   ├─► update_cached_balance(user_id, new_balance)       │
│   ├─► update_cached_messages(thread_id, new_msg)        │
│   └─► queue_write(...) → Redis Queue                    │
└─────────────────────────────────────────────────────────┘
    │
    ▼
[Response to User]

    ... Background Task ...

┌─────────────────────────────────────────────────────────┐
│ Write-Behind Task                                        │
│   └─► flush_writes() → Postgres                         │
└─────────────────────────────────────────────────────────┘
```

### Новые функции кэша

**Файл: `bot/cache/user_cache.py`**

Добавить полные данные пользователя:

```python
async def get_cached_user_full(user_id: int) -> Optional[dict]:
    """Get full user data from cache.

    Returns dict with: balance, model_id, custom_prompt,
    first_name, username, message_count, total_tokens_used
    """
    ...

async def cache_user_full(user_id: int, user: User) -> bool:
    """Cache full user data."""
    ...
```

**Файл: `bot/cache/thread_cache.py`**

Добавить update функции:

```python
async def update_cached_messages(
    thread_id: int,
    new_message: dict
) -> bool:
    """Add message to cached history without full invalidation."""
    cached = await get_cached_messages(thread_id)
    if cached is None:
        return False

    cached.append(new_message)
    return await cache_messages(thread_id, cached)
```

### Изменения в handler

**Файл: `bot/telegram/handlers/claude.py`**

```python
async def _process_message_batch(thread_id: int, messages: list) -> None:
    # 1. Get user from cache (NOT from DB in hot path)
    cached_user = await get_cached_user_full(thread.user_id)
    if cached_user is None:
        # Cache miss - load from DB and cache
        async with get_session() as session:
            user_repo = UserRepository(session)
            user = await user_repo.get_by_id(thread.user_id)
            await cache_user_full(user.id, user)
            cached_user = _user_to_dict(user)

    # 2. Get messages from cache
    cached_messages = await get_cached_messages(thread_id)
    if cached_messages is None:
        # Cache miss - load and cache
        async with get_session() as session:
            msg_repo = MessageRepository(session)
            messages = await msg_repo.get_thread_messages(thread_id)
            await cache_messages(thread_id, [_msg_to_dict(m) for m in messages])
            cached_messages = ...

    # 3. Get files from cache (already implemented)
    cached_files = await get_cached_files(thread_id)
    ...

    # 4. After Claude response - update caches and queue writes
    await update_cached_balance(user_id, new_balance)
    await update_cached_messages(thread_id, new_assistant_msg)
    await queue_write(WriteType.MESSAGE, assistant_msg_data)
    await queue_write(WriteType.BALANCE_OP, balance_op_data)
```

---

## Порядок реализации

### Этап 1: Подготовка (без риска)
1. ✅ Fix files_delivered bug
2. ✅ Add files cache
3. ✅ Improve format_files_section for all types (format_unified_files_section)
4. ✅ Add TTFT optimization (already in session.py)

### Этап 2: Write-Behind (низкий риск)
5. ✅ Create write_behind.py module
6. ✅ Add background flush task (in main.py)
7. ✅ Queue messages writes (keep DB writes as fallback)
8. ✅ Queue stats updates

### Этап 3: Full Cache-First (medium risk)
9. ✅ Add cache update functions (custom_prompt in user_cache)
10. ✅ Refactor claude handler to cache-first (user data)
11. ✅ Message cache: invalidate after user writes, update after assistant
12. ✅ Cache hit rate metrics (bot_redis_cache_hits/misses_total)

### Этап 4: Production Hardening
13. ✅ Add circuit breaker for Redis (3 failures → 30s timeout)
14. ✅ Add metrics for write queue depth (bot_write_queue_depth)
15. [ ] Add alerting for queue backlog
16. [ ] Load testing

---

## Файлы для создания

| Файл | Назначение |
|------|------------|
| `bot/cache/write_behind.py` | Write queue и background flush |

## Файлы для изменения

| Файл | Изменения |
|------|-----------|
| `bot/telegram/streaming.py` | TTFT: first_update_sent flag |
| `bot/telegram/draft_streaming.py` | force parameter для skip throttle |
| `bot/core/tools/helpers.py` | format_files_section для всех типов |
| `bot/cache/user_cache.py` | get/cache_user_full |
| `bot/cache/thread_cache.py` | update_cached_messages |
| `bot/telegram/handlers/claude.py` | Cache-first reads, queue writes |
| `bot/main.py` | Write-behind background task |
| `bot/utils/metrics.py` | Метрики для write queue |

---

## Метрики

```python
# Write-behind
bot_write_queue_depth          # Глубина очереди записей
bot_write_flush_duration       # Время flush операции
bot_write_flush_count          # Количество записей за flush

# Cache
bot_cache_hit_rate{type}       # Hit rate по типам
bot_cache_latency{operation}   # Латентность кэша

# TTFT
bot_ttft_seconds               # Time to first token
```

---

## Риски и митигация

| Риск | Митигация |
|------|-----------|
| Потеря данных при crash Redis | AOF persistence, graceful shutdown flush |
| Рассинхронизация cache/DB | Периодическая валидация, TTL |
| Write queue overflow | Metrics + alerts, circuit breaker |
| Balance inconsistency | Balance writes остаются синхронными |
