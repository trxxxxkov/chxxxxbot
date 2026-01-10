"""Tests for PaymentRepository.

Phase 2.1: Payment system tests for PaymentRepository CRUD operations.
"""

from datetime import datetime
from datetime import timedelta
from datetime import timezone
from decimal import Decimal

from db.models.balance_operation import \
    BalanceOperation  # noqa: F401 - needed for SQLAlchemy relationships
from db.models.payment import Payment
from db.models.payment import PaymentStatus
from db.models.user import \
    User  # noqa: F401 - needed for SQLAlchemy relationships
from db.repositories.payment_repository import PaymentRepository
import pytest


@pytest.mark.asyncio
class TestPaymentRepository:
    """Test PaymentRepository methods."""

    @pytest.fixture
    async def payment_repo(self, pg_session):
        """Create PaymentRepository instance."""
        return PaymentRepository(pg_session)

    @pytest.fixture
    async def sample_payment(self, pg_session, pg_sample_user):
        """Create sample payment for testing."""
        payment = Payment(
            user_id=pg_sample_user.id,
            telegram_payment_charge_id="tg_charge_sample",
            stars_amount=100,
            nominal_usd_amount=Decimal("1.3000"),
            credited_usd_amount=Decimal("0.6500"),
            commission_k1=Decimal("0.3500"),
            commission_k2=Decimal("0.1500"),
            commission_k3=Decimal("0.0000"),
            status=PaymentStatus.COMPLETED,
            invoice_payload="topup_123_1234567890_100",
        )

        pg_session.add(payment)
        await pg_session.flush()
        await pg_session.refresh(payment)
        return payment

    async def test_create_payment(self, payment_repo, pg_sample_user):
        """Test creating a payment via repository."""
        payment = Payment(
            user_id=pg_sample_user.id,
            telegram_payment_charge_id="tg_charge_create",
            stars_amount=50,
            nominal_usd_amount=Decimal("0.6500"),
            credited_usd_amount=Decimal("0.3250"),
            commission_k1=Decimal("0.3500"),
            commission_k2=Decimal("0.1500"),
            commission_k3=Decimal("0.0000"),
            status=PaymentStatus.COMPLETED,
            invoice_payload="topup_123_1234567890_50",
        )
        payment = await payment_repo.create(payment)

        assert payment.id is not None
        assert payment.user_id == pg_sample_user.id
        assert payment.stars_amount == 50
        assert payment.status == PaymentStatus.COMPLETED

    async def test_get_by_id(self, payment_repo, sample_payment):
        """Test retrieving payment by ID."""
        payment = await payment_repo.get_by_id(sample_payment.id)

        assert payment is not None
        assert payment.id == sample_payment.id
        assert payment.telegram_payment_charge_id == "tg_charge_sample"

    async def test_get_by_id_not_found(self, payment_repo):
        """Test get_by_id returns None for non-existent payment."""
        payment = await payment_repo.get_by_id(999999)

        assert payment is None

    async def test_get_by_charge_id(self, payment_repo, sample_payment):
        """Test retrieving payment by telegram_payment_charge_id."""
        payment = await payment_repo.get_by_charge_id("tg_charge_sample")

        assert payment is not None
        assert payment.id == sample_payment.id
        assert payment.telegram_payment_charge_id == "tg_charge_sample"

    async def test_get_by_charge_id_not_found(self, payment_repo):
        """Test get_by_charge_id returns None for non-existent charge ID."""
        payment = await payment_repo.get_by_charge_id("non_existent_charge")

        assert payment is None

    async def test_get_user_payments(self, payment_repo, pg_session,
                                     pg_sample_user):
        """Test retrieving all payments for a user."""
        # Create multiple payments
        for i in range(3):
            payment = Payment(
                user_id=pg_sample_user.id,
                telegram_payment_charge_id=f"tg_charge_user_{i}",
                stars_amount=100,
                nominal_usd_amount=Decimal("1.3000"),
                credited_usd_amount=Decimal("0.6500"),
                commission_k1=Decimal("0.3500"),
                commission_k2=Decimal("0.1500"),
                commission_k3=Decimal("0.0000"),
                status=PaymentStatus.COMPLETED,
                invoice_payload=f"topup_123_{i}_100",
            )
            pg_session.add(payment)

        await pg_session.flush()

        # Get user payments
        payments = await payment_repo.get_user_payments(pg_sample_user.id,
                                                        limit=10)

        assert len(payments) == 3
        # Should be ordered by created_at DESC (newest first)
        assert payments[0].created_at >= payments[1].created_at
        assert payments[1].created_at >= payments[2].created_at

    async def test_get_user_payments_limit(self, payment_repo, pg_session,
                                           pg_sample_user):
        """Test get_user_payments respects limit parameter."""
        # Create 5 payments
        for i in range(5):
            payment = Payment(
                user_id=pg_sample_user.id,
                telegram_payment_charge_id=f"tg_charge_limit_{i}",
                stars_amount=100,
                nominal_usd_amount=Decimal("1.3000"),
                credited_usd_amount=Decimal("0.6500"),
                commission_k1=Decimal("0.3500"),
                commission_k2=Decimal("0.1500"),
                commission_k3=Decimal("0.0000"),
                status=PaymentStatus.COMPLETED,
                invoice_payload=f"topup_123_{i}_100",
            )
            pg_session.add(payment)

        await pg_session.flush()

        # Get only 3 payments
        payments = await payment_repo.get_user_payments(pg_sample_user.id,
                                                        limit=3)

        assert len(payments) == 3

    async def test_get_refundable_payments(self, payment_repo, pg_session,
                                           pg_sample_user):
        """Test retrieving only refundable payments (completed, not expired)."""
        # Create completed payment (refundable)
        payment1 = Payment(
            user_id=pg_sample_user.id,
            telegram_payment_charge_id="tg_charge_refundable",
            stars_amount=100,
            nominal_usd_amount=Decimal("1.3000"),
            credited_usd_amount=Decimal("0.6500"),
            commission_k1=Decimal("0.3500"),
            commission_k2=Decimal("0.1500"),
            commission_k3=Decimal("0.0000"),
            status=PaymentStatus.COMPLETED,
            invoice_payload="topup_123_1_100",
        )
        pg_session.add(payment1)

        # Create refunded payment (not refundable)
        payment2 = Payment(
            user_id=pg_sample_user.id,
            telegram_payment_charge_id="tg_charge_already_refunded",
            stars_amount=50,
            nominal_usd_amount=Decimal("0.6500"),
            credited_usd_amount=Decimal("0.3250"),
            commission_k1=Decimal("0.3500"),
            commission_k2=Decimal("0.1500"),
            commission_k3=Decimal("0.0000"),
            status=PaymentStatus.REFUNDED,
            refunded_at=datetime.now(timezone.utc),
            invoice_payload="topup_123_2_50",
        )
        pg_session.add(payment2)

        # Create old payment (not refundable - expired)
        payment3 = Payment(
            user_id=pg_sample_user.id,
            telegram_payment_charge_id="tg_charge_old",
            stars_amount=100,
            nominal_usd_amount=Decimal("1.3000"),
            credited_usd_amount=Decimal("0.6500"),
            commission_k1=Decimal("0.3500"),
            commission_k2=Decimal("0.1500"),
            commission_k3=Decimal("0.0000"),
            status=PaymentStatus.COMPLETED,
            invoice_payload="topup_123_3_100",
        )
        pg_session.add(payment3)
        await pg_session.flush()

        # Make payment3 old (31 days ago)
        payment3.created_at = datetime.now(timezone.utc) - timedelta(days=31)
        await pg_session.flush()

        # Get refundable payments (30 days window by default)
        refundable = await payment_repo.get_refundable_payments(
            pg_sample_user.id)

        # Only payment1 should be refundable
        assert len(refundable) == 1
        assert refundable[
            0].telegram_payment_charge_id == "tg_charge_refundable"

    async def test_update_payment_status(self, payment_repo, sample_payment):
        """Test updating payment status."""
        # Initially completed
        assert sample_payment.status == PaymentStatus.COMPLETED
        assert sample_payment.refunded_at is None

        # Update to refunded
        sample_payment.status = PaymentStatus.REFUNDED
        sample_payment.refunded_at = datetime.now(timezone.utc)

        updated = await payment_repo.update(sample_payment)

        assert updated.status == PaymentStatus.REFUNDED
        assert updated.refunded_at is not None

    async def test_delete_payment(self, payment_repo, sample_payment):
        """Test deleting a payment."""
        payment_id = sample_payment.id

        # Delete payment
        await payment_repo.delete(sample_payment)

        # Verify deleted
        deleted_payment = await payment_repo.get_by_id(payment_id)
        assert deleted_payment is None

    async def test_get_user_payments_empty(self, payment_repo):
        """Test get_user_payments returns empty list for user with no payments."""
        payments = await payment_repo.get_user_payments(999999999, limit=10)

        assert payments == []

    async def test_get_refundable_payments_empty(self, payment_repo):
        """Test get_refundable_payments returns empty list when none available."""
        refundable = await payment_repo.get_refundable_payments(999999999)

        assert refundable == []
