"""Test assertion helpers.

Phase 5.5.3: Test Utilities
Reusable assertion functions for common test patterns.
"""

from decimal import Decimal
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession


async def assert_balance_changed(
    session: AsyncSession,
    user_id: int,
    expected_delta: Decimal,
    initial_balance: Decimal,
) -> None:
    """Assert user balance changed by expected amount.

    Args:
        session: Database session
        user_id: User ID to check
        expected_delta: Expected balance change (positive or negative)
        initial_balance: Balance before the operation

    Raises:
        AssertionError: If balance didn't change as expected
    """
    from db.models.user import User

    result = await session.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()

    assert user is not None, f"User {user_id} not found"

    expected_balance = initial_balance + expected_delta
    assert user.balance == expected_balance, (
        f"Balance mismatch: expected {expected_balance}, "
        f"got {user.balance} (delta: {user.balance - initial_balance})")


async def assert_balance_equals(
    session: AsyncSession,
    user_id: int,
    expected_balance: Decimal,
) -> None:
    """Assert user has specific balance.

    Args:
        session: Database session
        user_id: User ID to check
        expected_balance: Expected balance value

    Raises:
        AssertionError: If balance doesn't match
    """
    from db.models.user import User

    result = await session.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()

    assert user is not None, f"User {user_id} not found"
    assert user.balance == expected_balance, (
        f"Balance mismatch: expected {expected_balance}, got {user.balance}")


async def assert_message_saved(
    session: AsyncSession,
    thread_id: int,
    role: str,
    content_contains: Optional[str] = None,
) -> None:
    """Assert a message was saved to thread.

    Args:
        session: Database session
        thread_id: Thread ID to check
        role: Expected message role ('user' or 'assistant')
        content_contains: Optional substring to check in content

    Raises:
        AssertionError: If message not found or doesn't match
    """
    from db.models.message import Message

    result = await session.execute(
        select(Message).where(Message.thread_id == thread_id).where(
            Message.role == role).order_by(Message.created_at.desc()).limit(1))
    message = result.scalar_one_or_none()

    assert message is not None, (
        f"No {role} message found in thread {thread_id}")

    if content_contains:
        # Handle both string content and structured content
        content_str = message.text_content or ""
        assert content_contains in content_str, (
            f"Message content doesn't contain '{content_contains}': {content_str[:100]}..."
        )


async def assert_message_count(
    session: AsyncSession,
    thread_id: int,
    expected_count: int,
    role: Optional[str] = None,
) -> None:
    """Assert number of messages in thread.

    Args:
        session: Database session
        thread_id: Thread ID to check
        expected_count: Expected number of messages
        role: Optional role filter ('user' or 'assistant')

    Raises:
        AssertionError: If count doesn't match
    """
    from db.models.message import Message
    from sqlalchemy import func

    query = select(
        func.count()).select_from(Message).where(Message.thread_id == thread_id)

    if role:
        query = query.where(Message.role == role)

    result = await session.execute(query)
    count = result.scalar()

    assert count == expected_count, (
        f"Message count mismatch: expected {expected_count}, got {count}" +
        (f" (role={role})" if role else ""))


async def assert_thread_exists(
    session: AsyncSession,
    chat_id: int,
    thread_id: Optional[int] = None,
) -> int:
    """Assert thread exists and return its internal ID.

    Args:
        session: Database session
        chat_id: Chat ID
        thread_id: Optional Telegram thread/topic ID (None = main chat)

    Returns:
        Internal thread ID

    Raises:
        AssertionError: If thread not found
    """
    from db.models.thread import Thread

    query = select(Thread).where(Thread.chat_id == chat_id)

    if thread_id is not None:
        query = query.where(Thread.thread_id == thread_id)
    else:
        query = query.where(Thread.thread_id.is_(None))

    result = await session.execute(query)
    thread = result.scalar_one_or_none()

    assert thread is not None, (
        f"Thread not found for chat_id={chat_id}, thread_id={thread_id}")

    return thread.id


async def assert_payment_recorded(
    session: AsyncSession,
    user_id: int,
    stars_amount: int,
    telegram_payment_charge_id: Optional[str] = None,
) -> None:
    """Assert payment was recorded.

    Args:
        session: Database session
        user_id: User ID
        stars_amount: Expected stars amount
        telegram_payment_charge_id: Optional specific payment ID

    Raises:
        AssertionError: If payment not found
    """
    from db.models.payment import Payment

    query = select(Payment).where(
        Payment.user_id == user_id,
        Payment.stars_amount == stars_amount,
    )

    if telegram_payment_charge_id:
        query = query.where(
            Payment.telegram_payment_charge_id == telegram_payment_charge_id)

    result = await session.execute(query)
    payment = result.scalar_one_or_none()

    assert payment is not None, (
        f"Payment not found: user_id={user_id}, stars={stars_amount}")


def assert_cost_reasonable(
        cost: Decimal,
        min_cost: Decimal = Decimal("0"),
        max_cost: Decimal = Decimal("10"),
) -> None:
    """Assert cost is within reasonable bounds.

    Args:
        cost: Cost to check
        min_cost: Minimum expected cost
        max_cost: Maximum expected cost

    Raises:
        AssertionError: If cost out of bounds
    """
    assert cost >= min_cost, f"Cost {cost} below minimum {min_cost}"
    assert cost <= max_cost, f"Cost {cost} exceeds maximum {max_cost}"


def assert_tokens_counted(
    input_tokens: int,
    output_tokens: int,
    min_input: int = 0,
    min_output: int = 0,
) -> None:
    """Assert token counts are valid.

    Args:
        input_tokens: Input token count
        output_tokens: Output token count
        min_input: Minimum expected input tokens
        min_output: Minimum expected output tokens

    Raises:
        AssertionError: If token counts invalid
    """
    assert input_tokens >= min_input, (
        f"Input tokens {input_tokens} below minimum {min_input}")
    assert output_tokens >= min_output, (
        f"Output tokens {output_tokens} below minimum {min_output}")
    assert input_tokens >= 0, f"Negative input tokens: {input_tokens}"
    assert output_tokens >= 0, f"Negative output tokens: {output_tokens}"
