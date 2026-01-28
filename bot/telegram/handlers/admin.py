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

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message
import config
from db.repositories.thread_repository import ThreadRepository
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

    # Check privileges
    if not is_privileged(user_id):
        logger.warning(
            "admin.topup_unauthorized",
            user_id=user_id,
            username=message.from_user.username,
            msg="Unauthorized topup attempt",
        )
        await message.answer(
            "❌ This command is only available to privileged users.")
        return

    # Parse arguments
    args = message.text.split()
    if len(args) < 3:
        await message.answer(
            "ℹ️ <b>Admin Balance Adjustment</b>\n\n"
            "<b>Usage:</b> <code>/topup &lt;user_id or @username&gt; &lt;amount&gt;</code>\n\n"
            "<b>Examples:</b>\n"
            "<code>/topup 123456789 10.50</code>  (add $10.50)\n"
            "<code>/topup @username -5.00</code>  (deduct $5.00)\n\n"
            "💡 Positive amount = add to balance\n"
            "💡 Negative amount = deduct from balance")
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
            await message.answer("❌ Invalid user ID. Must be a number.")
            return

    # Parse amount
    try:
        amount = Decimal(amount_str)
    except Exception:
        await message.answer("❌ Invalid amount. Must be a number.")
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
        action = "Added" if amount > 0 else "Deducted"

        await message.answer(f"✅ <b>Balance adjusted</b>\n\n"
                             f"<b>Target:</b> {target_display}\n"
                             f"<b>{action}:</b> ${abs(amount)}\n"
                             f"<b>Before:</b> ${balance_before}\n"
                             f"<b>After:</b> ${balance_after}")

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
        await message.answer(f"❌ <b>Topup failed:</b>\n\n{str(e)}")

    except Exception as e:
        logger.error(
            "admin.topup_error",
            admin_user_id=user_id,
            error=str(e),
            exc_info=True,
            msg="Unexpected error during admin topup",
        )
        await message.answer("❌ Topup failed. Please try again.")


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

    # Check privileges
    if not is_privileged(user_id):
        logger.warning(
            "admin.set_margin_unauthorized",
            user_id=user_id,
            username=message.from_user.username,
            msg="Unauthorized set_margin attempt",
        )
        await message.answer(
            "❌ This command is only available to privileged users.")
        return

    # Parse k3 value
    args = message.text.split()
    if len(args) < 2:
        k1 = config.TELEGRAM_WITHDRAWAL_FEE
        k2 = config.TELEGRAM_TOPICS_FEE
        k3_current = config.DEFAULT_OWNER_MARGIN
        k3_max = 1.0 - k1 - k2

        await message.answer(
            f"ℹ️ <b>Owner Margin Configuration</b>\n\n"
            f"<b>Usage:</b> <code>/set_margin &lt;k3_value&gt;</code>\n\n"
            f"<b>Current settings:</b>\n"
            f"• k1 (Telegram withdrawal): {k1*100:.1f}%\n"
            f"• k2 (Topics fee): {k2*100:.1f}%\n"
            f"• k3 (Owner margin): {k3_current*100:.1f}%\n\n"
            f"<b>Constraint:</b> k1 + k2 + k3 ≤ 1.0\n"
            f"k3 must be in range [0, {k3_max:.2f}] ({k3_max*100:.1f}%)\n\n"
            f"<b>Example:</b>\n"
            f"<code>/set_margin 0.10</code>  (set 10% margin)")
        return

    try:
        k3 = float(args[1])
    except ValueError:
        await message.answer("❌ Invalid value. Must be a number.")
        return

    # Validate k3
    k1 = config.TELEGRAM_WITHDRAWAL_FEE
    k2 = config.TELEGRAM_TOPICS_FEE

    if not (0 <= k3 <= 1):
        await message.answer(f"❌ k3 must be in range [0, 1], got {k3}")
        return

    if k1 + k2 + k3 > 1.0001:  # Float precision tolerance
        k3_max = 1.0 - k1 - k2
        await message.answer(
            f"❌ <b>Total commission exceeds 100%</b>\n\n"
            f"k1 + k2 + k3 = {k1+k2+k3:.4f} > 1.0\n\n"
            f"<b>Maximum k3:</b> {k3_max:.4f} ({k3_max*100:.1f}%)")
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
        f"✅ <b>Owner margin updated</b>\n\n"
        f"<b>Old:</b> {old_margin*100:.1f}%\n"
        f"<b>New:</b> {k3*100:.1f}%\n\n"
        f"<b>Total commission breakdown:</b>\n"
        f"• k1 (Telegram): {k1*100:.1f}%\n"
        f"• k2 (Topics): {k2*100:.1f}%\n"
        f"• k3 (Owner): {k3*100:.1f}%\n"
        f"• <b>Total:</b> {(k1+k2+k3)*100:.1f}%\n\n"
        f"💡 Users will receive <b>{(1-k1-k2-k3)*100:.1f}%</b> of nominal Stars value."
    )

    logger.info(
        "admin.set_margin_success",
        admin_user_id=user_id,
        old_margin=old_margin,
        new_margin=k3,
        total_commission=k1 + k2 + k3,
        msg="Owner margin updated successfully",
    )


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
            await message.answer(
                "❌ Clearing all topics requires admin rights.\n"
                "💡 Use /clear inside a specific topic to delete only that topic."
            )
            return

    if is_general:
        # General - delete all topics
        topic_ids = list(existing_topic_ids)
        mode = "all"
    else:
        # Regular topic - delete only this one
        topic_ids = [current_topic_id]
        mode = "single"

    if not topic_ids:
        await message.answer("ℹ️ No forum topics to delete.")
        return

    logger.info(
        "clear.started",
        user_id=user_id,
        chat_id=chat_id,
        mode=mode,
        is_general=is_general,
        current_topic_id=current_topic_id,
        topic_count=len(topic_ids),
        topic_ids=topic_ids,
    )

    # Send progress message (only for "all" mode, single topic deletes immediately)
    deleted_count = 0
    skipped_general = False

    for topic_id in topic_ids:
        # Skip General topic (ID=1) - cannot be deleted
        if topic_id == 1:
            skipped_general = True
            continue

        try:
            await message.bot.delete_forum_topic(
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

    # Commit DB changes
    await session.commit()

    # No confirmation message - topics are silently deleted

    logger.info(
        "clear.complete",
        user_id=user_id,
        chat_id=chat_id,
        mode=mode,
        deleted=deleted_count,
        skipped_general=skipped_general,
    )
