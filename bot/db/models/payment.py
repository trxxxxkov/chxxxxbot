"""Payment model for Telegram Stars transactions.

This module defines the Payment model that tracks all balance top-ups via
Telegram Stars. Each payment stores commission breakdown, refund information,
and full audit trail.
"""

from datetime import datetime
from datetime import timedelta
from datetime import timezone
from decimal import Decimal
from enum import Enum

from db.models.base import Base
from db.models.base import TimestampMixin
from sqlalchemy import CheckConstraint
from sqlalchemy import DateTime
from sqlalchemy import ForeignKey
from sqlalchemy import Index
from sqlalchemy import Numeric
from sqlalchemy import String
from sqlalchemy.dialects.postgresql import ENUM
from sqlalchemy.orm import Mapped
from sqlalchemy.orm import mapped_column
from sqlalchemy.orm import relationship


class PaymentStatus(str, Enum):
    """Payment transaction status.

    COMPLETED: Payment successful, balance credited to user.
    REFUNDED: Payment refunded, balance deducted from user.
    """

    COMPLETED = "completed"
    REFUNDED = "refunded"


class Payment(Base, TimestampMixin):
    """Payment transaction record for Telegram Stars top-ups.

    Stores all information needed for:
    - Balance tracking
    - Refund processing (within 30 days)
    - Payment history
    - Financial reporting and audit

    Commission Formula:
        x = stars_amount * STARS_TO_USD_RATE
        y = x * (1 - k1 - k2 - k3)

    Where:
        x: Nominal USD value (before commissions)
        y: Credited USD amount (after commissions)
        k1: Telegram withdrawal fee (0.35)
        k2: Topics in private chats fee (0.15)
        k3: Owner margin (0.0+, configurable)
    """

    __tablename__ = "payments"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)

    # User who made the payment
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="User who made the payment",
    )

    # Telegram payment identifier (CRITICAL for refunds)
    telegram_payment_charge_id: Mapped[str] = mapped_column(
        String(255),
        unique=True,
        nullable=False,
        index=True,
        comment=
        "Telegram payment charge ID from SuccessfulPayment (for refunds)",
    )

    # Payment amounts
    stars_amount: Mapped[int] = mapped_column(
        nullable=False, comment="Amount paid in Telegram Stars")

    nominal_usd_amount: Mapped[Decimal] = mapped_column(
        Numeric(precision=10, scale=4),
        nullable=False,
        comment="Nominal USD value (stars * rate) WITHOUT commissions",
    )

    credited_usd_amount: Mapped[Decimal] = mapped_column(
        Numeric(precision=10, scale=4),
        nullable=False,
        comment="USD amount credited to user balance (AFTER commissions)",
    )

    # Commission breakdown (for transparency and audit)
    commission_k1: Mapped[Decimal] = mapped_column(
        Numeric(precision=5, scale=4),
        nullable=False,
        comment="Telegram withdrawal fee rate (k1, typically 0.35)",
    )

    commission_k2: Mapped[Decimal] = mapped_column(
        Numeric(precision=5, scale=4),
        nullable=False,
        comment="Topics in private chats fee rate (k2, typically 0.15)",
    )

    commission_k3: Mapped[Decimal] = mapped_column(
        Numeric(precision=5, scale=4),
        nullable=False,
        comment="Owner margin rate (k3, configurable, default 0.0)",
    )

    # Status and refund tracking
    status: Mapped[PaymentStatus] = mapped_column(
        ENUM("completed", "refunded", name="paymentstatus", create_type=False),
        default=PaymentStatus.COMPLETED,
        nullable=False,
        index=True,
        comment="Payment status (completed or refunded)",
    )

    refunded_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        comment="When payment was refunded (NULL if not refunded)",
    )

    # Invoice metadata (from sendInvoice)
    invoice_payload: Mapped[str] = mapped_column(
        String(128),
        nullable=False,
        comment=
        "Invoice payload from sendInvoice (format: topup_<user_id>_<timestamp>_<stars>)",
    )

    # Relationships
    user: Mapped["User"] = relationship("User", back_populates="payments")
    balance_operations: Mapped[list["BalanceOperation"]] = relationship(
        "BalanceOperation",
        back_populates="related_payment",
    )

    __table_args__ = (
        # Ensure positive amounts
        CheckConstraint("stars_amount > 0", name="check_stars_positive"),
        CheckConstraint("nominal_usd_amount > 0",
                        name="check_nominal_positive"),
        CheckConstraint("credited_usd_amount > 0",
                        name="check_credited_positive"),
        # Ensure valid commission rates (0 <= k <= 1)
        CheckConstraint("commission_k1 >= 0 AND commission_k1 <= 1",
                        name="check_k1_range"),
        CheckConstraint("commission_k2 >= 0 AND commission_k2 <= 1",
                        name="check_k2_range"),
        CheckConstraint("commission_k3 >= 0 AND commission_k3 <= 1",
                        name="check_k3_range"),
        # Ensure total commission doesn't exceed 100% (with tolerance for float precision)
        CheckConstraint(
            "commission_k1 + commission_k2 + commission_k3 <= 1.0001",
            name="check_total_commission",
        ),
        # Indexes for common queries
        Index("idx_payments_user_created", "user_id",
              "created_at"),  # User payment history
        Index("idx_payments_status_refunded", "status",
              "refunded_at"),  # Refund queries
    )

    def __repr__(self) -> str:
        """String representation for debugging."""
        return (f"<Payment(id={self.id}, user_id={self.user_id}, "
                f"stars={self.stars_amount}, usd=${self.credited_usd_amount}, "
                f"status={self.status.value})>")

    def can_refund(self, refund_period_days: int = 30) -> bool:
        """Check if this payment can be refunded.

        Refund eligibility requirements:
        1. Payment status is COMPLETED (not already refunded)
        2. Payment is within refund period (default 30 days)

        Args:
            refund_period_days: Maximum days since payment for refund
                eligibility (default: 30).

        Returns:
            True if payment is eligible for refund, False otherwise.
        """
        if self.status != PaymentStatus.COMPLETED:
            return False

        now = datetime.now(timezone.utc)

        # Handle both timezone-aware and naive datetimes (for SQLite compatibility)
        created_at = self.created_at
        if created_at.tzinfo is None:
            # Assume UTC if no timezone info (SQLite)
            created_at = created_at.replace(tzinfo=timezone.utc)

        max_refund_date = created_at + timedelta(days=refund_period_days)

        return now <= max_refund_date
