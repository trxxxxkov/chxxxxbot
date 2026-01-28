# План аудита логирования

## Философия логирования

| Уровень | Что означает | Моё действие |
|---------|--------------|--------------|
| **ERROR** | Баг в моём коде. Можно пофиксить без компромиссов. | Иду фиксить немедленно |
| **WARNING** | Архитектурный компромисс, который "стреляет". Trade-off. | Думаю: пересмотреть компромисс? |
| **INFO** | Внешние факторы / нормальная работа. Фиксить нечего. | Ничего не делаю |
| **DEBUG** | Детали для отладки. | Не смотрю в production |

---

## Критерии классификации

### ERROR - баги для немедленного фикса:
- "Should never happen" ситуации (user/thread not found после создания)
- Необработанные exceptions
- Нарушение инвариантов (data corruption)
- Ошибки инициализации (provider not initialized)
- Race conditions
- Логические ошибки в коде

### WARNING - архитектурные компромиссы:
- **Rate limiting (flood_control)** - компромисс между UX и API limits
- **Parse errors с fallback (MarkdownV2 → plain)** - компромисс форматирования
- **Context overflow** - компромисс размера контекста vs лимиты API
- **Concurrency limits** - компромисс между параллелизмом и ресурсами
- Любой fallback где МОЖНО было бы сделать лучше, но выбран trade-off

### INFO - внешние факторы, нормальная работа:
- Внешние API ошибки которые мы gracefully обрабатываем (rate_limit, timeout, connection_error)
- Retry operations (нормальный механизм)
- Cache miss/unavailable (graceful degradation работает)
- User input errors (LaTeX syntax, invalid commands)
- Любая ситуация где "система сделала всё возможное"

### DEBUG - детали реализации:
- Косметические операции (edit_failed для warning messages)
- Внутренние детали работы

---

## Результаты аудита по файлам

### telegram/handlers/claude.py

| Строка | Событие | Было | Стало | Обоснование |
|--------|---------|------|-------|-------------|
| 144 | `telegram.flood_control` | WARNING | WARNING ✓ | Компромисс частоты обновлений |
| 168 | `empty_batch` | WARNING | **ERROR** | "Should never happen" - баг в batching |
| 172 | `provider_not_initialized` | ERROR | ERROR ✓ | Баг инициализации |
| 227 | `concurrency_limit_exceeded` | WARNING | WARNING ✓ | Компромисс лимитов |
| 269 | `thread_not_found` | ERROR | ERROR ✓ | Баг - thread должен существовать |
| 350 | `user_not_found` | ERROR | ERROR ✓ | Баг - user должен существовать |
| 601 | `empty_response` | WARNING | **INFO** | Внешний API, gracefully показано |
| 609 | `streaming_failed` | ERROR | ERROR ✓ | Unexpected exception |
| 619 | `no_bot_message` | ERROR | ERROR ✓ | "Should never happen" |
| 809 | `context_overflow` | WARNING | WARNING ✓ | Компромисс размера контекста |
| 828 | `warning_edit_failed` | WARNING | **DEBUG** | Косметика, не влияет на UX |
| 832 | `refusal` | WARNING | **INFO** | Внешний API решил |
| 847 | `refusal_edit_failed` | WARNING | **DEBUG** | Косметика |
| 1012 | `topic_naming_failed` | WARNING | **INFO** | Внешняя ошибка, не критично |
| 1019 | `context_exceeded` | ERROR | **INFO** | Внешняя ошибка API, gracefully |
| 1032 | `rate_limit` | ERROR | **INFO** | Внешняя ошибка API, gracefully |
| 1049 | `connection_error` | ERROR | **INFO** | Внешняя инфраструктура |
| 1062 | `timeout` | ERROR | **INFO** | Внешняя ошибка API |
| 1075 | `llm_error` | ERROR | **INFO** | Внешняя ошибка API |
| 1089 | `unexpected_error` | ERROR | ERROR ✓ | Возможно баг в коде |

### telegram/draft_streaming.py

| Событие | Было | Стало | Обоснование |
|---------|------|-------|-------------|
| `flood_control` | WARNING→INFO | **WARNING** | Компромисс частоты обновлений |
| `parse_error_fallback` | WARNING→INFO | **WARNING** | Компромисс MarkdownV2 |
| `update_failed` | WARNING→INFO | **INFO** | Внешняя ошибка Telegram |
| `keepalive_flood` | WARNING→INFO | **WARNING** | Компромисс keepalive |
| `keepalive_parse_error` | WARNING→INFO | **INFO** | Внешняя ошибка |
| `keepalive_failed` | WARNING→INFO | **INFO** | Внешняя ошибка |
| `finalize_parse_error_fallback` | WARNING→DEBUG | **DEBUG** ✓ | Косметика |

### telegram/chat_action/manager.py

| Событие | Было | Стало | Обоснование |
|---------|------|-------|-------------|
| `chat_action.failed` | WARNING→INFO | **INFO** ✓ | Внешняя ошибка, косметика |

### core/tools/render_latex.py

| Событие | Было | Стало | Обоснование |
|---------|------|-------|-------------|
| `compilation_error` | WARNING→INFO | **INFO** ✓ | User input error |
| `failed` | WARNING→INFO | **INFO** ✓ | User input error |
| `cache_failed_fallback` | WARNING→INFO | **INFO** ✓ | Graceful fallback |

### cache/*.py - общий паттерн

| Тип события | Уровень | Обоснование |
|-------------|---------|-------------|
| Redis unavailable | INFO | Graceful degradation работает |
| Cache get/set error | INFO | Falls back to DB |
| File too large | INFO | Normal constraint |
| Retry/requeue | INFO | Normal mechanism |

### core/claude/files_api.py

| Событие | Было | Стало | Обоснование |
|---------|------|-------|-------------|
| `upload_retry` | WARNING→INFO | **INFO** ✓ | Normal retry |
| `download_retry` | WARNING→INFO | **INFO** ✓ | Normal retry |
| `delete_retry` | WARNING→INFO | **INFO** ✓ | Normal retry |
| `delete_not_found` | WARNING→DEBUG | **DEBUG** ✓ | Already deleted, ok |

### core/claude/client.py

| Событие | Было | Стало | Обоснование |
|---------|------|-------|-------------|
| `rate_limit` | ERROR | **INFO** | Внешняя ошибка, gracefully |
| `connection_error` | ERROR | **INFO** | Внешняя ошибка |
| `timeout` | ERROR | **INFO** | Внешняя ошибка |
| `unexpected_error` | ERROR | ERROR ✓ | Возможно баг |
| `token_counting.failed` | WARNING | **INFO** | Fallback работает |

### main.py

| Событие | Было | Стало | Обоснование |
|---------|------|-------|-------------|
| `privileged_users_file_not_found` | WARNING→INFO | **INFO** ✓ | Expected config |
| `cache_warming.failed` | WARNING→INFO | **INFO** ✓ | Optimization |
| `redis_init_failed` | WARNING | WARNING ✓ | Требует внимания ops |

### services/payment_service.py

| Событие | Было | Стало | Обоснование |
|---------|------|-------|-------------|
| `refund_ownership_mismatch` | WARNING | WARNING ✓ | Security issue |
| `refund_payment_not_found` | WARNING | **ERROR** | Баг - payment должен быть |
| API errors | ERROR | **INFO** | Внешние ошибки, gracefully |

### telegram/streaming/orchestrator.py

| Событие | Было | Стало | Обоснование |
|---------|------|-------|-------------|
| `unexpected_stop` | WARNING | **INFO** | Внешний API решил |
| `cancelled.finalize_failed` | ERROR | **INFO** | Внешняя ошибка Telegram |
| `finalize_failed` | ERROR | **INFO** | Внешняя ошибка Telegram |
| `turn_break.finalize_failed` | ERROR | **INFO** | Внешняя ошибка Telegram |
| `no_assistant_message` | ERROR | ERROR ✓ | Баг - context потерян |
| `max_iterations` | ERROR | ERROR ✓ | Требует исследования |

### services/balance_service.py

| Событие | Было | Стало | Обоснование |
|---------|------|-------|-------------|
| `user_not_found` | ERROR | ERROR ✓ | Баг - user должен быть |
| `insufficient_for_request` | WARNING | **INFO** | Нормальная работа |
| `invalid_charge_amount` | ERROR | ERROR ✓ | Баг в коде |
| `charge_user_not_found` | ERROR | ERROR ✓ | Баг |
| `negative_after_charge` | WARNING | **INFO** | Expected behavior |
| `admin_topup_*` | ERROR | ERROR ✓ | Баги |

### telegram/handlers/payment.py

| Событие | Было | Стало | Обоснование |
|---------|------|-------|-------------|
| `buy_package_calculation_error` | ERROR | ERROR ✓ | Баг в config |
| `invalid_callback_data` | ERROR | ERROR ✓ | Баг |
| `invalid_custom_amount` | WARNING | **INFO** | User input error |
| `custom_amount_out_of_range` | WARNING | **INFO** | User input error |
| `send_invoice_error` | ERROR | **INFO** | Внешняя ошибка Telegram |
| `invalid_invoice_payload` | ERROR | ERROR ✓ | Баг или tampering |
| `invalid_currency` | ERROR | ERROR ✓ | Баг или tampering |
| `process_error` | ERROR | ERROR ✓ | CRITICAL |
| `refund_telegram_api_failed` | ERROR | ERROR ✓ | Требует audit |
| `refund_validation_error` | WARNING | **INFO** | User error |
| `refund_error` | ERROR | ERROR ✓ | Unexpected error |

---

## Файлы для аудита (ЗАВЕРШЕНО)

### Основные файлы (✅ ИСПРАВЛЕНО)

- [x] telegram/handlers/claude.py ← ИСПРАВЛЕНО
- [x] telegram/draft_streaming.py ← ИСПРАВЛЕНО
- [x] telegram/chat_action/manager.py ← ИСПРАВЛЕНО
- [x] core/tools/render_latex.py ← ИСПРАВЛЕНО
- [x] cache/user_cache.py ← ИСПРАВЛЕНО
- [x] cache/write_behind.py ← ИСПРАВЛЕНО
- [x] cache/exec_cache.py ← ИСПРАВЛЕНО
- [x] core/claude/files_api.py ← ИСПРАВЛЕНО
- [x] core/tools/analyze_image.py ← ИСПРАВЛЕНО
- [x] core/tools/analyze_pdf.py ← ИСПРАВЛЕНО
- [x] main.py ← ИСПРАВЛЕНО
- [x] telegram/thread_resolver.py ← ИСПРАВЛЕНО
- [x] core/claude/client.py ← ИСПРАВЛЕНО
- [x] telegram/handlers/payment.py ← ИСПРАВЛЕНО
- [x] telegram/streaming/orchestrator.py ← ИСПРАВЛЕНО
- [x] services/payment_service.py ← ИСПРАВЛЕНО
- [x] services/balance_service.py ← ИСПРАВЛЕНО

### Сводка изменений

**ERROR → INFO** (внешние API ошибки, gracefully обрабатываемые):
- claude.*.rate_limit, connection_error, timeout
- payment.send_invoice_error
- orchestrator.finalize_failed

**WARNING → INFO** (нормальная работа / user errors):
- balance.insufficient_for_request, negative_after_charge
- payment.invalid_custom_amount, custom_amount_out_of_range
- payment.refund_invalid_status, refund_period_expired, refund_insufficient_balance
- payment.refund_validation_error
- orchestrator.unexpected_stop

**WARNING → ERROR** (баги, которые нужно фиксить):
- empty_batch (should never happen)
- refund_payment_not_found (payment должен существовать)

**Все тесты проходят: 1704 passed**
