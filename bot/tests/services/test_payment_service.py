"""Tests for PaymentService.

Phase 2.1: Payment system tests for PaymentService business logic.
"""

from decimal import Decimal
from unittest.mock import AsyncMock
from unittest.mock import MagicMock
from unittest.mock import patch

from db.models.balance_operation import BalanceOperation
from db.models.balance_operation import OperationType
from db.models.payment import Payment
from db.models.payment import PaymentStatus
from db.models.user import \
    User  # noqa: F401 - needed for SQLAlchemy relationships
from db.repositories.balance_operation_repository import \
    BalanceOperationRepository
from db.repositories.payment_repository import PaymentRepository
from db.repositories.user_repository import UserRepository
import pytest
from services.payment_service import PaymentService


class TestPaymentService:
    """Test PaymentService business logic."""

    @pytest.fixture
    async def payment_service(self, pg_session):
        """Create PaymentService instance with real repositories."""
        user_repo = UserRepository(pg_session)
        payment_repo = PaymentRepository(pg_session)
        balance_op_repo = BalanceOperationRepository(pg_session)
        return PaymentService(pg_session, user_repo, payment_repo,
                              balance_op_repo)

    def test_calculate_usd_amount_default_margin(self):
        """Test USD amount calculation with default owner margin (k3=0)."""
        service = PaymentService(None, None, None, None)

        # 100 Stars × $0.013 = $1.30 (nominal)
        # Commissions: k1=0.35, k2=0.15, k3=0.0 → total 0.5
        # Credited: $1.30 × (1 - 0.5) = $0.65
        nominal_usd, credited_usd, k1, k2, k3 = service.calculate_usd_amount(
            stars_amount=100, owner_margin=0.0)

        assert nominal_usd == Decimal("1.3000")
        assert credited_usd == Decimal("0.6500")
        assert k1 == Decimal("0.3500")
        assert k2 == Decimal("0.1500")
        assert k3 == Decimal("0.0000")

    def test_calculate_usd_amount_with_margin(self):
        """Test USD amount calculation with custom owner margin."""
        service = PaymentService(None, None, None, None)

        # 100 Stars × $0.013 = $1.30 (nominal)
        # Commissions: k1=0.35, k2=0.15, k3=0.1 → total 0.6
        # Credited: $1.30 × (1 - 0.6) = $0.52
        nominal_usd, credited_usd, k1, k2, k3 = service.calculate_usd_amount(
            stars_amount=100, owner_margin=0.1)

        assert nominal_usd == Decimal("1.3000")
        assert credited_usd == Decimal("0.5200")
        assert k3 == Decimal("0.1000")

    def test_calculate_usd_amount_small_stars(self):
        """Test calculation with small Stars amount."""
        service = PaymentService(None, None, None, None)

        # 10 Stars × $0.013 = $0.13 (nominal)
        # Commissions: total 0.5 (k1+k2)
        # Credited: $0.13 × 0.5 = $0.065
        nominal_usd, credited_usd, k1, k2, k3 = service.calculate_usd_amount(
            stars_amount=10, owner_margin=0.0)

        assert nominal_usd == Decimal("0.1300")
        assert credited_usd == Decimal("0.0650")

    def test_calculate_usd_amount_large_stars(self):
        """Test calculation with large Stars amount."""
        service = PaymentService(None, None, None, None)

        # 2500 Stars × $0.013 = $32.50 (nominal)
        # Commissions: total 0.5
        # Credited: $32.50 × 0.5 = $16.25
        nominal_usd, credited_usd, k1, k2, k3 = service.calculate_usd_amount(
            stars_amount=2500, owner_margin=0.0)

        assert nominal_usd == Decimal("32.5000")
        assert credited_usd == Decimal("16.2500")

    def test_calculate_usd_amount_precision(self):
        """Test calculation maintains 4 decimal places precision."""
        service = PaymentService(None, None, None, None)

        nominal_usd, credited_usd, k1, k2, k3 = service.calculate_usd_amount(
            stars_amount=123, owner_margin=0.05)

        # All amounts should have 4 decimal places
        assert nominal_usd.as_tuple().exponent == -4
        assert credited_usd.as_tuple().exponent == -4

    @pytest.mark.asyncio
    async def test_send_invoice(self, payment_service, pg_sample_user):
        """Test sending invoice via Telegram Bot API."""
        mock_bot = AsyncMock()
        mock_bot.send_invoice = AsyncMock()

        await payment_service.send_invoice(
            bot=mock_bot,
            user_id=pg_sample_user.id,
            stars_amount=100,
            owner_margin=0.0,
        )

        # Verify send_invoice was called
        mock_bot.send_invoice.assert_called_once()
        call_kwargs = mock_bot.send_invoice.call_args.kwargs

        # Check invoice parameters
        assert call_kwargs["chat_id"] == pg_sample_user.id
        assert call_kwargs["title"] == "Bot Balance Top-up"
        assert call_kwargs["prices"][0].amount == 100  # Stars amount
        assert call_kwargs["currency"] == "XTR"
        assert "topup_" in call_kwargs["payload"]

    @pytest.mark.asyncio
    async def test_process_successful_payment(self, payment_service, pg_session,
                                              pg_sample_user):
        """Test processing successful payment (create Payment + BalanceOperation)."""
        # Initial balance
        pg_sample_user.balance = Decimal("0.1000")
        await pg_session.flush()

        # Process payment
        payment = await payment_service.process_successful_payment(
            user_id=pg_sample_user.id,
            telegram_payment_charge_id="tg_charge_success",
            stars_amount=100,
            owner_margin=0.0,
            invoice_payload="topup_123_1234567890_100",
        )

        # Verify payment created
        assert payment.id is not None
        assert payment.stars_amount == 100
        assert payment.status == PaymentStatus.COMPLETED
        assert payment.credited_usd_amount == Decimal("0.6500")

        # Verify user balance updated
        await pg_session.refresh(pg_sample_user)
        assert pg_sample_user.balance == Decimal("0.7500")  # 0.1 + 0.65

        # Verify balance operation created
        from sqlalchemy import select
        result = await pg_session.execute(
            select(BalanceOperation).where(
                BalanceOperation.user_id == pg_sample_user.id,
                BalanceOperation.operation_type == OperationType.PAYMENT,
            ))
        operation = result.scalar_one()

        assert operation.amount == Decimal("0.6500")
        assert operation.balance_before == Decimal("0.1000")
        assert operation.balance_after == Decimal("0.7500")
        assert operation.related_payment_id == payment.id

    @pytest.mark.asyncio
    async def test_process_refund(self, payment_service, pg_session,
                                  pg_sample_user):
        """Test processing refund (update Payment, create BalanceOperation)."""
        # Create initial payment
        payment = await payment_service.process_successful_payment(
            user_id=pg_sample_user.id,
            telegram_payment_charge_id="tg_charge_refund_test",
            stars_amount=100,
            owner_margin=0.0,
            invoice_payload="topup_123_1234567890_100",
        )

        await pg_session.refresh(pg_sample_user)
        balance_before_refund = pg_sample_user.balance  # Should be 0.75

        # Process refund
        refunded_payment = await payment_service.process_refund(
            user_id=pg_sample_user.id,
            telegram_payment_charge_id="tg_charge_refund_test",
        )

        # Verify payment updated
        assert refunded_payment.status == PaymentStatus.REFUNDED
        assert refunded_payment.refunded_at is not None

        # Verify user balance decreased
        await pg_session.refresh(pg_sample_user)
        assert pg_sample_user.balance == Decimal("0.1000")  # 0.75 - 0.65

        # Verify refund operation created
        from sqlalchemy import select
        result = await pg_session.execute(
            select(BalanceOperation).where(
                BalanceOperation.user_id == pg_sample_user.id,
                BalanceOperation.operation_type == OperationType.REFUND,
            ).order_by(BalanceOperation.created_at.desc()))
        operation = result.scalars().first()

        assert operation.amount == Decimal("-0.6500")
        assert operation.balance_before == balance_before_refund
        assert operation.related_payment_id == payment.id

    @pytest.mark.asyncio
    async def test_process_refund_payment_not_found(self, payment_service,
                                                    pg_sample_user):
        """Test refund fails when payment not found."""
        with pytest.raises(ValueError, match="Payment .* not found"):
            await payment_service.process_refund(
                user_id=pg_sample_user.id,
                telegram_payment_charge_id="non_existent_charge",
            )

    @pytest.mark.asyncio
    async def test_process_refund_already_refunded(self, payment_service,
                                                   pg_session, pg_sample_user):
        """Test refund fails for already refunded payment."""
        # Create and refund payment
        payment = await payment_service.process_successful_payment(
            user_id=pg_sample_user.id,
            telegram_payment_charge_id="tg_charge_double_refund",
            stars_amount=100,
            owner_margin=0.0,
            invoice_payload="topup_123_1234567890_100",
        )

        await payment_service.process_refund(
            user_id=pg_sample_user.id,
            telegram_payment_charge_id="tg_charge_double_refund",
        )

        # Try to refund again
        with pytest.raises(ValueError, match="status refunded"):
            await payment_service.process_refund(
                user_id=pg_sample_user.id,
                telegram_payment_charge_id="tg_charge_double_refund",
            )

    @pytest.mark.asyncio
    async def test_process_refund_insufficient_balance(self, payment_service,
                                                       pg_session,
                                                       pg_sample_user):
        """Test refund fails when user has insufficient balance."""
        # Create payment (balance becomes 0.75)
        payment = await payment_service.process_successful_payment(
            user_id=pg_sample_user.id,
            telegram_payment_charge_id="tg_charge_insufficient",
            stars_amount=100,
            owner_margin=0.0,
            invoice_payload="topup_123_1234567890_100",
        )

        # Spend most of the balance
        pg_sample_user.balance = Decimal("0.1000")  # Less than credited amount
        await pg_session.flush()

        # Try to refund (requires 0.65, but only has 0.1)
        with pytest.raises(ValueError, match="Insufficient balance"):
            await payment_service.process_refund(
                user_id=pg_sample_user.id,
                telegram_payment_charge_id="tg_charge_insufficient",
            )

    @pytest.mark.asyncio
    async def test_commission_formula_integrity(self):
        """Test that commission formula y = x * (1 - k1 - k2 - k3) is correct."""
        service = PaymentService(None, None, None, None)

        # Test with various combinations
        test_cases = [
            (100, 0.0, Decimal("0.6500")),  # k3=0: 1.3 * 0.5 = 0.65
            (100, 0.1, Decimal("0.5200")),  # k3=0.1: 1.3 * 0.4 = 0.52
            (50, 0.0, Decimal("0.3250")),  # 50 stars: 0.65 * 0.5 = 0.325
            (
                10,
                0.0,
                Decimal("0.0650"),
            ),  # 10 stars (minimum): 0.13 * 0.5 = 0.065
        ]

        for stars, margin, expected_credited in test_cases:
            nominal_usd, credited_usd, k1, k2, k3 = service.calculate_usd_amount(
                stars, margin)
            assert credited_usd == expected_credited, (
                f"Failed for {stars} stars, margin={margin}: "
                f"expected {expected_credited}, got {credited_usd}")

    @pytest.mark.asyncio
    async def test_payment_creates_audit_trail(self, payment_service,
                                               pg_session, pg_sample_user):
        """Test that payment creates complete audit trail."""
        await payment_service.process_successful_payment(
            user_id=pg_sample_user.id,
            telegram_payment_charge_id="tg_charge_audit",
            stars_amount=100,
            owner_margin=0.0,
            invoice_payload="topup_123_1234567890_100",
        )

        # Check Payment record
        from sqlalchemy import select
        payment_result = await pg_session.execute(
            select(Payment).where(
                Payment.telegram_payment_charge_id == "tg_charge_audit"))
        payment = payment_result.scalar_one()
        assert payment is not None

        # Check BalanceOperation record
        operation_result = await pg_session.execute(
            select(BalanceOperation).where(
                BalanceOperation.related_payment_id == payment.id))
        operation = operation_result.scalar_one()
        assert operation is not None
        assert operation.verify_balance_consistency() is True
