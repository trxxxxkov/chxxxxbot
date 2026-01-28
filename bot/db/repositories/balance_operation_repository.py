"""Repository for BalanceOperation model.

This module provides database operations for BalanceOperation records,
enabling complete audit trail queries for all balance changes.
"""

from datetime import datetime
from datetime import timedelta
from datetime import timezone
from decimal import Decimal

from db.models.balance_operation import BalanceOperation
from db.models.balance_operation import OperationType
from db.repositories.base import BaseRepository
from sqlalchemy import func
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from utils.structured_logging import get_logger

logger = get_logger(__name__)


class BalanceOperationRepository(BaseRepository[BalanceOperation]):
    """Repository for managing balance operation records.

    Provides specialized queries for:
    - User balance history
    - Operations by type (payments, charges, refunds, admin adjustments)
    - Time-based filtering
    - Aggregated totals for reporting
    """

    def __init__(self, session: AsyncSession):
        """Initialize balance operation repository.

        Args:
            session: Database session.
        """
        super().__init__(session, BalanceOperation)

    async def get_user_operations(
        self,
        user_id: int,
        limit: int = 10,
        operation_type: OperationType | None = None,
    ) -> list[BalanceOperation]:
        """Get user's balance operation history.

        Args:
            user_id: Telegram user ID.
            limit: Maximum number of operations to return (default: 10).
            operation_type: Optional filter by operation type.

        Returns:
            List of BalanceOperation instances, newest first.
        """
        stmt = select(BalanceOperation).where(
            BalanceOperation.user_id == user_id)

        if operation_type is not None:
            stmt = stmt.where(BalanceOperation.operation_type == operation_type)

        stmt = stmt.order_by(BalanceOperation.created_at.desc()).limit(limit)

        result = await self.session.execute(stmt)
        operations = list(result.scalars().all())

        logger.debug(
            "balance_operation.user_operations_retrieved",
            user_id=user_id,
            count=len(operations),
            limit=limit,
            operation_type=operation_type.value if operation_type else None,
        )

        return operations

    async def get_user_charges(
        self,
        user_id: int,
        period: str = "all",
    ) -> list[BalanceOperation]:
        """Get user's API usage charges for period.

        Args:
            user_id: Telegram user ID.
            period: Time period - "today", "week", "month", or "all".

        Returns:
            List of BalanceOperation instances with type=USAGE.
        """
        stmt = select(BalanceOperation).where(
            BalanceOperation.user_id == user_id,
            BalanceOperation.operation_type == OperationType.USAGE,
        )

        # Add time filter
        if period != "all":
            now = datetime.now(timezone.utc)
            if period == "today":
                start_time = now.replace(hour=0,
                                         minute=0,
                                         second=0,
                                         microsecond=0)
            elif period == "week":
                start_time = now - timedelta(days=7)
            elif period == "month":
                start_time = now - timedelta(days=30)
            else:
                # Invalid period - use "all"
                start_time = datetime.min.replace(tzinfo=timezone.utc)

            stmt = stmt.where(BalanceOperation.created_at >= start_time)

        stmt = stmt.order_by(BalanceOperation.created_at.desc())

        result = await self.session.execute(stmt)
        charges = list(result.scalars().all())

        logger.debug(
            "balance_operation.user_charges_retrieved",
            user_id=user_id,
            period=period,
            count=len(charges),
        )

        return charges

    async def get_total_charged(self,
                                user_id: int,
                                period: str = "all") -> Decimal:
        """Get total amount charged to user for period.

        Args:
            user_id: Telegram user ID.
            period: Time period - "today", "week", "month", or "all".

        Returns:
            Total USD amount charged (positive number).
        """
        charges = await self.get_user_charges(user_id, period)
        total = sum((abs(op.amount) for op in charges), Decimal("0.0000"))

        logger.debug(
            "balance_operation.total_charged",
            user_id=user_id,
            period=period,
            total=float(total),
        )

        return total

    async def get_total_deposited(self,
                                  user_id: int,
                                  period: str = "all") -> Decimal:
        """Get total amount deposited by user for period.

        Args:
            user_id: Telegram user ID.
            period: Time period - "today", "week", "month", or "all".

        Returns:
            Total USD amount deposited via payments.
        """
        stmt = select(func.sum(BalanceOperation.amount)).where(
            BalanceOperation.user_id == user_id,
            BalanceOperation.operation_type == OperationType.PAYMENT,
        )

        # Add time filter
        if period != "all":
            now = datetime.now(timezone.utc)
            if period == "today":
                start_time = now.replace(hour=0,
                                         minute=0,
                                         second=0,
                                         microsecond=0)
            elif period == "week":
                start_time = now - timedelta(days=7)
            elif period == "month":
                start_time = now - timedelta(days=30)
            else:
                start_time = datetime.min.replace(tzinfo=timezone.utc)

            stmt = stmt.where(BalanceOperation.created_at >= start_time)

        result = await self.session.execute(stmt)
        total = result.scalar() or Decimal("0.0000")

        logger.debug(
            "balance_operation.total_deposited",
            user_id=user_id,
            period=period,
            total=float(total),
        )

        return total

    async def verify_user_balance_integrity(self, user_id: int) -> bool:
        """Verify user balance matches sum of all operations.

        Critical audit function to detect balance discrepancies.

        Args:
            user_id: Telegram user ID.

        Returns:
            True if balance is consistent, False if discrepancy detected.
        """
        # Get all user operations
        stmt = (select(BalanceOperation).where(
            BalanceOperation.user_id == user_id).order_by(
                BalanceOperation.created_at.asc()))
        result = await self.session.execute(stmt)
        operations = list(result.scalars().all())

        if not operations:
            logger.info(
                "balance_operation.no_operations",
                user_id=user_id,
                msg="User has no balance operations",
            )
            return True

        # Verify each operation's balance consistency
        for op in operations:
            if not op.verify_balance_consistency():
                logger.error(
                    "balance_operation.inconsistency_detected",
                    user_id=user_id,
                    operation_id=op.id,
                    balance_before=float(op.balance_before),
                    amount=float(op.amount),
                    balance_after=float(op.balance_after),
                    expected=float(op.balance_before + op.amount),
                    msg="Balance calculation inconsistency",
                )
                return False

        logger.info(
            "balance_operation.integrity_verified",
            user_id=user_id,
            operations_count=len(operations),
        )
        return True
