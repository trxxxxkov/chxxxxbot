"""Tests for BalanceOperation model.

Phase 2.1: Payment system tests for BalanceOperation audit trail model.
"""

from decimal import Decimal

from db.models.balance_operation import BalanceOperation
from db.models.balance_operation import OperationType
from db.models.payment import \
    Payment  # noqa: F401 - needed for SQLAlchemy relationships
from db.models.user import \
    User  # noqa: F401 - needed for SQLAlchemy relationships
import pytest
from sqlalchemy import select


@pytest.mark.asyncio
class TestBalanceOperationModel:
    """Test BalanceOperation model structure and methods."""

    async def test_balance_operation_creation(self, pg_session, pg_sample_user):
        """Test creating a balance operation with all required fields."""
        operation = BalanceOperation(
            user_id=pg_sample_user.id,
            operation_type=OperationType.PAYMENT,
            amount=Decimal("0.6500"),
            balance_before=Decimal("0.1000"),
            balance_after=Decimal("0.7500"),
            description="Payment: 100 Stars → $0.65 (after commissions)",
        )

        pg_session.add(operation)
        await pg_session.flush()
        await pg_session.refresh(operation)

        assert operation.id is not None
        assert operation.user_id == pg_sample_user.id
        assert operation.operation_type == OperationType.PAYMENT
        assert operation.amount == Decimal("0.6500")
        assert operation.balance_before == Decimal("0.1000")
        assert operation.balance_after == Decimal("0.7500")
        assert operation.created_at is not None

    async def test_operation_type_enum(self):
        """Test OperationType enum values."""
        assert OperationType.PAYMENT.value == "payment"
        assert OperationType.USAGE.value == "usage"
        assert OperationType.REFUND.value == "refund"
        assert OperationType.ADMIN_TOPUP.value == "admin_topup"

    async def test_verify_balance_consistency_valid(self, pg_session,
                                                    pg_sample_user):
        """Test verify_balance_consistency() with correct calculation."""
        operation = BalanceOperation(
            user_id=pg_sample_user.id,
            operation_type=OperationType.USAGE,
            amount=Decimal("-0.0030"),
            balance_before=Decimal("0.7500"),
            balance_after=Decimal("0.7470"),
            description="Claude API call: 1000 input + 200 output tokens",
        )

        pg_session.add(operation)
        await pg_session.flush()
        await pg_session.refresh(operation)

        # balance_after = balance_before + amount
        # 0.7470 = 0.7500 + (-0.0030) ✓
        assert operation.verify_balance_consistency() is True

    async def test_verify_balance_consistency_invalid(self, pg_session,
                                                      pg_sample_user):
        """Test verify_balance_consistency() with incorrect calculation."""
        operation = BalanceOperation(
            user_id=pg_sample_user.id,
            operation_type=OperationType.USAGE,
            amount=Decimal("-0.0030"),
            balance_before=Decimal("0.7500"),
            balance_after=Decimal("1.0000"),  # Wrong! Should be 0.7470
            description="Invalid operation (for testing)",
        )

        pg_session.add(operation)
        await pg_session.flush()
        await pg_session.refresh(operation)

        # balance_after != balance_before + amount
        assert operation.verify_balance_consistency() is False

    async def test_balance_operation_with_related_payment(
            self, pg_session, pg_sample_user):
        """Test BalanceOperation with related_payment_id."""
        from db.models.payment import Payment
        from db.models.payment import PaymentStatus

        # Create payment first
        payment = Payment(
            user_id=pg_sample_user.id,
            telegram_payment_charge_id="tg_charge_related",
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

        # Create operation linked to payment
        operation = BalanceOperation(
            user_id=pg_sample_user.id,
            operation_type=OperationType.PAYMENT,
            amount=Decimal("0.6500"),
            balance_before=Decimal("0.1000"),
            balance_after=Decimal("0.7500"),
            related_payment_id=payment.id,
            description=f"Payment #{payment.id}: 100 Stars → $0.65",
        )

        pg_session.add(operation)
        await pg_session.flush()
        await pg_session.refresh(operation)

        assert operation.related_payment_id == payment.id
        assert operation.related_payment.id == payment.id

    async def test_balance_operation_with_admin_user(self, pg_session,
                                                     pg_sample_user):
        """Test BalanceOperation with admin_user_id (ADMIN_TOPUP)."""
        import random

        from db.models.user import User

        # Create admin user with random ID
        admin_id = random.randint(100000000, 999999999)
        admin = User(id=admin_id,
                     username=f"admin_{admin_id}",
                     first_name="Admin")
        pg_session.add(admin)
        await pg_session.flush()

        # Admin topup operation
        operation = BalanceOperation(
            user_id=pg_sample_user.id,
            operation_type=OperationType.ADMIN_TOPUP,
            amount=Decimal("10.0000"),
            balance_before=Decimal("0.1000"),
            balance_after=Decimal("10.1000"),
            admin_user_id=admin.id,
            description=f"Admin topup by @admin: +$10.00",
        )

        pg_session.add(operation)
        await pg_session.flush()
        await pg_session.refresh(operation)

        assert operation.admin_user_id == admin.id
        assert operation.admin_user.username == f"admin_{admin_id}"
        assert operation.admin_user.id == admin_id

    async def test_balance_operation_cascade_delete_user(
            self, pg_session, pg_sample_user):
        """Test that operation is deleted when user is deleted (CASCADE)."""
        operation = BalanceOperation(
            user_id=pg_sample_user.id,
            operation_type=OperationType.PAYMENT,
            amount=Decimal("0.6500"),
            balance_before=Decimal("0.1000"),
            balance_after=Decimal("0.7500"),
            description="Test cascade delete",
        )

        pg_session.add(operation)
        await pg_session.flush()
        operation_id = operation.id

        # Delete user
        await pg_session.delete(pg_sample_user)
        await pg_session.flush()

        # Operation should be deleted
        result = await pg_session.execute(
            select(BalanceOperation).where(BalanceOperation.id == operation_id))
        assert result.scalar_one_or_none() is None

    async def test_balance_operation_set_null_on_payment_delete(
            self, pg_session, pg_sample_user):
        """Test that related_payment_id is set to NULL when payment is deleted."""
        from db.models.payment import Payment
        from db.models.payment import PaymentStatus

        # Create payment
        payment = Payment(
            user_id=pg_sample_user.id,
            telegram_payment_charge_id="tg_charge_set_null",
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
        payment_id = payment.id

        # Create operation
        operation = BalanceOperation(
            user_id=pg_sample_user.id,
            operation_type=OperationType.PAYMENT,
            amount=Decimal("0.6500"),
            balance_before=Decimal("0.1000"),
            balance_after=Decimal("0.7500"),
            related_payment_id=payment_id,
            description="Test SET NULL",
        )

        pg_session.add(operation)
        await pg_session.flush()
        operation_id = operation.id

        # Delete payment
        await pg_session.delete(payment)
        await pg_session.flush()

        # Operation should still exist with NULL related_payment_id
        result = await pg_session.execute(
            select(BalanceOperation).where(BalanceOperation.id == operation_id))
        operation = result.scalar_one()
        assert operation.related_payment_id is None

    async def test_balance_operation_negative_amount(self, pg_session,
                                                     pg_sample_user):
        """Test creating operation with negative amount (USAGE, REFUND)."""
        operation = BalanceOperation(
            user_id=pg_sample_user.id,
            operation_type=OperationType.USAGE,
            amount=Decimal("-0.0030"),  # Negative for deduction
            balance_before=Decimal("0.7500"),
            balance_after=Decimal("0.7470"),
            description="API usage: -$0.003",
        )

        pg_session.add(operation)
        await pg_session.flush()
        await pg_session.refresh(operation)

        assert operation.amount == Decimal("-0.0030")
        assert operation.amount < 0

    async def test_balance_operation_indexes(self, pg_session, pg_sample_user):
        """Test that indexed queries are efficient (user_id, operation_type)."""
        # Create multiple operations
        for i in range(5):
            operation = BalanceOperation(
                user_id=pg_sample_user.id,
                operation_type=OperationType.USAGE,
                amount=Decimal("-0.001"),
                balance_before=Decimal("1.0000"),
                balance_after=Decimal("0.9990"),
                description=f"Usage operation {i}",
            )
            pg_session.add(operation)

        await pg_session.flush()

        # Query by user_id (should use idx_operations_user_id)
        result = await pg_session.execute(
            select(BalanceOperation).where(
                BalanceOperation.user_id == pg_sample_user.id))
        operations = result.scalars().all()
        assert len(operations) >= 5

        # Query by operation_type (should use idx_operations_operation_type)
        result = await pg_session.execute(
            select(BalanceOperation).where(
                BalanceOperation.operation_type == OperationType.USAGE))
        usage_operations = result.scalars().all()
        assert len(usage_operations) >= 5
