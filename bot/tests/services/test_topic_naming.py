"""Tests for services/topic_naming.py - LLM-based topic naming.

Tests for TopicNamingService with mocked dependencies.

NO __init__.py - use direct import:
    pytest tests/services/test_topic_naming.py
"""

from decimal import Decimal
from unittest.mock import AsyncMock
from unittest.mock import MagicMock
from unittest.mock import patch

import pytest
from services.topic_naming import get_topic_naming_service
from services.topic_naming import TopicNamingService

# =============================================================================
# Test Fixtures
# =============================================================================


@pytest.fixture
def mock_anthropic_response():
    """Create mock Anthropic API response."""

    def _create_response(title: str,
                         input_tokens: int = 100,
                         output_tokens: int = 10):
        response = MagicMock()
        response.content = [MagicMock(text=title)]
        response.usage = MagicMock(input_tokens=input_tokens,
                                   output_tokens=output_tokens)
        return response

    return _create_response


@pytest.fixture
def mock_anthropic_client(mock_anthropic_response):
    """Create mock Anthropic async client."""
    client = AsyncMock()
    client.messages.create = AsyncMock(
        return_value=mock_anthropic_response("Test Title"))
    return client


@pytest.fixture
def mock_thread():
    """Create mock Thread object."""
    thread = MagicMock()
    thread.id = 1
    thread.user_id = 12345
    thread.chat_id = -100123456789
    thread.thread_id = 42
    thread.title = None
    thread.needs_topic_naming = True
    return thread


@pytest.fixture
def mock_bot():
    """Create mock Telegram Bot."""
    bot = AsyncMock()
    bot.edit_forum_topic = AsyncMock()
    return bot


@pytest.fixture
def mock_session():
    """Create mock database session."""
    return AsyncMock()


@pytest.fixture
def mock_service_factory():
    """Create mock ServiceFactory with balance service."""
    factory = MagicMock()
    factory.balance = MagicMock()
    factory.balance.charge_user = AsyncMock(return_value=Decimal("9.99"))
    return factory


@pytest.fixture
def topic_naming_service():
    """Create TopicNamingService instance for testing."""
    return TopicNamingService(
        model="claude-haiku-test",
        max_tokens=50,
    )


# =============================================================================
# generate_title Tests
# =============================================================================


class TestGenerateTitle:
    """Tests for generate_title method."""

    @pytest.mark.asyncio
    async def test_generate_title_basic(self, topic_naming_service,
                                        mock_anthropic_client,
                                        mock_anthropic_response):
        """Should generate title from user message and bot response."""
        mock_anthropic_client.messages.create.return_value = (
            mock_anthropic_response("Python async/await", 150, 8))

        with patch("services.topic_naming.get_anthropic_async_client",
                   return_value=mock_anthropic_client):
            title, input_tokens, output_tokens = await (
                topic_naming_service.generate_title(
                    user_message=
                    "What's the difference between async and await?",
                    bot_response="Great question! In Python, async/await...",
                ))

        assert title == "Python async/await"
        assert input_tokens == 150
        assert output_tokens == 8

    @pytest.mark.asyncio
    async def test_generate_title_removes_double_quotes(
            self, topic_naming_service, mock_anthropic_client,
            mock_anthropic_response):
        """Should remove double quotes from title."""
        mock_anthropic_client.messages.create.return_value = (
            mock_anthropic_response('"Quoted Title"'))

        with patch("services.topic_naming.get_anthropic_async_client",
                   return_value=mock_anthropic_client):
            title, _, _ = await topic_naming_service.generate_title(
                "user msg", "bot response")

        assert title == "Quoted Title"

    @pytest.mark.asyncio
    async def test_generate_title_removes_single_quotes(
            self, topic_naming_service, mock_anthropic_client,
            mock_anthropic_response):
        """Should remove single quotes from title."""
        mock_anthropic_client.messages.create.return_value = (
            mock_anthropic_response("'Single Quoted'"))

        with patch("services.topic_naming.get_anthropic_async_client",
                   return_value=mock_anthropic_client):
            title, _, _ = await topic_naming_service.generate_title(
                "user msg", "bot response")

        assert title == "Single Quoted"

    @pytest.mark.asyncio
    async def test_generate_title_truncates_long_title(self,
                                                       topic_naming_service,
                                                       mock_anthropic_client,
                                                       mock_anthropic_response):
        """Should truncate titles longer than 50 characters."""
        long_title = "A" * 100
        mock_anthropic_client.messages.create.return_value = (
            mock_anthropic_response(long_title))

        with patch("services.topic_naming.get_anthropic_async_client",
                   return_value=mock_anthropic_client):
            title, _, _ = await topic_naming_service.generate_title(
                "user msg", "bot response")

        assert len(title) == 50
        assert title == "A" * 50

    @pytest.mark.asyncio
    async def test_generate_title_truncates_input_messages(
            self, topic_naming_service, mock_anthropic_client,
            mock_anthropic_response):
        """Should truncate user message and bot response to 300 chars."""
        mock_anthropic_client.messages.create.return_value = (
            mock_anthropic_response("Short Title"))

        long_user_msg = "U" * 500
        long_bot_msg = "B" * 500

        with patch("services.topic_naming.get_anthropic_async_client",
                   return_value=mock_anthropic_client):
            await topic_naming_service.generate_title(long_user_msg,
                                                      long_bot_msg)

        # Check the API was called with truncated messages
        call_args = mock_anthropic_client.messages.create.call_args
        content = call_args[1]["messages"][0]["content"]

        # User message should be truncated to 300 chars
        assert "U" * 300 in content
        assert "U" * 301 not in content

    @pytest.mark.asyncio
    async def test_generate_title_strips_whitespace(self, topic_naming_service,
                                                    mock_anthropic_client,
                                                    mock_anthropic_response):
        """Should strip whitespace from title."""
        mock_anthropic_client.messages.create.return_value = (
            mock_anthropic_response("  Title with spaces  \n"))

        with patch("services.topic_naming.get_anthropic_async_client",
                   return_value=mock_anthropic_client):
            title, _, _ = await topic_naming_service.generate_title(
                "user msg", "bot response")

        assert title == "Title with spaces"


# =============================================================================
# maybe_name_topic Tests
# =============================================================================


class TestMaybeNameTopic:
    """Tests for maybe_name_topic method."""

    @pytest.mark.asyncio
    async def test_maybe_name_topic_success(self, topic_naming_service,
                                            mock_bot, mock_thread, mock_session,
                                            mock_service_factory,
                                            mock_anthropic_client,
                                            mock_anthropic_response):
        """Should generate title, charge user, and apply to Telegram."""
        mock_anthropic_client.messages.create.return_value = (
            mock_anthropic_response("Test Topic Title", 100, 10))

        with patch("services.topic_naming.get_anthropic_async_client",
                   return_value=mock_anthropic_client), \
             patch("services.topic_naming.ServiceFactory",
                   return_value=mock_service_factory), \
             patch("services.topic_naming.update_cached_balance",
                   new_callable=AsyncMock) as mock_update_cache, \
             patch("services.topic_naming.record_claude_request"), \
             patch("services.topic_naming.record_claude_tokens"), \
             patch("services.topic_naming.record_cost"), \
             patch.object(topic_naming_service, "model", "claude-haiku-test"), \
             patch("config.TOPIC_NAMING_ENABLED", True):

            result = await topic_naming_service.maybe_name_topic(
                bot=mock_bot,
                thread=mock_thread,
                user_message="Hello, help me with Python",
                bot_response="Sure! I can help with Python...",
                session=mock_session,
            )

        assert result == "Test Topic Title"
        assert mock_thread.title == "Test Topic Title"
        assert mock_thread.needs_topic_naming is False

        # Verify Bot API was called
        mock_bot.edit_forum_topic.assert_called_once_with(
            chat_id=mock_thread.chat_id,
            message_thread_id=mock_thread.thread_id,
            name="Test Topic Title",
        )

        # Verify user was charged
        mock_service_factory.balance.charge_user.assert_called_once()

        # Verify cache was updated
        mock_update_cache.assert_called_once()

    @pytest.mark.asyncio
    async def test_maybe_name_topic_skip_if_not_needed(self,
                                                       topic_naming_service,
                                                       mock_bot, mock_thread,
                                                       mock_session):
        """Should skip if needs_topic_naming is False."""
        mock_thread.needs_topic_naming = False

        with patch("config.TOPIC_NAMING_ENABLED", True):
            result = await topic_naming_service.maybe_name_topic(
                bot=mock_bot,
                thread=mock_thread,
                user_message="Hello",
                bot_response="Hi!",
                session=mock_session,
            )

        assert result is None
        mock_bot.edit_forum_topic.assert_not_called()

    @pytest.mark.asyncio
    async def test_maybe_name_topic_skip_if_disabled(self, topic_naming_service,
                                                     mock_bot, mock_thread,
                                                     mock_session):
        """Should skip if TOPIC_NAMING_ENABLED is False."""
        with patch("config.TOPIC_NAMING_ENABLED", False):
            result = await topic_naming_service.maybe_name_topic(
                bot=mock_bot,
                thread=mock_thread,
                user_message="Hello",
                bot_response="Hi!",
                session=mock_session,
            )

        assert result is None
        mock_bot.edit_forum_topic.assert_not_called()

    @pytest.mark.asyncio
    async def test_maybe_name_topic_skip_if_no_thread_id(
            self, topic_naming_service, mock_bot, mock_thread, mock_session):
        """Should skip if thread has no thread_id (not a topic)."""
        mock_thread.thread_id = None

        with patch("config.TOPIC_NAMING_ENABLED", True):
            result = await topic_naming_service.maybe_name_topic(
                bot=mock_bot,
                thread=mock_thread,
                user_message="Hello",
                bot_response="Hi!",
                session=mock_session,
            )

        assert result is None
        assert mock_thread.needs_topic_naming is False
        mock_bot.edit_forum_topic.assert_not_called()

    @pytest.mark.asyncio
    async def test_maybe_name_topic_continues_on_charge_failure(
            self, topic_naming_service, mock_bot, mock_thread, mock_session,
            mock_service_factory, mock_anthropic_client,
            mock_anthropic_response):
        """Should apply title even if charging fails."""
        mock_anthropic_client.messages.create.return_value = (
            mock_anthropic_response("Test Title", 100, 10))

        # Make charge_user raise an exception
        mock_service_factory.balance.charge_user.side_effect = Exception(
            "DB Error")

        with patch("services.topic_naming.get_anthropic_async_client",
                   return_value=mock_anthropic_client), \
             patch("services.topic_naming.ServiceFactory",
                   return_value=mock_service_factory), \
             patch("services.topic_naming.update_cached_balance",
                   new_callable=AsyncMock), \
             patch("services.topic_naming.record_claude_request"), \
             patch("services.topic_naming.record_claude_tokens"), \
             patch("services.topic_naming.record_cost"), \
             patch.object(topic_naming_service, "model", "claude-haiku-test"), \
             patch("config.TOPIC_NAMING_ENABLED", True):

            result = await topic_naming_service.maybe_name_topic(
                bot=mock_bot,
                thread=mock_thread,
                user_message="Hello",
                bot_response="Hi!",
                session=mock_session,
            )

        # Title should still be applied
        assert result == "Test Title"
        mock_bot.edit_forum_topic.assert_called_once()

    @pytest.mark.asyncio
    async def test_maybe_name_topic_returns_none_on_api_error(
            self, topic_naming_service, mock_bot, mock_thread, mock_session,
            mock_anthropic_client):
        """Should return None and keep needs_topic_naming=True on API error."""
        mock_anthropic_client.messages.create.side_effect = Exception(
            "API Error")

        with patch("services.topic_naming.get_anthropic_async_client",
                   return_value=mock_anthropic_client), \
             patch("config.TOPIC_NAMING_ENABLED", True):

            result = await topic_naming_service.maybe_name_topic(
                bot=mock_bot,
                thread=mock_thread,
                user_message="Hello",
                bot_response="Hi!",
                session=mock_session,
            )

        assert result is None
        # Should keep True to retry later
        assert mock_thread.needs_topic_naming is True
        mock_bot.edit_forum_topic.assert_not_called()

    @pytest.mark.asyncio
    async def test_maybe_name_topic_records_metrics(self, topic_naming_service,
                                                    mock_bot, mock_thread,
                                                    mock_session,
                                                    mock_service_factory,
                                                    mock_anthropic_client,
                                                    mock_anthropic_response):
        """Should record Prometheus metrics on success."""
        mock_anthropic_client.messages.create.return_value = (
            mock_anthropic_response("Metrics Test", 150, 15))

        with patch("services.topic_naming.get_anthropic_async_client",
                   return_value=mock_anthropic_client), \
             patch("services.topic_naming.ServiceFactory",
                   return_value=mock_service_factory), \
             patch("services.topic_naming.update_cached_balance",
                   new_callable=AsyncMock), \
             patch("services.topic_naming.record_claude_request") as mock_req, \
             patch("services.topic_naming.record_claude_tokens") as mock_tok, \
             patch("services.topic_naming.record_cost") as mock_cost, \
             patch.object(topic_naming_service, "model", "claude-haiku-test"), \
             patch("config.TOPIC_NAMING_ENABLED", True):

            await topic_naming_service.maybe_name_topic(
                bot=mock_bot,
                thread=mock_thread,
                user_message="Hello",
                bot_response="Hi!",
                session=mock_session,
            )

        # Verify metrics were recorded
        mock_req.assert_called_once_with(model="claude-haiku-test",
                                         success=True)
        mock_tok.assert_called_once_with(
            model="claude-haiku-test",
            input_tokens=150,
            output_tokens=15,
            cache_read_tokens=0,
            cache_write_tokens=0,
        )
        mock_cost.assert_called_once()


# =============================================================================
# Singleton Tests
# =============================================================================


class TestGetTopicNamingService:
    """Tests for get_topic_naming_service singleton function."""

    def test_returns_topic_naming_service_instance(self):
        """Should return TopicNamingService instance."""
        # Reset singleton for test
        get_topic_naming_service.reset()

        service = get_topic_naming_service()

        assert isinstance(service, TopicNamingService)

    def test_returns_same_instance(self):
        """Should return same instance on subsequent calls."""
        # Reset singleton for test
        get_topic_naming_service.reset()

        service1 = get_topic_naming_service()
        service2 = get_topic_naming_service()

        assert service1 is service2


# =============================================================================
# Configuration Tests
# =============================================================================


class TestTopicNamingServiceConfiguration:
    """Tests for TopicNamingService configuration."""

    def test_uses_default_model_from_config(self):
        """Should use config.TOPIC_NAMING_MODEL by default."""
        with patch("config.TOPIC_NAMING_MODEL", "claude-test-model"):
            service = TopicNamingService()

        assert service.model == "claude-test-model"

    def test_uses_default_max_tokens_from_config(self):
        """Should use config.TOPIC_NAMING_MAX_TOKENS by default."""
        with patch("config.TOPIC_NAMING_MAX_TOKENS", 100):
            service = TopicNamingService()

        assert service.max_tokens == 100

    def test_allows_custom_model(self):
        """Should allow overriding model."""
        service = TopicNamingService(model="custom-model")

        assert service.model == "custom-model"

    def test_allows_custom_max_tokens(self):
        """Should allow overriding max_tokens."""
        service = TopicNamingService(max_tokens=200)

        assert service.max_tokens == 200


# =============================================================================
# Edge Cases
# =============================================================================


class TestTopicNamingEdgeCases:
    """Edge case tests for topic naming."""

    @pytest.mark.asyncio
    async def test_generate_title_with_empty_messages(self,
                                                      topic_naming_service,
                                                      mock_anthropic_client,
                                                      mock_anthropic_response):
        """Should handle empty user/bot messages."""
        mock_anthropic_client.messages.create.return_value = (
            mock_anthropic_response("New Chat"))

        with patch("services.topic_naming.get_anthropic_async_client",
                   return_value=mock_anthropic_client):
            title, _, _ = await topic_naming_service.generate_title("", "")

        assert title == "New Chat"

    @pytest.mark.asyncio
    async def test_generate_title_with_unicode(self, topic_naming_service,
                                               mock_anthropic_client,
                                               mock_anthropic_response):
        """Should handle unicode in messages and titles."""
        mock_anthropic_client.messages.create.return_value = (
            mock_anthropic_response("Резюме Python разработчика"))

        with patch("services.topic_naming.get_anthropic_async_client",
                   return_value=mock_anthropic_client):
            title, _, _ = await topic_naming_service.generate_title(
                "Помоги написать резюме", "Конечно! Создам резюме...")

        assert title == "Резюме Python разработчика"

    @pytest.mark.asyncio
    async def test_generate_title_with_emojis(self, topic_naming_service,
                                              mock_anthropic_client,
                                              mock_anthropic_response):
        """Should handle emojis in title."""
        mock_anthropic_client.messages.create.return_value = (
            mock_anthropic_response("🐍 Python Help"))

        with patch("services.topic_naming.get_anthropic_async_client",
                   return_value=mock_anthropic_client):
            title, _, _ = await topic_naming_service.generate_title(
                "Help with Python", "Sure!")

        assert title == "🐍 Python Help"

    @pytest.mark.asyncio
    async def test_maybe_name_topic_with_bot_api_error(
            self, topic_naming_service, mock_bot, mock_thread, mock_session,
            mock_service_factory, mock_anthropic_client,
            mock_anthropic_response):
        """Should return None if Telegram API fails."""
        mock_anthropic_client.messages.create.return_value = (
            mock_anthropic_response("Test Title"))
        mock_bot.edit_forum_topic.side_effect = Exception("Telegram API Error")

        with patch("services.topic_naming.get_anthropic_async_client",
                   return_value=mock_anthropic_client), \
             patch("services.topic_naming.ServiceFactory",
                   return_value=mock_service_factory), \
             patch("services.topic_naming.update_cached_balance",
                   new_callable=AsyncMock), \
             patch("services.topic_naming.record_claude_request"), \
             patch("services.topic_naming.record_claude_tokens"), \
             patch("services.topic_naming.record_cost"), \
             patch.object(topic_naming_service, "model", "claude-haiku-test"), \
             patch("config.TOPIC_NAMING_ENABLED", True):

            result = await topic_naming_service.maybe_name_topic(
                bot=mock_bot,
                thread=mock_thread,
                user_message="Hello",
                bot_response="Hi!",
                session=mock_session,
            )

        # Should return None on error
        assert result is None
        # Should keep needs_topic_naming=True for retry
        assert mock_thread.needs_topic_naming is True
