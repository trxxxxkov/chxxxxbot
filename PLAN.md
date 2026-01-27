# Architecture Improvement Plan

**Date:** 2026-01-27
**Status:** Phase 1-3.3 Complete, Phase 3.4 In Progress (modules ready), Phase 4 Pending
**Based on:** Comprehensive Architecture Audit

---

## Executive Summary

Audit выявил 3 категории проблем:
1. **Кэширование** — race conditions, несоответствие TTL, отсутствие retry
2. **Документация** — устаревшая структура файлов, недокументированные модели
3. **Архитектура** — дублирование кода, несогласованные паттерны, монолитные хендлеры

---

## Phase 1: Critical Fixes (P0) — ✅ COMPLETE

### 1.1 TTL Mismatch Fix ✅

**Проблема:** Документация утверждает `messages TTL=300s`, `threads TTL=600s`, но код использует `3600s`.

**Файлы:**
- `bot/cache/keys.py:95-98`
- `docs/phase-3.2-redis-cache.md:92`

**Решение:** Обновить документацию под фактические значения (3600s разумнее для production).

```python
# keys.py - текущее (оставить)
THREAD_TTL = 3600  # 1 hour
MESSAGES_TTL = 3600  # 1 hour

# docs/phase-3.2-redis-cache.md - обновить
# Thread cache TTL: 3600 seconds (1 hour)
# Messages cache TTL: 3600 seconds (1 hour)
```

**Effort:** 30 минут

---

### 1.2 Atomic Message Cache Updates ✅

**Проблема:** Race condition в `thread_cache.py:359-423`:
```python
data = await redis.get(key)           # Read
cached["messages"].append(new_msg)    # Modify
await redis.setex(key, TTL, ...)      # Write
# Между Read и Write другой процесс может записать свои данные!
```

**Решение:** Lua скрипт для атомарного append:

**Файл:** `bot/cache/thread_cache.py`

```python
# Lua script for atomic message append
APPEND_MESSAGE_SCRIPT = """
local key = KEYS[1]
local new_message = ARGV[1]
local ttl = tonumber(ARGV[2])

local data = redis.call('GET', key)
if not data then
    return 0  -- Cache miss, let caller handle
end

local cached = cjson.decode(data)
local messages = cached.messages or {}
table.insert(messages, cjson.decode(new_message))
cached.messages = messages
cached.cached_at = ARGV[3]

redis.call('SETEX', key, ttl, cjson.encode(cached))
return 1  -- Success
"""

async def append_message_atomic(
    thread_id: int,
    message: dict,
) -> bool:
    """Atomically append message to cache.

    Returns:
        True if appended, False if cache miss (caller should rebuild).
    """
    redis = await get_redis()
    key = messages_key(thread_id)

    result = await redis.eval(
        APPEND_MESSAGE_SCRIPT,
        1,  # number of keys
        key,
        json.dumps(message),
        str(MESSAGES_TTL),
        datetime.utcnow().isoformat(),
    )

    return result == 1
```

**Effort:** 2-3 часа

---

### 1.3 Write-Behind Retry Logic ✅

**Проблема:** `write_behind.py` теряет данные при ошибке flush:
```python
try:
    await self._flush_batch(items)
except Exception as e:
    logger.error(...)
    # items LOST!
```

**Решение:** Возвращать failed items в очередь с exponential backoff:

**Файл:** `bot/cache/write_behind.py`

```python
MAX_RETRY_ATTEMPTS = 3
RETRY_BACKOFF_BASE = 2  # seconds

async def _flush_batch(self, items: list[WriteItem]) -> None:
    """Flush batch with retry logic."""
    failed_items = []

    for item in items:
        try:
            await self._write_single(item)
        except Exception as e:
            item.retry_count = getattr(item, 'retry_count', 0) + 1

            if item.retry_count < MAX_RETRY_ATTEMPTS:
                failed_items.append(item)
                logger.warning(
                    "write_behind.item_failed_will_retry",
                    write_type=item.write_type,
                    retry_count=item.retry_count,
                    error=str(e),
                )
            else:
                logger.error(
                    "write_behind.item_failed_max_retries",
                    write_type=item.write_type,
                    data=item.data,
                    error=str(e),
                )

    # Return failed items to queue for retry
    if failed_items:
        for item in failed_items:
            # Add delay based on retry count
            item.retry_after = time.time() + (RETRY_BACKOFF_BASE ** item.retry_count)
            await self._queue.put(item)
```

**Effort:** 2-3 часа

---

## Phase 2: Documentation Updates (P1) — ✅ COMPLETE

### 2.1 Update CLAUDE.md File Structure ✅

**Проблема:** Отсутствует `telegram/pipeline/` — ключевая архитектура.

**Добавить в секцию File Structure:**

```markdown
│   ├── telegram/
│   │   ├── handlers/           # Message handlers (claude.py is main)
│   │   ├── pipeline/           # Unified message processing (NEW)
│   │   │   ├── handler.py      # Entry point, batching
│   │   │   ├── processor.py    # Core processing logic
│   │   │   ├── normalizer.py   # Message normalization
│   │   │   ├── models.py       # ProcessedMessage, UploadedFile
│   │   │   ├── queue.py        # Message queue management
│   │   │   └── tracker.py      # Upload tracking
│   │   ├── middlewares/        # Logging, database, balance check
```

**Effort:** 30 минут

---

### 2.2 Update phase-1.2-database.md ✅

**Проблема:** Отсутствуют 5 моделей и 5 репозиториев.

**Добавить:**

```markdown
## Models (9 total)

| Model | File | Purpose |
|-------|------|---------|
| User | user.py | Telegram users, balance, settings |
| Chat | chat.py | Chats/groups/channels |
| Thread | thread.py | Conversation threads |
| Message | message.py | Messages with JSONB attachments |
| **UserFile** | user_file.py | Files API integration |
| **Payment** | payment.py | Telegram Stars payments |
| **BalanceOperation** | balance_operation.py | Balance audit trail |
| **ToolCall** | tool_call.py | Tool execution history |

## Repositories (9 total)

| Repository | Purpose |
|------------|---------|
| UserRepository | User CRUD, balance ops |
| ChatRepository | Chat CRUD |
| ThreadRepository | Thread CRUD with caching |
| MessageRepository | Message CRUD, history |
| **UserFileRepository** | File management |
| **PaymentRepository** | Payment records |
| **BalanceOperationRepository** | Balance audit |
| **ToolCallRepository** | Tool call tracking |
```

**Effort:** 1 час

---

### 2.3 Update CLAUDE.md Tools Table ✅

**Проблема:** Показано 9 инструментов, реально 10.

**Обновить таблицу:**

```markdown
### Tools (11 total)
| Tool | Purpose | Cost |
|------|---------|------|
| analyze_image | Vision analysis via Files API | Paid |
| analyze_pdf | PDF text + visual analysis | Paid |
| execute_python | E2B sandbox with file I/O | Paid |
| generate_image | Google Gemini image generation | Paid |
| transcribe_audio | Whisper speech-to-text | Paid |
| web_search | Internet search (server-side) | Paid |
| web_fetch | Fetch URL content (server-side) | Free |
| render_latex | LaTeX to PNG | Free |
| deliver_file | Send cached file to user | Free |
| preview_file | Verify file before delivery | Free* |
| **cost_estimator** | Estimate tool costs | Free |

*preview_file is FREE for text/CSV, PAID for images/PDFs (Vision API)
```

**Effort:** 30 минут

---

### 2.4 Update phase-1.5-agent-tools.md ✅

**Проблема:** execute_python показан как "TODO/pending", но полностью реализован.

**Обновить Stage 5:**

```markdown
## Stage 5: Code Execution (execute_python) — IMPLEMENTED

**Status:** ✅ Complete (E2B integration)

**Features:**
- E2B Code Interpreter sandbox
- Pip package installation
- File I/O (upload inputs, download outputs)
- Timeout handling (default 1 hour)
- Sandbox reuse between calls (cached in Redis)
- Output file caching with preview generation

**Implementation:** `bot/core/tools/execute_python.py` (800+ lines)
```

**Effort:** 30 минут

---

## Phase 3: Architecture Refactoring (P2)

### 3.1 Create ServiceFactory ✅

**Проблема:** Дублирование инициализации сервисов в 5+ местах:
```python
# Повторяется везде
user_repo = UserRepository(session)
balance_op_repo = BalanceOperationRepository(session)
balance_service = BalanceService(session, user_repo, balance_op_repo)
```

**Решение:** Создать `ServiceFactory`:

**Файл:** `bot/services/factory.py` (NEW)

```python
"""Service factory for dependency injection.

Eliminates duplicate service initialization across handlers.
Use: services = ServiceFactory(session)
     await services.balance.charge_user(...)

NO __init__.py - use direct import:
    from services.factory import ServiceFactory
"""

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

from db.repositories.user_repository import UserRepository
from db.repositories.balance_operation_repository import BalanceOperationRepository
from db.repositories.user_file_repository import UserFileRepository
from db.repositories.message_repository import MessageRepository
from db.repositories.thread_repository import ThreadRepository
from services.balance_service import BalanceService


@dataclass
class ServiceFactory:
    """Factory for creating service instances with shared session.

    Usage:
        async with get_session() as session:
            services = ServiceFactory(session)
            await services.balance.charge_user(user_id, amount, ...)
            await services.messages.create_message(...)

    Benefits:
        - Single point of service creation
        - Repositories created once per request
        - Easy to mock in tests
        - Consistent initialization
    """

    session: "AsyncSession"

    # Lazy-loaded repositories
    _user_repo: UserRepository | None = None
    _balance_op_repo: BalanceOperationRepository | None = None
    _user_file_repo: UserFileRepository | None = None
    _message_repo: MessageRepository | None = None
    _thread_repo: ThreadRepository | None = None

    # Lazy-loaded services
    _balance_service: BalanceService | None = None

    @property
    def users(self) -> UserRepository:
        if self._user_repo is None:
            self._user_repo = UserRepository(self.session)
        return self._user_repo

    @property
    def balance_ops(self) -> BalanceOperationRepository:
        if self._balance_op_repo is None:
            self._balance_op_repo = BalanceOperationRepository(self.session)
        return self._balance_op_repo

    @property
    def files(self) -> UserFileRepository:
        if self._user_file_repo is None:
            self._user_file_repo = UserFileRepository(self.session)
        return self._user_file_repo

    @property
    def messages(self) -> MessageRepository:
        if self._message_repo is None:
            self._message_repo = MessageRepository(self.session)
        return self._message_repo

    @property
    def threads(self) -> ThreadRepository:
        if self._thread_repo is None:
            self._thread_repo = ThreadRepository(self.session)
        return self._thread_repo

    @property
    def balance(self) -> BalanceService:
        if self._balance_service is None:
            self._balance_service = BalanceService(
                self.session,
                self.users,
                self.balance_ops,
            )
        return self._balance_service
```

**Использование (замена текущего кода):**

```python
# БЫЛО (в 5+ местах):
user_repo = UserRepository(session)
balance_op_repo = BalanceOperationRepository(session)
balance_service = BalanceService(session, user_repo, balance_op_repo)
await balance_service.charge_user(user_id, amount, description)

# СТАЛО:
from services.factory import ServiceFactory
services = ServiceFactory(session)
await services.balance.charge_user(user_id, amount, description)
```

**Файлы для обновления:**
- `telegram/handlers/claude.py`
- `telegram/handlers/claude_tools.py`
- `services/topic_naming.py`
- `telegram/middlewares/balance_middleware.py`
- `telegram/pipeline/processor.py`

**Effort:** 4-6 часов

---

### 3.2 Унификация Singleton Pattern ✅

**Проблема:** 3 разных паттерна синглтонов в коде.

**Текущие варианты:**
```python
# Pattern 1: Global + init function (claude.py)
claude_provider = None
def init_claude_provider(api_key): ...

# Pattern 2: Global + getter (topic_naming.py)
_service = None
def get_service():
    global _service
    if _service is None:
        _service = Service()
    return _service

# Pattern 3: Double-check (clients.py)
_client = None
def get_client():
    global _client
    if _client is None:
        _client = Client()
    return _client
```

**Решение:** Использовать единый паттерн — Pattern 2 (lazy getter) везде:

**Файл:** `bot/core/singleton.py` (NEW)

```python
"""Singleton pattern utilities.

Provides consistent lazy initialization for service singletons.
Thread-safe through Python's GIL for simple cases.

Usage:
    from core.singleton import singleton

    @singleton
    def get_my_service() -> MyService:
        return MyService(config.SETTING)
"""

from functools import wraps
from typing import TypeVar, Callable

T = TypeVar('T')


def singleton(func: Callable[[], T]) -> Callable[[], T]:
    """Decorator for singleton getter functions.

    Caches the result of the first call and returns it
    for all subsequent calls.

    Example:
        @singleton
        def get_claude_provider() -> ClaudeProvider:
            return ClaudeProvider(config.ANTHROPIC_API_KEY)

        # First call creates instance
        provider = get_claude_provider()

        # Subsequent calls return same instance
        same_provider = get_claude_provider()
        assert provider is same_provider
    """
    instance = None

    @wraps(func)
    def wrapper() -> T:
        nonlocal instance
        if instance is None:
            instance = func()
        return instance

    # Allow resetting for tests
    def reset():
        nonlocal instance
        instance = None

    wrapper.reset = reset
    return wrapper
```

**Рефакторинг существующих синглтонов:**

```python
# core/clients.py
from core.singleton import singleton

@singleton
def get_anthropic_async_client() -> AsyncAnthropic:
    return AsyncAnthropic(api_key=config.ANTHROPIC_API_KEY)

@singleton
def get_anthropic_files_client() -> AsyncAnthropic:
    return AsyncAnthropic(
        api_key=config.ANTHROPIC_API_KEY,
        default_headers={"anthropic-beta": "files-api-2025-04-14"},
    )

# services/topic_naming.py
from core.singleton import singleton

@singleton
def get_topic_naming_service() -> TopicNamingService:
    return TopicNamingService()

# telegram/handlers/claude.py
from core.singleton import singleton

@singleton
def get_claude_provider() -> ClaudeProvider:
    return ClaudeProvider(config.ANTHROPIC_API_KEY)
```

**Effort:** 3-4 часа

---

### 3.3 Extract BalancePolicy ✅

**Проблема:** Логика проверки баланса в 4 местах с разными подходами.

**Решение:** Единый интерфейс `BalancePolicy`:

**Файл:** `bot/services/balance_policy.py` (NEW)

```python
"""Unified balance checking policy.

Single source of truth for:
- Can user make request? (before handler)
- Can user use paid tool? (during handler)
- Charge user for usage (after response)

NO __init__.py - use direct import:
    from services.balance_policy import BalancePolicy
"""

from decimal import Decimal
from typing import Optional
from dataclasses import dataclass

from cache.user_cache import get_cached_user
from db.repositories.user_repository import UserRepository


@dataclass
class BalanceCheckResult:
    """Result of balance check."""
    allowed: bool
    balance: Decimal
    source: str  # "cache" or "database"
    reason: Optional[str] = None


class BalancePolicy:
    """Unified balance checking policy.

    Implements soft-check: user can go negative ONCE, then blocked.
    This allows completing started requests without abrupt cutoff.

    Usage:
        policy = BalancePolicy()

        # Quick check (cache-first)
        result = await policy.can_make_request(user_id)
        if not result.allowed:
            return "Insufficient balance"

        # Tool pre-check
        can_use = await policy.can_use_paid_tool(user_id, tool_name)
    """

    # Minimum balance to start new request
    MIN_BALANCE_FOR_REQUEST = Decimal("0")

    # Minimum balance to use paid tools
    MIN_BALANCE_FOR_TOOLS = Decimal("0")

    async def can_make_request(
        self,
        user_id: int,
        session: Optional["AsyncSession"] = None,
    ) -> BalanceCheckResult:
        """Check if user can make a new request.

        Uses cache-first approach for speed.
        Falls back to database if cache miss.

        Args:
            user_id: Telegram user ID.
            session: Optional DB session for fallback.

        Returns:
            BalanceCheckResult with allowed status and balance.
        """
        # Try cache first
        cached_user = await get_cached_user(user_id)

        if cached_user is not None:
            balance = cached_user.balance
            allowed = balance > self.MIN_BALANCE_FOR_REQUEST
            return BalanceCheckResult(
                allowed=allowed,
                balance=balance,
                source="cache",
                reason=None if allowed else "Insufficient balance (cached)",
            )

        # Cache miss - check database
        if session is None:
            # No session, allow request (will check later)
            return BalanceCheckResult(
                allowed=True,
                balance=Decimal("0"),
                source="unknown",
                reason="Cache miss, no session",
            )

        user_repo = UserRepository(session)
        user = await user_repo.get_by_id(user_id)

        if user is None:
            # New user, allow first request
            return BalanceCheckResult(
                allowed=True,
                balance=Decimal("0"),
                source="database",
                reason="New user",
            )

        balance = user.balance
        allowed = balance > self.MIN_BALANCE_FOR_REQUEST
        return BalanceCheckResult(
            allowed=allowed,
            balance=balance,
            source="database",
            reason=None if allowed else "Insufficient balance",
        )

    async def can_use_paid_tool(
        self,
        user_id: int,
        tool_name: str,
    ) -> bool:
        """Check if user can use a paid tool.

        More lenient than can_make_request - allows tools
        if user has any positive balance (soft-check).

        Args:
            user_id: Telegram user ID.
            tool_name: Name of the tool (for logging).

        Returns:
            True if user can use the tool.
        """
        cached_user = await get_cached_user(user_id)

        if cached_user is None:
            # Cache miss - allow (will charge later)
            return True

        return cached_user.balance > self.MIN_BALANCE_FOR_TOOLS


# Global instance
_balance_policy: Optional[BalancePolicy] = None


def get_balance_policy() -> BalancePolicy:
    """Get singleton BalancePolicy instance."""
    global _balance_policy
    if _balance_policy is None:
        _balance_policy = BalancePolicy()
    return _balance_policy
```

**Использование:**

```python
# В BalanceMiddleware:
from services.balance_policy import get_balance_policy

policy = get_balance_policy()
result = await policy.can_make_request(user_id, session)
if not result.allowed:
    await message.answer(f"Insufficient balance: ${result.balance}")
    return None

# В claude_tools.py:
policy = get_balance_policy()
if not await policy.can_use_paid_tool(user_id, tool_name):
    return {"error": "Insufficient balance for paid tool"}
```

**Effort:** 4-5 часов

---

### 3.4 Split Streaming Handler 🔄

**Проблема:** `_stream_with_unified_events` — 572 строки, 7 return values.

**Статус:** В процессе. Созданы модули, интеграция в claude.py ожидается.

**Решение:** Разбить на компоненты:

**Файл:** `bot/telegram/handlers/streaming/` (NEW directory)

```
streaming/
├── __init__.py
├── orchestrator.py    # Main coordination
├── session.py         # StreamingSession state
├── tool_executor.py   # Tool execution loop
├── file_processor.py  # Generated file handling
├── cost_tracker.py    # Partial billing
└── models.py          # StreamResult, CancellationReason
```

**Ключевые классы:**

```python
# streaming/models.py
@dataclass
class StreamResult:
    """Result of streaming operation."""
    text: str
    message: types.Message
    needs_continuation: bool
    was_cancelled: bool
    cancellation_reason: Optional[CancellationReason]
    thinking_tokens: int
    output_tokens: int
    cost_usd: Decimal

    def build_continuation_request(self) -> "StreamRequest":
        """Build request for continuation if needed."""
        ...


# streaming/orchestrator.py
class StreamingOrchestrator:
    """Coordinates streaming, tools, files, and billing.

    Replaces monolithic _stream_with_unified_events function.
    Each responsibility delegated to specialized component.
    """

    def __init__(
        self,
        tool_executor: ToolExecutor,
        file_processor: FileProcessor,
        cost_tracker: CostTracker,
    ):
        self.tool_executor = tool_executor
        self.file_processor = file_processor
        self.cost_tracker = cost_tracker

    async def stream_with_continuation(
        self,
        request: StreamRequest,
    ) -> StreamResult:
        """Stream response with automatic continuation.

        Handles the full loop:
        1. Stream from Claude API
        2. Execute tools if requested
        3. Process generated files
        4. Track costs
        5. Continue if needed (tool results, length limit)
        """
        while True:
            result = await self._stream_single(request)

            if not result.needs_continuation:
                return result

            # Build continuation request
            request = result.build_continuation_request()

    async def _stream_single(
        self,
        request: StreamRequest,
    ) -> StreamResult:
        """Single streaming iteration (may need continuation)."""
        session = StreamingSession(request)

        async for event in self._stream_events(request):
            await session.process_event(event)

            # Check for cancellation
            if await self._check_cancellation(session):
                return session.build_cancelled_result()

            # Process tool calls
            if event.type == "tool_use":
                tool_result = await self.tool_executor.execute(
                    event.tool_call,
                    session,
                )
                session.add_tool_result(tool_result)

                # Process any generated files
                if tool_result.output_files:
                    await self.file_processor.process(
                        tool_result.output_files,
                        session,
                    )

        # Track final cost
        await self.cost_tracker.record(session)

        return session.build_result()
```

**Effort:** 8-12 часов (большой рефакторинг)

---

## Phase 4: Additional Improvements (P3)

### 4.1 Cache Warming Strategy

**Проблема:** Cache miss на первом сообщении в сессии.

**Решение:** Warm cache при создании thread:

```python
# thread_resolver.py
async def get_or_create_thread(...):
    thread, was_created = await thread_repo.get_or_create_thread(...)

    if was_created:
        # Pre-populate caches for better first-message performance
        await cache_thread(thread)
        await cache_messages(thread.id, [])  # Empty history
        await cache_files(thread.id, [])     # No files yet
```

**Effort:** 2 часа

---

### 4.2 Redis Pipeline for Batch Operations

**Проблема:** Множество отдельных Redis calls.

**Решение:** Использовать pipeline для batch операций:

```python
async def get_user_context(user_id: int, thread_id: int) -> UserContext:
    """Get all user context in single Redis roundtrip."""
    redis = await get_redis()

    async with redis.pipeline() as pipe:
        pipe.get(user_key(user_id))
        pipe.get(thread_key(thread_id))
        pipe.get(messages_key(thread_id))
        pipe.get(files_key(thread_id))

        results = await pipe.execute()

    return UserContext(
        user=parse_user(results[0]),
        thread=parse_thread(results[1]),
        messages=parse_messages(results[2]),
        files=parse_files(results[3]),
    )
```

**Effort:** 4-6 часов

---

### 4.3 Standardize Error Handling

**Проблема:** 6+ разных паттернов обработки ошибок.

**Решение:** Создать error classification system:

```python
# core/errors.py

class BotError(Exception):
    """Base class for bot errors."""
    recoverable: bool = True
    user_message: str = "An error occurred"
    log_level: str = "warning"


class InsufficientBalanceError(BotError):
    """User has insufficient balance."""
    recoverable = True
    user_message = "Insufficient balance. Please top up with /pay"
    log_level = "info"  # Expected behavior, not warning


class ToolExecutionError(BotError):
    """Tool failed to execute."""
    recoverable = True
    user_message = "Tool execution failed. Please try again."
    log_level = "warning"


class APIError(BotError):
    """External API error."""
    recoverable = False
    user_message = "Service temporarily unavailable"
    log_level = "error"
```

**Effort:** 4-6 часов

---

## Implementation Timeline

| Phase | Items | Effort | Priority |
|-------|-------|--------|----------|
| **Phase 1** | TTL fix, Atomic updates, Retry logic | 5-7 часов | P0 (срочно) |
| **Phase 2** | Documentation updates | 3-4 часа | P1 (эта неделя) |
| **Phase 3.1** | ServiceFactory | 4-6 часов | P2 |
| **Phase 3.2** | Singleton pattern | 3-4 часа | P2 |
| **Phase 3.3** | BalancePolicy | 4-5 часов | P2 |
| **Phase 3.4** | Split streaming handler | 8-12 часов | P2 (большой) |
| **Phase 4** | Cache warming, Pipeline, Errors | 10-14 часов | P3 (future) |

**Total estimated effort:** 37-52 часа

---

## Risks & Mitigations

| Risk | Impact | Mitigation |
|------|--------|------------|
| Lua script compatibility | Redis version issues | Test on staging first |
| ServiceFactory breaks DI | Harder testing | Keep original constructors |
| Streaming split regression | User-facing bugs | Comprehensive test coverage |
| Cache warming overhead | Slower thread creation | Make async, measure impact |

---

## Success Metrics

| Metric | Current | Target |
|--------|---------|--------|
| Message cache race conditions | Unknown | 0 |
| Write-behind data loss | ~1-2% | <0.1% |
| Service initialization LOC | 15 lines/place | 2 lines/place |
| Streaming handler size | 572 lines | <200 lines/file |
| Documentation coverage | ~70% | 95% |

---

## Next Steps

1. **Approve plan** — review priorities with team
2. **Phase 1** — critical fixes first (TTL, atomic, retry)
3. **Phase 2** — documentation updates (parallel with Phase 1)
4. **Phase 3** — architecture improvements (incremental)
5. **Phase 4** — optimization (after stabilization)

---

*Plan created: 2026-01-27*
*Based on: Comprehensive Architecture Audit*
