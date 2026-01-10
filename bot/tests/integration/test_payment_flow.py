"""Payment flow integration tests (Phase 2.1 Stage 9).

This module contains end-to-end integration tests for the payment system,
testing the complete workflow from payment creation through balance updates
and refunds.

NO __init__.py - use direct import:
    pytest tests/integration/test_payment_flow.py
"""

from datetime import datetime
from datetime import timedelta
from datetime import timezone
from decimal import Decimal

from config import DEFAULT_OWNER_MARGIN
from config import REFUND_PERIOD_DAYS
from db.models.balance_operation import OperationType
from db.models.payment import PaymentStatus
from db.repositories.balance_operation_repository import \
    BalanceOperationRepository
from db.repositories.payment_repository import PaymentRepository
from db.repositories.user_repository import UserRepository
import pytest
from services.balance_service import BalanceService
from services.payment_service import PaymentService


@pytest.mark.asyncio
class TestFullPaymentFlow:
    """Test complete payment flow end-to-end."""

    async def test_successful_payment_processing(self, integration_session,
                                                 integration_sample_user):
        """Test process_successful_payment creates payment and credits balance.

        Args:
            integration_session: Integration session fixture.
            integration_sample_user: Sample user fixture.
        """
        # Setup
        user_repo = UserRepository(integration_session)
        payment_repo = PaymentRepository(integration_session)
        balance_op_repo = BalanceOperationRepository(integration_session)
        payment_service = PaymentService(integration_session, user_repo,
                                         payment_repo, balance_op_repo)

        # Initial balance
        user = await user_repo.get_by_id(integration_sample_user.id)
        initial_balance = user.balance

        # Process successful payment (100 Stars)
        payment = await payment_service.process_successful_payment(
            user_id=integration_sample_user.id,
            telegram_payment_charge_id="tg_charge_test_123",
            stars_amount=100,
            invoice_payload="topup_test",
            owner_margin=DEFAULT_OWNER_MARGIN,
        )

        # Verify payment created
        assert payment.user_id == integration_sample_user.id
        assert payment.stars_amount == 100
        assert payment.status == PaymentStatus.COMPLETED
        assert payment.telegram_payment_charge_id == "tg_charge_test_123"

        # Verify balance increased
        user = await user_repo.get_by_id(integration_sample_user.id)
        assert user.balance > initial_balance
        assert payment.credited_usd_amount > 0

        # Verify balance operation logged
        operations = await balance_op_repo.get_user_operations(
            integration_sample_user.id, limit=10)
        deposit_op = next((op for op in operations
                           if op.operation_type == OperationType.PAYMENT), None)
        assert deposit_op is not None
        assert deposit_op.related_payment_id == payment.id

    async def test_duplicate_payment_rejected(self, integration_session,
                                              integration_sample_user):
        """Test that duplicate payment charge_id is rejected.

        Args:
            integration_session: Integration session fixture.
            integration_sample_user: Sample user fixture.
        """
        # Setup
        user_repo = UserRepository(integration_session)
        payment_repo = PaymentRepository(integration_session)
        balance_op_repo = BalanceOperationRepository(integration_session)
        payment_service = PaymentService(integration_session, user_repo,
                                         payment_repo, balance_op_repo)

        charge_id = "tg_charge_duplicate_test"

        # First payment - should succeed
        payment1 = await payment_service.process_successful_payment(
            user_id=integration_sample_user.id,
            telegram_payment_charge_id=charge_id,
            stars_amount=100,
            invoice_payload="topup_1",
        )

        assert payment1.status == PaymentStatus.COMPLETED

        # Second payment with same charge_id - should fail
        with pytest.raises(ValueError, match="already processed"):
            await payment_service.process_successful_payment(
                user_id=integration_sample_user.id,
                telegram_payment_charge_id=charge_id,  # Duplicate!
                stars_amount=100,
                invoice_payload="topup_2",
            )

    async def test_refund_success(self, integration_session,
                                  integration_sample_user):
        """Test successful refund flow.

        Args:
            integration_session: Integration session fixture.
            integration_sample_user: Sample user fixture.
        """
        # Setup
        user_repo = UserRepository(integration_session)
        payment_repo = PaymentRepository(integration_session)
        balance_op_repo = BalanceOperationRepository(integration_session)
        payment_service = PaymentService(integration_session, user_repo,
                                         payment_repo, balance_op_repo)

        # Create payment first
        charge_id = "tg_charge_refund_test"
        payment = await payment_service.process_successful_payment(
            user_id=integration_sample_user.id,
            telegram_payment_charge_id=charge_id,
            stars_amount=100,
            invoice_payload="topup_refund",
        )

        user = await user_repo.get_by_id(integration_sample_user.id)
        balance_before_refund = user.balance
        credited_amount = payment.credited_usd_amount

        # Process refund
        refunded_payment = await payment_service.process_refund(
            user_id=integration_sample_user.id,
            telegram_payment_charge_id=charge_id,
        )

        # Verify payment marked as refunded
        assert refunded_payment.status == PaymentStatus.REFUNDED
        assert refunded_payment.refunded_at is not None

        # Verify balance decreased
        user = await user_repo.get_by_id(integration_sample_user.id)
        assert user.balance == balance_before_refund - credited_amount

        # Verify refund operation logged
        operations = await balance_op_repo.get_user_operations(
            integration_sample_user.id, limit=10)
        refund_op = next((op for op in operations
                          if op.operation_type == OperationType.REFUND), None)
        assert refund_op is not None
        # REFUND operations store negative amounts (balance decrease)
        assert refund_op.amount == -credited_amount

    async def test_refund_expired(self, integration_session,
                                  integration_sample_user):
        """Test refund rejection after refund period expires.

        Args:
            integration_session: Integration session fixture.
            integration_sample_user: Sample user fixture.
        """
        from unittest.mock import patch

        # Setup
        user_repo = UserRepository(integration_session)
        payment_repo = PaymentRepository(integration_session)
        balance_op_repo = BalanceOperationRepository(integration_session)
        payment_service = PaymentService(integration_session, user_repo,
                                         payment_repo, balance_op_repo)

        # Create payment
        charge_id = "tg_charge_old"
        payment = await payment_service.process_successful_payment(
            user_id=integration_sample_user.id,
            telegram_payment_charge_id=charge_id,
            stars_amount=100,
            invoice_payload="topup_old",
        )

        # Mock datetime.now() to simulate time passing (32 days later)
        # Ensure timezone-aware datetime
        created_at = payment.created_at
        if created_at.tzinfo is None:
            created_at = created_at.replace(tzinfo=timezone.utc)
        future_time = created_at + timedelta(days=REFUND_PERIOD_DAYS + 2)

        with patch('db.models.payment.datetime') as mock_datetime:
            mock_datetime.now.return_value = future_time
            mock_datetime.side_effect = datetime

            # Try to refund - should fail
            with pytest.raises(ValueError, match="refund period expired"):
                await payment_service.process_refund(
                    user_id=integration_sample_user.id,
                    telegram_payment_charge_id=charge_id,
                )

    async def test_refund_insufficient_balance(self, integration_session,
                                               integration_sample_user):
        """Test refund rejection when user has insufficient balance.

        Args:
            integration_session: Integration session fixture.
            integration_sample_user: Sample user fixture.
        """
        # Setup
        user_repo = UserRepository(integration_session)
        payment_repo = PaymentRepository(integration_session)
        balance_op_repo = BalanceOperationRepository(integration_session)
        payment_service = PaymentService(integration_session, user_repo,
                                         payment_repo, balance_op_repo)
        balance_service = BalanceService(integration_session, user_repo,
                                         balance_op_repo)

        # Create payment
        charge_id = "tg_charge_insufficient"
        payment = await payment_service.process_successful_payment(
            user_id=integration_sample_user.id,
            telegram_payment_charge_id=charge_id,
            stars_amount=100,
            invoice_payload="topup_insufficient",
        )

        # Spend all balance
        user = await user_repo.get_by_id(integration_sample_user.id)
        await balance_service.charge_user(
            user_id=user.id,
            amount=user.balance,
            description="API usage",
        )

        # Try to refund - should fail (insufficient balance)
        with pytest.raises(ValueError, match="Insufficient balance"):
            await payment_service.process_refund(
                user_id=integration_sample_user.id,
                telegram_payment_charge_id=charge_id,
            )


@pytest.mark.asyncio
class TestBalanceOperations:
    """Test balance operations and charging."""

    async def test_charge_user_creates_operation(self, integration_session,
                                                 integration_sample_user):
        """Test that charging user creates balance operation.

        Args:
            integration_session: Integration session fixture.
            integration_sample_user: Sample user fixture.
        """
        # Setup
        user_repo = UserRepository(integration_session)
        balance_op_repo = BalanceOperationRepository(integration_session)
        balance_service = BalanceService(integration_session, user_repo,
                                         balance_op_repo)

        initial_balance = (await user_repo.get_by_id(integration_sample_user.id
                                                    )).balance

        # Charge user
        await balance_service.charge_user(
            user_id=integration_sample_user.id,
            amount=Decimal("0.05"),
            description="API call",
        )

        # Verify balance decreased
        user = await user_repo.get_by_id(integration_sample_user.id)
        assert user.balance == initial_balance - Decimal("0.05")

        # Verify operation logged
        operations = await balance_op_repo.get_user_operations(
            integration_sample_user.id, limit=10)
        charge_op = next((op for op in operations
                          if op.operation_type == OperationType.USAGE), None)
        assert charge_op is not None
        # USAGE operations store negative amounts
        assert charge_op.amount == Decimal("-0.05")
        assert charge_op.description == "API call"

    async def test_negative_balance_allowed(self, integration_session,
                                            integration_sample_user):
        """Test that balance can go negative (soft check).

        Args:
            integration_session: Integration session fixture.
            integration_sample_user: Sample user fixture.
        """
        # Setup
        user_repo = UserRepository(integration_session)
        balance_op_repo = BalanceOperationRepository(integration_session)
        balance_service = BalanceService(integration_session, user_repo,
                                         balance_op_repo)

        # Spend most of balance
        await balance_service.charge_user(
            user_id=integration_sample_user.id,
            amount=Decimal("0.09"),
            description="API call 1",
        )

        user = await user_repo.get_by_id(integration_sample_user.id)
        assert user.balance == Decimal("0.01")

        # Charge more than balance (should allow going negative)
        await balance_service.charge_user(
            user_id=integration_sample_user.id,
            amount=Decimal("0.05"),
            description="Expensive API call",
        )

        # Balance should be negative
        user = await user_repo.get_by_id(integration_sample_user.id)
        assert user.balance == Decimal("-0.04")


@pytest.mark.asyncio
class TestCommissionCalculation:
    """Test commission calculation."""

    async def test_commission_with_default_margin(self, integration_session,
                                                  integration_sample_user):
        """Test commission calculation with default margin.

        Args:
            integration_session: Integration session fixture.
            integration_sample_user: Sample user fixture.
        """
        # Setup
        user_repo = UserRepository(integration_session)
        payment_repo = PaymentRepository(integration_session)
        balance_op_repo = BalanceOperationRepository(integration_session)
        payment_service = PaymentService(integration_session, user_repo,
                                         payment_repo, balance_op_repo)

        # Process payment with default margin
        payment = await payment_service.process_successful_payment(
            user_id=integration_sample_user.id,
            telegram_payment_charge_id="tg_charge_margin_test",
            stars_amount=100,
            invoice_payload="topup_margin",
            owner_margin=DEFAULT_OWNER_MARGIN,  # 0.0 by default
        )

        # Verify credited amount
        # 100 Stars * $0.013 = $1.30 nominal
        # With k3=0.0: $1.30 * (1 - 0.35 - 0.15 - 0.0) = $1.30 * 0.50 = $0.65
        assert payment.nominal_usd_amount == Decimal("1.30")
        assert payment.credited_usd_amount == Decimal("0.65")

    async def test_commission_with_custom_margin(self, integration_session,
                                                 integration_sample_user):
        """Test commission calculation with custom margin.

        Args:
            integration_session: Integration session fixture.
            integration_sample_user: Sample user fixture.
        """
        # Setup
        user_repo = UserRepository(integration_session)
        payment_repo = PaymentRepository(integration_session)
        balance_op_repo = BalanceOperationRepository(integration_session)
        payment_service = PaymentService(integration_session, user_repo,
                                         payment_repo, balance_op_repo)

        # Process payment with 10% margin (k3=0.10)
        payment = await payment_service.process_successful_payment(
            user_id=integration_sample_user.id,
            telegram_payment_charge_id="tg_charge_custom_margin",
            stars_amount=100,
            invoice_payload="topup_custom",
            owner_margin=0.10,  # 10% custom margin
        )

        # Verify credited amount
        # 100 Stars * $0.013 = $1.30 nominal
        # With k3=0.10: $1.30 * (1 - 0.35 - 0.15 - 0.10) = $1.30 * 0.40 = $0.52
        assert payment.nominal_usd_amount == Decimal("1.30")
        assert payment.credited_usd_amount == Decimal("0.52")
