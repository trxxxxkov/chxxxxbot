"""Balance service for user balance management.

This module handles all balance-related operations:
- Balance checking and validation
- Charging for API usage (LLM, tools, etc.)
- Admin balance adjustments
- Balance history retrieval

Phase 3.2: Invalidates Redis cache on balance changes.
"""

from decimal import Decimal
from decimal import ROUND_HALF_UP

from cache.user_cache import invalidate_user
from cache.user_cache import update_cached_balance
from config import MINIMUM_BALANCE_FOR_REQUEST
from db.models.balance_operation import BalanceOperation
from db.models.balance_operation import OperationType
from db.repositories.balance_operation_repository import \
    BalanceOperationRepository
from db.repositories.user_repository import UserRepository
from sqlalchemy.ext.asyncio import AsyncSession
from utils.structured_logging import get_logger

logger = get_logger(__name__)


class BalanceService:
    """Service for managing user balances.

    Handles:
    - Balance queries and validation
    - Charging users for API usage
    - Admin balance adjustments (topup/deduction)
    - Balance history and audit trail
    """

    def __init__(
        self,
        session: AsyncSession,
        user_repo: UserRepository,
        balance_op_repo: BalanceOperationRepository,
    ):
        """Initialize balance service.

        Args:
            session: Database session for transaction management.
            user_repo: User repository for balance queries/updates.
            balance_op_repo: Balance operation repository for audit trail.
        """
        self.session = session
        self.user_repo = user_repo
        self.balance_op_repo = balance_op_repo

    async def get_balance(self, user_id: int) -> Decimal:
        """Get user's current balance.

        Args:
            user_id: Telegram user ID.

        Returns:
            User balance in USD.

        Raises:
            ValueError: If user not found.
        """
        user = await self.user_repo.get_by_id(user_id)
        if not user:
            logger.error(
                "balance.user_not_found",
                user_id=user_id,
                msg="User not found when getting balance",
            )
            raise ValueError(f"User {user_id} not found")

        logger.debug("balance.retrieved",
                     user_id=user_id,
                     balance=float(user.balance))
        return user.balance

    async def can_make_request(self, user_id: int) -> tuple[bool, bool]:
        """Check if user can make a paid request.

        Rule: Allow requests while balance > MINIMUM_BALANCE_FOR_REQUEST (0.0).
        User can go negative after one request, but next request will be blocked.

        Args:
            user_id: Telegram user ID.

        Returns:
            Tuple of (can_request, user_exists):
            - can_request: True if user can make a request, False otherwise.
            - user_exists: True if user exists in database, False otherwise.
        """
        user = await self.user_repo.get_by_id(user_id)

        if not user:
            # User doesn't exist - this is expected for new users
            # They need to /start first
            logger.info(
                "balance.user_not_registered",
                user_id=user_id,
                msg="User not registered, needs to /start first",
            )
            return False, False

        balance = user.balance
        can_request = balance > Decimal(str(MINIMUM_BALANCE_FOR_REQUEST))

        logger.debug(
            "balance.can_make_request_checked",
            user_id=user_id,
            balance=float(balance),
            minimum_required=MINIMUM_BALANCE_FOR_REQUEST,
            can_request=can_request,
        )

        if not can_request:
            logger.info(
                "balance.insufficient_for_request",
                user_id=user_id,
                balance=float(balance),
                msg="User blocked: insufficient balance",
            )

        return can_request, True

    async def charge_user(
        self,
        user_id: int,
        amount: Decimal | float,
        description: str,
        related_message_id: int | None = None,
    ) -> Decimal:
        """Charge user for API usage.

        CRITICAL: This is where money is spent! Always log thoroughly.

        Args:
            user_id: Telegram user ID.
            amount: Amount to charge (positive value).
            description: Human-readable description of what was charged.
            related_message_id: Optional message ID that caused the charge.

        Returns:
            User's balance after charge.

        Raises:
            ValueError: If user not found or amount is invalid.
        """
        if isinstance(amount, float):
            amount = Decimal(str(amount))

        if amount <= 0:
            logger.error(
                "balance.invalid_charge_amount",
                user_id=user_id,
                amount=float(amount),
                msg="Charge amount must be positive",
            )
            raise ValueError(f"Charge amount must be positive, got {amount}")

        logger.info(
            "balance.charge_started",
            user_id=user_id,
            amount=float(amount),
            description=description,
            related_message_id=related_message_id,
        )

        # Get user
        user = await self.user_repo.get_by_id(user_id)
        if not user:
            logger.error(
                "balance.charge_user_not_found",
                user_id=user_id,
                msg="User not found when charging",
            )
            raise ValueError(f"User {user_id} not found")

        # Deduct balance
        balance_before = user.balance
        user.balance -= amount
        balance_after = user.balance

        # Round to 4 decimal places
        user.balance = user.balance.quantize(Decimal("0.0001"),
                                             rounding=ROUND_HALF_UP)

        # Create balance operation record (CRITICAL for audit)
        operation = BalanceOperation(
            user_id=user_id,
            operation_type=OperationType.USAGE,
            amount=-amount,  # Negative = deduction
            balance_before=balance_before,
            balance_after=balance_after,
            related_message_id=related_message_id,
            description=description,
        )
        self.session.add(operation)

        # Commit transaction
        await self.session.commit()

        logger.info(
            "balance.user_charged",
            user_id=user_id,
            amount=float(amount),
            balance_before=float(balance_before),
            balance_after=float(balance_after),
            description=description,
            related_message_id=related_message_id,
            msg="User charged for API usage",
        )

        # Phase 3.2: Update cache with new balance (don't invalidate!)
        # This keeps the cache warm for subsequent requests
        await update_cached_balance(user_id, balance_after)

        # Alert if balance went negative
        if balance_after < 0:
            logger.info(
                "balance.negative_after_charge",
                user_id=user_id,
                balance_after=float(balance_after),
                amount=float(amount),
                msg=
                "User balance went negative after charge (expected behavior)",
            )

        return balance_after

    async def admin_topup(
        self,
        admin_user_id: int,
        target_user_id: int | None = None,
        target_username: str | None = None,
        amount: Decimal | float = Decimal("0"),
        description: str | None = None,
    ) -> tuple[Decimal, Decimal]:
        """Adjust user balance (admin operation).

        Privileged users can add or subtract any amount from user balance.

        CRITICAL: Log all admin operations for audit.

        Args:
            admin_user_id: Telegram user ID of admin performing operation.
            target_user_id: Telegram user ID to modify (optional if username
                provided).
            target_username: Username to modify (optional if user_id provided).
            amount: Amount to add (positive) or subtract (negative).
            description: Optional custom description.

        Returns:
            Tuple of (balance_before, balance_after).

        Raises:
            ValueError: If target user not found or neither ID nor username
                provided.
        """
        if isinstance(amount, float):
            amount = Decimal(str(amount))

        logger.info(
            "balance.admin_topup_started",
            admin_user_id=admin_user_id,
            target_user_id=target_user_id,
            target_username=target_username,
            amount=float(amount),
        )

        # Find target user
        if target_user_id:
            user = await self.user_repo.get_by_id(target_user_id)
        elif target_username:
            user = await self.user_repo.get_by_username(target_username)
        else:
            logger.error(
                "balance.admin_topup_no_target",
                admin_user_id=admin_user_id,
                msg="Neither target_user_id nor target_username provided",
            )
            raise ValueError(
                "Must provide either target_user_id or target_username")

        if not user:
            logger.info(
                "balance.admin_topup_user_not_found",
                admin_user_id=admin_user_id,
                target_user_id=target_user_id,
                target_username=target_username,
                msg="Target user not found",
            )
            raise ValueError(
                f"User not found: id={target_user_id}, username={target_username}"
            )

        # Adjust balance
        balance_before = user.balance
        user.balance += amount
        balance_after = user.balance

        # Round to 4 decimal places
        user.balance = user.balance.quantize(Decimal("0.0001"),
                                             rounding=ROUND_HALF_UP)

        # Create balance operation record (CRITICAL for audit)
        if not description:
            action = "added" if amount > 0 else "deducted"
            description = (f"Admin balance adjustment: ${abs(amount)} {action} "
                           f"by admin {admin_user_id}")

        operation = BalanceOperation(
            user_id=user.id,
            operation_type=OperationType.ADMIN_TOPUP,
            amount=amount,
            balance_before=balance_before,
            balance_after=balance_after,
            admin_user_id=admin_user_id,
            description=description,
        )
        self.session.add(operation)

        # Commit transaction
        await self.session.commit()

        logger.info(
            "balance.admin_topup_completed",
            admin_user_id=admin_user_id,
            target_user_id=user.id,
            target_username=user.username,
            amount=float(amount),
            balance_before=float(balance_before),
            balance_after=float(balance_after),
            description=description,
            msg="Admin adjusted user balance",
        )

        # Phase 3.2: Update cache with new balance
        await update_cached_balance(user.id, balance_after)

        return balance_before, balance_after

    async def get_balance_history(
        self,
        user_id: int,
        limit: int = 10,
    ) -> list[BalanceOperation]:
        """Get user's recent balance operations.

        Args:
            user_id: Telegram user ID.
            limit: Maximum number of operations to return (default: 10).

        Returns:
            List of BalanceOperation records, newest first.
        """
        operations = await self.balance_op_repo.get_user_operations(user_id,
                                                                    limit=limit)

        logger.debug(
            "balance.history_retrieved",
            user_id=user_id,
            count=len(operations),
            limit=limit,
        )

        return operations
