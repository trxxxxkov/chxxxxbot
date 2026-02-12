"""Tests for services/topic_routing.py - Topic routing orchestrator.

Tests for TopicRoutingService with mocked dependencies.

NO __init__.py - use direct import:
    pytest tests/services/test_topic_routing.py
"""

from datetime import datetime
from datetime import timedelta
from datetime import timezone
from unittest.mock import AsyncMock
from unittest.mock import MagicMock
from unittest.mock import patch

import pytest
from services.topic_relevance import RelevanceResult
from services.topic_relevance import TopicContext
from services.topic_routing import get_topic_routing_service
from services.topic_routing import TopicRoutingService

# =============================================================================
# Test Fixtures
# =============================================================================


@pytest.fixture
def mock_relevance():
    """Create mock TopicRelevanceService."""
    return AsyncMock()


@pytest.fixture
def service(mock_relevance):
    """Create TopicRoutingService with mock relevance."""
    return TopicRoutingService(relevance=mock_relevance)


@pytest.fixture
def mock_message():
    """Create mock Telegram message from General (no thread_id)."""
    msg = MagicMock()
    msg.chat.type = "private"
    msg.chat.id = 123
    msg.chat.is_forum = True
    msg.from_user.id = 456
    msg.message_thread_id = None
    msg.bot = AsyncMock()
    msg.bot.me = AsyncMock(return_value=MagicMock(
        has_topics_enabled=True,
        allows_users_to_create_topics=False,
    ))
    return msg


@pytest.fixture
def mock_message_in_topic():
    """Create mock Telegram message from existing topic."""
    msg = MagicMock()
    msg.chat.type = "private"
    msg.chat.id = 123
    msg.chat.is_forum = True
    msg.from_user.id = 456
    msg.message_thread_id = 42
    msg.bot = AsyncMock()
    msg.bot.me = AsyncMock(return_value=MagicMock(
        has_topics_enabled=True,
        allows_users_to_create_topics=False,
    ))
    return msg


@pytest.fixture
def mock_session():
    """Create mock database session."""
    return AsyncMock()


@pytest.fixture
def sample_topics():
    """Create sample topic contexts."""
    return [
        TopicContext(
            label="A",
            thread_id=10,
            internal_id=1,
            title="React rendering bug",
            recent_user_messages=["How do I fix..."],
        ),
        TopicContext(
            label="B",
            thread_id=20,
            internal_id=2,
            title="Italian Recipes",
            recent_user_messages=["Best pasta recipe"],
        ),
    ]


# =============================================================================
# Passthrough Tests
# =============================================================================


class TestPassthrough:
    """Tests for passthrough conditions."""

    @pytest.mark.asyncio
    async def test_passthrough_when_disabled(self, service, mock_message,
                                             mock_session):
        """Should passthrough when routing is disabled."""
        with patch("config.TOPIC_ROUTING_ENABLED", False):
            result = await service.maybe_route(
                message=mock_message,
                processed_text="test",
                session=mock_session,
            )

        assert result.action == "passthrough"

    @pytest.mark.asyncio
    async def test_passthrough_for_group_chat(self, service, mock_session):
        """Should passthrough for group chats."""
        msg = MagicMock()
        msg.chat.type = "group"
        msg.from_user.id = 456

        with patch("config.TOPIC_ROUTING_ENABLED", True):
            result = await service.maybe_route(
                message=msg,
                processed_text="test",
                session=mock_session,
            )

        assert result.action == "passthrough"

    @pytest.mark.asyncio
    async def test_passthrough_for_non_forum_private_chat(
            self, service, mock_session):
        """Should passthrough for private chats without forum/topics."""
        msg = MagicMock()
        msg.chat.type = "private"
        msg.chat.is_forum = False
        msg.from_user.id = 456

        with patch("config.TOPIC_ROUTING_ENABLED", True):
            result = await service.maybe_route(
                message=msg,
                processed_text="test",
                session=mock_session,
            )

        assert result.action == "passthrough"

    @pytest.mark.asyncio
    async def test_passthrough_no_user(self, service, mock_session):
        """Should passthrough when message has no from_user."""
        msg = MagicMock()
        msg.chat.type = "private"
        msg.chat.is_forum = True
        msg.from_user = None

        with patch("config.TOPIC_ROUTING_ENABLED", True):
            result = await service.maybe_route(
                message=msg,
                processed_text="test",
                session=mock_session,
            )

        assert result.action == "passthrough"


# =============================================================================
# Route from General Tests
# =============================================================================


class TestRouteFromGeneral:
    """Tests for routing from General (no thread_id)."""

    @pytest.mark.asyncio
    async def test_no_topics_creates_new(self, service, mock_message,
                                         mock_session):
        """Should create new topic when no existing topics."""
        mock_topic = MagicMock()
        mock_topic.message_thread_id = 99

        mock_message.bot.create_forum_topic = AsyncMock(return_value=mock_topic)

        with patch("config.TOPIC_ROUTING_ENABLED", True), \
             patch("services.topic_routing.load_recent_topic_contexts",
                   new_callable=AsyncMock, return_value=[]):
            result = await service.maybe_route(
                message=mock_message,
                processed_text="Hello world",
                session=mock_session,
            )

        assert result.action == "new"
        assert result.override_thread_id == 99
        assert result.needs_topic_naming is True

    @pytest.mark.asyncio
    async def test_resume_existing_topic(self, service, mock_relevance,
                                         mock_message, mock_session,
                                         sample_topics):
        """Should resume existing topic when Haiku says so."""
        mock_relevance.check_relevance = AsyncMock(return_value=RelevanceResult(
            action="resume",
            target_thread_id=10,
            target_internal_id=1,
        ))

        with patch("config.TOPIC_ROUTING_ENABLED", True), \
             patch("services.topic_routing.load_recent_topic_contexts",
                   new_callable=AsyncMock, return_value=sample_topics):
            result = await service.maybe_route(
                message=mock_message,
                processed_text="Fix the React bug",
                session=mock_session,
            )

        assert result.action == "resume"
        assert result.override_thread_id == 10
        assert result.needs_topic_naming is False

    @pytest.mark.asyncio
    async def test_new_topic_from_general(self, service, mock_relevance,
                                          mock_message, mock_session,
                                          sample_topics):
        """Should create new topic when Haiku says new."""
        mock_relevance.check_relevance = AsyncMock(return_value=RelevanceResult(
            action="new",
            title="Docker Setup",
        ))

        mock_topic = MagicMock()
        mock_topic.message_thread_id = 55
        mock_message.bot.create_forum_topic = AsyncMock(return_value=mock_topic)

        with patch("config.TOPIC_ROUTING_ENABLED", True), \
             patch("services.topic_routing.load_recent_topic_contexts",
                   new_callable=AsyncMock, return_value=sample_topics):
            result = await service.maybe_route(
                message=mock_message,
                processed_text="How to setup Docker?",
                session=mock_session,
            )

        assert result.action == "new"
        assert result.override_thread_id == 55
        assert result.title == "Docker Setup"
        assert result.needs_topic_naming is True

    @pytest.mark.asyncio
    async def test_create_topic_failure_passthrough(self, service,
                                                    mock_relevance,
                                                    mock_message, mock_session):
        """Should passthrough when topic creation fails."""
        mock_message.bot.create_forum_topic = AsyncMock(
            side_effect=Exception("Telegram Error"))

        with patch("config.TOPIC_ROUTING_ENABLED", True), \
             patch("services.topic_routing.load_recent_topic_contexts",
                   new_callable=AsyncMock, return_value=[]):
            result = await service.maybe_route(
                message=mock_message,
                processed_text="Hello",
                session=mock_session,
            )

        assert result.action == "passthrough"


# =============================================================================
# Route from Topic Tests
# =============================================================================


class TestRouteFromTopic:
    """Tests for routing from existing topic."""

    @pytest.mark.asyncio
    async def test_passthrough_short_gap(self, service, mock_message_in_topic,
                                         mock_session):
        """Should passthrough when gap < min minutes."""
        recent_time = datetime.now(timezone.utc) - timedelta(minutes=2)

        mock_thread = MagicMock()
        mock_thread.updated_at = recent_time
        mock_thread.thread_id = 42
        mock_thread.id = 1

        with patch("config.TOPIC_ROUTING_ENABLED", True), \
             patch("services.topic_routing.ThreadRepository") as mock_repo_cls:
            mock_repo = mock_repo_cls.return_value
            mock_repo.get_active_thread = AsyncMock(return_value=mock_thread)

            result = await service.maybe_route(
                message=mock_message_in_topic,
                processed_text="test",
                session=mock_session,
            )

        assert result.action == "passthrough"

    @pytest.mark.asyncio
    async def test_stay_after_haiku_check(self, service, mock_relevance,
                                          mock_message_in_topic, mock_session):
        """Should stay when Haiku says message is on-topic."""
        old_time = datetime.now(timezone.utc) - timedelta(minutes=30)

        mock_thread = MagicMock()
        mock_thread.updated_at = old_time
        mock_thread.thread_id = 42
        mock_thread.id = 1
        mock_thread.title = "Python Topic"

        mock_relevance.check_relevance = AsyncMock(return_value=RelevanceResult(
            action="stay"))

        with patch("config.TOPIC_ROUTING_ENABLED", True), \
             patch("services.topic_routing.ThreadRepository") as mock_repo_cls, \
             patch("services.topic_routing.load_recent_topic_contexts",
                   new_callable=AsyncMock, return_value=[]), \
             patch("services.topic_relevance._get_user_messages_for_topic",
                   new_callable=AsyncMock, return_value=["msg1"]):
            mock_repo = mock_repo_cls.return_value
            mock_repo.get_active_thread = AsyncMock(return_value=mock_thread)

            result = await service.maybe_route(
                message=mock_message_in_topic,
                processed_text="More about Python",
                session=mock_session,
            )

        assert result.action == "passthrough"

    @pytest.mark.asyncio
    async def test_resume_different_topic(self, service, mock_relevance,
                                          mock_message_in_topic, mock_session,
                                          sample_topics):
        """Should resume another topic and send redirect."""
        old_time = datetime.now(timezone.utc) - timedelta(minutes=30)

        mock_thread = MagicMock()
        mock_thread.updated_at = old_time
        mock_thread.thread_id = 42
        mock_thread.id = 1
        mock_thread.title = "Python Topic"

        mock_relevance.check_relevance = AsyncMock(return_value=RelevanceResult(
            action="resume",
            target_thread_id=20,
            target_internal_id=2,
        ))

        with patch("config.TOPIC_ROUTING_ENABLED", True), \
             patch("services.topic_routing.ThreadRepository") as mock_repo_cls, \
             patch("services.topic_routing.load_recent_topic_contexts",
                   new_callable=AsyncMock, return_value=sample_topics), \
             patch("services.topic_relevance._get_user_messages_for_topic",
                   new_callable=AsyncMock, return_value=["msg1"]):
            mock_repo = mock_repo_cls.return_value
            mock_repo.get_active_thread = AsyncMock(return_value=mock_thread)

            result = await service.maybe_route(
                message=mock_message_in_topic,
                processed_text="How to cook pasta?",
                session=mock_session,
            )

        assert result.action == "resume"
        assert result.override_thread_id == 20
        assert result.needs_topic_naming is False

    @pytest.mark.asyncio
    async def test_new_topic_from_existing(self, service, mock_relevance,
                                           mock_message_in_topic, mock_session):
        """Should create new topic and send redirect."""
        old_time = datetime.now(timezone.utc) - timedelta(minutes=30)

        mock_thread = MagicMock()
        mock_thread.updated_at = old_time
        mock_thread.thread_id = 42
        mock_thread.id = 1
        mock_thread.title = "Python Topic"

        mock_relevance.check_relevance = AsyncMock(return_value=RelevanceResult(
            action="new",
            title="Docker Setup",
        ))

        mock_topic = MagicMock()
        mock_topic.message_thread_id = 77
        mock_message_in_topic.bot.create_forum_topic = AsyncMock(
            return_value=mock_topic)
        mock_message_in_topic.bot.send_message = AsyncMock()

        with patch("config.TOPIC_ROUTING_ENABLED", True), \
             patch("services.topic_routing.ThreadRepository") as mock_repo_cls, \
             patch("services.topic_routing.load_recent_topic_contexts",
                   new_callable=AsyncMock, return_value=[]), \
             patch("services.topic_relevance._get_user_messages_for_topic",
                   new_callable=AsyncMock, return_value=["msg1"]):
            mock_repo = mock_repo_cls.return_value
            mock_repo.get_active_thread = AsyncMock(return_value=mock_thread)

            result = await service.maybe_route(
                message=mock_message_in_topic,
                processed_text="How to setup Docker?",
                session=mock_session,
            )

        assert result.action == "new"
        assert result.override_thread_id == 77
        assert result.title == "Docker Setup"
        assert result.needs_topic_naming is False


# =============================================================================
# Helper Tests
# =============================================================================


class TestHelpers:
    """Tests for helper methods."""

    @pytest.mark.asyncio
    async def test_is_topics_enabled_private_chat(self, service):
        """Should return True for private forum chats."""
        msg = MagicMock()
        msg.chat.type = "private"
        msg.chat.is_forum = True

        result = await service._is_topics_enabled_private_chat(msg)
        assert result is True

    @pytest.mark.asyncio
    async def test_is_topics_enabled_not_private(self, service):
        """Should return False for non-private chats."""
        msg = MagicMock()
        msg.chat.type = "group"

        result = await service._is_topics_enabled_private_chat(msg)
        assert result is False

    @pytest.mark.asyncio
    async def test_is_topics_enabled_not_forum(self, service):
        """Should return False for non-forum private chats."""
        msg = MagicMock()
        msg.chat.type = "private"
        msg.chat.is_forum = False

        result = await service._is_topics_enabled_private_chat(msg)
        assert result is False

    @pytest.mark.asyncio
    async def test_create_topic_success(self, service):
        """Should return thread_id on success."""
        bot = AsyncMock()
        topic = MagicMock()
        topic.message_thread_id = 99
        bot.create_forum_topic = AsyncMock(return_value=topic)

        result = await service._create_topic(bot, 123, "Test Topic")
        assert result == 99

    @pytest.mark.asyncio
    async def test_create_topic_failure(self, service):
        """Should return None on failure."""
        bot = AsyncMock()
        bot.create_forum_topic = AsyncMock(side_effect=Exception("API Error"))

        result = await service._create_topic(bot, 123, "Test Topic")
        assert result is None

    @pytest.mark.asyncio
    async def test_send_redirect(self, service):
        """Should send redirect message."""
        bot = AsyncMock()
        bot.send_message = AsyncMock()

        await service._send_redirect(bot, 123, 42, "New Topic")

        bot.send_message.assert_called_once_with(
            chat_id=123,
            text="\u2197\ufe0f New Topic",
            message_thread_id=42,
        )

    @pytest.mark.asyncio
    async def test_send_redirect_failure_silent(self, service):
        """Should not raise on redirect failure."""
        bot = AsyncMock()
        bot.send_message = AsyncMock(side_effect=Exception("Error"))

        # Should not raise
        await service._send_redirect(bot, 123, 42, "Topic")

    def test_find_topic_title(self, service, sample_topics):
        """Should find topic title by thread_id."""
        assert service._find_topic_title(sample_topics, 10) == \
            "React rendering bug"
        assert service._find_topic_title(sample_topics, 20) == \
            "Italian Recipes"
        assert service._find_topic_title(sample_topics, 99) == "Topic"


# =============================================================================
# Singleton Tests
# =============================================================================


class TestGetTopicRoutingService:
    """Tests for get_topic_routing_service singleton."""

    def test_returns_instance(self):
        """Should return TopicRoutingService instance."""
        get_topic_routing_service.reset()
        svc = get_topic_routing_service()
        assert isinstance(svc, TopicRoutingService)

    def test_returns_same_instance(self):
        """Should return same instance on subsequent calls."""
        get_topic_routing_service.reset()
        svc1 = get_topic_routing_service()
        svc2 = get_topic_routing_service()
        assert svc1 is svc2
