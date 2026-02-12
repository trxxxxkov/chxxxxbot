# Plan: Bot API 9.4 Topic Routing in Private Chats

**Status:** PAUSED — blocked by Telegram client bug (bot-created topics invisible in UI)
**Date:** 2026-02-12
**Resume when:** Telegram fixes client rendering of bot-created topics via `createForumTopic`

---

## What We Built

Intelligent auto-topic routing for private chats using Bot API 9.4:

1. **From General → existing/new topic**: When user writes in General, Haiku analyzes the message against recent topics and either routes to an existing one (`resume`) or creates a new one (`new`)
2. **From topic → other topic**: When user returns to an old topic after 5+ min gap with an unrelated message, Haiku detects off-topic and routes to the correct topic (existing or new)

### Files Modified
- `bot/services/topic_routing.py` — main orchestration (TopicRoutingService)
- `bot/services/topic_relevance.py` — Haiku-based relevance checking
- `bot/config.py` — `TOPIC_ROUTING_ENABLED` flag

### How It Works
1. `unified_handler` calls `_try_topic_routing()` after normalization, before thread resolution
2. `TopicRoutingService.maybe_route()` checks if routing applies (`_is_topics_enabled_private_chat`)
3. Routes to `_route_from_general()` or `_route_from_topic()` based on `message_thread_id`
4. Loads recent topic contexts from Redis cache (60s TTL) → DB fallback
5. Haiku decides: `stay` / `resume` (existing topic) / `new` (create topic)
6. Result propagates as `TopicRouteResult` with `override_thread_id`

---

## Bugs Found & Fixed (apply when re-enabling)

### Bug 1: `allows_users_to_create_topics` check too restrictive

**File:** `bot/services/topic_routing.py`, method `_is_topics_enabled_private_chat`

**Problem:** Original code disabled routing when `allows_users_to_create_topics=True`:
```python
# OLD — wrong:
if getattr(bot_me, 'allows_users_to_create_topics', True):
    return False
```

Routing is needed in BOTH modes:
- `False`: messages arrive from General (thread_id=None), bot should route them
- `True`: Telegram auto-creates topics, but cross-topic routing still needed

**Fix:** Remove the `allows_users_to_create_topics` check entirely:
```python
# NEW — correct:
async def _is_topics_enabled_private_chat(self, message):
    if message.chat.type != "private":
        return False
    bot_me = await message.bot.me()
    if not getattr(bot_me, 'has_topics_enabled', False):
        return False
    return True
```

### Bug 2: Stale `bot.me()` cache

**Problem:** aiogram caches `bot.me()` once at first call, never refreshes. If BotFather settings change after bot startup, the cache is stale and routing silently disables.

**Symptom:** Zero `topic_routing.started` logs despite `TOPIC_ROUTING_ENABLED=True`.

**Fix:** Restart bot after changing BotFather settings. Long-term: add periodic cache refresh or use `bot.get_me()` (uncached) for critical checks.

### Bug 3: Haiku returns topic title instead of label

**File:** `bot/services/topic_relevance.py`, method `_build_prompt`

**Problem:** Prompt said `"topic": "LABEL"` — Haiku interpreted "LABEL" as the topic title:
```
Haiku response: {"action": "resume", "topic": "Daniil"}  ← title, not label
Expected:       {"action": "resume", "topic": "A"}       ← letter label
```
Parser couldn't find label "DANIIL" → fell back to action "new" with generic "New chat" title.

**Fix:** Show actual labels in the example:
```python
# OLD:
'{"action": "resume", "topic": "LABEL"}'

# NEW:
label_examples = "/".join(t.label for t in other_topics)  # "A/B/C"
f'{{"action": "resume", "topic": "{label_examples}"}}'
```

### Bug 4: Missing `icon_color` in `createForumTopic`

**File:** `bot/services/topic_routing.py`, method `_create_topic`

**Problem:** Auto-created topics (by Telegram client) have icons. Bot-created topics had no `icon_color` → visually different (though this alone doesn't fix the visibility bug).

**Fix:** Add deterministic `icon_color` based on topic name:
```python
_TOPIC_ICON_COLORS = [
    7322096,   # 0x6FB9F0 — blue
    16766590,  # 0xFFD67E — yellow
    13338331,  # 0xCB86DB — purple
    9367192,   # 0x8EEE98 — green
    16749490,  # 0xFF93B2 — pink
    16478047,  # 0xFB6F5F — orange
]

color_idx = int(hashlib.md5(name.encode()).hexdigest(), 16) % len(_TOPIC_ICON_COLORS)
topic = await bot.create_forum_topic(
    chat_id=chat_id, name=name[:128], icon_color=_TOPIC_ICON_COLORS[color_idx],
)
```

---

## Telegram Client Bug (Blocker)

**Issue:** `createForumTopic` in private chats succeeds server-side but topic is NOT rendered in Telegram client UI.

**Evidence:**
- API returns `thread_id` ✓
- `forum_topic_created` system message arrives ✓
- Bot can send messages to the created topic ✓
- Topic does NOT appear in client sidebar/topic list ✗

**Tested with both:**
- `allows_users_to_create_topics=False`: bot-created topics invisible
- `allows_users_to_create_topics=True`: bot-created topics invisible (auto-created visible)
- With and without `icon_color`: no difference

**Context:** Bot API 9.4 released Feb 9, 2026 (3 days old). `createForumTopic` support for private chats was added in this version. Server-side works, client-side rendering is incomplete.

**Action needed:** Report on [bugs.telegram.org](https://bugs.telegram.org/) with tag "Bot API".

---

## BotFather Settings

| Setting | Value | Effect |
|---------|-------|--------|
| `has_topics_enabled` | `True` | Topics mode active in private chats |
| `allows_users_to_create_topics` | `False` | Bot controls topics (users write in General) |
| `allows_users_to_create_topics` | `True` | Telegram auto-creates topic per message (no General) |

**Current production:** `allows_users_to_create_topics=True` (workaround), routing disabled.

---

## Re-enable Checklist

When Telegram fixes the client bug:

1. Apply Bug 1 fix: remove `allows_users_to_create_topics` check in `_is_topics_enabled_private_chat`
2. Apply Bug 3 fix: use actual labels in Haiku prompt
3. Apply Bug 4 fix: add `icon_color` to `createForumTopic`
4. Set `TOPIC_ROUTING_ENABLED = True` in `config.py`
5. Set `allows_users_to_create_topics = False` in BotFather
6. Restart bot (for fresh `bot.me()` cache)
7. Test: message from General → routes to existing or creates new visible topic
8. Test: off-topic message in existing topic after 5+ min → redirects
