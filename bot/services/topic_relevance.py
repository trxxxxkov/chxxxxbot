"""Topic relevance service for intelligent routing decisions.

Uses a single Haiku call to determine whether a new message should:
- Stay in the current topic
- Resume an existing topic
- Start a new topic

Bot API 9.4: Auto-topic management in private chats.

NO __init__.py - use direct import:
    from services.topic_relevance import TopicRelevanceService
"""

import asyncio
from dataclasses import dataclass
from dataclasses import field
import json
import string
import time

from cache.client import get_redis
from cache.thread_cache import get_cached_messages
import config
from core.clients import get_anthropic_async_client
from core.pricing import calculate_claude_cost
from db.models.thread import Thread
from db.repositories.thread_repository import ThreadRepository
from sqlalchemy.ext.asyncio import AsyncSession
from utils.metrics import record_cost
from utils.structured_logging import get_logger

# Cache TTL for recent topics list (short — topics change often)
_RECENT_TOPICS_TTL = 60  # seconds

logger = get_logger(__name__)


@dataclass
class TopicContext:
    """Context of one topic for relevance checking."""

    label: str  # "A", "B", "C"...
    thread_id: int  # Telegram thread_id
    internal_id: int  # DB thread.id
    title: str  # Topic title
    recent_user_messages: list[str] = field(default_factory=list)


@dataclass
class RelevanceResult:
    """Result of topic relevance check."""

    action: str  # "stay" | "resume" | "new"
    target_thread_id: int | None = None  # For "resume"
    target_internal_id: int | None = None
    title: str | None = None  # For "new" — suggested title


# System prompt for relevance checking
RELEVANCE_SYSTEM_PROMPT = """You route messages to the correct chat topic.

<rules>
- Analyze the new message and decide which topic it belongs to
- Consider semantic meaning, not just keywords
- A greeting or follow-up question usually continues the current topic
- A completely different subject needs a new topic or matches another one
- Output ONLY valid JSON, nothing else
</rules>"""

# Labels for topics
TOPIC_LABELS = list(string.ascii_uppercase)


class TopicRelevanceService:
    """Haiku-based topic relevance checker."""

    def __init__(
        self,
        model: str | None = None,
        max_tokens: int | None = None,
    ):
        """Initialize TopicRelevanceService.

        Args:
            model: Model to use. Default: config.TOPIC_ROUTING_MODEL
            max_tokens: Max tokens. Default: config.TOPIC_ROUTING_MAX_TOKENS
        """
        self.model = model or config.TOPIC_ROUTING_MODEL
        self.max_tokens = max_tokens or config.TOPIC_ROUTING_MAX_TOKENS

    async def check_relevance(
        self,
        new_message: str,
        current_topic: TopicContext | None,
        other_topics: list[TopicContext],
    ) -> RelevanceResult:
        """Check if message fits current topic, another topic, or needs new one.

        Args:
            new_message: The new user message text.
            current_topic: Current topic context (None when from General).
            other_topics: Other recent topics to check against.

        Returns:
            RelevanceResult with routing decision.
        """
        if not new_message.strip():
            # Empty message — stay or create new
            if current_topic:
                logger.debug("topic_relevance.empty_message_stay")
                return RelevanceResult(action="stay")
            logger.debug("topic_relevance.empty_message_new")
            return RelevanceResult(action="new", title="New chat")

        prompt = self._build_prompt(new_message, current_topic, other_topics)

        try:
            client = get_anthropic_async_client()
            haiku_start = time.perf_counter()
            response = await client.messages.create(
                model=self.model,
                max_tokens=self.max_tokens,
                system=RELEVANCE_SYSTEM_PROMPT,
                messages=[{
                    "role": "user",
                    "content": prompt,
                }],
            )
            haiku_ms = (time.perf_counter() - haiku_start) * 1000

            raw = response.content[0].text.strip()
            input_tokens = response.usage.input_tokens
            output_tokens = response.usage.output_tokens

            # Calculate and log cost for Grafana
            cost_usd = calculate_claude_cost(
                model_id=self.model,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
            )
            record_cost(service="topic_routing", amount_usd=float(cost_usd))

            logger.info(
                "topic_routing.cost",
                cost_usd=float(cost_usd),
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                haiku_ms=round(haiku_ms, 2),
            )

            logger.info(
                "topic_relevance.haiku_response",
                raw=raw,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                haiku_ms=round(haiku_ms, 2),
                from_general=current_topic is None,
                topics_checked=len(other_topics),
            )

            result = self._parse_response(raw, current_topic, other_topics)

            logger.info(
                "topic_relevance.decision",
                action=result.action,
                target_thread_id=result.target_thread_id,
                title=result.title,
                haiku_ms=round(haiku_ms, 2),
            )

            return result

        except Exception as e:
            logger.error(
                "topic_relevance.check_failed",
                error=str(e),
                error_type=type(e).__name__,
                from_general=current_topic is None,
                topics_checked=len(other_topics),
            )
            # Safe fallback
            if current_topic:
                return RelevanceResult(action="stay")
            return RelevanceResult(action="new", title="New chat")

    def _build_prompt(
        self,
        new_message: str,
        current_topic: TopicContext | None,
        other_topics: list[TopicContext],
    ) -> str:
        """Build the relevance check prompt.

        Args:
            new_message: New user message.
            current_topic: Current topic (None from General).
            other_topics: Other recent topics.

        Returns:
            Formatted prompt string.
        """
        parts = []

        if current_topic:
            parts.append(f'Current topic: "{current_topic.title}"')
            if current_topic.recent_user_messages:
                msgs = ", ".join(
                    f'"{m}"' for m in current_topic.recent_user_messages)
                parts.append(f"Recent messages: {msgs}")
            parts.append("")

        if other_topics:
            parts.append("Other recent topics:")
            for topic in other_topics:
                msgs = ""
                if topic.recent_user_messages:
                    msgs = " — " + ", ".join(
                        f'"{m}"' for m in topic.recent_user_messages)
                parts.append(f'{topic.label}) "{topic.title}"{msgs}')
            parts.append("")

        truncated = new_message[:config.TOPIC_SWITCH_MSG_TRUNCATE]
        parts.append(f'New message: "{truncated}"')
        parts.append("")

        if current_topic and other_topics:
            parts.append("Does this message:")
            parts.append('A) Continue current topic → {"action": "stay"}')
            parts.append(
                'B) Fit another topic → {"action": "resume", "topic": "LABEL"}')
            parts.append(
                'C) Need a new topic → {"action": "new", "title": "Short Title"}'
            )
        elif current_topic:
            parts.append("Does this message:")
            parts.append('A) Continue current topic → {"action": "stay"}')
            parts.append(
                'B) Need a new topic → {"action": "new", "title": "Short Title"}'
            )
        else:
            # From General
            if other_topics:
                parts.append(
                    "Does this message continue one of the existing topics?")
                parts.append('{"action": "resume", "topic": "LABEL"}')
                parts.append("Or is it a completely new subject?")
                parts.append('{"action": "new", "title": "Short Title"}')
            else:
                parts.append('Generate a short title:')
                parts.append('{"action": "new", "title": "Short Title"}')

        return "\n".join(parts)

    def _parse_response(
        self,
        raw: str,
        current_topic: TopicContext | None,
        other_topics: list[TopicContext],
    ) -> RelevanceResult:
        """Parse Haiku JSON response into RelevanceResult.

        Args:
            raw: Raw response text from Haiku.
            current_topic: Current topic context.
            other_topics: Other topic contexts.

        Returns:
            Parsed RelevanceResult.
        """
        try:
            # Extract JSON from response (may have extra text)
            json_start = raw.find("{")
            json_end = raw.rfind("}") + 1
            if json_start == -1 or json_end == 0:
                raise ValueError("No JSON found in response")

            data = json.loads(raw[json_start:json_end])
            action = data.get("action", "")

            if action == "stay":
                return RelevanceResult(action="stay")

            if action == "resume":
                label = data.get("topic", "").upper()
                # Find matching topic
                for topic in other_topics:
                    if topic.label == label:
                        return RelevanceResult(
                            action="resume",
                            target_thread_id=topic.thread_id,
                            target_internal_id=topic.internal_id,
                        )
                # Label not found — treat as new
                logger.info("topic_relevance.label_not_found", label=label)
                return RelevanceResult(
                    action="new",
                    title=data.get("title", "New chat"),
                )

            if action == "new":
                title = data.get("title", "New chat")
                # Clean up title
                if title.startswith('"') and title.endswith('"'):
                    title = title[1:-1]
                if title.startswith("'") and title.endswith("'"):
                    title = title[1:-1]
                title = title[:config.TOPIC_TEMP_NAME_MAX_LENGTH]
                return RelevanceResult(action="new", title=title)

            # Unknown action
            raise ValueError(f"Unknown action: {action}")

        except (json.JSONDecodeError, ValueError, KeyError) as e:
            logger.info("topic_relevance.parse_failed", raw=raw, error=str(e))
            if current_topic:
                return RelevanceResult(action="stay")
            return RelevanceResult(action="new", title="New chat")


async def load_recent_topic_contexts(
    user_id: int,
    chat_id: int,
    exclude_thread_id: int | None,
    session: AsyncSession,
    limit: int | None = None,
) -> list[TopicContext]:
    """Load recent topic contexts for relevance checking.

    Uses Redis cache for topic list (60s TTL) and parallel Redis reads
    for message histories.

    Args:
        user_id: Telegram user ID.
        chat_id: Telegram chat ID.
        exclude_thread_id: Telegram thread_id to exclude.
        session: Database session.
        limit: Max topics. Default: config.TOPIC_SWITCH_RECENT_TOPICS

    Returns:
        List of TopicContext with recent user messages.
    """
    if limit is None:
        limit = config.TOPIC_SWITCH_RECENT_TOPICS

    load_start = time.perf_counter()

    # Step 1: Get topic metadata (Redis cache → DB fallback)
    topics_info = await _get_recent_topics_cached(chat_id, user_id, session,
                                                  limit + 1)

    # Filter out excluded topic, then limit
    if exclude_thread_id is not None:
        topics_info = [
            t for t in topics_info if t["thread_id"] != exclude_thread_id
        ]
    topics_info = topics_info[:limit]

    if not topics_info:
        logger.debug(
            "topic_relevance.no_topics_found",
            user_id=user_id,
            chat_id=chat_id,
        )
        return []

    # Cap to available labels
    topics_info = topics_info[:len(TOPIC_LABELS)]

    # Step 2: Load messages for all topics in parallel
    coros = [_get_user_messages_for_topic(t["id"]) for t in topics_info]
    msgs_list = await asyncio.gather(*coros)

    # Step 3: Build TopicContext list
    contexts = []
    for idx, (tinfo, msgs) in enumerate(zip(topics_info, msgs_list)):
        contexts.append(
            TopicContext(
                label=TOPIC_LABELS[idx],
                thread_id=tinfo["thread_id"],
                internal_id=tinfo["id"],
                title=tinfo["title"],
                recent_user_messages=msgs,
            ))

    load_ms = (time.perf_counter() - load_start) * 1000
    total_msgs = sum(len(c.recent_user_messages) for c in contexts)
    logger.info(
        "topic_relevance.contexts_loaded",
        user_id=user_id,
        chat_id=chat_id,
        topics_count=len(contexts),
        total_messages=total_msgs,
        load_ms=round(load_ms, 2),
    )

    return contexts


async def _get_recent_topics_cached(
    chat_id: int,
    user_id: int,
    session: AsyncSession,
    limit: int,
) -> list[dict]:
    """Get recent topic metadata from Redis cache or DB.

    Caches the full (unfiltered) list for 60s to avoid DB query on
    every message from General.

    Args:
        chat_id: Telegram chat ID.
        user_id: Telegram user ID.
        session: Database session.
        limit: Max topics to fetch.

    Returns:
        List of dicts with id, thread_id, title.
    """
    cache_key = f"cache:recent_topics:{chat_id}:{user_id}"
    redis = await get_redis()

    # Try cache first
    if redis:
        try:
            data = await redis.get(cache_key)
            if data is not None:
                logger.debug("topic_relevance.recent_topics_cache_hit",
                             chat_id=chat_id,
                             user_id=user_id)
                return json.loads(data.decode("utf-8"))
        except Exception:
            pass

    # Cache miss — DB query
    thread_repo = ThreadRepository(session)
    threads = await thread_repo.get_recent_active_topics(
        chat_id=chat_id,
        user_id=user_id,
        exclude_thread_id=None,  # Cache full list, filter after
        limit=limit,
    )

    result = [{
        "id": t.id,
        "thread_id": t.thread_id,
        "title": t.title or "Untitled",
    } for t in threads]

    # Cache for 60s
    if redis:
        try:
            await redis.set(cache_key,
                            json.dumps(result),
                            ex=_RECENT_TOPICS_TTL)
            logger.debug("topic_relevance.recent_topics_cached",
                         chat_id=chat_id,
                         user_id=user_id,
                         count=len(result))
        except Exception:
            pass

    return result


async def _get_user_messages_for_topic(internal_thread_id: int,) -> list[str]:
    """Get recent user message texts for a topic from cache.

    Args:
        internal_thread_id: Internal thread ID.

    Returns:
        List of truncated user message texts.
    """
    cached = await get_cached_messages(internal_thread_id)
    if not cached:
        return []

    user_msgs = []
    for msg in reversed(cached):
        if msg.get("role") == "user" and msg.get("text_content"):
            text = msg["text_content"][:config.TOPIC_SWITCH_MSG_TRUNCATE]
            user_msgs.append(text)
            if len(user_msgs) >= config.TOPIC_SWITCH_RECENT_MESSAGES:
                break

    # Reverse to chronological order
    user_msgs.reverse()
    return user_msgs
