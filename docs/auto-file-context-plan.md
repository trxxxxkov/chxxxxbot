# File Context Architecture

## Implemented: Upload Context

Instead of auto-including file contents (which wastes tokens), we store
the text message that accompanied each file upload. This helps the model
understand which file the user is asking about without analyzing all files.

### Current Flow

```
User sends image + text → File uploaded to Files API → Metadata + context stored
"Here's my math homework"  → claude_file_id saved    → upload_context saved

Model sees in system prompt:
  - photo.jpg (1.2 MB, 5 min ago) [user]
    file_id: file-xxx
    context: "Here's my math homework"

When user asks "check the homework" → Model identifies correct file by context
```

### Implementation

1. **Database**: `upload_context` column in `user_files` table
2. **Pipeline**: `processor.py` passes `processed.text` as `upload_context`
3. **Caching**: `helpers.py` includes `upload_context` in cache serialization
4. **Display**: `format_unified_files_section()` shows context for each file

---

## Alternative: Auto-Include (NOT implemented)

The alternative approach would auto-include files in context like ChatGPT.
This was rejected because:

---

## Архитектура

### Multimodal Messages

Claude API поддерживает multimodal content blocks:

```python
# User message with image
{
    "role": "user",
    "content": [
        {"type": "text", "text": "What's in this image?"},
        {"type": "image", "source": {"type": "file", "file_id": "file-xxx"}}
    ]
}

# User message with PDF
{
    "role": "user",
    "content": [
        {"type": "text", "text": "Summarize this document"},
        {"type": "document", "source": {"type": "file", "file_id": "file-xxx"}}
    ]
}
```

### Token Budget для файлов

**Проблема:** Файлы могут быстро заполнить контекст (200K токенов).

**Решение:** Бюджет токенов для файлов с приоритетом новых.

```python
FILE_TOKEN_BUDGET = 100_000  # 100K токенов на файлы (50% контекста)

# Примерные размеры:
# - Image (1024x1024): ~1,000 tokens
# - Image (2048x2048): ~4,000 tokens
# - PDF page: ~1,500 tokens
# - Audio transcript: ~300 tokens/minute
```

### Стратегия включения

1. **Текущее сообщение** — всегда включать файлы (пользователь ожидает)
2. **История** — включать файлы пока есть бюджет (новые → старые)
3. **Превышение бюджета** — оставить только metadata (как сейчас)

```python
def build_context_with_files(messages, files, budget=100_000):
    used_tokens = 0
    result = []

    for msg in reversed(messages):  # От новых к старым
        msg_files = get_files_for_message(msg, files)

        for file in msg_files:
            file_tokens = estimate_file_tokens(file)

            if used_tokens + file_tokens <= budget:
                # Include file content
                msg.content.append(file_content_block(file))
                used_tokens += file_tokens
            else:
                # Only metadata reference
                msg.content.append({"type": "text", "text": f"[File: {file.filename}]"})

    return result
```

---

## Типы файлов

| Тип | Как включать | Токены (примерно) |
|-----|--------------|-------------------|
| Image | `{"type": "image", "source": {"type": "file", "file_id": "..."}}` | 1K-4K |
| PDF | `{"type": "document", "source": {"type": "file", "file_id": "..."}}` | 1.5K/page |
| Audio/Video | Transcription как text | 300/min |
| Other docs | Text extraction или описание | varies |

### Audio/Video — особый случай

Аудио нельзя передать напрямую в Claude. Варианты:
1. **Auto-transcribe** — транскрибировать при загрузке, хранить текст
2. **Lazy transcribe** — транскрибировать при первом использовании
3. **Keep current** — оставить transcribe_audio tool

**Рекомендация:** Auto-transcribe для voice messages (короткие), lazy для длинных файлов.

---

## Изменения

### Phase 1: Multimodal message format

**Файлы:**
- `telegram/context/formatter.py` — включать файлы в content blocks
- `db/models/message.py` — хранить file references в сообщении

**Задачи:**
1. [ ] Добавить `file_ids` поле в Message model (JSONB array)
2. [ ] При сохранении сообщения — связывать с file_ids
3. [ ] В ContextFormatter — строить multimodal content

### Phase 2: Token budgeting

**Файлы:**
- `core/claude/context.py` — token budget для файлов
- `config.py` — FILE_TOKEN_BUDGET constant

**Задачи:**
1. [ ] Добавить estimate_file_tokens() function
2. [ ] Implement budget-aware context building
3. [ ] Logging для отладки (какие файлы включены/исключены)

### Phase 3: Audio handling

**Файлы:**
- `telegram/pipeline/normalizer.py` — auto-transcribe voice
- `db/models/message.py` — хранить transcript

**Задачи:**
1. [ ] Auto-transcribe voice messages при загрузке
2. [ ] Хранить transcript в message или отдельно
3. [ ] Включать transcript как text content

### Phase 4: Cleanup (optional)

**Задачи:**
1. [ ] Deprecate analyze_image, analyze_pdf (или оставить для edge cases)
2. [ ] Update system prompt
3. [ ] Update documentation

---

## Оценка токенов

```python
def estimate_file_tokens(file: UserFile) -> int:
    """Estimate tokens for file based on type and size."""

    if file.file_type == FileType.IMAGE:
        # Based on resolution from metadata
        width = file.metadata.get("width", 1024)
        height = file.metadata.get("height", 1024)
        pixels = width * height
        # ~1 token per 1000 pixels (rough estimate)
        return max(1000, pixels // 1000)

    if file.file_type == FileType.PDF:
        # ~1500 tokens per page
        pages = file.metadata.get("pages", 1)
        return pages * 1500

    if file.file_type in (FileType.AUDIO, FileType.VOICE, FileType.VIDEO):
        # Transcript: ~4 chars per token, ~150 words per minute
        duration = file.metadata.get("duration", 60)
        words = duration / 60 * 150
        return int(words * 1.3)  # ~1.3 tokens per word

    # Default for documents
    return file.file_size // 4  # ~4 bytes per token for text
```

---

## Конфигурация

```python
# config.py

# Maximum tokens for file content in context
FILE_TOKEN_BUDGET = 100_000  # 100K tokens (50% of 200K context)

# Always include files from last N messages regardless of budget
ALWAYS_INCLUDE_RECENT_FILES = 3

# Auto-transcribe audio shorter than N seconds
AUTO_TRANSCRIBE_THRESHOLD = 120  # 2 minutes
```

---

## Миграция

### Database migration

```sql
-- Add file_ids to messages
ALTER TABLE messages ADD COLUMN file_ids JSONB DEFAULT '[]';

-- Backfill from user_files
UPDATE messages m
SET file_ids = (
    SELECT jsonb_agg(uf.id)
    FROM user_files uf
    WHERE uf.message_id = m.message_id
);
```

### Backward compatibility

- Старые сообщения без file_ids — работают как раньше (metadata only)
- Новые сообщения — автоматически включают файлы

---

## Риски

| Риск | Митигация |
|------|-----------|
| Превышение контекста | Token budget + graceful degradation |
| Увеличение стоимости | Бюджет контролирует расход |
| Files API TTL (24h) | Re-upload при истечении |
| Длинные аудио | Lazy transcription + budget |

---

## Метрики успеха

| Метрика | До | После |
|---------|-----|-------|
| analyze_* tool calls | Many | Few (edge cases only) |
| User experience | "Analyze this image" required | Image understood immediately |
| Latency for file questions | +2-3s (tool call) | 0 (already in context) |

---

## Вопросы для обсуждения

1. **FILE_TOKEN_BUDGET** — 100K достаточно? Или 50K/150K?
2. **Audio handling** — auto-transcribe все или только voice messages?
3. **Deprecate analyze_* tools** — убрать совсем или оставить для edge cases?
4. **PDF pages** — включать все страницы или только первые N?
