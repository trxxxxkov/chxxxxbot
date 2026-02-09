"""Handler for /announce command — broadcast messages to users.

Privileged users only. Supports broadcasting any message type
(text, photo, document, etc.) to all users or specific targets.

Flow:
1. Admin sends /announce (all) or /announce @user1 123456 (specific)
2. Bot enters FSM state waiting_for_message
3. Admin sends any message to broadcast
4. Bot shows confirmation with inline buttons
5. Admin confirms → broadcast via copy_message + delivery report
"""

from datetime import datetime
from datetime import timezone
import io

from aiogram import F
from aiogram import Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.exceptions import TelegramForbiddenError
from aiogram.filters import Command
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State
from aiogram.fsm.state import StatesGroup
from aiogram.types import BufferedInputFile
from aiogram.types import CallbackQuery
from aiogram.types import InlineKeyboardButton
from aiogram.types import InlineKeyboardMarkup
from aiogram.types import Message
import config
from db.repositories.user_repository import UserRepository
from i18n import get_lang
from i18n import get_text
from sqlalchemy.ext.asyncio import AsyncSession
from telegram.handlers.admin import is_privileged
from utils.structured_logging import get_logger

logger = get_logger(__name__)
router = Router(name="announce")


class AnnounceStates(StatesGroup):
    """FSM states for announce flow."""

    waiting_for_message = State()
    waiting_for_confirmation = State()


@router.message(Command("announce"))
async def cmd_announce(
    message: Message,
    session: AsyncSession,
    state: FSMContext,
) -> None:
    """Handle /announce command.

    Parses optional targets (user IDs or @usernames), resolves them,
    and enters FSM state waiting for the broadcast message.

    Args:
        message: Telegram message with /announce command.
        session: Database session from middleware.
        state: FSM context for state management.
    """
    if not message.from_user:
        return

    user_id = message.from_user.id
    lang = get_lang(message.from_user.language_code)

    if not is_privileged(user_id):
        logger.warning(
            "announce.unauthorized",
            user_id=user_id,
            username=message.from_user.username,
        )
        await message.answer(get_text("announce.unauthorized", lang))
        return

    user_repo = UserRepository(session)

    # Parse targets from command args
    args = (message.text or "").split()[1:]  # Skip "/announce"

    if args:
        # Specific targets mode
        target_ids: list[int] = []
        not_found: list[str] = []

        for target in args:
            if target.startswith("@"):
                # Username lookup
                username = target[1:]
                user = await user_repo.get_by_username(username)
                if user:
                    target_ids.append(user.id)
                else:
                    not_found.append(target)
            else:
                # Try as numeric ID
                try:
                    tid = int(target)
                    user = await user_repo.get_by_telegram_id(tid)
                    if user:
                        target_ids.append(user.id)
                    else:
                        not_found.append(target)
                except ValueError:
                    not_found.append(target)

        # Report not-found targets
        if not_found:
            warnings = "\n".join(
                get_text("announce.user_not_found", lang, target=t)
                for t in not_found)
            await message.answer(warnings)

        if not target_ids:
            await message.answer(get_text("announce.no_valid_targets", lang))
            return

        # Remove duplicates preserving order
        seen = set()
        unique_ids = []
        for tid in target_ids:
            if tid not in seen:
                seen.add(tid)
                unique_ids.append(tid)
        target_ids = unique_ids

        await state.set_state(AnnounceStates.waiting_for_message)
        await state.update_data(
            target_ids=target_ids,
            is_all=False,
            admin_user_id=user_id,
        )

        await message.answer(
            get_text("announce.waiting_for_message",
                     lang,
                     count=len(target_ids)))

        logger.info(
            "announce.targets_parsed",
            admin_user_id=user_id,
            target_count=len(target_ids),
            not_found=not_found,
        )
    else:
        # All users mode
        all_users = await user_repo.get_all_users()
        all_ids = [u.id for u in all_users]

        if not all_ids:
            await message.answer(get_text("announce.no_valid_targets", lang))
            return

        await state.set_state(AnnounceStates.waiting_for_message)
        await state.update_data(
            target_ids=all_ids,
            is_all=True,
            admin_user_id=user_id,
        )

        await message.answer(
            get_text("announce.waiting_for_message_all",
                     lang,
                     count=len(all_ids)))

        logger.info(
            "announce.all_users_mode",
            admin_user_id=user_id,
            total_users=len(all_ids),
        )


@router.message(StateFilter(AnnounceStates.waiting_for_message))
async def announce_message_received(
    message: Message,
    state: FSMContext,
) -> None:
    """Receive the message to broadcast and show confirmation.

    Args:
        message: Any message type from the admin.
        state: FSM context with target data.
    """
    if not message.from_user:
        return

    data = await state.get_data()
    admin_user_id = data.get("admin_user_id")

    # Only the admin who started the flow can send the message
    if message.from_user.id != admin_user_id:
        return

    lang = get_lang(message.from_user.language_code)
    target_ids = data.get("target_ids", [])

    # Store the message reference for broadcasting
    await state.update_data(
        broadcast_chat_id=message.chat.id,
        broadcast_message_id=message.message_id,
    )
    await state.set_state(AnnounceStates.waiting_for_confirmation)

    # Send preview: copy the message back to admin so they see
    # exactly how recipients will see it
    try:
        await message.bot.copy_message(
            chat_id=message.chat.id,
            from_chat_id=message.chat.id,
            message_id=message.message_id,
        )
    except Exception as e:
        logger.warning("announce.preview_copy_failed", error=str(e))

    # Show confirmation with inline buttons
    keyboard = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(
            text=get_text("announce.confirm_button", lang),
            callback_data="announce:confirm",
        ),
        InlineKeyboardButton(
            text=get_text("announce.cancel_button", lang),
            callback_data="announce:cancel",
        ),
    ]])

    await message.answer(
        get_text("announce.confirm", lang, count=len(target_ids)),
        reply_markup=keyboard,
    )


@router.callback_query(
    F.data == "announce:confirm",
    StateFilter(AnnounceStates.waiting_for_confirmation),
)
async def announce_confirm_callback(
    callback: CallbackQuery,
    state: FSMContext,
) -> None:
    """Handle broadcast confirmation.

    Broadcasts via copy_message and sends delivery report.

    Args:
        callback: Callback query from confirm button.
        state: FSM context with broadcast data.
    """
    if not callback.from_user:
        return

    data = await state.get_data()
    admin_user_id = data.get("admin_user_id")

    # Only the admin who started the flow can confirm
    if callback.from_user.id != admin_user_id:
        await callback.answer()
        return

    lang = get_lang(callback.from_user.language_code)
    target_ids = data.get("target_ids", [])
    broadcast_chat_id = data.get("broadcast_chat_id")
    broadcast_message_id = data.get("broadcast_message_id")

    # Clear state immediately
    await state.clear()

    # Remove confirmation buttons
    try:
        await callback.message.edit_reply_markup(reply_markup=None)
    except Exception:
        pass

    await callback.answer()

    # Send progress message
    progress_msg = await callback.message.answer(
        get_text("announce.sending", lang, sent=0, total=len(target_ids)))

    # Broadcast
    delivered = []
    failed = []
    last_progress_update = 0

    for i, target_id in enumerate(target_ids):
        try:
            await callback.bot.copy_message(
                chat_id=target_id,
                from_chat_id=broadcast_chat_id,
                message_id=broadcast_message_id,
            )
            delivered.append(target_id)
        except TelegramForbiddenError:
            failed.append((target_id, "Bot blocked by user"))
        except TelegramBadRequest as e:
            failed.append((target_id, str(e)))
        except Exception as e:
            failed.append((target_id, str(e)))

        # Update progress every 10 messages
        sent = i + 1
        if sent - last_progress_update >= 10 or sent == len(target_ids):
            try:
                await progress_msg.edit_text(
                    get_text("announce.sending",
                             lang,
                             sent=sent,
                             total=len(target_ids)))
                last_progress_update = sent
            except Exception:
                pass

    # Final summary
    try:
        await progress_msg.edit_text(
            get_text("announce.complete",
                     lang,
                     delivered=len(delivered),
                     failed=len(failed)))
    except Exception:
        pass

    logger.info(
        "announce.broadcast_complete",
        admin_user_id=admin_user_id,
        delivered=len(delivered),
        failed=len(failed),
        total=len(target_ids),
    )

    # Generate and send delivery report if there were any sends
    if delivered or failed:
        report = _generate_report(delivered, failed)
        report_file = BufferedInputFile(
            report.encode("utf-8"),
            filename=
            f"broadcast_report_{datetime.now(timezone.utc):%Y%m%d_%H%M%S}.txt",
        )
        await callback.message.answer_document(
            report_file,
            caption=get_text("announce.report_caption", lang),
        )


@router.callback_query(
    F.data == "announce:cancel",
    StateFilter(AnnounceStates.waiting_for_confirmation),
)
async def announce_cancel_callback(
    callback: CallbackQuery,
    state: FSMContext,
) -> None:
    """Handle broadcast cancellation.

    Args:
        callback: Callback query from cancel button.
        state: FSM context to clear.
    """
    if not callback.from_user:
        return

    data = await state.get_data()
    admin_user_id = data.get("admin_user_id")

    if callback.from_user.id != admin_user_id:
        await callback.answer()
        return

    lang = get_lang(callback.from_user.language_code)

    await state.clear()

    try:
        await callback.message.edit_text(get_text("announce.cancelled", lang))
    except Exception:
        pass

    await callback.answer()

    logger.info("announce.cancelled", admin_user_id=admin_user_id)


def _generate_report(
    delivered: list[int],
    failed: list[tuple[int, str]],
) -> str:
    """Generate a text delivery report.

    Args:
        delivered: List of user IDs that received the message.
        failed: List of (user_id, error_reason) tuples.

    Returns:
        Report text as string.
    """
    now = datetime.now(timezone.utc)
    lines = [
        f"Broadcast Report — {now:%Y-%m-%d %H:%M:%S} UTC",
        f"Total: {len(delivered) + len(failed)}",
        f"Delivered: {len(delivered)}",
        f"Failed: {len(failed)}",
        "",
    ]

    if delivered:
        lines.append("=== Delivered ===")
        for uid in delivered:
            lines.append(str(uid))
        lines.append("")

    if failed:
        lines.append("=== Failed ===")
        for uid, reason in failed:
            lines.append(f"{uid}: {reason}")
        lines.append("")

    return "\n".join(lines)
