"""Tests for BalanceService.

Phase 2.1: Payment system tests for BalanceService balance management.
"""

from decimal import Decimal
import random

from db.models.balance_operation import BalanceOperation
from db.models.balance_operation import OperationType
from db.models.payment import \
    Payment  # noqa: F401 - needed for SQLAlchemy relationships
from db.models.user import \
    User  # noqa: F401 - needed for SQLAlchemy relationships
from db.repositories.balance_operation_repository import \
    BalanceOperationRepository
from db.repositories.user_repository import UserRepository
import pytest
from services.balance_service import BalanceService
from sqlalchemy import select


class TestBalanceService:
    """Test BalanceService balance management logic."""

    @pytest.fixture
    async def balance_service(self, pg_session):
        """Create BalanceService instance with real repositories."""
        user_repo = UserRepository(pg_session)
        balance_op_repo = BalanceOperationRepository(pg_session)
        return BalanceService(pg_session, user_repo, balance_op_repo)

    @pytest.mark.asyncio
    async def test_get_balance(self, balance_service, pg_sample_user):
        """Test retrieving user balance."""
        balance = await balance_service.get_balance(pg_sample_user.id)

        assert balance == Decimal("0.1000")  # Default starter balance

    @pytest.mark.asyncio
    async def test_get_balance_user_not_found(self, balance_service):
        """Test get_balance raises ValueError for non-existent user."""
        with pytest.raises(ValueError, match="User .* not found"):
            await balance_service.get_balance(
                random.randint(100000000, 999999999))

    @pytest.mark.asyncio
    async def test_can_make_request_positive_balance(self, balance_service,
                                                     pg_session,
                                                     pg_sample_user):
        """Test can_make_request returns True when balance > 0."""
        pg_sample_user.balance = Decimal("0.1000")
        await pg_session.flush()

        can_request, user_exists = await balance_service.can_make_request(
            pg_sample_user.id)

        assert can_request is True
        assert user_exists is True

    @pytest.mark.asyncio
    async def test_can_make_request_zero_balance(self, balance_service,
                                                 pg_session, pg_sample_user):
        """Test can_make_request returns False when balance = 0."""
        pg_sample_user.balance = Decimal("0.0000")
        await pg_session.flush()

        can_request, user_exists = await balance_service.can_make_request(
            pg_sample_user.id)

        assert can_request is False
        assert user_exists is True

    @pytest.mark.asyncio
    async def test_can_make_request_negative_balance(self, balance_service,
                                                     pg_session,
                                                     pg_sample_user):
        """Test can_make_request returns False when balance < 0."""
        pg_sample_user.balance = Decimal("-0.0001")
        await pg_session.flush()

        can_request, user_exists = await balance_service.can_make_request(
            pg_sample_user.id)

        assert can_request is False
        assert user_exists is True

    @pytest.mark.asyncio
    async def test_can_make_request_user_not_found(self, balance_service):
        """Test can_make_request returns False when user doesn't exist."""
        can_request, user_exists = await balance_service.can_make_request(
            999999999)

        assert can_request is False
        assert user_exists is False

    @pytest.mark.asyncio
    async def test_charge_user(self, balance_service, pg_session,
                               pg_sample_user):
        """Test charging user for API usage."""
        # Set initial balance
        pg_sample_user.balance = Decimal("1.0000")
        await pg_session.flush()

        # Charge user
        balance_after = await balance_service.charge_user(
            user_id=pg_sample_user.id,
            amount=Decimal("0.0030"),
            description="Claude API call: 1000 input + 200 output tokens",
            related_message_id=12345,
        )

        # Verify balance updated
        assert balance_after == Decimal("0.9970")

        # Verify user balance in database
        await pg_session.refresh(pg_sample_user)
        assert pg_sample_user.balance == Decimal("0.9970")

        # Verify balance operation created
        result = await pg_session.execute(
            select(BalanceOperation).where(
                BalanceOperation.user_id == pg_sample_user.id,
                BalanceOperation.operation_type == OperationType.USAGE,
            ).order_by(BalanceOperation.created_at.desc()))
        operation = result.scalars().first()

        assert operation is not None
        assert operation.amount == Decimal("-0.0030")
        assert operation.balance_before == Decimal("1.0000")
        assert operation.balance_after == Decimal("0.9970")
        assert operation.related_message_id == 12345
        assert operation.verify_balance_consistency() is True

    @pytest.mark.asyncio
    async def test_charge_user_zero_amount(self, balance_service,
                                           pg_sample_user):
        """Test charge_user raises error for zero amount."""
        with pytest.raises(ValueError, match="Charge amount must be positive"):
            await balance_service.charge_user(
                user_id=pg_sample_user.id,
                amount=Decimal("0.0000"),
                description="Invalid charge",
            )

    @pytest.mark.asyncio
    async def test_charge_user_negative_amount(self, balance_service,
                                               pg_sample_user):
        """Test charge_user raises error for negative amount."""
        with pytest.raises(ValueError, match="Charge amount must be positive"):
            await balance_service.charge_user(
                user_id=pg_sample_user.id,
                amount=Decimal("-0.0030"),
                description="Invalid charge",
            )

    @pytest.mark.asyncio
    async def test_charge_allows_negative_balance(self, balance_service,
                                                  pg_session, pg_sample_user):
        """Test charging can bring balance below zero (soft limit)."""
        # Set low balance
        pg_sample_user.balance = Decimal("0.0010")
        await pg_session.flush()

        # Charge more than balance (should succeed - soft limit)
        balance_after = await balance_service.charge_user(
            user_id=pg_sample_user.id,
            amount=Decimal("0.0030"),
            description="Charge that brings balance negative",
        )

        # Balance can go negative
        assert balance_after == Decimal("-0.0020")

    @pytest.mark.asyncio
    async def test_admin_topup_positive(self, balance_service, pg_session,
                                        pg_sample_user, pg_admin_user):
        """Test admin topup with positive amount (add balance)."""
        # Initial balance
        pg_sample_user.balance = Decimal("0.1000")
        await pg_session.flush()

        # Admin adds $10
        balance_before, balance_after = await balance_service.admin_topup(
            admin_user_id=pg_admin_user.id,
            target_user_id=pg_sample_user.id,
            amount=Decimal("10.0000"),
            description="Testing topup",
        )

        # Verify balance increased
        assert balance_before == Decimal("0.1000")
        assert balance_after == Decimal("10.1000")

        # Verify operation created
        result = await pg_session.execute(
            select(BalanceOperation).where(
                BalanceOperation.user_id == pg_sample_user.id,
                BalanceOperation.operation_type == OperationType.ADMIN_TOPUP,
            ).order_by(BalanceOperation.created_at.desc()))
        operation = result.scalars().first()

        assert operation is not None
        assert operation.amount == Decimal("10.0000")
        assert operation.admin_user_id == pg_admin_user.id
        assert "Testing topup" in operation.description

    @pytest.mark.asyncio
    async def test_admin_topup_negative(self, balance_service, pg_session,
                                        pg_sample_user, pg_admin_user):
        """Test admin topup with negative amount (subtract balance)."""
        # Initial balance
        pg_sample_user.balance = Decimal("5.0000")
        await pg_session.flush()

        # Admin removes $2
        balance_before, balance_after = await balance_service.admin_topup(
            admin_user_id=pg_admin_user.id,
            target_user_id=pg_sample_user.id,
            amount=Decimal("-2.0000"),
            description="Correcting error",
        )

        # Verify balance decreased
        assert balance_before == Decimal("5.0000")
        assert balance_after == Decimal("3.0000")

        # Verify operation has negative amount
        result = await pg_session.execute(
            select(BalanceOperation).where(
                BalanceOperation.user_id == pg_sample_user.id,
                BalanceOperation.operation_type == OperationType.ADMIN_TOPUP,
            ).order_by(BalanceOperation.created_at.desc()))
        operation = result.scalars().first()

        assert operation.amount == Decimal("-2.0000")

    @pytest.mark.asyncio
    async def test_admin_topup_zero_amount(self, balance_service,
                                           pg_sample_user, pg_admin_user):
        """Test admin_topup with zero amount (no-op operation)."""
        balance_before, balance_after = await balance_service.admin_topup(
            admin_user_id=pg_admin_user.id,
            target_user_id=pg_sample_user.id,
            amount=Decimal("0.0000"),
            description="Zero amount test",
        )
        # Balance should remain unchanged
        assert balance_before == Decimal("0.1000")
        assert balance_after == Decimal("0.1000")

    @pytest.mark.asyncio
    async def test_get_balance_history(self, balance_service, pg_session,
                                       pg_sample_user):
        """Test retrieving balance history."""
        # Create some operations
        operations_data = [
            (OperationType.PAYMENT, Decimal("1.0000")),
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
                description=f"{op_type.value}",
            )
            pg_session.add(operation)

        await pg_session.flush()

        # Get history
        history = await balance_service.get_balance_history(pg_sample_user.id,
                                                            limit=10)

        assert len(history) == 3
        # Should be in reverse chronological order
        assert history[0].created_at >= history[1].created_at

    @pytest.mark.asyncio
    async def test_get_balance_history_limit(self, balance_service, pg_session,
                                             pg_sample_user):
        """Test get_balance_history respects limit parameter."""
        # Create 10 operations
        for i in range(10):
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

        # Get only 5
        history = await balance_service.get_balance_history(pg_sample_user.id,
                                                            limit=5)

        assert len(history) == 5

    @pytest.mark.asyncio
    async def test_multiple_charges_maintain_consistency(
            self, balance_service, pg_session, pg_sample_user):
        """Test multiple charges maintain balance consistency."""
        # Initial balance
        pg_sample_user.balance = Decimal("1.0000")
        await pg_session.flush()

        # Make multiple charges
        charges = [
            Decimal("0.0010"),
            Decimal("0.0020"),
            Decimal("0.0030"),
            Decimal("0.0015"),
        ]

        for charge in charges:
            await balance_service.charge_user(
                user_id=pg_sample_user.id,
                amount=charge,
                description=f"Charge ${charge}",
            )

        # Verify final balance
        expected_final = Decimal("1.0000") - sum(charges)
        await pg_session.refresh(pg_sample_user)
        assert pg_sample_user.balance == expected_final

        # Verify all operations are consistent
        result = await pg_session.execute(
            select(BalanceOperation).where(
                BalanceOperation.user_id == pg_sample_user.id))
        operations = result.scalars().all()

        for operation in operations:
            assert operation.verify_balance_consistency() is True

    @pytest.mark.asyncio
    async def test_charge_user_creates_detailed_description(
            self, balance_service, pg_session, pg_sample_user):
        """Test that charge creates descriptive operation log."""
        pg_sample_user.balance = Decimal("1.0000")
        await pg_session.flush()

        await balance_service.charge_user(
            user_id=pg_sample_user.id,
            amount=Decimal("0.0123"),
            description=
            "Claude Opus 4.6: 5000 input + 1000 output tokens, execute_python tool",
            related_message_id=54321,
        )

        # Verify description stored
        result = await pg_session.execute(
            select(BalanceOperation).where(
                BalanceOperation.user_id == pg_sample_user.id).order_by(
                    BalanceOperation.created_at.desc()))
        operation = result.scalars().first()

        assert "Claude Opus 4.6" in operation.description
        assert "execute_python" in operation.description
        assert operation.related_message_id == 54321

    @pytest.mark.asyncio
    async def test_balance_service_integration_flow(self, balance_service,
                                                    pg_session, pg_sample_user,
                                                    pg_admin_user):
        """Test complete flow: topup → charge → check balance."""
        # 1. Admin topup
        await balance_service.admin_topup(
            admin_user_id=pg_admin_user.id,
            target_user_id=pg_sample_user.id,
            amount=Decimal("5.0000"),
            description="Initial funding",
        )

        balance = await balance_service.get_balance(pg_sample_user.id)
        assert balance == Decimal("5.1000")  # 0.1 starter + 5.0 topup

        # 2. Make several charges
        for i in range(5):
            await balance_service.charge_user(
                user_id=pg_sample_user.id,
                amount=Decimal("0.5000"),
                description=f"API call {i}",
            )

        balance = await balance_service.get_balance(pg_sample_user.id)
        assert balance == Decimal("2.6000")  # 5.1 - 2.5

        # 3. Check can still make requests
        can_request, user_exists = await balance_service.can_make_request(
            pg_sample_user.id)
        assert can_request is True
        assert user_exists is True

        # 4. Drain balance
        await balance_service.charge_user(
            user_id=pg_sample_user.id,
            amount=Decimal("2.6000"),
            description="Final charge",
        )

        balance = await balance_service.get_balance(pg_sample_user.id)
        assert balance == Decimal("0.0000")

        # 5. Cannot make more requests
        can_request, user_exists = await balance_service.can_make_request(
            pg_sample_user.id)
        assert can_request is False
        assert user_exists is True

        # 6. Verify complete audit trail
        history = await balance_service.get_balance_history(pg_sample_user.id,
                                                            limit=20)
        assert len(history) == 7  # 1 topup + 6 charges

        # All operations should be consistent
        for operation in history:
            assert operation.verify_balance_consistency() is True
