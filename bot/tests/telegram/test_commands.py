"""Tests for bot command registry and registration.

Tests cover:
- BotCmd data model (description, help_line, bot_command)
- Command registry integrity (no duplicates, admin flags)
- build_help_text() output (sections, admin filtering, languages)
- setup_bot_commands() API calls (scopes, languages, error handling)
"""

from unittest.mock import AsyncMock

import pytest
from telegram.commands import COMMANDS
from telegram.commands import BotCmd
from telegram.commands import Section
from telegram.commands import build_help_text
from telegram.commands import setup_bot_commands

# =============================================================================
# Constants
# =============================================================================

ADMIN_USER_1 = 111111111
ADMIN_USER_2 = 222222222


# =============================================================================
# Tests: BotCmd data model
# =============================================================================


class TestBotCmd:
    """Tests for BotCmd dataclass methods."""

    def test_description_english(self):
        cmd = BotCmd("test", "English desc", "Russian desc", Section.BASIC)
        assert cmd.description("en") == "English desc"

    def test_description_russian(self):
        cmd = BotCmd("test", "English desc", "Russian desc", Section.BASIC)
        assert cmd.description("ru") == "Russian desc"

    def test_description_unknown_lang_falls_back_to_english(self):
        cmd = BotCmd("test", "English desc", "Russian desc", Section.BASIC)
        assert cmd.description("de") == "English desc"

    def test_help_line_format(self):
        cmd = BotCmd("start", "Start the bot", "Старт", Section.BASIC)
        assert cmd.help_line("en") == "/start — Start the bot\n"
        assert cmd.help_line("ru") == "/start — Старт\n"

    def test_bot_command(self):
        cmd = BotCmd("help", "Show help", "Справка", Section.BASIC)
        bc = cmd.bot_command("en")
        assert bc.command == "help"
        assert bc.description == "Show help"

    def test_bot_command_no_slash(self):
        cmd = BotCmd("model", "Select model", "Модель", Section.MODEL)
        bc = cmd.bot_command("en")
        assert not bc.command.startswith("/")

    def test_admin_default_false(self):
        cmd = BotCmd("test", "desc", "desc", Section.BASIC)
        assert cmd.admin is False

    def test_admin_explicit_true(self):
        cmd = BotCmd("test", "desc", "desc", Section.ADMIN, admin=True)
        assert cmd.admin is True


# =============================================================================
# Tests: Command registry integrity
# =============================================================================


class TestCommandRegistry:
    """Tests for the COMMANDS tuple integrity."""

    def test_no_duplicate_names(self):
        names = [cmd.name for cmd in COMMANDS]
        assert len(names) == len(set(names)), (
            f"Duplicate command names: "
            f"{[n for n in names if names.count(n) > 1]}"
        )

    def test_admin_commands_in_admin_section(self):
        for cmd in COMMANDS:
            if cmd.admin:
                assert cmd.section == Section.ADMIN, (
                    f"Admin command '{cmd.name}' should be in ADMIN section"
                )

    def test_non_admin_commands_not_in_admin_section(self):
        """Non-admin commands should not be in the ADMIN section."""
        for cmd in COMMANDS:
            if cmd.section == Section.ADMIN:
                assert cmd.admin, (
                    f"Command '{cmd.name}' in ADMIN section "
                    f"should have admin=True"
                )

    def test_all_descriptions_non_empty(self):
        for cmd in COMMANDS:
            assert cmd.desc_en, f"Empty English desc for '{cmd.name}'"
            assert cmd.desc_ru, f"Empty Russian desc for '{cmd.name}'"

    def test_expected_user_commands_present(self):
        names = {cmd.name for cmd in COMMANDS if not cmd.admin}
        expected = {"start", "help", "stop", "clear", "model",
                    "personality", "pay", "balance", "refund"}
        assert expected.issubset(names), (
            f"Missing user commands: {expected - names}"
        )

    def test_expected_admin_commands_present(self):
        names = {cmd.name for cmd in COMMANDS if cmd.admin}
        expected = {"topup", "set_margin", "set_cache_subsidy", "announce"}
        assert expected == names

    def test_commands_is_immutable_tuple(self):
        assert isinstance(COMMANDS, tuple)


# =============================================================================
# Tests: build_help_text
# =============================================================================


class TestBuildHelpText:
    """Tests for help text generation."""

    def test_contains_all_user_commands_en(self):
        text = build_help_text("en")
        for cmd in COMMANDS:
            if not cmd.admin:
                assert f"/{cmd.name}" in text

    def test_contains_all_user_commands_ru(self):
        text = build_help_text("ru")
        for cmd in COMMANDS:
            if not cmd.admin:
                assert f"/{cmd.name}" in text

    def test_no_admin_commands_by_default(self):
        text = build_help_text("en")
        for cmd in COMMANDS:
            if cmd.admin:
                assert f"/{cmd.name}" not in text

    def test_admin_commands_when_enabled(self):
        text = build_help_text("en", show_admin=True)
        for cmd in COMMANDS:
            if cmd.admin:
                assert f"/{cmd.name}" in text

    def test_russian_descriptions(self):
        text = build_help_text("ru")
        assert "Начать работу с ботом" in text
        assert "Показать эту справку" in text

    def test_english_descriptions(self):
        text = build_help_text("en")
        assert "Start the bot" in text
        assert "Show this help" in text

    def test_section_headers_present(self):
        text = build_help_text("en", show_admin=True)
        assert "Basic" in text
        assert "Model" in text
        assert "Payment" in text
        assert "Admin" in text

    def test_admin_section_absent_for_regular_user(self):
        text = build_help_text("en", show_admin=False)
        assert "Admin" not in text

    def test_paysupport_not_in_help(self):
        text = build_help_text("en", show_admin=True)
        assert "/paysupport" not in text

    def test_header_present(self):
        text = build_help_text("en")
        assert "Help" in text

    def test_header_russian(self):
        text = build_help_text("ru")
        assert "Справка" in text


# =============================================================================
# Tests: setup_bot_commands
# =============================================================================


class TestSetupBotCommands:
    """Tests for Telegram API command registration."""

    @pytest.mark.asyncio
    async def test_default_scope_en_and_ru(self):
        """Should set commands for default scope: EN fallback + RU."""
        bot = AsyncMock()

        await setup_bot_commands(bot, privileged_users=set())

        assert bot.set_my_commands.call_count == 2

        # First: EN default (no language_code)
        first = bot.set_my_commands.call_args_list[0]
        assert first.kwargs.get("language_code") is None

        # Second: RU
        second = bot.set_my_commands.call_args_list[1]
        assert second.kwargs.get("language_code") == "ru"

    @pytest.mark.asyncio
    async def test_default_scope_excludes_admin_commands(self):
        """Default scope should NOT include admin commands."""
        bot = AsyncMock()
        admin_names = {cmd.name for cmd in COMMANDS if cmd.admin}

        await setup_bot_commands(bot, privileged_users=set())

        first = bot.set_my_commands.call_args_list[0]
        cmd_names = {c.command for c in first.kwargs["commands"]}
        assert not cmd_names & admin_names, (
            f"Admin commands leaked into default scope: "
            f"{cmd_names & admin_names}"
        )

    @pytest.mark.asyncio
    async def test_user_command_count(self):
        """Default scope should have correct number of user commands."""
        bot = AsyncMock()
        expected = sum(1 for c in COMMANDS if not c.admin)

        await setup_bot_commands(bot, privileged_users=set())

        first = bot.set_my_commands.call_args_list[0]
        assert len(first.kwargs["commands"]) == expected

    @pytest.mark.asyncio
    async def test_admin_commands_for_privileged_user(self):
        """Privileged users get all commands including admin."""
        bot = AsyncMock()
        expected = len(COMMANDS)

        await setup_bot_commands(bot, privileged_users={ADMIN_USER_1})

        # 2 default + 2 per admin = 4
        assert bot.set_my_commands.call_count == 4

        # Third call = admin EN
        admin_call = bot.set_my_commands.call_args_list[2]
        assert len(admin_call.kwargs["commands"]) == expected

    @pytest.mark.asyncio
    async def test_admin_scope_includes_admin_commands(self):
        """Admin scope should include admin command names."""
        bot = AsyncMock()
        admin_names = {cmd.name for cmd in COMMANDS if cmd.admin}

        await setup_bot_commands(bot, privileged_users={ADMIN_USER_1})

        admin_call = bot.set_my_commands.call_args_list[2]
        cmd_names = {c.command for c in admin_call.kwargs["commands"]}
        assert admin_names.issubset(cmd_names)

    @pytest.mark.asyncio
    async def test_multiple_admins(self):
        """Each admin gets their own scoped commands."""
        bot = AsyncMock()
        admins = {ADMIN_USER_1, ADMIN_USER_2}

        await setup_bot_commands(bot, privileged_users=admins)

        # 2 default + 2 per admin * 2 = 6
        assert bot.set_my_commands.call_count == 6

    @pytest.mark.asyncio
    async def test_admin_error_does_not_crash(self):
        """API error for one admin should not stop others."""
        from aiogram.types import BotCommandScopeChat

        bot = AsyncMock()

        async def side_effect(**kwargs):
            scope = kwargs.get("scope")
            if (isinstance(scope, BotCommandScopeChat)
                    and scope.chat_id == ADMIN_USER_1
                    and kwargs.get("language_code") is None):
                raise Exception("Chat not found")

        bot.set_my_commands = AsyncMock(side_effect=side_effect)

        # Should not raise
        await setup_bot_commands(
            bot, privileged_users={ADMIN_USER_1, ADMIN_USER_2})

    @pytest.mark.asyncio
    async def test_no_admins_only_default_scope(self):
        """Empty privileged_users should only set default scope."""
        bot = AsyncMock()

        await setup_bot_commands(bot, privileged_users=set())

        assert bot.set_my_commands.call_count == 2
