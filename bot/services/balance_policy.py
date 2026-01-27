"""Unified balance checking policy.

Single source of truth for balance checks:
- Can user make request? (before handler)
- Can user use paid tool? (during handler)

Uses cache-first approach for fast checks with database fallback.

Implements soft-check: user can go negative ONCE, then blocked.
This allows completing started requests without abrupt cutoff.

NO __init__.py - use direct import:
    from services.balance_policy import BalancePolicy, BalanceCheckResult
"""

from dataclasses import dataclass
from decimal import Decimal
from typing import Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

from cache.user_cache import get_balance_from_cached
from cache.user_cache import get_cached_user
import config
from utils.structured_logging import get_logger

logger = get_logger(__name__)


@dataclass
class BalanceCheckResult:
    """Result of balance check."""

    allowed: bool
    balance: Decimal
    source: str  # "cache" or "database"
    reason: Optional[str] = None


class BalancePolicy:
    """Unified balance checking policy.

    Implements soft-check: user can go negative ONCE, then blocked.
    This allows completing started requests without abrupt cutoff.

    Usage:
        policy = BalancePolicy()

        # Quick check (cache-first)
        result = await policy.can_make_request(user_id)
        if not result.allowed:
            return "Insufficient balance"

        # Tool pre-check (cache-first, no DB fallback)
        can_use = await policy.can_use_paid_tool(user_id)
    """

    def __init__(
        self,
        min_balance_for_request: Optional[Decimal] = None,
        min_balance_for_tools: Optional[Decimal] = None,
    ):
        """Initialize policy with thresholds.

        Args:
            min_balance_for_request: Minimum balance to start new request.
                Defaults to config.MINIMUM_BALANCE_FOR_REQUEST.
            min_balance_for_tools: Minimum balance to use paid tools.
                Defaults to 0 (user must have non-negative balance).
        """
        self.min_balance_for_request = (
            min_balance_for_request if min_balance_for_request is not None else
            Decimal(str(config.MINIMUM_BALANCE_FOR_REQUEST)))
        self.min_balance_for_tools = (min_balance_for_tools
                                      if min_balance_for_tools is not None else
                                      Decimal("0"))

    async def can_make_request(
        self,
        user_id: int,
        session: Optional["AsyncSession"] = None,
    ) -> BalanceCheckResult:
        """Check if user can make a new request.

        Uses cache-first approach for speed.
        Falls back to database if cache miss and session provided.

        Args:
            user_id: Telegram user ID.
            session: Optional DB session for fallback.

        Returns:
            BalanceCheckResult with allowed status and balance.
        """
        # Import here to avoid circular imports
        from services.factory import ServiceFactory

        # Try cache first
        cached_user = await get_cached_user(user_id)

        if cached_user is not None:
            balance = get_balance_from_cached(cached_user)
            allowed = balance > self.min_balance_for_request
            return BalanceCheckResult(
                allowed=allowed,
                balance=balance,
                source="cache",
                reason=None if allowed else "Insufficient balance (cached)",
            )

        # Cache miss - check database if session provided
        if session is None:
            # No session, fail-open (will check again in handler)
            logger.debug(
                "balance_policy.cache_miss_no_session",
                user_id=user_id,
            )
            return BalanceCheckResult(
                allowed=True,
                balance=Decimal("0"),
                source="unknown",
                reason="Cache miss, no session - fail open",
            )

        services = ServiceFactory(session)
        user = await services.users.get_by_id(user_id)

        if user is None:
            # New user, allow first request
            return BalanceCheckResult(
                allowed=True,
                balance=Decimal("0"),
                source="database",
                reason="New user",
            )

        balance = user.balance
        allowed = balance > self.min_balance_for_request
        return BalanceCheckResult(
            allowed=allowed,
            balance=balance,
            source="database",
            reason=None if allowed else "Insufficient balance",
        )

    async def can_use_paid_tool(
        self,
        user_id: int,
        session: Optional["AsyncSession"] = None,
    ) -> bool:
        """Check if user can use paid tools.

        Quick cache-first check. Returns False if balance is negative.

        Args:
            user_id: Telegram user ID.
            session: Optional DB session for fallback.

        Returns:
            True if user can use paid tools, False otherwise.
        """
        # Import here to avoid circular imports
        from services.factory import ServiceFactory

        # Try cache first
        cached_user = await get_cached_user(user_id)

        if cached_user is not None:
            balance = get_balance_from_cached(cached_user)
            return balance >= self.min_balance_for_tools

        # Cache miss - check database if session provided
        if session is None:
            # No session, fail-open
            return True

        services = ServiceFactory(session)
        user = await services.users.get_by_id(user_id)

        if user is None:
            # New user, allow (will fail later if no balance)
            return True

        return user.balance >= self.min_balance_for_tools

    async def get_balance(
        self,
        user_id: int,
        session: Optional["AsyncSession"] = None,
    ) -> Decimal:
        """Get user balance from cache or database.

        Args:
            user_id: Telegram user ID.
            session: Optional DB session for fallback.

        Returns:
            User balance, or Decimal("0") if not found.
        """
        # Import here to avoid circular imports
        from services.factory import ServiceFactory

        # Try cache first
        cached_user = await get_cached_user(user_id)

        if cached_user is not None:
            return get_balance_from_cached(cached_user)

        # Cache miss - check database if session provided
        if session is None:
            return Decimal("0")

        services = ServiceFactory(session)
        user = await services.users.get_by_id(user_id)

        if user is None:
            return Decimal("0")

        return user.balance


# Default policy instance
_default_policy: Optional[BalancePolicy] = None


def get_balance_policy() -> BalancePolicy:
    """Get the default BalancePolicy instance.

    Returns:
        Default BalancePolicy singleton.
    """
    global _default_policy  # pylint: disable=global-statement
    if _default_policy is None:
        _default_policy = BalancePolicy()
    return _default_policy
