"""Tests for BalanceOperationRepository.

Phase 2.1: Payment system tests for BalanceOperationRepository CRUD and audit.
"""

from datetime import datetime
from datetime import timedelta
from datetime import timezone
from decimal import Decimal

from db.models.balance_operation import BalanceOperation
from db.models.balance_operation import OperationType
from db.models.payment import \
    Payment  # noqa: F401 - needed for SQLAlchemy relationships
from db.models.user import \
    User  # noqa: F401 - needed for SQLAlchemy relationships
from db.repositories.balance_operation_repository import \
    BalanceOperationRepository
import pytest


@pytest.mark.asyncio
class TestBalanceOperationRepository:
    """Test BalanceOperationRepository methods."""

    @pytest.fixture
    async def operation_repo(self, pg_session):
        """Create BalanceOperationRepository instance."""
        return BalanceOperationRepository(pg_session)

    @pytest.fixture
    async def sample_operation(self, pg_session, pg_sample_user):
        """Create sample balance operation for testing."""
        operation = BalanceOperation(
            user_id=pg_sample_user.id,
            operation_type=OperationType.PAYMENT,
            amount=Decimal("0.6500"),
            balance_before=Decimal("0.1000"),
            balance_after=Decimal("0.7500"),
            description="Payment: 100 Stars → $0.65",
        )

        pg_session.add(operation)
        await pg_session.flush()
        await pg_session.refresh(operation)
        return operation

    async def test_create_operation(self, operation_repo, pg_sample_user):
        """Test creating a balance operation via repository."""
        operation = BalanceOperation(
            user_id=pg_sample_user.id,
            operation_type=OperationType.USAGE,
            amount=Decimal("-0.0030"),
            balance_before=Decimal("0.7500"),
            balance_after=Decimal("0.7470"),
            description="Claude API call: $0.003",
        )
        operation = await operation_repo.create(operation)

        assert operation.id is not None
        assert operation.user_id == pg_sample_user.id
        assert operation.operation_type == OperationType.USAGE
        assert operation.amount == Decimal("-0.0030")

    async def test_get_by_id(self, operation_repo, sample_operation):
        """Test retrieving operation by ID."""
        operation = await operation_repo.get_by_id(sample_operation.id)

        assert operation is not None
        assert operation.id == sample_operation.id
        assert operation.operation_type == OperationType.PAYMENT

    async def test_get_user_operations(self, operation_repo, pg_session,
                                       pg_sample_user):
        """Test retrieving all operations for a user."""
        # Create multiple operations
        operations_data = [
            (OperationType.PAYMENT, Decimal("0.6500")),
            (OperationType.USAGE, Decimal("-0.0030")),
            (OperationType.USAGE, Decimal("-0.0020")),
        ]

        balance = Decimal("0.1000")
        for op_type, amount in operations_data:
            balance_before = balance
            balance += amount
            operation = BalanceOperation(
                user_id=pg_sample_user.id,
                operation_type=op_type,
                amount=amount,
                balance_before=balance_before,
                balance_after=balance,
                description=f"{op_type.value}: {amount}",
            )
            pg_session.add(operation)

        await pg_session.flush()

        # Get user operations
        operations = await operation_repo.get_user_operations(pg_sample_user.id,
                                                              limit=10)

        assert len(operations) == 3
        # Should be ordered by created_at DESC (newest first)
        assert operations[0].created_at >= operations[1].created_at

    async def test_get_user_operations_limit(self, operation_repo, pg_session,
                                             pg_sample_user):
        """Test get_user_operations respects limit parameter."""
        # Create 5 operations
        for i in range(5):
            operation = BalanceOperation(
                user_id=pg_sample_user.id,
                operation_type=OperationType.USAGE,
                amount=Decimal("-0.001"),
                balance_before=Decimal("1.0000"),
                balance_after=Decimal("0.9990"),
                description=f"Operation {i}",
            )
            pg_session.add(operation)

        await pg_session.flush()

        # Get only 3 operations
        operations = await operation_repo.get_user_operations(pg_sample_user.id,
                                                              limit=3)

        assert len(operations) == 3

    async def test_get_user_charges(self, operation_repo, pg_session,
                                    pg_sample_user):
        """Test retrieving only USAGE operations (charges)."""
        # Create mixed operations
        operations_data = [
            (OperationType.PAYMENT, Decimal("1.0000")),
            (OperationType.USAGE, Decimal("-0.0030")),
            (OperationType.USAGE, Decimal("-0.0020")),
            (OperationType.REFUND, Decimal("-0.5000")),
            (OperationType.USAGE, Decimal("-0.0010")),
        ]

        for op_type, amount in operations_data:
            operation = BalanceOperation(
                user_id=pg_sample_user.id,
                operation_type=op_type,
                amount=amount,
                balance_before=Decimal("1.0000"),
                balance_after=Decimal("1.0000") + amount,
                description=f"{op_type.value}",
            )
            pg_session.add(operation)

        await pg_session.flush()

        # Get only charges (USAGE type)
        charges = await operation_repo.get_user_charges(pg_sample_user.id,
                                                        period="all")

        # Should return 3 USAGE operations
        assert len(charges) == 3
        assert all(op.operation_type == OperationType.USAGE for op in charges)

    async def test_get_user_charges_with_period(self, operation_repo,
                                                pg_session, pg_sample_user):
        """Test get_user_charges with time period filter."""
        # Create old charge (31 days ago)
        old_charge = BalanceOperation(
            user_id=pg_sample_user.id,
            operation_type=OperationType.USAGE,
            amount=Decimal("-0.0050"),
            balance_before=Decimal("1.0000"),
            balance_after=Decimal("0.9950"),
            description="Old charge",
        )
        pg_session.add(old_charge)
        await pg_session.flush()

        old_charge.created_at = datetime.now(timezone.utc) - timedelta(days=31)
        await pg_session.flush()

        # Create recent charge
        recent_charge = BalanceOperation(
            user_id=pg_sample_user.id,
            operation_type=OperationType.USAGE,
            amount=Decimal("-0.0030"),
            balance_before=Decimal("0.9950"),
            balance_after=Decimal("0.9920"),
            description="Recent charge",
        )
        pg_session.add(recent_charge)
        await pg_session.flush()

        # Get charges from last 30 days (month period)
        charges_30d = await operation_repo.get_user_charges(pg_sample_user.id,
                                                            period="month")

        # Should only return recent charge
        assert len(charges_30d) == 1
        assert charges_30d[0].description == "Recent charge"

    async def test_get_total_charged(self, operation_repo, pg_session,
                                     pg_sample_user):
        """Test calculating total charged amount (sum of USAGE operations)."""
        # Create usage operations
        usage_amounts = [
            Decimal("-0.0030"),
            Decimal("-0.0020"),
            Decimal("-0.0050"),
        ]

        for amount in usage_amounts:
            operation = BalanceOperation(
                user_id=pg_sample_user.id,
                operation_type=OperationType.USAGE,
                amount=amount,
                balance_before=Decimal("1.0000"),
                balance_after=Decimal("1.0000") + amount,
                description="Usage",
            )
            pg_session.add(operation)

        # Create non-usage operation (should not be counted)
        payment = BalanceOperation(
            user_id=pg_sample_user.id,
            operation_type=OperationType.PAYMENT,
            amount=Decimal("1.0000"),
            balance_before=Decimal("0.1000"),
            balance_after=Decimal("1.1000"),
            description="Payment",
        )
        pg_session.add(payment)

        await pg_session.flush()

        # Get total charged
        total = await operation_repo.get_total_charged(pg_sample_user.id,
                                                       period="all")

        # Sum of usage operations (absolute values)
        expected = Decimal("0.0100")  # 0.0030 + 0.0020 + 0.0050
        assert total == expected

    async def test_verify_user_balance_integrity(self, operation_repo,
                                                 pg_session, pg_sample_user):
        """Test verifying balance integrity (all operations have correct math)."""
        # Create operations with correct calculations
        operations_data = [
            (Decimal("0.6500"), Decimal("0.1000"),
             Decimal("0.7500")),  # 0.1 + 0.65
            (Decimal("-0.0030"), Decimal("0.7500"),
             Decimal("0.7470")),  # 0.75 - 0.003
            (Decimal("-0.0020"), Decimal("0.7470"),
             Decimal("0.7450")),  # 0.747 - 0.002
        ]

        for amount, before, after in operations_data:
            operation = BalanceOperation(
                user_id=pg_sample_user.id,
                operation_type=OperationType.USAGE,
                amount=amount,
                balance_before=before,
                balance_after=after,
                description="Correct calculation",
            )
            pg_session.add(operation)

        await pg_session.flush()

        # Verify integrity
        is_consistent = await operation_repo.verify_user_balance_integrity(
            pg_sample_user.id)

        assert is_consistent is True

    async def test_verify_user_balance_integrity_invalid(
            self, operation_repo, pg_session, pg_sample_user):
        """Test detecting balance integrity violations."""
        # Create operation with incorrect calculation
        operation = BalanceOperation(
            user_id=pg_sample_user.id,
            operation_type=OperationType.USAGE,
            amount=Decimal("-0.0030"),
            balance_before=Decimal("0.7500"),
            balance_after=Decimal("1.0000"),  # Wrong! Should be 0.747
            description="Incorrect calculation",
        )
        pg_session.add(operation)
        await pg_session.flush()

        # Verify integrity
        is_consistent = await operation_repo.verify_user_balance_integrity(
            pg_sample_user.id)

        assert is_consistent is False

    async def test_get_user_operations_empty(self, operation_repo):
        """Test get_user_operations returns empty list for user with no operations."""
        operations = await operation_repo.get_user_operations(999999999,
                                                              limit=10)

        assert operations == []

    async def test_get_total_charged_zero(self, operation_repo, pg_sample_user):
        """Test get_total_charged returns 0 for user with no charges."""
        total = await operation_repo.get_total_charged(pg_sample_user.id,
                                                       period="all")

        assert total == Decimal("0.0000")

    async def test_verify_balance_integrity_no_operations(
            self, operation_repo, pg_sample_user):
        """Test balance integrity check with no operations."""
        is_consistent = await operation_repo.verify_user_balance_integrity(
            pg_sample_user.id)

        # No operations = consistent (vacuous truth)
        assert is_consistent is True

    async def test_get_user_charges_different_periods(self, operation_repo,
                                                      pg_session,
                                                      pg_sample_user):
        """Test get_user_charges with different period parameters."""
        # Create charges at different times
        now = datetime.now(timezone.utc)

        charges_data = [
            (now - timedelta(days=40), "40d_ago"),  # 40 days ago
            (now - timedelta(days=20), "20d_ago"),  # 20 days ago
            (now - timedelta(days=5), "5d_ago"),  # 5 days ago
            (now - timedelta(hours=1), "1h_ago"),  # 1 hour ago
        ]

        for created_at, desc in charges_data:
            charge = BalanceOperation(
                user_id=pg_sample_user.id,
                operation_type=OperationType.USAGE,
                amount=Decimal("-0.001"),
                balance_before=Decimal("1.0000"),
                balance_after=Decimal("0.9990"),
                description=desc,
            )
            pg_session.add(charge)
            await pg_session.flush()
            charge.created_at = created_at

        await pg_session.flush()

        # Test different periods
        charges_all = await operation_repo.get_user_charges(
            pg_sample_user.id, "all")
        assert len(charges_all) == 4

        charges_month = await operation_repo.get_user_charges(
            pg_sample_user.id, "month")
        assert len(charges_month) == 3  # 20d, 5d, 1h ago

        charges_week = await operation_repo.get_user_charges(
            pg_sample_user.id, "week")
        assert len(charges_week) == 2  # 5d, 1h ago

        charges_today = await operation_repo.get_user_charges(
            pg_sample_user.id, "today")
        assert len(charges_today) == 1  # 1h ago
