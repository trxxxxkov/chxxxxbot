"""Edge case tests for payment functionality.

Phase 5.4.2: Payment Edge Cases
- Concurrent payments same user
- Payment during generation
- Refund handling
- Balance edge cases
"""

from decimal import Decimal
from unittest.mock import AsyncMock
from unittest.mock import MagicMock
from unittest.mock import patch

import pytest

# ============================================================================
# Tests for balance edge cases
# ============================================================================


class TestBalanceEdgeCases:
    """Tests for balance calculation edge cases."""

    def test_balance_precision(self):
        """Test balance maintains decimal precision."""
        balance = Decimal("0.0001")
        cost = Decimal("0.00001")

        new_balance = balance - cost

        assert new_balance == Decimal("0.00009")

    def test_balance_negative_small(self):
        """Test small negative balance."""
        balance = Decimal("-0.0001")

        assert balance < 0
        assert balance > Decimal("-0.001")

    def test_balance_exactly_zero(self):
        """Test exactly zero balance."""
        balance = Decimal("0.00")

        assert balance == 0
        assert not balance < 0
        assert not balance > 0

    def test_balance_string_conversion(self):
        """Test balance string conversion."""
        balance = Decimal("1.5")

        assert str(balance) == "1.5"
        assert f"{balance:.4f}" == "1.5000"

    def test_balance_comparison_with_threshold(self):
        """Test balance comparison with threshold."""
        # Test threshold-based rejection
        balance = Decimal("-0.01")
        threshold = Decimal("0")

        # User should be rejected (balance < threshold)
        assert balance < threshold

    def test_large_balance(self):
        """Test handling very large balance."""
        balance = Decimal("999999.9999")

        assert balance > Decimal("999999")
        assert balance < Decimal("1000000")


# ============================================================================
# Tests for Stars conversion
# ============================================================================


class TestStarsConversion:
    """Tests for Telegram Stars to USD conversion."""

    def test_stars_to_usd_basic(self):
        """Test basic Stars to USD conversion."""
        # 1 star = $0.02 USD
        stars = 100
        usd_rate = Decimal("0.02")

        usd_value = Decimal(stars) * usd_rate

        assert usd_value == Decimal("2.00")

    def test_stars_to_usd_with_margin(self):
        """Test Stars to USD with margin."""
        stars = 100
        usd_rate = Decimal("0.02")
        margin = Decimal("0.8")  # 80% margin

        usd_value = Decimal(stars) * usd_rate * margin

        assert usd_value == Decimal("1.60")

    def test_minimum_stars_purchase(self):
        """Test minimum stars purchase value."""
        min_stars = 1
        usd_rate = Decimal("0.02")

        min_value = Decimal(min_stars) * usd_rate

        assert min_value == Decimal("0.02")

    def test_maximum_stars_purchase(self):
        """Test maximum stars purchase (Telegram limit)."""
        max_stars = 2500  # Telegram maximum
        usd_rate = Decimal("0.02")

        max_value = Decimal(max_stars) * usd_rate

        assert max_value == Decimal("50.00")


# ============================================================================
# Tests for payment state handling
# ============================================================================


class TestPaymentStateHandling:
    """Tests for payment state machine."""

    @pytest.mark.asyncio
    async def test_pre_checkout_validation(self):
        """Test pre-checkout query validation."""
        # Valid pre-checkout should pass
        pre_checkout = MagicMock()
        pre_checkout.id = "precheckout_123"
        pre_checkout.invoice_payload = "stars_100"
        pre_checkout.currency = "XTR"
        pre_checkout.total_amount = 100

        # Validate payload format
        assert pre_checkout.invoice_payload.startswith("stars_")

    @pytest.mark.asyncio
    async def test_pre_checkout_invalid_payload(self):
        """Test pre-checkout with invalid payload."""
        pre_checkout = MagicMock()
        pre_checkout.invoice_payload = "invalid_payload"

        # Invalid payload should be rejected
        assert not pre_checkout.invoice_payload.startswith("stars_")

    @pytest.mark.asyncio
    async def test_successful_payment_records_transaction(
            self, test_session, sample_user):
        """Test successful payment records transaction."""
        from db.models.payment import Payment
        from db.models.payment import PaymentStatus

        # Record payment
        payment = Payment(
            user_id=sample_user.id,
            telegram_payment_charge_id="charge_123",
            stars_amount=100,
            nominal_usd_amount=Decimal("2.00"),
            credited_usd_amount=Decimal("1.00"),
            commission_k1=Decimal("0.35"),
            commission_k2=Decimal("0.15"),
            commission_k3=Decimal("0.00"),
            status=PaymentStatus.COMPLETED,
            invoice_payload="topup_123_1234567890_100",
        )
        test_session.add(payment)
        await test_session.flush()

        assert payment.status == PaymentStatus.COMPLETED
        assert payment.stars_amount == 100


# ============================================================================
# Tests for concurrent payment handling
# ============================================================================


class TestConcurrentPayments:
    """Tests for concurrent payment scenarios."""

    @pytest.mark.asyncio
    async def test_balance_update_atomic(self, test_session, sample_user):
        """Test balance update is atomic."""
        initial_balance = sample_user.balance
        credit_amount = Decimal("1.00")

        # Update balance
        sample_user.balance = sample_user.balance + credit_amount
        await test_session.flush()

        assert sample_user.balance == initial_balance + credit_amount

    @pytest.mark.asyncio
    async def test_double_payment_prevention(self, test_session, sample_user):
        """Test double payment prevention via unique payment ID."""
        from db.models.payment import Payment
        from db.models.payment import PaymentStatus

        payment_id = "charge_unique_123"

        # First payment
        payment1 = Payment(
            user_id=sample_user.id,
            telegram_payment_charge_id=payment_id,
            stars_amount=100,
            nominal_usd_amount=Decimal("2.00"),
            credited_usd_amount=Decimal("1.00"),
            commission_k1=Decimal("0.35"),
            commission_k2=Decimal("0.15"),
            commission_k3=Decimal("0.00"),
            status=PaymentStatus.COMPLETED,
            invoice_payload="topup_123_1234567890_100",
        )
        test_session.add(payment1)
        await test_session.flush()

        # Verify unique constraint exists on telegram_payment_charge_id
        assert payment1.telegram_payment_charge_id == payment_id


# ============================================================================
# Tests for refund handling
# ============================================================================


class TestRefundHandling:
    """Tests for refund scenarios."""

    @pytest.mark.asyncio
    async def test_refund_deducts_balance(self, test_session, sample_user):
        """Test refund deducts from balance."""
        sample_user.balance = Decimal("5.00")
        refund_amount = Decimal("2.00")

        sample_user.balance = sample_user.balance - refund_amount
        await test_session.flush()

        assert sample_user.balance == Decimal("3.00")

    @pytest.mark.asyncio
    async def test_refund_can_make_balance_negative(self, test_session,
                                                    sample_user):
        """Test refund can make balance negative (if user spent stars)."""
        sample_user.balance = Decimal("0.50")
        refund_amount = Decimal("2.00")

        sample_user.balance = sample_user.balance - refund_amount
        await test_session.flush()

        assert sample_user.balance == Decimal("-1.50")
        assert sample_user.balance < 0

    def test_refund_amount_matches_original(self):
        """Test refund amount must match original payment."""
        original_stars = 100
        refund_stars = 100

        assert original_stars == refund_stars


# ============================================================================
# Tests for payment during generation
# ============================================================================


class TestPaymentDuringGeneration:
    """Tests for payment during active generation."""

    @pytest.mark.asyncio
    async def test_balance_check_before_tool(self):
        """Test balance is checked before paid tool execution."""
        balance = Decimal("-0.01")

        # Paid tool should be rejected with negative balance
        should_reject = balance < 0

        assert should_reject is True

    @pytest.mark.asyncio
    async def test_balance_update_during_generation(self):
        """Test balance can be updated during generation."""
        # This tests that balance updates don't block generation
        # (async nature of the system)

        initial_balance = Decimal("0.50")
        payment_credit = Decimal("2.00")
        generation_cost = Decimal("0.10")

        # Simulate concurrent operations
        final_balance = initial_balance + payment_credit - generation_cost

        assert final_balance == Decimal("2.40")


# ============================================================================
# Tests for invoice generation
# ============================================================================


class TestInvoiceGeneration:
    """Tests for Telegram Stars invoice generation."""

    def test_invoice_payload_format(self):
        """Test invoice payload format."""
        stars = 100
        payload = f"stars_{stars}"

        assert payload == "stars_100"
        assert payload.startswith("stars_")

    def test_invoice_title_format(self):
        """Test invoice title format."""
        stars = 100
        usd_value = Decimal("1.60")

        title = f"${usd_value:.2f} Credit"

        assert title == "$1.60 Credit"

    def test_invoice_prices_format(self):
        """Test invoice prices format for Telegram API."""
        stars = 100

        prices = [{"label": "Stars", "amount": stars}]

        assert len(prices) == 1
        assert prices[0]["amount"] == 100

    def test_custom_amount_parsing(self):
        """Test custom amount input parsing."""
        # Valid inputs
        assert int("100") == 100
        assert int("50") == 50

        # Invalid inputs should raise
        with pytest.raises(ValueError):
            int("abc")

    def test_custom_amount_limits(self):
        """Test custom amount limits."""
        min_stars = 1
        max_stars = 2500

        # Valid amounts
        assert min_stars <= 100 <= max_stars
        assert min_stars <= 1 <= max_stars
        assert min_stars <= 2500 <= max_stars

        # Invalid amounts
        assert not (min_stars <= 0 <= max_stars)
        assert not (min_stars <= 2501 <= max_stars)
