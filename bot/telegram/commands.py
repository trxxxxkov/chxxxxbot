"""Bot command registry — single source of truth.

Defines all bot commands with bilingual descriptions. Used by:
- setup_bot_commands(): registers "/" menu via Telegram API (setMyCommands)
- build_help_text(): generates /help response

Adding a new command:
    1. Append a BotCmd to the appropriate section in COMMANDS
    2. Register the handler in the router
    3. Done — help and menu update automatically
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from aiogram import Bot
from aiogram.types import BotCommand
from aiogram.types import BotCommandScopeChat
from aiogram.types import BotCommandScopeDefault

from i18n import get_text
from utils.structured_logging import get_logger

logger = get_logger(__name__)


# =============================================================================
# Data model
# =============================================================================


class Section(Enum):
    """Help sections — defines display order and i18n header key."""
    BASIC = "help.section_basic"
    MODEL = "help.section_model"
    PAYMENT = "help.section_payment"
    ADMIN = "help.section_admin"


@dataclass(frozen=True, slots=True)
class BotCmd:
    """Single bot command definition.

    Attributes:
        name: Command name without '/' (e.g. "start").
        desc_en: English description for menu and help.
        desc_ru: Russian description for menu and help.
        section: Help section this command belongs to.
        admin: If True, only shown to privileged users.
    """
    name: str
    desc_en: str
    desc_ru: str
    section: Section
    admin: bool = False

    def description(self, lang: str) -> str:
        """Return description for a given language."""
        return self.desc_ru if lang == "ru" else self.desc_en

    def help_line(self, lang: str) -> str:
        """Format as help text line: '/command — Description'."""
        return f"/{self.name} — {self.description(lang)}\n"

    def bot_command(self, lang: str) -> BotCommand:
        """Convert to aiogram BotCommand for setMyCommands."""
        return BotCommand(command=self.name, description=self.description(lang))


# =============================================================================
# Command registry
# =============================================================================

COMMANDS: tuple[BotCmd, ...] = (
    # --- Basic ---
    BotCmd("stop", "Stop current generation",
           "Остановить текущую генерацию", Section.BASIC),
    BotCmd("clear", "Clear history / delete topics",
           "Очистить историю / удалить топики", Section.BASIC),
    # --- Model & Settings ---
    BotCmd("model", "Select AI model",
           "Выбрать модель ИИ", Section.MODEL),
    BotCmd("personality", "Set custom AI personality",
           "Настроить персональные инструкции для ИИ", Section.MODEL),
    # --- Payment ---
    BotCmd("pay", "Top up balance (Telegram Stars)",
           "Пополнить баланс (Telegram Stars)", Section.PAYMENT),
    BotCmd("balance", "Check balance and history",
           "Проверить баланс и историю операций", Section.PAYMENT),
    BotCmd("refund", "Request payment refund",
           "Запросить возврат платежа", Section.PAYMENT),
    BotCmd("help", "Show all commands",
           "Показать все команды", Section.PAYMENT),
    # --- Admin ---
    BotCmd("topup", "Adjust user balance",
           "Пополнить/списать баланс пользователя",
           Section.ADMIN, admin=True),
    BotCmd("set_margin", "Set owner margin",
           "Настроить маржу владельца",
           Section.ADMIN, admin=True),
    BotCmd("set_cache_subsidy", "Toggle cache write cost subsidy",
           "Субсидия стоимости записи кэша",
           Section.ADMIN, admin=True),
    BotCmd("announce", "Broadcast messages to users",
           "Рассылка сообщений пользователям",
           Section.ADMIN, admin=True),
)


# =============================================================================
# Help text builder
# =============================================================================


def build_help_text(lang: str, *, show_admin: bool = False) -> str:
    """Build /help response from the command registry.

    Args:
        lang: Language code ("en" or "ru").
        show_admin: Include admin section.

    Returns:
        Formatted HTML help text (without contact footer).
    """
    parts: list[str] = [get_text("help.header", lang)]
    current_section: Section | None = None

    for cmd in COMMANDS:
        if cmd.admin and not show_admin:
            continue

        # Emit section header on change
        if cmd.section != current_section:
            current_section = cmd.section
            parts.append(get_text(cmd.section.value, lang))

        parts.append(cmd.help_line(lang))

    return "".join(parts)


# =============================================================================
# Telegram menu registration (setMyCommands)
# =============================================================================


def _bot_commands(lang: str, *, include_admin: bool) -> list[BotCommand]:
    """Build BotCommand list for setMyCommands."""
    return [
        cmd.bot_command(lang)
        for cmd in COMMANDS
        if not cmd.admin or include_admin
    ]


async def setup_bot_commands(
    bot: Bot,
    privileged_users: set[int],
) -> None:
    """Register bot commands for the Telegram "/" menu.

    Sets localized commands for all users (EN default + RU),
    and extended command lists for each privileged user.

    Args:
        bot: Bot instance.
        privileged_users: Set of admin user IDs.
    """
    # Default scope — English fallback (all languages not explicitly set)
    await bot.set_my_commands(
        commands=_bot_commands("en", include_admin=False),
        scope=BotCommandScopeDefault(),
    )

    # Default scope — Russian
    await bot.set_my_commands(
        commands=_bot_commands("ru", include_admin=False),
        scope=BotCommandScopeDefault(),
        language_code="ru",
    )

    logger.debug(
        "bot_commands_set",
        user_commands=sum(1 for c in COMMANDS if not c.admin),
        languages=["en", "ru"],
    )

    # Per-admin: extended command list in private chat
    if not privileged_users:
        return

    admin_cmds_en = _bot_commands("en", include_admin=True)
    admin_cmds_ru = _bot_commands("ru", include_admin=True)

    for user_id in privileged_users:
        try:
            scope = BotCommandScopeChat(chat_id=user_id)
            await bot.set_my_commands(commands=admin_cmds_en, scope=scope)
            await bot.set_my_commands(
                commands=admin_cmds_ru,
                scope=scope,
                language_code="ru",
            )
        except Exception as exc:  # pylint: disable=broad-exception-caught
            logger.warning(
                "bot_commands_admin_failed",
                user_id=user_id,
                error=str(exc),
            )

    logger.debug(
        "bot_commands_admin_set",
        admin_commands=len(admin_cmds_en),
        privileged_users=len(privileged_users),
    )
