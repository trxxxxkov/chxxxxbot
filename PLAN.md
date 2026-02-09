# PLAN: Deep Think Tool + Отключение thinking по умолчанию

## Цель

Экономия ~3500 токенов cache overhead на каждый запрос путём отключения Extended Thinking по умолчанию, с возможностью глубокого анализа через tool `extended_thinking`.

## Ожидаемый результат

- **Экономия**: ~$0.01 на запрос (cache_read 7340 → ~3800 токенов)
- **UX**: Нулевая латентность до первого токена + глубокий анализ когда нужно
- **Гибкость**: Claude сам решает, когда нужно "подумать"

---

## Фаза 1: Tool `extended_thinking`

### 1.1 Создать `bot/core/tools/extended_thinking.py`

**Tool definition (сжатый, по Claude 4 best practices):**

```python
DEEP_THINK_TOOL = {
    "name": "extended_thinking",
    "description": """Extended reasoning for complex problems.

Use for: math proofs, algorithm design, debugging complex logic, architectural decisions.
Skip for: simple questions, formatting, lookups (use web_search instead).

Returns structured reasoning that you incorporate into your response.
Cost: ~$0.01-0.03 per call (thinking tokens).""",
    "input_schema": {
        "type": "object",
        "properties": {
            "problem": {
                "type": "string",
                "description": "Problem statement requiring deep analysis"
            },
            "context": {
                "type": "string",
                "description": "Relevant context (code, data, constraints)"
            },
            "focus": {
                "type": "string",
                "enum": ["correctness", "optimization", "edge_cases", "architecture"],
                "description": "Primary analysis focus"
            }
        },
        "required": ["problem"]
    }
}
```

### 1.2 Реализация `execute_extended_thinking()`

```python
async def execute_extended_thinking(
    problem: str,
    context: str | None,
    focus: str | None,
    # Dependencies
    claude_provider: ClaudeProvider,
    thread_id: int,
    user_id: int,
    **kwargs
) -> dict:
    """Execute deep thinking with Extended Thinking enabled."""

    # Формируем запрос
    system_prompt = """You are a reasoning engine. Analyze the problem deeply.
Structure your thinking, consider edge cases, verify your logic."""

    user_message = f"Problem: {problem}"
    if context:
        user_message += f"\n\nContext:\n{context}"
    if focus:
        user_message += f"\n\nFocus on: {focus}"

    # Запрос с thinking enabled
    request = LLMRequest(
        model="claude:sonnet",  # Или текущая модель пользователя
        messages=[Message(role="user", content=user_message)],
        system_prompt=system_prompt,
        max_tokens=8000,
        thinking_budget=16000,  # Extended Thinking включён!
    )

    # Стримим результат (thinking + answer)
    thinking_text = ""
    answer_text = ""

    async for chunk in claude_provider.stream_message(request):
        if chunk.type == "thinking":
            thinking_text += chunk.text
        else:
            answer_text += chunk.text

    return {
        "thinking": thinking_text,
        "conclusion": answer_text,
        "tokens_used": claude_provider.last_usage.thinking_tokens
    }
```

### 1.3 Добавить в registry

```python
# core/tools/registry.py
from core.tools.extended_thinking import TOOL_CONFIG as DEEP_THINK_CONFIG

TOOLS = {
    ...
    "extended_thinking": DEEP_THINK_CONFIG,
}
```

---

## Фаза 2: UX — Expandable blockquote для thinking

### 2.1 Текущее поведение
- Thinking блоки всегда наверху в `<blockquote expandable>`
- Текст ответа ниже

### 2.2 Новое поведение
1. Сообщение начинается БЕЗ blockquote (обычный текст)
2. Когда `extended_thinking` вызван:
   - В существующее сообщение добавляется `<blockquote expandable>` сверху
   - Внутри blockquote стримятся thinking токены
3. После завершения extended_thinking:
   - Blockquote остаётся (свёрнут по умолчанию)
   - Текст продолжается ниже

### 2.3 Изменения в streaming

**`telegram/streaming/session.py`:**
```python
class StreamingSession:
    def __init__(self, ...):
        self.has_thinking = False  # Новый флаг
        self.thinking_blocks: list[str] = []
        self.text_blocks: list[str] = []

    async def add_thinking(self, text: str):
        """Добавить thinking блок (от extended_thinking tool)."""
        if not self.has_thinking:
            self.has_thinking = True
            # Нужно пересобрать сообщение с blockquote сверху
        self.thinking_blocks.append(text)
        await self._update_message()
```

**`telegram/streaming/formatting.py`:**
```python
def format_blocks_dynamic(
    thinking_parts: list[str],
    text_parts: list[str],
    is_streaming: bool
) -> str:
    """Форматирование с динамическим добавлением thinking."""

    result_parts = []

    # Thinking только если есть
    if thinking_parts:
        thinking_content = "\n\n".join(thinking_parts)
        thinking_html = f"<blockquote expandable>🧠 {thinking_content}</blockquote>"
        result_parts.append(thinking_html)

    # Текст всегда
    if text_parts:
        result_parts.append("\n\n".join(text_parts))

    return "\n\n".join(result_parts)
```

### 2.4 Интеграция с tool execution

**`telegram/handlers/claude.py`:**
```python
async def _handle_extended_thinking_tool(
    self,
    tool_input: dict,
    session: StreamingSession,
    ...
):
    """Обработка extended_thinking с добавлением thinking в сообщение."""

    # Показываем статус
    await session.add_tool_status("🧠 Думаю...")

    # Выполняем extended_thinking со стримингом thinking
    async for chunk in execute_extended_thinking_stream(...):
        if chunk.type == "thinking":
            await session.add_thinking(chunk.text)  # Стримится в blockquote
        else:
            # Conclusion сохраняем для возврата
            conclusion += chunk.text

    # Возвращаем результат для Claude
    return {"thinking": "...", "conclusion": conclusion}
```

---

## Фаза 3: Отключение thinking по умолчанию

### 3.1 Изменить `core/claude/client.py`

```python
# Было:
api_params["thinking"] = {"type": "enabled", "budget_tokens": 16000}

# Стало:
if request.thinking_budget:
    api_params["thinking"] = {"type": "enabled", "budget_tokens": request.thinking_budget}
# Иначе thinking не включается
```

### 3.2 Обновить `LLMRequest`

```python
@dataclass
class LLMRequest:
    model: str
    messages: list[Message]
    system_prompt: str | list[dict] | None = None
    max_tokens: int = 8096
    temperature: float = 1.0
    tools: list[dict] | None = None
    thinking_budget: int | None = None  # None = thinking выключен
```

### 3.3 Обновить вызовы в `claude.py`

```python
# Обычный запрос - без thinking
request = LLMRequest(
    model=model_id,
    messages=messages,
    system_prompt=system_blocks,
    tools=tools,
    # thinking_budget не указан = выключен
)

# extended_thinking tool - с thinking
request = LLMRequest(
    ...
    thinking_budget=16000,  # Включён
)
```

---

## Фаза 4: Совместимость с self_critique

### 4.1 Проверить сценарий

```
User: "Напиши алгоритм сортировки и проверь его"
          ↓
Claude: "Вот алгоритм..." [extended_thinking для логики]
          ↓
Claude: "Проверю..." [self_critique на результат]
```

### 4.2 Оба tool могут работать вместе

- `extended_thinking` — размышление над проблемой (thinking токены)
- `self_critique` — независимая проверка ответа (отдельный Opus запрос)

Конфликта нет — они решают разные задачи.

---

## Фаза 5: Тесты

### 5.1 Unit тесты

- `test_extended_thinking.py` — базовая функциональность
- `test_extended_thinking_streaming.py` — стриминг thinking
- `test_formatting_dynamic.py` — динамическое добавление blockquote

### 5.2 Integration тесты

- Запрос без thinking → быстрый ответ
- Запрос с extended_thinking → thinking в blockquote
- extended_thinking + self_critique → оба работают

---

## Порядок реализации

1. **[Фаза 1]** ✅ Создать tool extended_thinking — `core/tools/extended_thinking.py`
2. **[Фаза 3]** ✅ Отключить thinking по умолчанию — `core/claude/client.py`, `core/models.py`
3. **[Фаза 2]** ✅ UX — thinking стримится через `on_thinking_chunk` → `handle_thinking_delta`
4. **[Фаза 4]** ✅ Совместимость с self_critique — оба tools в registry
5. **[Фаза 5]** ⏳ Тесты — нужны unit/integration тесты для extended_thinking
6. **[Фаза 6]** ✅ Аудит безопасности и биллинга (2026-02-02)

---

## Риски и митигация

| Риск | Митигация |
|------|-----------|
| Claude не вызывает extended_thinking когда нужно | Хороший промпт в tool description |
| Латентность на tool call | Минимальна (~1 сек), компенсируется экономией |
| Сложность UX с динамическим blockquote | Fallback: добавить blockquote при перерисовке |

---

## Метрики успеха

- cache_read снижается с ~7340 до ~3800 токенов
- Качество ответов на сложные запросы не падает
- extended_thinking вызывается на ~20-30% запросов (эвристика)

---

## Решения (согласовано 2026-02-02)

1. **Модель для extended_thinking** — текущая модель пользователя
2. **Стриминг thinking** — в реальном времени (видно как Claude думает)
3. **Лимит вызовов** — пока не нужен (без ограничений по балансу)

---

## Аудит безопасности и биллинга (2026-02-02)

### Исправленные проблемы

| Проблема | Статус | Файл |
|----------|--------|------|
| extended_thinking не в PAID_TOOLS | ✅ Исправлено | `cost_estimator.py` |
| Отсутствует DB logging | ✅ Исправлено | `extended_thinking.py` |
| Тест на количество PAID_TOOLS | ✅ Обновлён | `test_cost_estimator.py` |

### Добавленные поля для DB logging

```python
return {
    ...
    "_model_id": model_config.model_id,
    "_input_tokens": input_tokens,
    "_output_tokens": output_tokens,
    "_cache_read_tokens": 0,
    "_cache_creation_tokens": 0,
}
```

### Проверенные аспекты

| Аспект | Статус |
|--------|--------|
| Списание cost_usd | ✅ Работает через charge_for_tool |
| Pre-check баланса | ✅ Блокируется для отрицательного баланса |
| DB logging в tool_calls | ✅ Все поля переданы |
| Prometheus метрики | ✅ DEEP_THINK_* counters/histograms |
| Cancellation handling | ✅ cancel_event проверяется |
| Streaming thinking | ✅ on_thinking_chunk callback |

### Тесты

- 288 тестов прошло (streaming + cost_estimator)

---

# PLAN: Аудит кэширования (2026-02-09)

## Контекст

Полный аудит двух уровней кэширования:
1. **Anthropic Prompt Cache** — серверное кэширование prefix (tools + system prompt)
2. **Redis Cache** — локальное кэширование данных (user, messages, files, write-behind)

---

## P1. Race condition в `update_cached_balance()` [HIGH]

**Файл:** `bot/cache/user_cache.py:212-275`

**Проблема:** GET → modify → SET не атомарный. Два параллельных списания могут потерять обновление:
```
Thread A: GET balance=10.00
Thread B: GET balance=10.00
Thread A: SET balance=9.50  (charged $0.50)
Thread B: SET balance=8.00  (charged $2.00, overwrites A's -$0.50)
# Реальный баланс должен быть $7.50, а в кэше $8.00
```

**Решение:** Lua-скрипт для atomic read-modify-write (аналогично `append_message_atomic` в `thread_cache.py`):
```lua
-- KEYS[1] = user key
-- ARGV[1] = new_balance
-- ARGV[2] = USER_TTL
-- ARGV[3] = current timestamp
local data = redis.call('GET', KEYS[1])
if not data then return 0 end
local cached = cjson.decode(data)
cached['balance'] = ARGV[1]
cached['cached_at'] = tonumber(ARGV[3])
redis.call('SETEX', KEYS[1], tonumber(ARGV[2]), cjson.encode(cached))
return 1
```

**Изменения:**
- `bot/cache/user_cache.py` — заменить GET+SET на EVALSHA с Lua-скриптом
- Тесты: `bot/tests/cache/test_user_cache.py` — добавить тест на concurrent updates

---

## P2. Комментарий в `user_cache.py` — TTL mismatch [LOW]

**Файл:** `bot/cache/user_cache.py:12`

**Проблема:** Комментарий говорит `TTL: 60 seconds`, но реальный TTL = `USER_TTL = 3600` (1 час) из `keys.py:95`.

**Решение:** Исправить комментарий на `TTL: 3600 seconds (1 hour)`.

---

## P3. Write-behind DLQ никогда не разгребается [MEDIUM]

**Файл:** `bot/cache/write_behind.py:34-35, 154-183`

**Проблема:** `move_to_dlq()` и `get_dlq_depth()` существуют, но нет механизма replay. Items в `write:dlq` копятся вечно без TTL.

**Решение:**
1. Добавить admin-команду `/dlq` для привилегированных пользователей
2. Команда показывает: `DLQ depth`, `типы items`, `возраст самого старого`
3. Кнопки: "Replay all" (re-queue в write:queue), "Purge" (очистить)
4. Добавить Prometheus gauge `write_behind_dlq_depth` в `collect_metrics_task`

**Изменения:**
- `bot/cache/write_behind.py` — добавить `replay_dlq()`, `purge_dlq()`
- `bot/telegram/handlers/admin.py` — добавить `/dlq` команду
- `bot/main.py` — добавить DLQ depth в метрики (каждые 60s)

---

## P4. Неточная оценка токенов для custom prompt cache threshold [LOW]

**Файл:** `bot/telegram/handlers/claude_helpers.py:128`

**Проблема:** `len(custom_prompt) // 4` — грубая оценка. Для custom prompt на границе 1024 токенов может ошибиться в обе стороны.

**Решение:** Снизить порог с 1024 до 256 токенов (1024 символов). Кастомные промпты статичны per-user, поэтому кэш-выигрыш оправдан даже для маленьких промптов.

**Изменения:**
- `bot/telegram/handlers/claude_helpers.py:128` — `>= 1024` → `>= 256`
- `bot/tests/telegram/handlers/test_claude_helpers.py` — обновить тесты на новый порог

---

## ~~P5. Compaction сбрасывает кэш контекста~~ [НЕ ПРОБЛЕМА]

Compaction заменяет прошлые сообщения, но они и так НЕ кэшируются (cache_control только
на system prompt prefix). Cache hit rate не страдает. Полезно только как observability —
добавить Prometheus counter `compaction_triggered_total` для наблюдения.

---

## P6. Misleading комментарий про кэширование tools [LOW]

**Файлы:**
- `bot/core/tools/registry.py:73-74`
- `bot/core/tools/execute_python.py:583, 671-672`

**Проблема:** Комментарии технически корректны (tools действительно кэшируются через system prompt prefix), но формулировка сбивает с толку — звучит как будто cache_control на system каскадно применяется к tools, что неточно. Механизм: Anthropic кэширует prefix в порядке tools→system→messages, и breakpoint на system включает все tools в prefix.

**Решение:** Уточнить комментарии:
```python
# Tools are part of the cached prefix: Anthropic caches everything
# from prompt start up to the cache_control breakpoint (on system prompt).
# Order: tools → system → messages. So tools are implicitly cached.
```

---

## P7. Exec файлы до 100MB могут забить Redis [LOW]

**Файл:** `bot/cache/keys.py:104`

**Проблема:** `EXEC_FILE_MAX_SIZE = 100 * 1024 * 1024`. Data science workload может создать несколько 100MB файлов, забив Redis (лимит 512mb в compose.yaml). `allkeys-lru` спасает, но при вытеснении могут пострадать user/message кэши.

**Решение:** Снизить лимит до 20MB (как file_bytes) или 50MB. Файлы >лимита сохранять на диск (tmpfs) вместо Redis.

**Решение принять после анализа реального использования.**

---

## P8. `batch.py` — non-transactional pipeline [LOW]

**Файл:** `bot/cache/batch.py`

**Проблема:** `pipeline(transaction=False)` — чтения не атомарны. Между fetch user и fetch messages данные могут измениться.

**Решение:** На практике не критично — кэш best-effort, и данные всё равно могут устареть за время обработки. Оставить как есть, документировать.

---

## Порядок реализации

1. **[P1]** Fix race condition в `update_cached_balance()` — Lua-скрипт
2. **[P2]** Fix комментарий TTL в `user_cache.py`
3. **[P4]** Снизить порог кэширования custom prompt 1024→256
4. **[P6]** Уточнить комментарии про кэширование tools
5. **[P3]** DLQ replay механизм + admin команда
6. **[P7]** Анализ exec file sizes в проде, потом решение по лимиту
7. **[P8]** Документировать non-transactional batch — не фиксить
