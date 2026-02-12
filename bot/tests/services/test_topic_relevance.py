"""Tests for services/topic_relevance.py - Topic relevance checking.

Tests for TopicRelevanceService with mocked Haiku API.

NO __init__.py - use direct import:
    pytest tests/services/test_topic_relevance.py
"""

from unittest.mock import AsyncMock
from unittest.mock import MagicMock
from unittest.mock import patch

import pytest
from services.topic_relevance import _get_user_messages_for_topic
from services.topic_relevance import load_recent_topic_contexts
from services.topic_relevance import RelevanceResult
from services.topic_relevance import TopicContext
from services.topic_relevance import TopicRelevanceService

# =============================================================================
# Test Fixtures
# =============================================================================


@pytest.fixture
def mock_haiku_response():
    """Create mock Haiku API response."""

    def _create(text: str, input_tokens: int = 100, output_tokens: int = 20):
        response = MagicMock()
        response.content = [MagicMock(text=text)]
        response.usage = MagicMock(input_tokens=input_tokens,
                                   output_tokens=output_tokens)
        return response

    return _create


@pytest.fixture
def mock_anthropic_client(mock_haiku_response):
    """Create mock Anthropic async client."""
    client = AsyncMock()
    client.messages.create = AsyncMock(
        return_value=mock_haiku_response('{"action": "stay"}'))
    return client


@pytest.fixture
def service():
    """Create TopicRelevanceService for testing."""
    return TopicRelevanceService(
        model="claude-haiku-test",
        max_tokens=60,
    )


@pytest.fixture
def current_topic():
    """Create sample current topic context."""
    return TopicContext(
        label="current",
        thread_id=42,
        internal_id=1,
        title="Python async/await",
        recent_user_messages=["What's async?", "Show example"],
    )


@pytest.fixture
def other_topics():
    """Create sample other topic contexts."""
    return [
        TopicContext(
            label="A",
            thread_id=10,
            internal_id=2,
            title="React rendering bug",
            recent_user_messages=["How do I fix...", "Still broken"],
        ),
        TopicContext(
            label="B",
            thread_id=20,
            internal_id=3,
            title="Italian Recipes",
            recent_user_messages=["Best pasta recipe", "What about..."],
        ),
    ]


# =============================================================================
# check_relevance Tests
# =============================================================================


class TestCheckRelevance:
    """Tests for check_relevance method."""

    @pytest.mark.asyncio
    async def test_stay_in_current_topic(self, service, mock_anthropic_client,
                                         mock_haiku_response, current_topic,
                                         other_topics):
        """Should return stay when message continues current topic."""
        mock_anthropic_client.messages.create.return_value = (
            mock_haiku_response('{"action": "stay"}'))

        with patch("services.topic_relevance.get_anthropic_async_client",
                   return_value=mock_anthropic_client):
            result = await service.check_relevance(
                new_message="What about threads?",
                current_topic=current_topic,
                other_topics=other_topics,
            )

        assert result.action == "stay"
        assert result.target_thread_id is None

    @pytest.mark.asyncio
    async def test_resume_existing_topic(self, service, mock_anthropic_client,
                                         mock_haiku_response, current_topic,
                                         other_topics):
        """Should return resume with target when matching another topic."""
        mock_anthropic_client.messages.create.return_value = (
            mock_haiku_response('{"action": "resume", "topic": "B"}'))

        with patch("services.topic_relevance.get_anthropic_async_client",
                   return_value=mock_anthropic_client):
            result = await service.check_relevance(
                new_message="How to cook pasta?",
                current_topic=current_topic,
                other_topics=other_topics,
            )

        assert result.action == "resume"
        assert result.target_thread_id == 20
        assert result.target_internal_id == 3

    @pytest.mark.asyncio
    async def test_new_topic(self, service, mock_anthropic_client,
                             mock_haiku_response, current_topic, other_topics):
        """Should return new with title for unrelated message."""
        mock_anthropic_client.messages.create.return_value = (
            mock_haiku_response('{"action": "new", "title": "Docker Setup"}'))

        with patch("services.topic_relevance.get_anthropic_async_client",
                   return_value=mock_anthropic_client):
            result = await service.check_relevance(
                new_message="How to setup Docker?",
                current_topic=current_topic,
                other_topics=other_topics,
            )

        assert result.action == "new"
        assert result.title == "Docker Setup"

    @pytest.mark.asyncio
    async def test_from_general_resume(self, service, mock_anthropic_client,
                                       mock_haiku_response, other_topics):
        """Should resume topic when message from General matches."""
        mock_anthropic_client.messages.create.return_value = (
            mock_haiku_response('{"action": "resume", "topic": "A"}'))

        with patch("services.topic_relevance.get_anthropic_async_client",
                   return_value=mock_anthropic_client):
            result = await service.check_relevance(
                new_message="Fix the React bug",
                current_topic=None,
                other_topics=other_topics,
            )

        assert result.action == "resume"
        assert result.target_thread_id == 10

    @pytest.mark.asyncio
    async def test_from_general_new(self, service, mock_anthropic_client,
                                    mock_haiku_response, other_topics):
        """Should create new topic when message from General doesn't match."""
        mock_anthropic_client.messages.create.return_value = (
            mock_haiku_response('{"action": "new", "title": "Haiku Cats"}'))

        with patch("services.topic_relevance.get_anthropic_async_client",
                   return_value=mock_anthropic_client):
            result = await service.check_relevance(
                new_message="Write a haiku about cats",
                current_topic=None,
                other_topics=other_topics,
            )

        assert result.action == "new"
        assert result.title == "Haiku Cats"

    @pytest.mark.asyncio
    async def test_empty_message_stays(self, service, current_topic):
        """Should stay in current topic for empty message."""
        result = await service.check_relevance(
            new_message="",
            current_topic=current_topic,
            other_topics=[],
        )

        assert result.action == "stay"

    @pytest.mark.asyncio
    async def test_empty_message_from_general_creates_new(self, service):
        """Should create new topic for empty message from General."""
        result = await service.check_relevance(
            new_message="  ",
            current_topic=None,
            other_topics=[],
        )

        assert result.action == "new"
        assert result.title == "New chat"

    @pytest.mark.asyncio
    async def test_api_failure_fallback_stay(self, service,
                                             mock_anthropic_client,
                                             current_topic):
        """Should fall back to stay on API error in topic."""
        mock_anthropic_client.messages.create.side_effect = Exception(
            "API Error")

        with patch("services.topic_relevance.get_anthropic_async_client",
                   return_value=mock_anthropic_client):
            result = await service.check_relevance(
                new_message="test",
                current_topic=current_topic,
                other_topics=[],
            )

        assert result.action == "stay"

    @pytest.mark.asyncio
    async def test_api_failure_fallback_new(self, service,
                                            mock_anthropic_client):
        """Should fall back to new on API error from General."""
        mock_anthropic_client.messages.create.side_effect = Exception(
            "API Error")

        with patch("services.topic_relevance.get_anthropic_async_client",
                   return_value=mock_anthropic_client):
            result = await service.check_relevance(
                new_message="test",
                current_topic=None,
                other_topics=[],
            )

        assert result.action == "new"


# =============================================================================
# _parse_response Tests
# =============================================================================


class TestParseResponse:
    """Tests for _parse_response method."""

    def test_parse_stay(self, service):
        """Should parse stay action."""
        result = service._parse_response('{"action": "stay"}', None, [])
        assert result.action == "stay"

    def test_parse_resume_valid_label(self, service, other_topics):
        """Should parse resume with valid label."""
        result = service._parse_response(
            '{"action": "resume", "topic": "B"}',
            None,
            other_topics,
        )
        assert result.action == "resume"
        assert result.target_thread_id == 20

    def test_parse_resume_invalid_label_falls_back_to_new(
            self, service, other_topics):
        """Should fall back to new when label not found."""
        result = service._parse_response(
            '{"action": "resume", "topic": "Z"}',
            None,
            other_topics,
        )
        assert result.action == "new"

    def test_parse_new_with_title(self, service):
        """Should parse new action with title."""
        result = service._parse_response(
            '{"action": "new", "title": "My Topic"}',
            None,
            [],
        )
        assert result.action == "new"
        assert result.title == "My Topic"

    def test_parse_new_strips_quotes(self, service):
        """Should strip quotes from title."""
        result = service._parse_response(
            '{"action": "new", "title": "\\"Quoted Title\\""}',
            None,
            [],
        )
        assert result.action == "new"
        assert result.title == "Quoted Title"

    def test_parse_new_truncates_long_title(self, service):
        """Should truncate long titles."""
        long = "A" * 100
        result = service._parse_response(
            f'{{"action": "new", "title": "{long}"}}',
            None,
            [],
        )
        assert result.action == "new"
        assert len(result.title) == 30  # TOPIC_TEMP_NAME_MAX_LENGTH

    def test_parse_invalid_json_fallback_stay(self, service, current_topic):
        """Should fall back to stay on invalid JSON in topic."""
        result = service._parse_response("not json", current_topic, [])
        assert result.action == "stay"

    def test_parse_invalid_json_fallback_new(self, service):
        """Should fall back to new on invalid JSON from General."""
        result = service._parse_response("not json", None, [])
        assert result.action == "new"

    def test_parse_json_with_extra_text(self, service):
        """Should extract JSON from text with surrounding content."""
        result = service._parse_response(
            'Here is the result: {"action": "stay"} Done.',
            None,
            [],
        )
        assert result.action == "stay"

    def test_parse_unknown_action_fallback(self, service, current_topic):
        """Should fall back on unknown action."""
        result = service._parse_response(
            '{"action": "unknown"}',
            current_topic,
            [],
        )
        assert result.action == "stay"


# =============================================================================
# _build_prompt Tests
# =============================================================================


class TestBuildPrompt:
    """Tests for _build_prompt method."""

    def test_from_general_with_topics(self, service, other_topics):
        """Should include other topics when from General."""
        prompt = service._build_prompt(
            new_message="test message",
            current_topic=None,
            other_topics=other_topics,
        )

        assert "Other recent topics:" in prompt
        assert 'A) "React rendering bug"' in prompt
        assert 'B) "Italian Recipes"' in prompt
        assert '"test message"' in prompt
        assert "resume" in prompt
        assert "new" in prompt

    def test_from_topic_with_others(self, service, current_topic, other_topics):
        """Should include current and other topics when in topic."""
        prompt = service._build_prompt(
            new_message="cooking question",
            current_topic=current_topic,
            other_topics=other_topics,
        )

        assert 'Current topic: "Python async/await"' in prompt
        assert "Other recent topics:" in prompt
        assert '"cooking question"' in prompt
        assert "stay" in prompt

    def test_from_general_no_topics(self, service):
        """Should generate title prompt when no topics exist."""
        prompt = service._build_prompt(
            new_message="hello world",
            current_topic=None,
            other_topics=[],
        )

        assert '"hello world"' in prompt
        assert "title" in prompt

    def test_truncates_message(self, service):
        """Should truncate long messages."""
        long_msg = "A" * 500
        prompt = service._build_prompt(
            new_message=long_msg,
            current_topic=None,
            other_topics=[],
        )

        # Should be truncated to TOPIC_SWITCH_MSG_TRUNCATE (200)
        assert "A" * 200 in prompt
        assert "A" * 201 not in prompt


# =============================================================================
# load_recent_topic_contexts Tests
# =============================================================================


class TestLoadRecentTopicContexts:
    """Tests for load_recent_topic_contexts helper."""

    @pytest.mark.asyncio
    async def test_loads_topics_with_messages(self):
        """Should load topics and their cached messages."""
        mock_thread1 = MagicMock()
        mock_thread1.thread_id = 10
        mock_thread1.id = 1
        mock_thread1.title = "Topic One"

        mock_thread2 = MagicMock()
        mock_thread2.thread_id = 20
        mock_thread2.id = 2
        mock_thread2.title = "Topic Two"

        mock_session = AsyncMock()

        cached_msgs = [
            {
                "role": "user",
                "text_content": "Hello"
            },
            {
                "role": "assistant",
                "text_content": "Hi!"
            },
            {
                "role": "user",
                "text_content": "Question"
            },
        ]

        with patch(
                "services.topic_relevance.ThreadRepository") as mock_repo_cls, \
             patch("services.topic_relevance.get_cached_messages",
                   new_callable=AsyncMock, return_value=cached_msgs):

            mock_repo = mock_repo_cls.return_value
            mock_repo.get_recent_active_topics = AsyncMock(
                return_value=[mock_thread1, mock_thread2])

            contexts = await load_recent_topic_contexts(
                user_id=123,
                chat_id=456,
                exclude_thread_id=None,
                session=mock_session,
            )

        assert len(contexts) == 2
        assert contexts[0].label == "A"
        assert contexts[0].thread_id == 10
        assert contexts[0].title == "Topic One"
        assert contexts[1].label == "B"
        assert contexts[1].thread_id == 20

    @pytest.mark.asyncio
    async def test_empty_when_no_topics(self):
        """Should return empty list when no topics exist."""
        mock_session = AsyncMock()

        with patch(
                "services.topic_relevance.ThreadRepository") as mock_repo_cls:
            mock_repo = mock_repo_cls.return_value
            mock_repo.get_recent_active_topics = AsyncMock(return_value=[])

            contexts = await load_recent_topic_contexts(
                user_id=123,
                chat_id=456,
                exclude_thread_id=None,
                session=mock_session,
            )

        assert contexts == []


# =============================================================================
# _get_user_messages_for_topic Tests
# =============================================================================


class TestGetUserMessagesForTopic:
    """Tests for _get_user_messages_for_topic helper."""

    @pytest.mark.asyncio
    async def test_extracts_user_messages(self):
        """Should extract only user role messages."""
        cached = [
            {
                "role": "user",
                "text_content": "First"
            },
            {
                "role": "assistant",
                "text_content": "Reply"
            },
            {
                "role": "user",
                "text_content": "Second"
            },
        ]

        with patch("services.topic_relevance.get_cached_messages",
                   new_callable=AsyncMock,
                   return_value=cached):
            msgs = await _get_user_messages_for_topic(1)

        assert msgs == ["First", "Second"]

    @pytest.mark.asyncio
    async def test_returns_most_recent(self):
        """Should return most recent messages (up to limit)."""
        cached = [{
            "role": "user",
            "text_content": f"Msg {i}"
        } for i in range(20)]

        with patch("services.topic_relevance.get_cached_messages",
                   new_callable=AsyncMock,
                   return_value=cached), \
             patch("config.TOPIC_SWITCH_RECENT_MESSAGES", 3):
            msgs = await _get_user_messages_for_topic(1)

        assert len(msgs) == 3
        # Should be most recent, in chronological order
        assert msgs == ["Msg 17", "Msg 18", "Msg 19"]

    @pytest.mark.asyncio
    async def test_empty_on_cache_miss(self):
        """Should return empty list on cache miss."""
        with patch("services.topic_relevance.get_cached_messages",
                   new_callable=AsyncMock,
                   return_value=None):
            msgs = await _get_user_messages_for_topic(1)

        assert msgs == []

    @pytest.mark.asyncio
    async def test_truncates_long_messages(self):
        """Should truncate messages to config limit."""
        cached = [{
            "role": "user",
            "text_content": "A" * 500,
        }]

        with patch("services.topic_relevance.get_cached_messages",
                   new_callable=AsyncMock,
                   return_value=cached), \
             patch("config.TOPIC_SWITCH_MSG_TRUNCATE", 200):
            msgs = await _get_user_messages_for_topic(1)

        assert len(msgs) == 1
        assert len(msgs[0]) == 200
