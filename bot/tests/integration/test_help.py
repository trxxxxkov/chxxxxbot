"""Tests for /help command.

Tests cover:
- Regular user sees basic, model, and payment commands (no admin section)
- Privileged user sees admin commands
- Contact link to first privileged user's username
- /paysupport not shown in help
"""

from contextlib import contextmanager
from datetime import datetime
from datetime import timezone
from unittest.mock import AsyncMock
from unittest.mock import Mock
from unittest.mock import patch

import config
from db.models.user import User
import pytest
from telegram.handlers.start import help_handler

# =============================================================================
# Constants
# =============================================================================

ADMIN_USER_ID = 111111111
REGULAR_USER_ID = 222222222

# =============================================================================
# Helpers
# =============================================================================


@contextmanager
def privileged_context(user_id: int):
    """Temporarily set user as privileged."""
    with patch.object(config, 'PRIVILEGED_USERS', {user_id}):
        yield


@contextmanager
def no_privileged_users():
    """Empty privileged users set."""
    with patch.object(config, 'PRIVILEGED_USERS', set()):
        yield


def make_message(user_id: int, lang: str = "en") -> Mock:
    """Create mock message for help tests."""
    msg = Mock()
    msg.from_user = Mock()
    msg.from_user.id = user_id
    msg.from_user.language_code = lang
    msg.chat = Mock()
    msg.chat.id = 100
    msg.answer = AsyncMock()
    return msg


# =============================================================================
# Tests
# =============================================================================


@pytest.mark.asyncio
class TestHelpCommand:
    """Test /help command output."""

    async def test_regular_user_sees_basic_commands(self, test_session):
        """Regular user sees basic, model, and payment sections."""
        with no_privileged_users():
            msg = make_message(REGULAR_USER_ID)

            await help_handler(msg, test_session)

            msg.answer.assert_called_once()
            text = msg.answer.call_args[0][0]

            # Should include basic commands (/start hidden from menu/help)
            assert "/help" in text
            assert "/stop" in text
            assert "/clear" in text

            # Should include model commands
            assert "/model" in text
            assert "/personality" in text

            # Should include payment commands
            assert "/pay" in text
            assert "/balance" in text
            assert "/refund" in text

            # Should NOT include admin commands
            assert "/topup" not in text
            assert "/set_margin" not in text
            assert "/announce" not in text

    async def test_privileged_user_sees_admin_commands(self, test_session):
        """Privileged user sees admin section."""
        with privileged_context(ADMIN_USER_ID):
            msg = make_message(ADMIN_USER_ID)

            await help_handler(msg, test_session)

            text = msg.answer.call_args[0][0]

            # Should include admin commands
            assert "/topup" in text
            assert "/set_margin" in text
            assert "/announce" in text

    async def test_paysupport_not_shown(self, test_session):
        """/paysupport is not listed in help."""
        with privileged_context(ADMIN_USER_ID):
            msg = make_message(ADMIN_USER_ID)

            await help_handler(msg, test_session)

            text = msg.answer.call_args[0][0]
            assert "/paysupport" not in text

    async def test_contact_username_shown(self, test_session):
        """First privileged user's username shown as contact."""
        # Create a user record for the admin
        user = User(
            id=ADMIN_USER_ID,
            first_name="Admin",
            username="admin_user",
            first_seen_at=datetime.now(timezone.utc),
            last_seen_at=datetime.now(timezone.utc),
        )
        test_session.add(user)
        await test_session.flush()

        with privileged_context(ADMIN_USER_ID):
            msg = make_message(REGULAR_USER_ID)

            await help_handler(msg, test_session)

            text = msg.answer.call_args[0][0]
            assert "@admin_user" in text

    async def test_contact_not_shown_when_no_privileged(self, test_session):
        """No contact line when no privileged users."""
        with no_privileged_users():
            msg = make_message(REGULAR_USER_ID)

            await help_handler(msg, test_session)

            text = msg.answer.call_args[0][0]
            # Should not have a contact line with @
            assert "💬" not in text

    async def test_help_uses_html_parse_mode(self, test_session):
        """Help response uses HTML parse mode."""
        with no_privileged_users():
            msg = make_message(REGULAR_USER_ID)

            await help_handler(msg, test_session)

            call_kwargs = msg.answer.call_args[1]
            assert call_kwargs.get("parse_mode") == "HTML"

    async def test_russian_language(self, test_session):
        """Help shown in Russian for Russian users."""
        with no_privileged_users():
            msg = make_message(REGULAR_USER_ID, lang="ru")

            await help_handler(msg, test_session)

            text = msg.answer.call_args[0][0]
            assert "Справка" in text
