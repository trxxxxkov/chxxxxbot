"""Tests for Payment model.

Phase 2.1: Payment system tests for Payment model with constraints and methods.
"""

from datetime import datetime
from datetime import timedelta
from decimal import Decimal

from db.models.payment import Payment
from db.models.payment import PaymentStatus
import pytest
from sqlalchemy import select


@pytest.mark.asyncio
class TestPaymentModel:
    """Test Payment model structure and constraints."""

    async def test_payment_creation(self, pg_session, pg_sample_user):
        """Test creating a payment with all required fields."""
        payment = Payment(
            user_id=pg_sample_user.id,
            telegram_payment_charge_id="tg_charge_12345",
            stars_amount=100,
            nominal_usd_amount=Decimal("1.3000"),
            credited_usd_amount=Decimal("0.6500"),
            commission_k1=Decimal("0.3500"),
            commission_k2=Decimal("0.1500"),
            commission_k3=Decimal("0.0000"),
            status=PaymentStatus.COMPLETED,
            invoice_payload="topup_123456789_1234567890_100",
        )

        pg_session.add(payment)
        await pg_session.flush()
        await pg_session.refresh(payment)

        assert payment.id is not None
        assert payment.user_id == pg_sample_user.id
        assert payment.stars_amount == 100
        assert payment.status == PaymentStatus.COMPLETED
        assert payment.created_at is not None
        assert payment.updated_at is not None

    async def test_payment_status_enum(self, pg_session):
        """Test PaymentStatus enum values."""
        assert PaymentStatus.COMPLETED.value == "completed"
        assert PaymentStatus.REFUNDED.value == "refunded"

    async def test_payment_commission_constraints(self, pg_session,
                                                  pg_sample_user):
        """Test commission constraints (k1, k2, k3 range 0-1)."""
        # Valid commissions
        payment = Payment(
            user_id=pg_sample_user.id,
            telegram_payment_charge_id="tg_charge_valid",
            stars_amount=50,
            nominal_usd_amount=Decimal("0.6500"),
            credited_usd_amount=Decimal("0.3250"),
            commission_k1=Decimal("0.3500"),
            commission_k2=Decimal("0.1500"),
            commission_k3=Decimal("0.0000"),
            status=PaymentStatus.COMPLETED,
            invoice_payload="topup_123456789_1234567890_50",
        )

        pg_session.add(payment)
        await pg_session.flush()

        assert payment.id is not None

    async def test_payment_positive_amounts_constraint(self, pg_session,
                                                       pg_sample_user):
        """Test that stars_amount must be positive."""
        payment = Payment(
            user_id=pg_sample_user.id,
            telegram_payment_charge_id="tg_charge_zero",
            stars_amount=0,  # Invalid: must be > 0
            nominal_usd_amount=Decimal("0.0000"),
            credited_usd_amount=Decimal("0.0000"),
            commission_k1=Decimal("0.3500"),
            commission_k2=Decimal("0.1500"),
            commission_k3=Decimal("0.0000"),
            status=PaymentStatus.COMPLETED,
            invoice_payload="topup_123456789_1234567890_0",
        )

        pg_session.add(payment)

        with pytest.raises(Exception):  # IntegrityError or CheckViolation
            await pg_session.flush()

        await pg_session.rollback()

    async def test_payment_unique_charge_id(self, pg_session, pg_sample_user):
        """Test telegram_payment_charge_id uniqueness constraint."""
        payment1 = Payment(
            user_id=pg_sample_user.id,
            telegram_payment_charge_id="tg_charge_unique",
            stars_amount=100,
            nominal_usd_amount=Decimal("1.3000"),
            credited_usd_amount=Decimal("0.6500"),
            commission_k1=Decimal("0.3500"),
            commission_k2=Decimal("0.1500"),
            commission_k3=Decimal("0.0000"),
            status=PaymentStatus.COMPLETED,
            invoice_payload="topup_123456789_1234567890_100",
        )

        pg_session.add(payment1)
        await pg_session.flush()

        # Try to create duplicate
        payment2 = Payment(
            user_id=pg_sample_user.id,
            telegram_payment_charge_id="tg_charge_unique",  # Duplicate!
            stars_amount=50,
            nominal_usd_amount=Decimal("0.6500"),
            credited_usd_amount=Decimal("0.3250"),
            commission_k1=Decimal("0.3500"),
            commission_k2=Decimal("0.1500"),
            commission_k3=Decimal("0.0000"),
            status=PaymentStatus.COMPLETED,
            invoice_payload="topup_987654321_1234567890_50",
        )

        pg_session.add(payment2)

        with pytest.raises(Exception):  # IntegrityError (unique constraint)
            await pg_session.flush()

        await pg_session.rollback()

    async def test_payment_can_refund_within_period(self, pg_session,
                                                    pg_sample_user):
        """Test can_refund() returns True within refund period."""
        payment = Payment(
            user_id=pg_sample_user.id,
            telegram_payment_charge_id="tg_charge_recent",
            stars_amount=100,
            nominal_usd_amount=Decimal("1.3000"),
            credited_usd_amount=Decimal("0.6500"),
            commission_k1=Decimal("0.3500"),
            commission_k2=Decimal("0.1500"),
            commission_k3=Decimal("0.0000"),
            status=PaymentStatus.COMPLETED,
            invoice_payload="topup_123456789_1234567890_100",
        )

        pg_session.add(payment)
        await pg_session.flush()
        await pg_session.refresh(payment)

        # Just created - should be refundable
        assert payment.can_refund(refund_period_days=30) is True

    async def test_payment_can_refund_outside_period(self, pg_session,
                                                     pg_sample_user):
        """Test can_refund() returns False outside refund period."""
        payment = Payment(
            user_id=pg_sample_user.id,
            telegram_payment_charge_id="tg_charge_old",
            stars_amount=100,
            nominal_usd_amount=Decimal("1.3000"),
            credited_usd_amount=Decimal("0.6500"),
            commission_k1=Decimal("0.3500"),
            commission_k2=Decimal("0.1500"),
            commission_k3=Decimal("0.0000"),
            status=PaymentStatus.COMPLETED,
            invoice_payload="topup_123456789_1234567890_100",
        )

        pg_session.add(payment)
        await pg_session.flush()
        await pg_session.refresh(payment)

        # Manually set created_at to 31 days ago
        payment.created_at = datetime.now() - timedelta(days=31)
        await pg_session.flush()
        await pg_session.refresh(payment)

        # Should not be refundable (> 30 days)
        assert payment.can_refund(refund_period_days=30) is False

    async def test_payment_already_refunded(self, pg_session, pg_sample_user):
        """Test can_refund() returns False for already refunded payments."""
        payment = Payment(
            user_id=pg_sample_user.id,
            telegram_payment_charge_id="tg_charge_refunded",
            stars_amount=100,
            nominal_usd_amount=Decimal("1.3000"),
            credited_usd_amount=Decimal("0.6500"),
            commission_k1=Decimal("0.3500"),
            commission_k2=Decimal("0.1500"),
            commission_k3=Decimal("0.0000"),
            status=PaymentStatus.REFUNDED,
            refunded_at=datetime.now(),
            invoice_payload="topup_123456789_1234567890_100",
        )

        pg_session.add(payment)
        await pg_session.flush()
        await pg_session.refresh(payment)

        # Already refunded - should not be refundable
        assert payment.can_refund(refund_period_days=30) is False

    async def test_payment_total_commission_constraint(self, pg_session,
                                                       pg_sample_user):
        """Test that k1 + k2 + k3 <= 1.0001."""
        # Valid: total = 0.9999 (very high but still leaves small amount)
        payment = Payment(
            user_id=pg_sample_user.id,
            telegram_payment_charge_id="tg_charge_max_commission",
            stars_amount=100,
            nominal_usd_amount=Decimal("1.3000"),
            credited_usd_amount=Decimal(
                "0.0001"),  # 1.3 * (1 - 0.9999) = 0.00013 ~ 0.0001
            commission_k1=Decimal("0.5000"),
            commission_k2=Decimal("0.3000"),
            commission_k3=Decimal("0.1999"),  # Total = 0.9999
            status=PaymentStatus.COMPLETED,
            invoice_payload="topup_123456789_1234567890_100",
        )

        pg_session.add(payment)
        await pg_session.flush()

        assert payment.id is not None

    async def test_payment_cascade_delete(self, pg_session, pg_sample_user):
        """Test that payment is deleted when user is deleted (CASCADE)."""
        payment = Payment(
            user_id=pg_sample_user.id,
            telegram_payment_charge_id="tg_charge_cascade",
            stars_amount=100,
            nominal_usd_amount=Decimal("1.3000"),
            credited_usd_amount=Decimal("0.6500"),
            commission_k1=Decimal("0.3500"),
            commission_k2=Decimal("0.1500"),
            commission_k3=Decimal("0.0000"),
            status=PaymentStatus.COMPLETED,
            invoice_payload="topup_123456789_1234567890_100",
        )

        pg_session.add(payment)
        await pg_session.flush()
        payment_id = payment.id

        # Delete user
        await pg_session.delete(pg_sample_user)
        await pg_session.flush()

        # Payment should be deleted
        result = await pg_session.execute(
            select(Payment).where(Payment.id == payment_id))
        assert result.scalar_one_or_none() is None
