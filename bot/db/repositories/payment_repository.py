"""Repository for Payment model.

This module provides database operations for Payment records, including
querying by charge ID, user payment history, and refund-related queries.
"""

from db.models.payment import Payment
from db.models.payment import PaymentStatus
from db.repositories.base import BaseRepository
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from utils.structured_logging import get_logger

logger = get_logger(__name__)


class PaymentRepository(BaseRepository[Payment]):
    """Repository for managing payment records.

    Provides specialized queries for:
    - Finding payments by Telegram charge ID (for refunds)
    - Retrieving user payment history
    - Filtering by payment status
    """

    def __init__(self, session: AsyncSession):
        """Initialize payment repository.

        Args:
            session: Database session.
        """
        super().__init__(session, Payment)

    async def get_by_charge_id(
            self, telegram_payment_charge_id: str) -> Payment | None:
        """Get payment by Telegram payment charge ID.

        Critical for refund operations - charge ID is the only way to
        process refunds via Telegram API.

        Args:
            telegram_payment_charge_id: Telegram payment charge ID from
                SuccessfulPayment.

        Returns:
            Payment instance or None if not found.
        """
        stmt = select(Payment).where(
            Payment.telegram_payment_charge_id == telegram_payment_charge_id)
        result = await self.session.execute(stmt)
        payment = result.scalar_one_or_none()

        if payment:
            logger.debug(
                "payment.found_by_charge_id",
                charge_id=telegram_payment_charge_id,
                payment_id=payment.id,
                user_id=payment.user_id,
                status=payment.status
                if isinstance(payment.status, str) else payment.status.value,
            )
        else:
            logger.debug(
                "payment.not_found_by_charge_id",
                charge_id=telegram_payment_charge_id,
            )

        return payment

    async def get_user_payments(
        self,
        user_id: int,
        limit: int = 10,
        status: PaymentStatus | None = None,
    ) -> list[Payment]:
        """Get user's payment history.

        Args:
            user_id: Telegram user ID.
            limit: Maximum number of payments to return (default: 10).
            status: Optional filter by payment status.

        Returns:
            List of Payment instances, newest first.
        """
        stmt = select(Payment).where(Payment.user_id == user_id)

        if status is not None:
            stmt = stmt.where(Payment.status == status)

        stmt = stmt.order_by(Payment.created_at.desc()).limit(limit)

        result = await self.session.execute(stmt)
        payments = list(result.scalars().all())

        logger.debug(
            "payment.user_payments_retrieved",
            user_id=user_id,
            count=len(payments),
            limit=limit,
            status=status.value if status else None,
        )

        return payments

    async def get_refundable_payments(self, user_id: int) -> list[Payment]:
        """Get user's payments eligible for refund.

        Returns payments that are:
        - Status: COMPLETED (not already refunded)
        - Within refund period (checked via can_refund() method)

        Args:
            user_id: Telegram user ID.

        Returns:
            List of refundable Payment instances.
        """
        # Get all completed payments
        payments = await self.get_user_payments(user_id,
                                                limit=100,
                                                status=PaymentStatus.COMPLETED)

        # Filter by refund eligibility (within 30 days)
        refundable = [p for p in payments if p.can_refund()]

        logger.debug(
            "payment.refundable_retrieved",
            user_id=user_id,
            total_payments=len(payments),
            refundable_count=len(refundable),
        )

        return refundable
