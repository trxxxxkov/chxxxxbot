"""Topic routing service for intelligent auto-topic management.

Orchestrates routing decisions for Bot API 9.4 private chats:
- From General: route to existing topic or create new one
- From existing topic: detect off-topic → route to another or create new

Uses TopicRelevanceService for Haiku-based decisions.
Topic creation and redirect messages are sent in parallel.

NO __init__.py - use direct import:
    from services.topic_routing import get_topic_routing_service
"""

import asyncio
from dataclasses import dataclass
from dataclasses import field
from datetime import datetime
from datetime import timezone
import time
from typing import Any

from aiogram import Bot
from aiogram import types
import config
from core.singleton import singleton
from db.repositories.thread_repository import ThreadRepository
from services.topic_relevance import load_recent_topic_contexts
from services.topic_relevance import TopicContext
from services.topic_relevance import TopicRelevanceService
from sqlalchemy.ext.asyncio import AsyncSession
from utils.structured_logging import get_logger

logger = get_logger(__name__)


@dataclass
class TopicRouteResult:
    """Result of topic routing decision."""

    action: str  # "passthrough" | "new" | "resume"
    override_thread_id: int | None = None  # Telegram topic ID to use
    title: str | None = None  # Title for new topic
    needs_topic_naming: bool = True  # False when title already set
    resolved_thread: Any = field(default=None,
                                 repr=False)  # Thread from gap check


_PASSTHROUGH = TopicRouteResult(action="passthrough")


class TopicRoutingService:
    """Orchestrates intelligent topic routing."""

    def __init__(self, relevance: TopicRelevanceService | None = None):
        """Initialize TopicRoutingService.

        Args:
            relevance: TopicRelevanceService instance. Creates default if None.
        """
        self.relevance = relevance or TopicRelevanceService()

    async def maybe_route(
        self,
        message: types.Message,
        processed_text: str | None,
        session: AsyncSession,
    ) -> TopicRouteResult:
        """Determine if message should be routed to a different topic.

        Args:
            message: Telegram message.
            processed_text: Extracted text (or transcript).
            session: Database session.

        Returns:
            TopicRouteResult with routing decision.
        """
        if not config.TOPIC_ROUTING_ENABLED:
            return _PASSTHROUGH

        if not await self._is_topics_enabled_private_chat(message):
            return _PASSTHROUGH

        if not message.from_user:
            return _PASSTHROUGH

        user_id = message.from_user.id
        chat_id = message.chat.id
        text = processed_text or ""
        route_start = time.perf_counter()

        logger.info(
            "topic_routing.started",
            user_id=user_id,
            chat_id=chat_id,
            from_general=message.message_thread_id is None,
            current_thread_id=message.message_thread_id,
            text_length=len(text),
        )

        if message.message_thread_id is None:
            # From General
            result = await self._route_from_general(
                message=message,
                text=text,
                user_id=user_id,
                chat_id=chat_id,
                session=session,
            )
        else:
            # From existing topic
            result = await self._route_from_topic(
                message=message,
                text=text,
                user_id=user_id,
                chat_id=chat_id,
                session=session,
            )

        route_ms = (time.perf_counter() - route_start) * 1000
        logger.info(
            "topic_routing.completed",
            user_id=user_id,
            chat_id=chat_id,
            action=result.action,
            override_thread_id=result.override_thread_id,
            route_ms=round(route_ms, 2),
        )

        return result

    async def _route_from_general(  # pylint: disable=too-many-return-statements
        self,
        message: types.Message,
        text: str,
        user_id: int,
        chat_id: int,
        session: AsyncSession,
    ) -> TopicRouteResult:
        """Route a message sent from General (no topic).

        Args:
            message: Telegram message.
            text: Message text.
            user_id: Telegram user ID.
            chat_id: Telegram chat ID.
            session: Database session.

        Returns:
            TopicRouteResult.
        """
        topics = await load_recent_topic_contexts(
            user_id=user_id,
            chat_id=chat_id,
            exclude_thread_id=None,
            session=session,
        )

        if not topics and not text.strip():
            # No topics and no text — create with default name
            logger.info(
                "topic_routing.general_no_topics_no_text",
                user_id=user_id,
            )
            thread_id = await self._create_topic(message.bot, chat_id,
                                                 "New chat")
            if thread_id is None:
                return _PASSTHROUGH
            return TopicRouteResult(
                action="new",
                override_thread_id=thread_id,
                title="New chat",
                needs_topic_naming=True,
            )

        if not topics:
            # No existing topics — create new with temp name
            temp_name = text[:config.TOPIC_TEMP_NAME_MAX_LENGTH] or "New chat"
            logger.info(
                "topic_routing.general_no_topics",
                user_id=user_id,
                temp_name=temp_name,
            )
            thread_id = await self._create_topic(message.bot, chat_id,
                                                 temp_name)
            if thread_id is None:
                return _PASSTHROUGH
            return TopicRouteResult(
                action="new",
                override_thread_id=thread_id,
                title=temp_name,
                needs_topic_naming=True,
            )

        logger.info(
            "topic_routing.general_checking_relevance",
            user_id=user_id,
            topics_count=len(topics),
        )

        # Have topics — check relevance
        result = await self.relevance.check_relevance(
            new_message=text,
            current_topic=None,
            other_topics=topics,
        )

        if result.action == "resume" and result.target_thread_id is not None:
            logger.info(
                "topic_routing.resume_from_general",
                user_id=user_id,
                target_thread_id=result.target_thread_id,
            )
            return TopicRouteResult(
                action="resume",
                override_thread_id=result.target_thread_id,
                needs_topic_naming=False,
            )

        # action == "new" (or fallback)
        title = result.title or text[:config.
                                     TOPIC_TEMP_NAME_MAX_LENGTH] or "New chat"
        logger.info(
            "topic_routing.new_from_general",
            user_id=user_id,
            title=title,
        )
        thread_id = await self._create_topic(message.bot, chat_id, title)
        if thread_id is None:
            return _PASSTHROUGH
        return TopicRouteResult(
            action="new",
            override_thread_id=thread_id,
            title=title,
            needs_topic_naming=True,
        )

    async def _route_from_topic(
        self,
        message: types.Message,
        text: str,
        user_id: int,
        chat_id: int,
        session: AsyncSession,
    ) -> TopicRouteResult:
        """Route a message sent from an existing topic.

        Args:
            message: Telegram message.
            text: Message text.
            user_id: Telegram user ID.
            chat_id: Telegram chat ID.
            session: Database session.

        Returns:
            TopicRouteResult.
        """
        current_thread_id = message.message_thread_id

        # Check time gap — skip if recent activity
        thread_repo = ThreadRepository(session)
        thread = await thread_repo.get_active_thread(
            chat_id=chat_id,
            user_id=user_id,
            thread_id=current_thread_id,
        )

        if thread and thread.updated_at:
            now = datetime.now(timezone.utc)
            gap_minutes = (now - thread.updated_at).total_seconds() / 60
            if gap_minutes < config.TOPIC_SWITCH_MIN_GAP_MINUTES:
                logger.debug(
                    "topic_routing.short_gap_passthrough",
                    user_id=user_id,
                    thread_id=current_thread_id,
                    gap_minutes=round(gap_minutes, 1),
                    min_gap=config.TOPIC_SWITCH_MIN_GAP_MINUTES,
                )
                return TopicRouteResult(action="passthrough",
                                        resolved_thread=thread)
            logger.info(
                "topic_routing.gap_exceeded",
                user_id=user_id,
                thread_id=current_thread_id,
                gap_minutes=round(gap_minutes, 1),
            )

        # Load current topic context and other topics in parallel
        current_ctx_coro = self._build_current_context(thread)
        others_coro = load_recent_topic_contexts(
            user_id=user_id,
            chat_id=chat_id,
            exclude_thread_id=current_thread_id,
            session=session,
            limit=config.TOPIC_SWITCH_RECENT_TOPICS - 1,
        )
        current_ctx, others = await asyncio.gather(current_ctx_coro,
                                                   others_coro)

        if not current_ctx:
            logger.debug(
                "topic_routing.no_current_context",
                user_id=user_id,
                thread_id=current_thread_id,
            )
            return _PASSTHROUGH

        logger.info(
            "topic_routing.topic_checking_relevance",
            user_id=user_id,
            current_thread_id=current_thread_id,
            current_title=current_ctx.title,
            other_topics_count=len(others),
        )

        result = await self.relevance.check_relevance(
            new_message=text,
            current_topic=current_ctx,
            other_topics=others,
        )

        if result.action == "stay":
            logger.info(
                "topic_routing.stay_in_topic",
                user_id=user_id,
                thread_id=current_thread_id,
            )
            return TopicRouteResult(action="passthrough",
                                    resolved_thread=thread)

        if result.action == "resume" and result.target_thread_id is not None:
            # Route to existing topic — send redirect in old topic (parallel)
            target_title = self._find_topic_title(others,
                                                  result.target_thread_id)
            asyncio.create_task(
                self._send_redirect(message.bot, chat_id, current_thread_id,
                                    target_title))

            logger.info(
                "topic_routing.resume_from_topic",
                user_id=user_id,
                old_thread_id=current_thread_id,
                target_thread_id=result.target_thread_id,
                target_title=target_title,
            )
            return TopicRouteResult(
                action="resume",
                override_thread_id=result.target_thread_id,
                needs_topic_naming=False,
            )

        # action == "new"
        title = result.title or text[:config.
                                     TOPIC_TEMP_NAME_MAX_LENGTH] or "New chat"

        # Create topic and send redirect in parallel
        create_coro = self._create_topic(message.bot, chat_id, title)
        redirect_coro = self._send_redirect(message.bot, chat_id,
                                            current_thread_id, title)
        new_thread_id, _ = await asyncio.gather(create_coro, redirect_coro)

        if new_thread_id is None:
            return _PASSTHROUGH

        logger.info(
            "topic_routing.new_from_topic",
            user_id=user_id,
            old_thread_id=current_thread_id,
            new_thread_id=new_thread_id,
            title=title,
        )
        return TopicRouteResult(
            action="new",
            override_thread_id=new_thread_id,
            title=title,
            needs_topic_naming=False,
        )

    async def _build_current_context(
        self,
        thread,
    ) -> TopicContext | None:
        """Build TopicContext for current topic from thread.

        Args:
            thread: Thread model instance.

        Returns:
            TopicContext or None.
        """
        if not thread or thread.thread_id is None:
            return None

        from services.topic_relevance import \
            _get_user_messages_for_topic  # pylint: disable=import-outside-toplevel

        recent = await _get_user_messages_for_topic(thread.id)
        return TopicContext(
            label="current",
            thread_id=thread.thread_id,
            internal_id=thread.id,
            title=thread.title or "Untitled",
            recent_user_messages=recent,
        )

    async def _is_topics_enabled_private_chat(
        self,
        message: types.Message,
    ) -> bool:
        """Check if this is a private chat with bot-managed topics.

        Args:
            message: Telegram message.

        Returns:
            True if routing should be applied.
        """
        if message.chat.type != "private":
            return False

        # Private chat with topics: is_forum=True indicates topics are enabled
        if not getattr(message.chat, 'is_forum', False):
            return False

        return True

    async def _create_topic(
        self,
        bot: Bot,
        chat_id: int,
        name: str,
    ) -> int | None:
        """Create a new forum topic.

        Args:
            bot: Telegram Bot instance.
            chat_id: Chat ID.
            name: Topic name (max 128 chars).

        Returns:
            New topic's message_thread_id, or None on failure.
        """
        try:
            topic = await bot.create_forum_topic(chat_id=chat_id,
                                                 name=name[:128])
            logger.info(
                "topic_routing.topic_created",
                chat_id=chat_id,
                thread_id=topic.message_thread_id,
                name=name[:128],
            )
            return topic.message_thread_id
        except Exception as e:
            logger.error(
                "topic_routing.create_failed",
                chat_id=chat_id,
                name=name[:128],
                error=str(e),
                error_type=type(e).__name__,
            )
            return None

    async def _send_redirect(
        self,
        bot: Bot,
        chat_id: int,
        old_topic_id: int,
        title: str,
    ) -> None:
        """Send redirect message in old topic.

        Args:
            bot: Telegram Bot instance.
            chat_id: Chat ID.
            old_topic_id: Topic to send redirect in.
            title: Title of target topic.
        """
        try:
            await bot.send_message(
                chat_id=chat_id,
                text=f"\u2197\ufe0f {title}",
                message_thread_id=old_topic_id,
            )
            logger.debug(
                "topic_routing.redirect_sent",
                chat_id=chat_id,
                old_topic_id=old_topic_id,
                title=title,
            )
        except Exception as e:
            logger.debug(
                "topic_routing.redirect_failed",
                chat_id=chat_id,
                old_topic_id=old_topic_id,
                error=str(e),
            )

    @staticmethod
    def _find_topic_title(
        topics: list[TopicContext],
        thread_id: int,
    ) -> str:
        """Find topic title by thread_id.

        Args:
            topics: List of topic contexts.
            thread_id: Telegram thread_id to find.

        Returns:
            Topic title or "Topic".
        """
        for t in topics:
            if t.thread_id == thread_id:
                return t.title
        return "Topic"


@singleton
def get_topic_routing_service() -> TopicRoutingService:
    """Get or create TopicRoutingService singleton.

    Returns:
        TopicRoutingService instance.
    """
    return TopicRoutingService()
