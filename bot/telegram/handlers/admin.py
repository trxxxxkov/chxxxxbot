"""Admin handlers for privileged users.

This module handles admin-only commands:
- /topup - Adjust any user's balance (add or subtract)
- /set_margin - Configure owner margin (k3) for payment commissions
- /delete_topics - Delete all forum topics in the current chat

Only users in PRIVILEGED_USERS (from secrets/privileged_users.txt) can use these.
"""

from decimal import Decimal

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message
import config
from db.repositories.balance_operation_repository import \
    BalanceOperationRepository
from db.repositories.thread_repository import ThreadRepository
from db.repositories.user_repository import UserRepository
from services.balance_service import BalanceService
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
    user_repo = UserRepository(session)
    balance_op_repo = BalanceOperationRepository(session)
    balance_service = BalanceService(session, user_repo, balance_op_repo)

    try:
        # Perform topup
        balance_before, balance_after = await balance_service.admin_topup(
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
        logger.warning(
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


@router.message(Command("delete_topics"))
async def cmd_delete_topics(message: Message, session: AsyncSession):
    """Handler for /delete_topics command - delete all forum topics.

    Privileged users only. Deletes all forum topics in the current chat
    that are known to the bot (stored in database).

    Note: Topic ID=1 (General) cannot be deleted by Telegram.
    Note: Bot must have can_delete_messages admin right.

    Args:
        message: Telegram message with /delete_topics command.
        session: Database session from middleware.
    """
    user_id = message.from_user.id
    chat_id = message.chat.id

    # Check privileges
    if not is_privileged(user_id):
        logger.warning(
            "admin.delete_topics_unauthorized",
            user_id=user_id,
            username=message.from_user.username,
        )
        await message.answer(
            "❌ This command is only available to privileged users.")
        return

    # Get unique topic IDs from database
    thread_repo = ThreadRepository(session)
    topic_ids = await thread_repo.get_unique_topic_ids(chat_id)

    if not topic_ids:
        await message.answer(
            "ℹ️ No forum topics found in database for this chat.")
        return

    logger.info(
        "admin.delete_topics_started",
        admin_user_id=user_id,
        chat_id=chat_id,
        topic_count=len(topic_ids),
        topic_ids=topic_ids,
    )

    # Send progress message
    progress_msg = await message.answer(
        f"🗑️ Deleting {len(topic_ids)} topic(s)...\n\n"
        f"Topic IDs: {', '.join(map(str, topic_ids))}")

    deleted_count = 0
    failed_count = 0
    skipped_general = False
    errors = []

    for topic_id in topic_ids:
        # Skip General topic (ID=1) - cannot be deleted
        if topic_id == 1:
            skipped_general = True
            # Still delete DB records for General topic threads
            await thread_repo.delete_threads_by_topic_id(chat_id, topic_id)
            continue

        try:
            # Delete topic via Bot API
            await message.bot.delete_forum_topic(
                chat_id=chat_id,
                message_thread_id=topic_id,
            )
            deleted_count += 1

            # Delete DB records for this topic
            await thread_repo.delete_threads_by_topic_id(chat_id, topic_id)

            logger.info(
                "admin.delete_topic_success",
                chat_id=chat_id,
                topic_id=topic_id,
            )

        except Exception as e:
            failed_count += 1
            error_msg = str(e)
            errors.append(f"Topic {topic_id}: {error_msg[:50]}")
            logger.error(
                "admin.delete_topic_failed",
                chat_id=chat_id,
                topic_id=topic_id,
                error=error_msg,
            )

    # Commit all DB changes
    await session.commit()

    # Build result message
    result_parts = [f"✅ <b>Topics deletion complete</b>\n"]
    result_parts.append(f"• Deleted: {deleted_count}")
    if failed_count:
        result_parts.append(f"• Failed: {failed_count}")
    if skipped_general:
        result_parts.append("• Skipped: General (ID=1, cannot be deleted)")

    if errors:
        result_parts.append(f"\n<b>Errors:</b>")
        for err in errors[:5]:  # Show max 5 errors
            result_parts.append(f"• {err}")
        if len(errors) > 5:
            result_parts.append(f"• ... and {len(errors) - 5} more")

    await progress_msg.edit_text("\n".join(result_parts))

    logger.info(
        "admin.delete_topics_complete",
        admin_user_id=user_id,
        chat_id=chat_id,
        deleted=deleted_count,
        failed=failed_count,
        skipped_general=skipped_general,
    )
