# Cache Layer Audit Report

**Date:** 2026-01-26
**Files:** `bot/cache/` (6 files)

---

## Summary

| Severity | Count |
|----------|-------|
| Critical | 1 |
| High | 3 |
| Medium | 5 |
| Low | 3 |

---

## Critical Issues

### #1: TTL Documentation Mismatch

**Files:** `keys.py:95-98`, `thread_cache.py:10-12`

**Issue:** Documentation claims TTLs of 600s/300s but actual implementation uses 3600s (1 hour) for all.

**Impact:** Message history cached for 1 hour instead of 5 minutes causes stale data scenarios.

**Fix:** Update either docs or implementation to be consistent. Recommend MESSAGES_TTL=300.

---

## High Issues

### #2: Race Condition in update_cached_messages

**File:** `thread_cache.py:359-423`

**Issue:** Read-modify-write without atomicity:
```python
data = await redis.get(key)  # Read
cached["messages"].append(new_message)  # Modify
await redis.setex(key, TTL, json.dumps(cached))  # Write
```

**Impact:** Concurrent updates can lose messages.

**Fix:** Use Redis WATCH/MULTI/EXEC or Lua script for atomicity.

---

### #3: Thread Index Stale Entries

**File:** `exec_cache.py:231-481`

**Issue:** Thread index SET (`exec:thread:{thread_id}`) may contain stale temp_ids after file expiration.

**Impact:** Memory leak with stale entries in Redis.

**Fix:** Explicit cleanup when files expire or use sorted sets with timestamps.

---

### #4: User Cache Update Not Atomic

**File:** `user_cache.py:205-269`

**Issue:** update_cached_balance performs in-place modification without atomicity.

**Impact:** Concurrent balance updates can overwrite each other.

**Fix:** Use compare-and-swap semantics or accept eventual consistency.

---

## Medium Issues

### #5: Concurrent Cache Invalidation Not Ordered

**Files:** `thread_cache.py:318-357`, `claude.py:795`

**Issue:** Invalidation between requests can race with cache population.

---

### #6: Circuit Breaker Half-Open Race

**File:** `client.py:141-169`

**Issue:** Global state without synchronization in circuit breaker.

---

### #7: Serialization Type Mismatch

**File:** `exec_cache.py:221-225`

**Issue:** No validation that content is bytes before storing.

---

### #8: Key Prefix Collision Risk

**File:** `keys.py`

**Issue:** No documented key registry - future key types could collide.

---

### #9: TTL Inconsistency with Invalidation

**Issue:** Cache uses both TTL (3600s) and explicit invalidation - conflicting strategies.

---

## Low Issues

- Missing specific JSON error handling (broad except catches all)
- No cache warming strategy
- Write-behind queue has no deduplication

---

## Priority Fixes

1. **CRITICAL:** Fix TTL values - decide on 300s or 3600s
2. **HIGH:** Make update_cached_messages atomic
3. **HIGH:** Add thread index cleanup mechanism
4. **MEDIUM:** Document cache consistency model
