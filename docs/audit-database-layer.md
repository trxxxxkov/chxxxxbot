# Database Layer Audit Report

**Date:** 2026-01-26
**Auditor:** Claude Code
**Scope:** Models, Repositories, Migrations

---

## Summary

| Severity | Count |
|----------|-------|
| Critical | 1 |
| High | 4 |
| Medium | 6 |
| Low | 3 |

---

## Critical Issues

### #1: Orphaned Reply Messages (No FK Constraint)

**File:** `bot/db/models/message.py:147-151`

**Issue:** `reply_to_message_id` is NOT a foreign key. If replied-to message is deleted, reference becomes dangling.

**Impact:** Data integrity - orphaned replies in database.

**Fix:**
```python
# Option 1: Add FK (requires composite key)
ForeignKeyConstraint(
    ['chat_id', 'reply_to_message_id'],
    ['messages.chat_id', 'messages.message_id'],
    ondelete='SET NULL'
)

# Option 2: Application-level cleanup
```

---

## High Issues

### #2: UserFile Join Query Broken

**File:** `bot/db/repositories/user_file_repository.py:207`

**Issue:** Join only on `message_id`, missing `chat_id`:
```python
# Current (WRONG):
Message, UserFile.message_id == Message.message_id

# Should be:
Message, and_(
    UserFile.message_id == Message.message_id,
    UserFile.chat_id == Message.chat_id
)
```

**Impact:** Query returns wrong files (matches any message_id across all chats).

**Fix:** Add `chat_id` to UserFile model and fix join.

---

### #3: Missing count() Method in BaseRepository

**File:** `bot/db/repositories/user_file_repository.py:307`

**Issue:** Calls `await self.count()` but BaseRepository doesn't define this method.

**Impact:** Runtime AttributeError when count_files() called.

**Fix:** Add to BaseRepository:
```python
async def count(self) -> int:
    stmt = select(func.count()).select_from(self.model)
    result = await self.session.execute(stmt)
    return result.scalar_one() or 0
```

---

### #4: Orphaned User Files (No FK)

**File:** `bot/db/models/user_file.py:99-104`

**Issue:** `message_id` is NOT a FK to messages (composite PK prevents simple FK).

**Impact:** Orphaned file records when messages deleted.

**Fix:** Add FK with both columns or implement cleanup cascade.

---

### #5: Cache Deserialization Type Mismatch

**File:** `bot/db/repositories/message_repository.py:323`

**Issue:** `created_at=msg_data["date"]` - `date` is Unix int, but `created_at` expects datetime.

**Impact:** Type mismatch during API serialization.

**Fix:**
```python
created_at=msg_data.get("created_at") or datetime.fromtimestamp(msg_data["date"], tz=timezone.utc)
```

---

## Medium Issues

### #6: Subquery Pagination Logic Unclear

**File:** `bot/db/repositories/message_repository.py:329-343`

**Issue:** With limit/offset, pagination skips most recent messages instead of standard pagination.

**Recommendation:** Document intent or use cursor-based pagination.

---

### #7: Duplicate Code - update_message() Methods

**File:** `bot/db/repositories/message_repository.py:175-261`

**Issue:** `update_message()` and `update_message_edit()` are nearly identical.

**Fix:** Consolidate into single method with optional return.

---

### #8: merge() Usage Inefficient

**File:** `bot/db/repositories/base.py:105`

**Issue:** Using `merge()` for updates reloads object from DB unnecessarily.

**Better:** Direct attribute assignment + flush.

---

### #9: Missing FK Migration for user_files.message_id

**Issue:** No migration adds FK constraint for message_id.

**Fix:** Create migration with composite FK.

---

## Positive Findings

- Strong async/await patterns
- No SQL injection vulnerabilities
- Excellent decimal precision handling
- Good audit trail (BalanceOperation)
- Proper timestamp handling (after migrations 008, 010)
- Clean separation of concerns

---

## Action Items

1. [ ] Fix UserFile join query (add chat_id)
2. [ ] Add count() method to BaseRepository
3. [ ] Fix cache deserialization type mismatch
4. [ ] Add FK constraints or cleanup logic for orphaned data
5. [ ] Document pagination behavior
