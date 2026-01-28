"""Tests for chat action module.

Comprehensive tests for telegram/chat_action/:
- types.py - ActionPhase, ActionPriority, ACTION_RESOLUTION_TABLE
- resolver.py - resolve_action() function
- manager.py - ChatActionManager class
- scope.py - ActionScope class
- legacy.py - send_action(), continuous_action(), ChatActionContext
"""

import asyncio
from unittest.mock import AsyncMock
from unittest.mock import MagicMock
from unittest.mock import patch

from db.models.user_file import FileType
import pytest
from telegram.chat_action.legacy import ChatActionContext
from telegram.chat_action.legacy import continuous_action
from telegram.chat_action.legacy import send_action
from telegram.chat_action.manager import ChatActionManager
from telegram.chat_action.resolver import resolve_action
from telegram.chat_action.scope import ActionScope
from telegram.chat_action.types import ACTION_RESOLUTION_TABLE
from telegram.chat_action.types import ActionPhase
from telegram.chat_action.types import ActionPriority
from telegram.chat_action.types import ChatAction
from telegram.pipeline.models import MediaType

# ============================================================================
# Fixtures
# ============================================================================


@pytest.fixture
def mock_bot():
    """Create mock Telegram bot."""
    bot = MagicMock()
    bot.send_chat_action = AsyncMock(return_value=True)
    return bot


@pytest.fixture
def chat_id():
    """Sample chat ID."""
    return 123456


@pytest.fixture
def thread_id():
    """Sample thread ID."""
    return 789


# ============================================================================
# Tests for types.py
# ============================================================================


class TestActionPhase:
    """Tests for ActionPhase enum."""

    def test_all_phases_defined(self):
        """Should have all expected phases."""
        phases = [p.name for p in ActionPhase]
        assert "IDLE" in phases
        assert "GENERATING" in phases
        assert "PROCESSING" in phases
        assert "UPLOADING" in phases
        assert "DOWNLOADING" in phases
        assert "SEARCHING" in phases

    def test_phases_are_unique(self):
        """Should have unique values for each phase."""
        values = [p.value for p in ActionPhase]
        assert len(values) == len(set(values))


class TestActionPriority:
    """Tests for ActionPriority enum."""

    def test_priority_ordering(self):
        """Should have LOW < NORMAL < HIGH ordering."""
        assert ActionPriority.LOW.value < ActionPriority.NORMAL.value
        assert ActionPriority.NORMAL.value < ActionPriority.HIGH.value

    def test_all_priorities_defined(self):
        """Should have all expected priorities."""
        priorities = [p.name for p in ActionPriority]
        assert "LOW" in priorities
        assert "NORMAL" in priorities
        assert "HIGH" in priorities


class TestActionResolutionTable:
    """Tests for ACTION_RESOLUTION_TABLE."""

    def test_generating_returns_typing(self):
        """GENERATING phase should return typing."""
        assert ACTION_RESOLUTION_TABLE[(ActionPhase.GENERATING,
                                        None)] == "typing"

    def test_uploading_image_returns_upload_photo(self):
        """UPLOADING with IMAGE should return upload_photo."""
        assert ACTION_RESOLUTION_TABLE[(ActionPhase.UPLOADING,
                                        MediaType.IMAGE)] == "upload_photo"
        assert ACTION_RESOLUTION_TABLE[(ActionPhase.UPLOADING,
                                        FileType.IMAGE)] == "upload_photo"

    def test_uploading_video_returns_upload_video(self):
        """UPLOADING with VIDEO should return upload_video."""
        assert ACTION_RESOLUTION_TABLE[(ActionPhase.UPLOADING,
                                        MediaType.VIDEO)] == "upload_video"
        assert ACTION_RESOLUTION_TABLE[(ActionPhase.UPLOADING,
                                        FileType.VIDEO)] == "upload_video"

    def test_uploading_document_returns_upload_document(self):
        """UPLOADING with DOCUMENT should return upload_document."""
        assert ACTION_RESOLUTION_TABLE[(
            ActionPhase.UPLOADING, MediaType.DOCUMENT)] == "upload_document"
        assert ACTION_RESOLUTION_TABLE[(ActionPhase.UPLOADING,
                                        FileType.DOCUMENT)] == "upload_document"

    def test_processing_voice_returns_record_voice(self):
        """PROCESSING with VOICE should return record_voice."""
        assert ACTION_RESOLUTION_TABLE[(ActionPhase.PROCESSING,
                                        MediaType.VOICE)] == "record_voice"

    def test_searching_returns_typing(self):
        """SEARCHING phase should return typing."""
        assert ACTION_RESOLUTION_TABLE[(ActionPhase.SEARCHING,
                                        None)] == "typing"


# ============================================================================
# Tests for resolver.py
# ============================================================================


class TestResolveAction:
    """Tests for resolve_action() function."""

    def test_generating_no_file_type(self):
        """Should return typing for GENERATING."""
        result = resolve_action(ActionPhase.GENERATING)
        assert result == "typing"

    def test_uploading_with_media_type(self):
        """Should resolve MediaType correctly."""
        assert resolve_action(ActionPhase.UPLOADING,
                              MediaType.IMAGE) == "upload_photo"
        assert resolve_action(ActionPhase.UPLOADING,
                              MediaType.VIDEO) == "upload_video"
        assert resolve_action(ActionPhase.UPLOADING,
                              MediaType.DOCUMENT) == "upload_document"

    def test_uploading_with_file_type(self):
        """Should resolve FileType correctly."""
        assert resolve_action(ActionPhase.UPLOADING,
                              FileType.IMAGE) == "upload_photo"
        assert resolve_action(ActionPhase.UPLOADING,
                              FileType.VIDEO) == "upload_video"
        assert resolve_action(ActionPhase.UPLOADING,
                              FileType.PDF) == "upload_document"

    def test_uploading_with_mime_type(self):
        """Should resolve MIME type correctly."""
        with patch("telegram.chat_action.resolver.mime_to_media_type"
                  ) as mock_mime:
            mock_mime.return_value = MediaType.IMAGE
            result = resolve_action(
                ActionPhase.UPLOADING,
                mime_type="image/png",
            )
            assert result == "upload_photo"
            mock_mime.assert_called_once_with("image/png")

    def test_fallback_to_phase_default(self):
        """Should fall back to phase default for unknown file type."""
        # Unknown file type should use phase default
        result = resolve_action(ActionPhase.UPLOADING, None)
        assert result == "upload_document"

    def test_ultimate_fallback_to_typing(self):
        """Should fall back to typing for completely unknown combination."""
        # IDLE phase has no entries in table - should return typing
        result = resolve_action(ActionPhase.IDLE)
        assert result == "typing"


# ============================================================================
# Tests for manager.py
# ============================================================================


class TestChatActionManager:
    """Tests for ChatActionManager class."""

    def test_get_creates_new_manager(self, mock_bot, chat_id):
        """Should create new manager for new chat."""
        # Clear registry
        ChatActionManager._registry.clear()

        manager = ChatActionManager.get(mock_bot, chat_id)

        assert manager is not None
        assert manager.chat_id == chat_id
        assert manager.bot is mock_bot

    def test_get_returns_same_manager(self, mock_bot, chat_id):
        """Should return same manager for same chat."""
        ChatActionManager._registry.clear()

        manager1 = ChatActionManager.get(mock_bot, chat_id)
        manager2 = ChatActionManager.get(mock_bot, chat_id)

        assert manager1 is manager2

    def test_get_different_for_different_thread(self, mock_bot, chat_id,
                                                thread_id):
        """Should return different managers for different threads."""
        ChatActionManager._registry.clear()

        manager1 = ChatActionManager.get(mock_bot, chat_id, None)
        manager2 = ChatActionManager.get(mock_bot, chat_id, thread_id)

        assert manager1 is not manager2

    def test_init_state(self, mock_bot, chat_id):
        """Should initialize with empty scope stack."""
        manager = ChatActionManager(mock_bot, chat_id)

        assert manager._scope_stack == []
        assert manager._loop_task is None
        assert manager._current_action is None

    @pytest.mark.asyncio
    async def test_push_scope_adds_entry(self, mock_bot, chat_id):
        """Should add scope entry to stack."""
        manager = ChatActionManager(mock_bot, chat_id)

        with patch.object(manager, "_update_action", AsyncMock()):
            scope_id = await manager.push_scope(ActionPhase.GENERATING)

        assert len(manager._scope_stack) == 1
        assert manager._scope_stack[0].scope_id == scope_id
        assert manager._scope_stack[0].phase == ActionPhase.GENERATING

    @pytest.mark.asyncio
    async def test_pop_scope_removes_entry(self, mock_bot, chat_id):
        """Should remove scope entry from stack."""
        manager = ChatActionManager(mock_bot, chat_id)

        with patch.object(manager, "_update_action", AsyncMock()):
            scope_id = await manager.push_scope(ActionPhase.GENERATING)
            await manager.pop_scope(scope_id)

        assert len(manager._scope_stack) == 0

    @pytest.mark.asyncio
    async def test_pop_scope_handles_out_of_order(self, mock_bot, chat_id):
        """Should handle out-of-order scope pops."""
        manager = ChatActionManager(mock_bot, chat_id)

        with patch.object(manager, "_update_action", AsyncMock()):
            scope1 = await manager.push_scope(ActionPhase.GENERATING)
            scope2 = await manager.push_scope(ActionPhase.UPLOADING)

            # Pop first one (not top of stack)
            await manager.pop_scope(scope1)

        assert len(manager._scope_stack) == 1
        assert manager._scope_stack[0].scope_id == scope2

    def test_get_active_action_empty_stack(self, mock_bot, chat_id):
        """Should return None for empty stack."""
        manager = ChatActionManager(mock_bot, chat_id)

        result = manager._get_active_action()

        assert result is None

    def test_get_active_action_single_scope(self, mock_bot, chat_id):
        """Should return action from single scope."""
        from telegram.chat_action.manager import _ScopeEntry

        manager = ChatActionManager(mock_bot, chat_id)
        manager._scope_stack.append(
            _ScopeEntry(
                scope_id="test",
                phase=ActionPhase.GENERATING,
                file_type=None,
                action="typing",
                priority=ActionPriority.NORMAL,
            ))

        result = manager._get_active_action()

        assert result == "typing"

    def test_get_active_action_priority_selection(self, mock_bot, chat_id):
        """Should return highest priority action."""
        from telegram.chat_action.manager import _ScopeEntry

        manager = ChatActionManager(mock_bot, chat_id)
        manager._scope_stack = [
            _ScopeEntry(
                scope_id="low",
                phase=ActionPhase.GENERATING,
                file_type=None,
                action="typing",
                priority=ActionPriority.LOW,
            ),
            _ScopeEntry(
                scope_id="high",
                phase=ActionPhase.UPLOADING,
                file_type=MediaType.IMAGE,
                action="upload_photo",
                priority=ActionPriority.HIGH,
            ),
        ]

        result = manager._get_active_action()

        assert result == "upload_photo"

    @pytest.mark.asyncio
    async def test_send_action_success(self, mock_bot, chat_id):
        """Should send chat action successfully."""
        manager = ChatActionManager(mock_bot, chat_id)

        with patch("telegram.chat_action.manager.logger"):
            result = await manager._send_action("typing")

        assert result is True
        mock_bot.send_chat_action.assert_called_once_with(
            chat_id=chat_id,
            action="typing",
            message_thread_id=None,
        )

    @pytest.mark.asyncio
    async def test_send_action_with_thread_id(self, mock_bot, chat_id,
                                              thread_id):
        """Should include thread_id in API call."""
        manager = ChatActionManager(mock_bot, chat_id, thread_id)

        with patch("telegram.chat_action.manager.logger"):
            await manager._send_action("typing")

        mock_bot.send_chat_action.assert_called_once_with(
            chat_id=chat_id,
            action="typing",
            message_thread_id=thread_id,
        )

    @pytest.mark.asyncio
    async def test_send_action_failure_returns_false(self, mock_bot, chat_id):
        """Should return False on API failure."""
        manager = ChatActionManager(mock_bot, chat_id)
        mock_bot.send_chat_action.side_effect = Exception("API error")

        with patch("telegram.chat_action.manager.logger"):
            result = await manager._send_action("typing")

        assert result is False


class TestChatActionManagerConvenienceMethods:
    """Tests for ChatActionManager convenience methods."""

    def test_generating_returns_scope(self, mock_bot, chat_id):
        """generating() should return ActionScope."""
        manager = ChatActionManager(mock_bot, chat_id)

        scope = manager.generating()

        assert isinstance(scope, ActionScope)
        assert scope.phase == ActionPhase.GENERATING

    def test_uploading_returns_scope(self, mock_bot, chat_id):
        """uploading() should return ActionScope with HIGH priority."""
        manager = ChatActionManager(mock_bot, chat_id)

        scope = manager.uploading(file_type=MediaType.IMAGE)

        assert isinstance(scope, ActionScope)
        assert scope.phase == ActionPhase.UPLOADING
        assert scope.file_type == MediaType.IMAGE
        assert scope.priority == ActionPriority.HIGH

    def test_downloading_returns_scope(self, mock_bot, chat_id):
        """downloading() should return ActionScope."""
        manager = ChatActionManager(mock_bot, chat_id)

        scope = manager.downloading(file_type=MediaType.VIDEO)

        assert isinstance(scope, ActionScope)
        assert scope.phase == ActionPhase.DOWNLOADING
        assert scope.file_type == MediaType.VIDEO

    def test_processing_returns_scope(self, mock_bot, chat_id):
        """processing() should return ActionScope."""
        manager = ChatActionManager(mock_bot, chat_id)

        scope = manager.processing(file_type=MediaType.VOICE)

        assert isinstance(scope, ActionScope)
        assert scope.phase == ActionPhase.PROCESSING
        assert scope.file_type == MediaType.VOICE

    def test_searching_returns_scope(self, mock_bot, chat_id):
        """searching() should return ActionScope."""
        manager = ChatActionManager(mock_bot, chat_id)

        scope = manager.searching()

        assert isinstance(scope, ActionScope)
        assert scope.phase == ActionPhase.SEARCHING


# ============================================================================
# Tests for scope.py
# ============================================================================


class TestActionScope:
    """Tests for ActionScope class."""

    def test_init(self, mock_bot, chat_id):
        """Should initialize with correct attributes."""
        manager = ChatActionManager(mock_bot, chat_id)
        scope = ActionScope(
            manager,
            ActionPhase.UPLOADING,
            file_type=MediaType.IMAGE,
            priority=ActionPriority.HIGH,
        )

        assert scope.manager is manager
        assert scope.phase == ActionPhase.UPLOADING
        assert scope.file_type == MediaType.IMAGE
        assert scope.priority == ActionPriority.HIGH
        assert scope._scope_id is None

    @pytest.mark.asyncio
    async def test_aenter_pushes_scope(self, mock_bot, chat_id):
        """Should push scope on enter."""
        manager = ChatActionManager(mock_bot, chat_id)

        with patch.object(manager, "push_scope",
                          AsyncMock(return_value="test_id")):
            scope = ActionScope(manager, ActionPhase.GENERATING)

            result = await scope.__aenter__()

            assert result is scope
            assert scope._scope_id == "test_id"
            manager.push_scope.assert_called_once()

    @pytest.mark.asyncio
    async def test_aexit_pops_scope(self, mock_bot, chat_id):
        """Should pop scope on exit."""
        manager = ChatActionManager(mock_bot, chat_id)

        with patch.object(manager, "push_scope",
                          AsyncMock(return_value="test_id")):
            with patch.object(manager, "pop_scope", AsyncMock()) as mock_pop:
                scope = ActionScope(manager, ActionPhase.GENERATING)

                await scope.__aenter__()
                await scope.__aexit__(None, None, None)

                mock_pop.assert_called_once_with("test_id")

    @pytest.mark.asyncio
    async def test_context_manager_usage(self, mock_bot, chat_id):
        """Should work as async context manager."""
        manager = ChatActionManager(mock_bot, chat_id)

        with patch.object(manager, "_update_action", AsyncMock()):
            async with manager.generating() as scope:
                assert scope._scope_id is not None
                assert len(manager._scope_stack) == 1

            # After exit
            assert len(manager._scope_stack) == 0


# ============================================================================
# Tests for legacy.py
# ============================================================================


class TestSendAction:
    """Tests for legacy send_action() function."""

    @pytest.mark.asyncio
    async def test_send_action_success(self, mock_bot, chat_id):
        """Should send action and return True."""
        with patch("telegram.chat_action.legacy.logger"):
            result = await send_action(mock_bot, chat_id, "typing")

        assert result is True
        mock_bot.send_chat_action.assert_called_once_with(
            chat_id=chat_id,
            action="typing",
            message_thread_id=None,
        )

    @pytest.mark.asyncio
    async def test_send_action_with_thread(self, mock_bot, chat_id, thread_id):
        """Should include thread_id."""
        with patch("telegram.chat_action.legacy.logger"):
            await send_action(mock_bot, chat_id, "typing", thread_id)

        mock_bot.send_chat_action.assert_called_once_with(
            chat_id=chat_id,
            action="typing",
            message_thread_id=thread_id,
        )

    @pytest.mark.asyncio
    async def test_send_action_failure(self, mock_bot, chat_id):
        """Should return False on failure."""
        mock_bot.send_chat_action.side_effect = Exception("API error")

        with patch("telegram.chat_action.legacy.logger"):
            result = await send_action(mock_bot, chat_id, "typing")

        assert result is False


class TestContinuousAction:
    """Tests for legacy continuous_action() context manager."""

    @pytest.mark.asyncio
    async def test_continuous_action_sends_initial(self, mock_bot, chat_id):
        """Should send action on entering context."""
        with patch("telegram.chat_action.legacy.logger"):
            async with continuous_action(mock_bot,
                                         chat_id,
                                         "typing",
                                         interval=10.0):
                # Give the loop time to send first action
                await asyncio.sleep(0.1)

        assert mock_bot.send_chat_action.called

    @pytest.mark.asyncio
    async def test_continuous_action_stops_on_exit(self, mock_bot, chat_id):
        """Should stop loop when context exits."""
        with patch("telegram.chat_action.legacy.logger"):
            async with continuous_action(mock_bot,
                                         chat_id,
                                         "typing",
                                         interval=0.1):
                await asyncio.sleep(0.05)

            # After exit, no more calls should happen
            call_count = mock_bot.send_chat_action.call_count

        await asyncio.sleep(0.2)
        assert mock_bot.send_chat_action.call_count == call_count


class TestChatActionContext:
    """Tests for ChatActionContext class."""

    def test_init(self, mock_bot, chat_id, thread_id):
        """Should store bot, chat_id, thread_id."""
        ctx = ChatActionContext(mock_bot, chat_id, thread_id)

        assert ctx.bot is mock_bot
        assert ctx.chat_id == chat_id
        assert ctx.message_thread_id == thread_id

    @pytest.mark.asyncio
    async def test_typing(self, mock_bot, chat_id):
        """typing() should send typing action."""
        ctx = ChatActionContext(mock_bot, chat_id)

        with patch("telegram.chat_action.legacy.logger"):
            result = await ctx.typing()

        assert result is True
        mock_bot.send_chat_action.assert_called_with(
            chat_id=chat_id,
            action="typing",
            message_thread_id=None,
        )

    @pytest.mark.asyncio
    async def test_uploading_photo(self, mock_bot, chat_id):
        """uploading_photo() should send upload_photo action."""
        ctx = ChatActionContext(mock_bot, chat_id)

        with patch("telegram.chat_action.legacy.logger"):
            await ctx.uploading_photo()

        mock_bot.send_chat_action.assert_called_with(
            chat_id=chat_id,
            action="upload_photo",
            message_thread_id=None,
        )

    @pytest.mark.asyncio
    async def test_uploading_document(self, mock_bot, chat_id):
        """uploading_document() should send upload_document action."""
        ctx = ChatActionContext(mock_bot, chat_id)

        with patch("telegram.chat_action.legacy.logger"):
            await ctx.uploading_document()

        mock_bot.send_chat_action.assert_called_with(
            chat_id=chat_id,
            action="upload_document",
            message_thread_id=None,
        )

    @pytest.mark.asyncio
    async def test_recording_voice(self, mock_bot, chat_id):
        """recording_voice() should send record_voice action."""
        ctx = ChatActionContext(mock_bot, chat_id)

        with patch("telegram.chat_action.legacy.logger"):
            await ctx.recording_voice()

        mock_bot.send_chat_action.assert_called_with(
            chat_id=chat_id,
            action="record_voice",
            message_thread_id=None,
        )

    def test_continuous_returns_context_manager(self, mock_bot, chat_id):
        """continuous() should return async context manager."""
        ctx = ChatActionContext(mock_bot, chat_id)

        cm = ctx.continuous("upload_video", interval=5.0)

        # Check it's an async context manager
        assert hasattr(cm, "__aenter__")
        assert hasattr(cm, "__aexit__")
