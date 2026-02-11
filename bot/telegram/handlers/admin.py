"""Admin handlers for privileged users.

This module handles admin-only commands:
- /topup - Adjust any user's balance (add or subtract)
- /set_margin - Configure owner margin (k3) for payment commissions

And user commands with admin escalation:
- /clear - Delete forum topics (current topic for all, all topics for admins)

Only users in PRIVILEGED_USERS (from secrets/privileged_users.txt) can use
privileged commands like /topup and /set_margin.
"""

from decimal import Decimal

from aiogram import F
from aiogram import Router
from aiogram.enums import ButtonStyle
from aiogram.filters import Command
from aiogram.types import CallbackQuery
from aiogram.types import InlineKeyboardButton
from aiogram.types import InlineKeyboardMarkup
from aiogram.types import Message
import config
from db.repositories.thread_repository import ThreadRepository
from i18n import get_lang
from i18n import get_text
from services.factory import ServiceFactory
from sqlalchemy.ext.asyncio import AsyncSession
from utils.structured_logging import get_logger

logger = get_logger(__name__)
router = Router(name="admin")


def is_privileged(user_id: int) -> bool:
    """Check if user is privileged (can use admin commands).

    Args:
        user_id: Telegram user ID.

    Returns:
        True if user is in PRIVILEGED_USERS set.
    """
    return user_id in config.PRIVILEGED_USERS


@router.message(Command("topup"))
async def cmd_topup(message: Message, session: AsyncSession):
    """Handler for /topup command - admin balance adjustment.

    Privileged users only.
    Usage: /topup <user_id or @username> <amount>

    Args:
        message: Telegram message with /topup command.
        session: Database session from middleware.

    Examples:
        /topup 123456789 10.50     (add $10.50)
        /topup @username -5.00     (deduct $5.00)
    """
    user_id = message.from_user.id
    lang = get_lang(message.from_user.language_code)

    # Check privileges
    if not is_privileged(user_id):
        logger.warning(
            "admin.topup_unauthorized",
            user_id=user_id,
            username=message.from_user.username,
            msg="Unauthorized topup attempt",
        )
        await message.answer(get_text("admin.unauthorized", lang))
        return

    # Parse arguments
    args = message.text.split()
    if len(args) < 3:
        await message.answer(get_text("admin.topup_usage", lang))
        return

    target_str = args[1]
    amount_str = args[2]

    # Parse target (ID or username)
    target_user_id = None
    target_username = None

    if target_str.startswith("@"):
        target_username = target_str[1:]  # Remove @
    else:
        try:
            target_user_id = int(target_str)
        except ValueError:
            await message.answer(get_text("admin.invalid_user_id", lang))
            return

    # Parse amount
    try:
        amount = Decimal(amount_str)
    except Exception:
        await message.answer(get_text("admin.invalid_amount", lang))
        return

    logger.info(
        "admin.topup_requested",
        admin_user_id=user_id,
        admin_username=message.from_user.username,
        target_user_id=target_user_id,
        target_username=target_username,
        amount=float(amount),
    )

    # Create services
    services = ServiceFactory(session)

    try:
        # Perform topup
        balance_before, balance_after = await services.balance.admin_topup(
            admin_user_id=user_id,
            target_user_id=target_user_id,
            target_username=target_username,
            amount=amount,
        )

        # Send confirmation
        target_display = (f"ID {target_user_id}"
                          if target_user_id else f"@{target_username}")
        action_key = ("admin.topup_action_added"
                      if amount > 0 else "admin.topup_action_deducted")
        action = get_text(action_key, lang)

        await message.answer(
            get_text("admin.topup_success",
                     lang,
                     target=target_display,
                     action=action,
                     amount=abs(amount),
                     before=balance_before,
                     after=balance_after))

        logger.info(
            "admin.topup_success",
            admin_user_id=user_id,
            target_user_id=target_user_id,
            target_username=target_username,
            amount=float(amount),
            balance_before=float(balance_before),
            balance_after=float(balance_after),
            msg="Admin topup completed successfully",
        )

    except ValueError as e:
        # Validation errors (user not found)
        logger.info(
            "admin.topup_validation_error",
            admin_user_id=user_id,
            error=str(e),
        )
        await message.answer(get_text("admin.topup_failed", lang, error=str(e)))

    except Exception as e:
        logger.error(
            "admin.topup_error",
            admin_user_id=user_id,
            error=str(e),
            exc_info=True,
            msg="Unexpected error during admin topup",
        )
        await message.answer(get_text("admin.topup_error", lang))


@router.message(Command("set_margin"))
async def cmd_set_margin(message: Message):
    """Handler for /set_margin command - configure owner margin (k3).

    Privileged users only.
    Usage: /set_margin <k3_value>

    Constraint: k1 + k2 + k3 <= 1.0
    Where:
        k1 = TELEGRAM_WITHDRAWAL_FEE (0.35)
        k2 = TELEGRAM_TOPICS_FEE (0.15)
        k3 = owner margin (configurable)

    Examples:
        /set_margin 0.10   (set 10% owner margin)
        /set_margin 0.0    (set 0% owner margin - no profit)
    """
    user_id = message.from_user.id
    lang = get_lang(message.from_user.language_code)

    # Check privileges
    if not is_privileged(user_id):
        logger.warning(
            "admin.set_margin_unauthorized",
            user_id=user_id,
            username=message.from_user.username,
            msg="Unauthorized set_margin attempt",
        )
        await message.answer(get_text("admin.unauthorized", lang))
        return

    # Parse k3 value
    args = message.text.split()
    if len(args) < 2:
        k1 = config.TELEGRAM_WITHDRAWAL_FEE
        k2 = config.TELEGRAM_TOPICS_FEE
        k3_current = config.DEFAULT_OWNER_MARGIN
        k3_max = 1.0 - k1 - k2

        await message.answer(
            get_text("admin.margin_usage",
                     lang,
                     k1=k1 * 100,
                     k2=k2 * 100,
                     k3=k3_current * 100,
                     k3_max=k3_max,
                     k3_max_pct=k3_max * 100))
        return

    try:
        k3 = float(args[1])
    except ValueError:
        await message.answer(get_text("admin.margin_invalid_value", lang))
        return

    # Validate k3
    k1 = config.TELEGRAM_WITHDRAWAL_FEE
    k2 = config.TELEGRAM_TOPICS_FEE

    if not (0 <= k3 <= 1):
        await message.answer(
            get_text("admin.margin_out_of_range", lang, value=k3))
        return

    if k1 + k2 + k3 > 1.0001:  # Float precision tolerance
        k3_max = 1.0 - k1 - k2
        await message.answer(
            get_text("admin.margin_exceeds_100",
                     lang,
                     total=k1 + k2 + k3,
                     k3_max=k3_max,
                     k3_max_pct=k3_max * 100))
        return

    logger.info(
        "admin.set_margin_requested",
        admin_user_id=user_id,
        admin_username=message.from_user.username,
        old_margin=config.DEFAULT_OWNER_MARGIN,
        new_margin=k3,
    )

    # Update global config
    old_margin = config.DEFAULT_OWNER_MARGIN
    config.DEFAULT_OWNER_MARGIN = k3

    await message.answer(
        get_text("admin.margin_updated",
                 lang,
                 old=old_margin * 100,
                 new=k3 * 100,
                 k1=k1 * 100,
                 k2=k2 * 100,
                 k3=k3 * 100,
                 total=(k1 + k2 + k3) * 100,
                 user_gets=(1 - k1 - k2 - k3) * 100))

    logger.info(
        "admin.set_margin_success",
        admin_user_id=user_id,
        old_margin=old_margin,
        new_margin=k3,
        total_commission=k1 + k2 + k3,
        msg="Owner margin updated successfully",
    )


@router.message(Command("set_cache_subsidy"))
async def cmd_set_cache_subsidy(message: Message):
    """Handler for /set_cache_subsidy command - toggle cache write cost subsidy.

    Privileged users only.
    Usage: /set_cache_subsidy [on|off]

    When ON, the bot owner absorbs cache write costs (users don't pay for
    cache_creation_input_tokens). When OFF, users pay full cost (default).

    Examples:
        /set_cache_subsidy        (show current status)
        /set_cache_subsidy on     (owner absorbs cache write costs)
        /set_cache_subsidy off    (users pay full cost)
    """
    user_id = message.from_user.id
    lang = get_lang(message.from_user.language_code)

    # Check privileges
    if not is_privileged(user_id):
        logger.warning(
            "admin.set_cache_subsidy_unauthorized",
            user_id=user_id,
            username=message.from_user.username,
            msg="Unauthorized set_cache_subsidy attempt",
        )
        await message.answer(get_text("admin.unauthorized", lang))
        return

    # Parse argument
    args = message.text.split()
    if len(args) < 2:
        # Show current status
        subsidy_active = not config.CHARGE_USERS_FOR_CACHE_WRITE
        await message.answer(
            get_text("admin.cache_subsidy_usage",
                     lang,
                     status="ON" if subsidy_active else "OFF"))
        return

    value = args[1].lower()
    if value == "on":
        new_value = False  # CHARGE_USERS = False means subsidy ON
    elif value == "off":
        new_value = True  # CHARGE_USERS = True means subsidy OFF
    else:
        await message.answer(get_text("admin.cache_subsidy_invalid_value",
                                      lang))
        return

    old_value = config.CHARGE_USERS_FOR_CACHE_WRITE
    config.CHARGE_USERS_FOR_CACHE_WRITE = new_value

    old_status = "OFF" if old_value else "ON"
    new_status = "ON" if not new_value else "OFF"

    logger.info(
        "admin.set_cache_subsidy_success",
        admin_user_id=user_id,
        admin_username=message.from_user.username,
        old_status=old_status,
        new_status=new_status,
        charge_users=new_value,
        msg="Cache write subsidy updated",
    )

    await message.answer(
        get_text("admin.cache_subsidy_updated",
                 lang,
                 old=old_status,
                 new=new_status))


@router.message(Command("clear"))
async def cmd_clear(
    message: Message,
    session: AsyncSession,
    topic_was_created: bool = False,
):
    """Handler for /clear command - delete forum topics.

    Available to all users with restrictions:
    - In private chats: clears all topics
    - In group chats (current topic): clears only the current topic
    - In group chats (General/all topics): requires admin or privileged user

    Behavior:
    - /clear in General (topic_id=None or 1) → deletes ALL topics (admin only)
    - /clear in new topic (just created by this command) → deletes ALL topics
    - /clear in existing topic → deletes only that topic (any user)

    Note: Bot must have can_manage_topics admin right.

    Args:
        message: Telegram message with /clear command.
        session: Database session from middleware.
        topic_was_created: Flag from CommandMiddleware - True if topic
            was just created by this command (sent from General).
    """
    user_id = message.from_user.id
    chat_id = message.chat.id
    lang = get_lang(message.from_user.language_code)

    current_topic_id = message.message_thread_id
    thread_repo = ThreadRepository(session)
    existing_topic_ids = await thread_repo.get_unique_topic_ids(chat_id)

    logger.debug(
        "clear.context",
        chat_id=chat_id,
        user_id=user_id,
        current_topic_id=current_topic_id,
        existing_topic_ids=existing_topic_ids,
        topic_was_created=topic_was_created,
    )

    # Determine mode:
    # - General (id=1 or None) → delete ALL topics
    # - New topic (just created by this command from General) → delete ALL topics
    # - Existing topic → delete only that one
    is_general = (not current_topic_id or current_topic_id == 1 or
                  topic_was_created)

    # Security check: clearing ALL topics in groups requires elevated rights
    is_private_chat = message.chat.type == "private"

    if is_general and not is_private_chat:
        # In group chats, clearing all topics requires admin rights
        is_chat_admin = False
        try:
            member = await message.bot.get_chat_member(chat_id, user_id)
            is_chat_admin = member.status in ("administrator", "creator")
        except Exception:
            pass

        if not is_privileged(user_id) and not is_chat_admin:
            logger.info(
                "clear.denied_no_admin_rights",
                user_id=user_id,
                chat_id=chat_id,
                msg="User tried to clear all topics without admin rights",
            )
            await message.answer(get_text("clear.requires_admin", lang))
            return

    if is_general:
        # General - delete all topics (with confirmation)
        # DB query already excludes cleared topics (is_cleared=False filter)
        topic_ids = [t for t in existing_topic_ids if t != 1]  # Exclude General
        topic_count = len(topic_ids)

        if topic_count == 0:
            await message.answer(get_text("clear.no_topics", lang))
            return

        # Show confirmation dialog with exact count
        keyboard = InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(
                text=get_text("clear.confirm_button", lang, count=topic_count),
                callback_data=f"clear_all:{chat_id}",
                style=ButtonStyle.DANGER,
            )
        ]])

        logger.info(
            "clear.confirmation_shown",
            user_id=user_id,
            chat_id=chat_id,
            topic_count=topic_count,
        )

        await message.answer(
            get_text("clear.confirm_delete", lang, count=topic_count),
            reply_markup=keyboard,
        )
        return

    # Single topic mode - delete immediately
    topic_ids = [current_topic_id]

    logger.info(
        "clear.started",
        user_id=user_id,
        chat_id=chat_id,
        mode="single",
        current_topic_id=current_topic_id,
    )

    await _delete_topics(message.bot, chat_id, topic_ids, thread_repo)
    await session.commit()

    logger.info(
        "clear.complete",
        user_id=user_id,
        chat_id=chat_id,
        mode="single",
        deleted=1,
    )


async def _delete_topics(
    bot,
    chat_id: int,
    topic_ids: list[int],
    thread_repo: ThreadRepository,
) -> int:
    """Delete forum topics and clean up DB records.

    Args:
        bot: Telegram Bot instance.
        chat_id: Chat ID where topics are located.
        topic_ids: List of topic IDs to delete.
        thread_repo: Thread repository for DB cleanup.

    Returns:
        Number of topics successfully deleted.
    """
    deleted_count = 0

    for topic_id in topic_ids:
        # Skip General topic (ID=1) - cannot be deleted
        if topic_id == 1:
            continue

        try:
            await bot.delete_forum_topic(
                chat_id=chat_id,
                message_thread_id=topic_id,
            )
            logger.info(
                "clear.delete_topic_success",
                chat_id=chat_id,
                topic_id=topic_id,
            )
        except Exception as e:
            # Log error but continue - topic may already be deleted
            logger.info(
                "clear.delete_topic_error",
                chat_id=chat_id,
                topic_id=topic_id,
                error=str(e),
            )

        # Always clean up DB record and count as success
        await thread_repo.delete_threads_by_topic_id(chat_id, topic_id)
        deleted_count += 1

    return deleted_count


@router.callback_query(F.data.startswith("clear_all:"))
async def handle_clear_all_confirmation(
    callback: CallbackQuery,
    session: AsyncSession,
):
    """Handle confirmation button for clearing all topics.

    Args:
        callback: Callback query from inline button.
        session: Database session from middleware.
    """
    user_id = callback.from_user.id
    lang = get_lang(callback.from_user.language_code)
    # Extract chat_id from callback data (safe parsing)
    try:
        parts = callback.data.split(":")
        if len(parts) < 2:
            raise ValueError("Missing chat_id in callback data")
        chat_id = int(parts[1])
    except (ValueError, IndexError) as e:
        logger.warning("clear.invalid_callback_data",
                       callback_data=callback.data,
                       error=str(e))
        await callback.answer("Invalid request", show_alert=True)
        return

    # Verify user has permission (re-check in case of stale button)
    is_private_chat = callback.message.chat.type == "private"

    if not is_private_chat:
        is_chat_admin = False
        try:
            member = await callback.bot.get_chat_member(chat_id, user_id)
            is_chat_admin = member.status in ("administrator", "creator")
        except Exception as e:
            logger.warning("clear.admin_check_failed",
                           chat_id=chat_id,
                           user_id=user_id,
                           error=str(e))

        if not is_privileged(user_id) and not is_chat_admin:
            await callback.answer(
                get_text("clear.no_permission", lang),
                show_alert=True,
            )
            return

    # Get all topics for this chat
    thread_repo = ThreadRepository(session)
    topic_ids = await thread_repo.get_unique_topic_ids(chat_id)

    if not topic_ids:
        await callback.answer(get_text("clear.no_topics_to_delete", lang),
                              show_alert=True)
        await callback.message.delete()
        return

    logger.info(
        "clear.confirmed",
        user_id=user_id,
        chat_id=chat_id,
        topic_count=len(topic_ids),
    )

    # Delete confirmation message first (it's in a topic that will be deleted)
    try:
        await callback.message.delete()
    except Exception:
        pass

    # Delete all topics
    deleted_count = await _delete_topics(callback.bot, chat_id, list(topic_ids),
                                         thread_repo)
    await session.commit()

    logger.info(
        "clear.complete",
        user_id=user_id,
        chat_id=chat_id,
        mode="all",
        deleted=deleted_count,
    )

    # Silent acknowledgment - no notification to user
    await callback.answer()
