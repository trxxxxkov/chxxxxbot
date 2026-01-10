"""Balance operation model for complete audit trail.

This module defines the BalanceOperation model that tracks EVERY balance change
for complete transparency, debugging, and financial reporting. No balance change
should occur without creating a corresponding BalanceOperation record.
"""

from decimal import Decimal
from enum import Enum

from db.models.base import Base
from db.models.base import TimestampMixin
from sqlalchemy import ForeignKey
from sqlalchemy import Index
from sqlalchemy import Numeric
from sqlalchemy import Text
from sqlalchemy.dialects.postgresql import ENUM
from sqlalchemy.orm import Mapped
from sqlalchemy.orm import mapped_column
from sqlalchemy.orm import relationship


class OperationType(str, Enum):
    """Type of balance operation.

    PAYMENT: Balance added via Telegram Stars payment.
    USAGE: Balance spent on API calls (LLM, tools, etc.).
    REFUND: Balance deducted due to payment refund.
    ADMIN_TOPUP: Balance adjusted by privileged user (manual correction).
    """

    PAYMENT = "payment"
    USAGE = "usage"
    REFUND = "refund"
    ADMIN_TOPUP = "admin_topup"


class BalanceOperation(Base, TimestampMixin):
    """Audit log for all user balance changes.

    CRITICAL RULE: Every balance modification MUST create a record here.

    This provides:
    - Transparency: Users can see where money went
    - Debugging: Trace balance issues and discrepancies
    - Financial reporting: Total revenue, usage patterns, leak detection
    - Compliance: Complete audit trail for all transactions

    Example Operations:
    - PAYMENT: User pays 100 Stars, balance +$0.65
    - USAGE: Claude API call costs $0.003, balance -$0.003
    - REFUND: Payment refunded, balance -$0.65
    - ADMIN_TOPUP: Admin adds $10 for testing, balance +$10.00
    """

    __tablename__ = "balance_operations"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)

    # User whose balance changed
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="User whose balance was modified",
    )

    # Operation type and amount
    operation_type: Mapped[OperationType] = mapped_column(
        ENUM("payment",
             "usage",
             "refund",
             "admin_topup",
             name="operationtype",
             create_type=False),
        nullable=False,
        index=True,
        comment="Type of balance operation",
    )

    amount: Mapped[Decimal] = mapped_column(
        Numeric(precision=10, scale=4),
        nullable=False,
        comment="Amount added (positive) or deducted (negative)",
    )

    # Balance snapshot (CRITICAL for audit verification)
    balance_before: Mapped[Decimal] = mapped_column(
        Numeric(precision=10, scale=4),
        nullable=False,
        comment="User balance BEFORE this operation",
    )

    balance_after: Mapped[Decimal] = mapped_column(
        Numeric(precision=10, scale=4),
        nullable=False,
        comment="User balance AFTER this operation",
    )

    # Related entities (optional foreign keys for linking)
    related_payment_id: Mapped[int | None] = mapped_column(
        ForeignKey("payments.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
        comment="Related payment (for PAYMENT/REFUND operations)",
    )

    related_message_id: Mapped[int | None] = mapped_column(
        nullable=True,
        index=True,
        comment=("Related message_id (for USAGE operations - which request "
                 "caused charge, no FK due to composite key)"),
    )

    # Admin topup tracking
    admin_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        comment="Admin who performed the topup (for ADMIN_TOPUP only)",
    )

    # Human-readable description (REQUIRED for transparency)
    description: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        comment="Human-readable operation description with all relevant details",
    )

    # Relationships
    user: Mapped["User"] = relationship("User",
                                        foreign_keys=[user_id],
                                        back_populates="balance_operations")
    related_payment: Mapped["Payment"] = relationship(
        "Payment", back_populates="balance_operations")
    # Note: No relationship for related_message_id (messages table has composite PK)
    admin_user: Mapped["User"] = relationship("User",
                                              foreign_keys=[admin_user_id])

    __table_args__ = (
        # Indexes for common queries
        Index("idx_operations_user_created", "user_id",
              "created_at"),  # User history
        Index("idx_operations_type_created", "operation_type",
              "created_at"),  # Analytics by type
    )

    def __repr__(self) -> str:
        """String representation for debugging."""
        return (f"<BalanceOperation(id={self.id}, user_id={self.user_id}, "
                f"type={self.operation_type.value}, amount=${self.amount}, "
                f"balance={self.balance_before} -> {self.balance_after})>")

    def verify_balance_consistency(self) -> bool:
        """Verify that balance_after = balance_before + amount.

        This is a critical consistency check for audit purposes.

        Returns:
            True if balance calculation is consistent, False otherwise.
        """
        expected_balance_after = self.balance_before + self.amount
        # Use small tolerance for Decimal comparison (floating point precision)
        tolerance = Decimal("0.0001")
        difference = abs(self.balance_after - expected_balance_after)
        return difference < tolerance
