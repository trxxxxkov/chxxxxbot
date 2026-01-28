"""Tests for assertion helpers.

Phase 5.5.3: Test Utilities
"""

from decimal import Decimal
from unittest.mock import AsyncMock
from unittest.mock import MagicMock
from unittest.mock import patch

import pytest
from tests.utils.assertions import assert_cost_reasonable
from tests.utils.assertions import assert_tokens_counted


class TestAssertCostReasonable:
    """Tests for assert_cost_reasonable helper."""

    def test_cost_within_bounds(self):
        """Test cost within default bounds passes."""
        assert_cost_reasonable(Decimal("1.50"))

    def test_cost_at_minimum(self):
        """Test cost at minimum passes."""
        assert_cost_reasonable(Decimal("0"))

    def test_cost_at_maximum(self):
        """Test cost at maximum passes."""
        assert_cost_reasonable(Decimal("10"))

    def test_cost_below_minimum_fails(self):
        """Test cost below minimum fails."""
        with pytest.raises(AssertionError, match="below minimum"):
            assert_cost_reasonable(Decimal("-0.01"))

    def test_cost_above_maximum_fails(self):
        """Test cost above maximum fails."""
        with pytest.raises(AssertionError, match="exceeds maximum"):
            assert_cost_reasonable(Decimal("10.01"))

    def test_custom_bounds(self):
        """Test with custom min/max bounds."""
        assert_cost_reasonable(
            Decimal("5.00"),
            min_cost=Decimal("1.00"),
            max_cost=Decimal("10.00"),
        )

    def test_custom_bounds_fail(self):
        """Test custom bounds failure."""
        with pytest.raises(AssertionError):
            assert_cost_reasonable(
                Decimal("0.50"),
                min_cost=Decimal("1.00"),
            )


class TestAssertTokensCounted:
    """Tests for assert_tokens_counted helper."""

    def test_valid_token_counts(self):
        """Test valid token counts pass."""
        assert_tokens_counted(100, 50)

    def test_zero_tokens_allowed(self):
        """Test zero tokens allowed by default."""
        assert_tokens_counted(0, 0)

    def test_minimum_input_check(self):
        """Test minimum input token check."""
        with pytest.raises(AssertionError, match="Input tokens.*below minimum"):
            assert_tokens_counted(5, 50, min_input=10)

    def test_minimum_output_check(self):
        """Test minimum output token check."""
        with pytest.raises(AssertionError,
                           match="Output tokens.*below minimum"):
            assert_tokens_counted(100, 5, min_output=10)

    def test_negative_input_fails(self):
        """Test negative input tokens fail."""
        with pytest.raises(AssertionError, match="below minimum"):
            assert_tokens_counted(-1, 50)

    def test_negative_output_fails(self):
        """Test negative output tokens fail."""
        with pytest.raises(AssertionError, match="below minimum"):
            assert_tokens_counted(100, -1)

    def test_large_token_counts(self):
        """Test large token counts pass."""
        assert_tokens_counted(200000, 16000)


class TestAssertBalanceChanged:
    """Tests for assert_balance_changed helper."""

    @pytest.mark.asyncio
    async def test_balance_changed_positive(self, test_session, sample_user):
        """Test balance increased correctly."""
        from tests.utils.assertions import assert_balance_changed

        initial = sample_user.balance
        credit = Decimal("2.00")
        sample_user.balance = initial + credit
        await test_session.flush()

        await assert_balance_changed(test_session, sample_user.id, credit,
                                     initial)

    @pytest.mark.asyncio
    async def test_balance_changed_negative(self, test_session, sample_user):
        """Test balance decreased correctly."""
        from tests.utils.assertions import assert_balance_changed

        initial = sample_user.balance
        debit = Decimal("-1.00")
        sample_user.balance = initial + debit
        await test_session.flush()

        await assert_balance_changed(test_session, sample_user.id, debit,
                                     initial)

    @pytest.mark.asyncio
    async def test_balance_mismatch_fails(self, test_session, sample_user):
        """Test balance mismatch raises error."""
        from tests.utils.assertions import assert_balance_changed

        initial = sample_user.balance

        with pytest.raises(AssertionError, match="Balance mismatch"):
            await assert_balance_changed(test_session, sample_user.id,
                                         Decimal("99.00"), initial)


class TestAssertBalanceEquals:
    """Tests for assert_balance_equals helper."""

    @pytest.mark.asyncio
    async def test_balance_equals(self, test_session, sample_user):
        """Test balance equals expected value."""
        from tests.utils.assertions import assert_balance_equals

        expected = sample_user.balance
        await assert_balance_equals(test_session, sample_user.id, expected)

    @pytest.mark.asyncio
    async def test_balance_not_equals_fails(self, test_session, sample_user):
        """Test balance not equals raises error."""
        from tests.utils.assertions import assert_balance_equals

        wrong_balance = Decimal("999.99")

        with pytest.raises(AssertionError, match="Balance mismatch"):
            await assert_balance_equals(test_session, sample_user.id,
                                        wrong_balance)


class TestAssertMessageSaved:
    """Tests for assert_message_saved helper."""

    @pytest.mark.asyncio
    async def test_message_found(self, test_session, sample_thread, sample_chat,
                                 sample_user):
        """Test message found in thread."""
        from db.models.message import Message
        from db.models.message import MessageRole
        from tests.utils.assertions import assert_message_saved

        # Create a message with required fields
        message = Message(
            chat_id=sample_chat.id,
            message_id=100,
            thread_id=sample_thread.id,
            from_user_id=sample_user.id,
            date=1234567890,
            role=MessageRole.USER,
            text_content="Test message content",
            attachments=[],
            has_photos=False,
            has_documents=False,
            has_voice=False,
            has_video=False,
            attachment_count=0,
            created_at=1234567890,
        )
        test_session.add(message)
        await test_session.flush()

        await assert_message_saved(test_session, sample_thread.id, "user")

    @pytest.mark.asyncio
    async def test_message_content_contains(self, test_session, sample_thread,
                                            sample_chat, sample_user):
        """Test message content contains substring."""
        from db.models.message import Message
        from db.models.message import MessageRole
        from tests.utils.assertions import assert_message_saved

        message = Message(
            chat_id=sample_chat.id,
            message_id=101,
            thread_id=sample_thread.id,
            from_user_id=sample_user.id,
            date=1234567890,
            role=MessageRole.ASSISTANT,
            text_content="Hello world response",
            attachments=[],
            has_photos=False,
            has_documents=False,
            has_voice=False,
            has_video=False,
            attachment_count=0,
            created_at=1234567890,
        )
        test_session.add(message)
        await test_session.flush()

        await assert_message_saved(test_session,
                                   sample_thread.id,
                                   "assistant",
                                   content_contains="world")

    @pytest.mark.asyncio
    async def test_message_not_found_fails(self, test_session, sample_thread):
        """Test message not found raises error."""
        from tests.utils.assertions import assert_message_saved

        with pytest.raises(AssertionError, match="No assistant message found"):
            await assert_message_saved(test_session, sample_thread.id,
                                       "assistant")


class TestAssertMessageCount:
    """Tests for assert_message_count helper."""

    @pytest.mark.asyncio
    async def test_count_matches(self, test_session, sample_thread, sample_chat,
                                 sample_user):
        """Test message count matches expected."""
        from db.models.message import Message
        from db.models.message import MessageRole
        from tests.utils.assertions import assert_message_count

        # Add 3 messages
        for i in range(3):
            message = Message(
                chat_id=sample_chat.id,
                message_id=200 + i,
                thread_id=sample_thread.id,
                from_user_id=sample_user.id,
                date=1234567890,
                role=MessageRole.USER,
                text_content=f"Message {i}",
                attachments=[],
                has_photos=False,
                has_documents=False,
                has_voice=False,
                has_video=False,
                attachment_count=0,
                created_at=1234567890,
            )
            test_session.add(message)
        await test_session.flush()

        await assert_message_count(test_session, sample_thread.id, 3)

    @pytest.mark.asyncio
    async def test_count_with_role_filter(self, test_session, sample_thread,
                                          sample_chat, sample_user):
        """Test message count with role filter."""
        from db.models.message import Message
        from db.models.message import MessageRole
        from tests.utils.assertions import assert_message_count

        # Add mixed messages
        test_session.add(
            Message(
                chat_id=sample_chat.id,
                message_id=300,
                thread_id=sample_thread.id,
                from_user_id=sample_user.id,
                date=1234567890,
                role=MessageRole.USER,
                text_content="q1",
                attachments=[],
                has_photos=False,
                has_documents=False,
                has_voice=False,
                has_video=False,
                attachment_count=0,
                created_at=1234567890,
            ))
        test_session.add(
            Message(
                chat_id=sample_chat.id,
                message_id=301,
                thread_id=sample_thread.id,
                from_user_id=sample_user.id,
                date=1234567890,
                role=MessageRole.ASSISTANT,
                text_content="a1",
                attachments=[],
                has_photos=False,
                has_documents=False,
                has_voice=False,
                has_video=False,
                attachment_count=0,
                created_at=1234567890,
            ))
        test_session.add(
            Message(
                chat_id=sample_chat.id,
                message_id=302,
                thread_id=sample_thread.id,
                from_user_id=sample_user.id,
                date=1234567890,
                role=MessageRole.USER,
                text_content="q2",
                attachments=[],
                has_photos=False,
                has_documents=False,
                has_voice=False,
                has_video=False,
                attachment_count=0,
                created_at=1234567890,
            ))
        await test_session.flush()

        await assert_message_count(test_session,
                                   sample_thread.id,
                                   2,
                                   role="user")
        await assert_message_count(test_session,
                                   sample_thread.id,
                                   1,
                                   role="assistant")

    @pytest.mark.asyncio
    async def test_count_mismatch_fails(self, test_session, sample_thread):
        """Test count mismatch raises error."""
        from tests.utils.assertions import assert_message_count

        with pytest.raises(AssertionError, match="Message count mismatch"):
            await assert_message_count(test_session, sample_thread.id, 99)


class TestAssertThreadExists:
    """Tests for assert_thread_exists helper."""

    @pytest.mark.asyncio
    async def test_thread_found(self, test_session, sample_thread):
        """Test thread found returns ID."""
        from tests.utils.assertions import assert_thread_exists

        thread_id = await assert_thread_exists(test_session,
                                               sample_thread.chat_id)
        assert thread_id == sample_thread.id

    @pytest.mark.asyncio
    async def test_thread_not_found_fails(self, test_session):
        """Test thread not found raises error."""
        from tests.utils.assertions import assert_thread_exists

        with pytest.raises(AssertionError, match="Thread not found"):
            await assert_thread_exists(test_session, 99999999)


class TestAssertPaymentRecorded:
    """Tests for assert_payment_recorded helper."""

    @pytest.mark.asyncio
    async def test_payment_found(self, test_session, sample_user):
        """Test payment found."""
        from db.models.payment import Payment
        from db.models.payment import PaymentStatus
        from tests.utils.assertions import assert_payment_recorded

        payment = Payment(
            user_id=sample_user.id,
            telegram_payment_charge_id="test_charge_123",
            stars_amount=100,
            nominal_usd_amount=Decimal("2.00"),
            credited_usd_amount=Decimal("1.60"),
            commission_k1=Decimal("0.35"),
            commission_k2=Decimal("0.15"),
            commission_k3=Decimal("0.00"),
            status=PaymentStatus.COMPLETED,
            invoice_payload="topup_123_1234567890_100",
        )
        test_session.add(payment)
        await test_session.flush()

        await assert_payment_recorded(test_session, sample_user.id, 100)

    @pytest.mark.asyncio
    async def test_payment_with_charge_id(self, test_session, sample_user):
        """Test payment found by charge ID."""
        from db.models.payment import Payment
        from db.models.payment import PaymentStatus
        from tests.utils.assertions import assert_payment_recorded

        payment = Payment(
            user_id=sample_user.id,
            telegram_payment_charge_id="specific_charge_456",
            stars_amount=50,
            nominal_usd_amount=Decimal("1.00"),
            credited_usd_amount=Decimal("0.80"),
            commission_k1=Decimal("0.35"),
            commission_k2=Decimal("0.15"),
            commission_k3=Decimal("0.00"),
            status=PaymentStatus.COMPLETED,
            invoice_payload="topup_123_1234567890_50",
        )
        test_session.add(payment)
        await test_session.flush()

        await assert_payment_recorded(
            test_session,
            sample_user.id,
            50,
            telegram_payment_charge_id="specific_charge_456")

    @pytest.mark.asyncio
    async def test_payment_not_found_fails(self, test_session, sample_user):
        """Test payment not found raises error."""
        from tests.utils.assertions import assert_payment_recorded

        with pytest.raises(AssertionError, match="Payment not found"):
            await assert_payment_recorded(test_session, sample_user.id, 99999)
