# Claude Integration: Phase 2.1 (Payment System)

User balance tracking with Telegram Stars integration, pre-request cost validation, and admin management tools.

**Status:** 📋 **PLANNED**

---

## Table of Contents

- [Overview](#overview)
- [User Balance System](#user-balance-system)
- [Cost Calculation](#cost-calculation)
- [Telegram Stars Integration](#telegram-stars-integration)
- [Admin Commands](#admin-commands)
- [Cost Reporting](#cost-reporting)
- [Implementation Plan](#implementation-plan)
- [Related Documents](#related-documents)

---

## Overview

Phase 2.1 adds a complete payment system with user balances, cost tracking, and Telegram Stars integration for deposits.

### Goals

1. **User balance** - Track USD balance per user, block requests if insufficient
2. **Cost tracking** - Log every API call with accurate cost calculation
3. **Telegram Stars** - Accept deposits via Telegram's native payment system
4. **Admin tools** - Privileged commands for balance management
5. **Cost reporting** - Per-user usage analytics and billing

### Prerequisites

- ✅ Phase 1.3 complete (Claude integration working)
- ✅ Token usage tracking in place
- ✅ Database supports transactions (PostgreSQL ACID)
- ⏳ Telegram Stars payment system available in bot

---

## User Balance System

### Database Changes

#### User Model Updates

Add balance field to existing User model.

**File:** `bot/db/models/user.py`

```python
from decimal import Decimal
from sqlalchemy import Numeric

class User(Base, TimestampMixin):
    # ... existing fields ...

    balance: Mapped[Decimal] = mapped_column(
        Numeric(10, 2),  # 10 digits total, 2 after decimal (e.g., 9999999.99)
        nullable=False,
        default=Decimal("0.00"),
        doc="User balance in USD"
    )
```

**Migration:**
```bash
# Generate migration
docker compose exec bot sh -c "cd /postgres && alembic revision --autogenerate -m 'Add user balance'"

# Apply migration
docker compose exec bot sh -c "cd /postgres && alembic upgrade head"
```

---

#### New Model: Transaction

Track all balance changes with full audit trail.

**File:** `bot/db/models/transaction.py` (new)

```python
from decimal import Decimal
from sqlalchemy import BigInteger, ForeignKey, Integer, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column
from db.models.base import Base, TimestampMixin

class Transaction(Base, TimestampMixin):
    """Balance transaction record.

    Tracks all balance changes (deposits, charges, refunds, admin adjustments).
    Immutable once created - never update, only create new transactions.
    """

    __tablename__ = "transactions"

    id: Mapped[int] = mapped_column(
        Integer().with_variant(BigInteger, "postgresql"),
        primary_key=True,
        autoincrement=True
    )

    user_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        doc="User who owns this transaction"
    )

    type: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        index=True,
        doc="Transaction type: deposit, charge, refund, admin_adjustment"
    )

    amount: Mapped[Decimal] = mapped_column(
        Numeric(10, 6),  # High precision for small API costs
        nullable=False,
        doc="Amount in USD (positive for deposits, negative for charges)"
    )

    balance_before: Mapped[Decimal] = mapped_column(
        Numeric(10, 2),
        nullable=False,
        doc="User balance before transaction"
    )

    balance_after: Mapped[Decimal] = mapped_column(
        Numeric(10, 2),
        nullable=False,
        doc="User balance after transaction"
    )

    description: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        doc="Human-readable description"
    )

    # Telegram Stars deposit metadata
    telegram_payment_charge_id: Mapped[Optional[str]] = mapped_column(
        String(255),
        nullable=True,
        index=True,
        doc="Telegram payment charge ID (for refunds)"
    )

    telegram_stars_amount: Mapped[Optional[int]] = mapped_column(
        Integer,
        nullable=True,
        doc="Original amount in Telegram Stars"
    )

    # LLM API charge metadata
    message_chat_id: Mapped[Optional[int]] = mapped_column(
        BigInteger,
        nullable=True,
        doc="Message chat_id that caused this charge"
    )

    message_id: Mapped[Optional[int]] = mapped_column(
        Integer,
        nullable=True,
        doc="Message ID that caused this charge"
    )

    input_tokens: Mapped[Optional[int]] = mapped_column(
        Integer,
        nullable=True,
        doc="LLM input tokens for this charge"
    )

    output_tokens: Mapped[Optional[int]] = mapped_column(
        Integer,
        nullable=True,
        doc="LLM output tokens for this charge"
    )

    model_name: Mapped[Optional[str]] = mapped_column(
        String(100),
        nullable=True,
        doc="LLM model used"
    )

    # Admin adjustment metadata
    admin_user_id: Mapped[Optional[int]] = mapped_column(
        BigInteger,
        nullable=True,
        doc="Admin who made adjustment"
    )

    admin_reason: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True,
        doc="Reason for admin adjustment"
    )


# Indexes
from sqlalchemy import Index

Index('idx_transactions_user_created', Transaction.user_id, Transaction.created_at)
Index('idx_transactions_type_created', Transaction.type, Transaction.created_at)
```

**Design decisions:**
- **Immutable records** - Never update, only create new transactions
- **Balance snapshots** - Store balance before/after for audit trail
- **Type-specific metadata** - Different fields for deposits, charges, refunds
- **High precision** - Numeric(10, 6) for small API costs (e.g., $0.000123)

---

#### Repository: TransactionRepository

**File:** `bot/db/repositories/transaction_repository.py` (new)

```python
from decimal import Decimal
from datetime import datetime, timedelta
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from db.models.transaction import Transaction
from db.repositories.base import BaseRepository

class TransactionRepository(BaseRepository[Transaction]):
    """Repository for transaction operations."""

    def __init__(self, session: AsyncSession):
        super().__init__(session, Transaction)

    async def create_transaction(
        self,
        user_id: int,
        type: str,
        amount: Decimal,
        balance_before: Decimal,
        balance_after: Decimal,
        description: str,
        **kwargs
    ) -> Transaction:
        """Create transaction record.

        Args:
            user_id: User ID.
            type: Transaction type (deposit, charge, refund, admin_adjustment).
            amount: Amount in USD.
            balance_before: Balance before transaction.
            balance_after: Balance after transaction.
            description: Human-readable description.
            **kwargs: Type-specific metadata.

        Returns:
            Created transaction.
        """
        transaction = Transaction(
            user_id=user_id,
            type=type,
            amount=amount,
            balance_before=balance_before,
            balance_after=balance_after,
            description=description,
            **kwargs
        )

        self.session.add(transaction)
        await self.session.flush()

        logger.info("transaction.created",
                    transaction_id=transaction.id,
                    user_id=user_id,
                    type=type,
                    amount=float(amount))

        return transaction

    async def get_user_transactions(
        self,
        user_id: int,
        limit: int = 100,
        offset: int = 0
    ) -> List[Transaction]:
        """Get user's transaction history (newest first)."""
        stmt = (
            select(Transaction)
            .where(Transaction.user_id == user_id)
            .order_by(Transaction.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def get_user_charges(
        self,
        user_id: int,
        period: str = "all"  # "today", "week", "month", "all"
    ) -> List[Transaction]:
        """Get user's API charges for period."""
        stmt = select(Transaction).where(
            Transaction.user_id == user_id,
            Transaction.type == "charge"
        )

        # Add time filter
        if period != "all":
            now = datetime.now()
            if period == "today":
                start_time = now.replace(hour=0, minute=0, second=0, microsecond=0)
            elif period == "week":
                start_time = now - timedelta(days=7)
            elif period == "month":
                start_time = now - timedelta(days=30)
            else:
                start_time = datetime.min

            stmt = stmt.where(Transaction.created_at >= start_time)

        stmt = stmt.order_by(Transaction.created_at.desc())
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def get_total_charged(self, user_id: int, period: str = "all") -> Decimal:
        """Get total amount charged for period."""
        charges = await self.get_user_charges(user_id, period)
        return sum((abs(tx.amount) for tx in charges), Decimal("0.00"))
```

---

## Cost Calculation

### Pre-Request Validation

Before sending request to Claude, estimate cost and validate balance.

**File:** `bot/core/billing/cost_estimator.py` (new)

```python
from decimal import Decimal
from core.models import TokenUsage
import config

class CostEstimator:
    """Estimate and calculate LLM API costs."""

    @staticmethod
    def estimate_cost(
        input_tokens: int,
        max_output_tokens: int,
        model: str
    ) -> Decimal:
        """Estimate MAXIMUM cost for request.

        Uses known input tokens + assumes max output tokens (worst case).

        Args:
            input_tokens: Known input tokens (context + system prompt).
            max_output_tokens: Maximum output tokens to request.
            model: Model name (e.g., "claude-sonnet-4.5").

        Returns:
            Estimated maximum cost in USD.
        """
        model_config = config.CLAUDE_MODELS[model]

        input_cost = (input_tokens / 1_000_000) * model_config.input_price_per_mtok
        output_cost = (max_output_tokens / 1_000_000) * model_config.output_price_per_mtok

        total = Decimal(str(input_cost + output_cost))

        logger.debug("cost.estimated",
                     input_tokens=input_tokens,
                     max_output_tokens=max_output_tokens,
                     model=model,
                     estimated_cost=float(total))

        return total

    @staticmethod
    def calculate_actual_cost(
        usage: TokenUsage,
        model: str
    ) -> Decimal:
        """Calculate ACTUAL cost from token usage.

        Args:
            usage: Token usage from API response.
            model: Model name.

        Returns:
            Actual cost in USD.
        """
        model_config = config.CLAUDE_MODELS[model]

        input_cost = (usage.input_tokens / 1_000_000) * model_config.input_price_per_mtok
        output_cost = (usage.output_tokens / 1_000_000) * model_config.output_price_per_mtok

        # Cache tokens (Phase 1.4)
        cache_read_cost = 0
        cache_creation_cost = 0
        if usage.cache_read_tokens > 0:
            # Cache reads are ~90% cheaper (check API docs for exact pricing)
            cache_read_price = model_config.input_price_per_mtok * 0.1
            cache_read_cost = (usage.cache_read_tokens / 1_000_000) * cache_read_price

        if usage.cache_creation_tokens > 0:
            # Cache creation same as input (or check API docs)
            cache_creation_cost = (usage.cache_creation_tokens / 1_000_000) * model_config.input_price_per_mtok

        total = Decimal(str(
            input_cost + output_cost + cache_read_cost + cache_creation_cost
        ))

        logger.info("cost.calculated",
                    input_tokens=usage.input_tokens,
                    output_tokens=usage.output_tokens,
                    cache_read_tokens=usage.cache_read_tokens,
                    cache_creation_tokens=usage.cache_creation_tokens,
                    model=model,
                    actual_cost=float(total))

        return total


async def validate_user_balance(
    user_id: int,
    estimated_cost: Decimal,
    session: AsyncSession
) -> bool:
    """Check if user has sufficient balance.

    Args:
        user_id: User ID.
        estimated_cost: Estimated maximum cost.
        session: Database session.

    Returns:
        True if user has sufficient balance.

    Raises:
        InsufficientBalanceError: If balance is insufficient.
    """
    user_repo = UserRepository(session)
    user = await user_repo.get_by_id(user_id)

    if user.balance < estimated_cost:
        logger.warning("balance.insufficient",
                       user_id=user_id,
                       balance=float(user.balance),
                       required=float(estimated_cost))

        raise InsufficientBalanceError(
            f"Insufficient balance: ${user.balance:.2f} available, "
            f"${estimated_cost:.4f} required",
            balance=float(user.balance),
            estimated_cost=float(estimated_cost)
        )

    logger.debug("balance.validated",
                 user_id=user_id,
                 balance=float(user.balance),
                 estimated_cost=float(estimated_cost))

    return True
```

---

### Charge User After Request

After Claude API call completes, charge user for actual usage.

**File:** `bot/core/billing/charge_user.py` (new)

```python
from decimal import Decimal
from sqlalchemy.ext.asyncio import AsyncSession
from db.repositories.user_repository import UserRepository
from db.repositories.transaction_repository import TransactionRepository
from core.billing.cost_estimator import CostEstimator
from core.models import TokenUsage

async def charge_user_for_request(
    user_id: int,
    usage: TokenUsage,
    model: str,
    chat_id: int,
    message_id: int,
    session: AsyncSession
) -> Decimal:
    """Charge user for LLM API usage.

    Args:
        user_id: User ID.
        usage: Token usage from API.
        model: Model name.
        chat_id: Message chat_id.
        message_id: Message ID.
        session: Database session.

    Returns:
        Amount charged.
    """
    # Calculate actual cost
    cost = CostEstimator.calculate_actual_cost(usage, model)

    # Get user
    user_repo = UserRepository(session)
    user = await user_repo.get_by_id(user_id)

    balance_before = user.balance

    # Deduct from balance
    user.balance -= cost

    # Create transaction record
    tx_repo = TransactionRepository(session)
    await tx_repo.create_transaction(
        user_id=user_id,
        type="charge",
        amount=-cost,  # Negative for charges
        balance_before=balance_before,
        balance_after=user.balance,
        description=f"Claude API call: {usage.input_tokens} in + {usage.output_tokens} out tokens",
        message_chat_id=chat_id,
        message_id=message_id,
        input_tokens=usage.input_tokens,
        output_tokens=usage.output_tokens,
        model_name=model
    )

    logger.info("user.charged",
                user_id=user_id,
                amount=float(cost),
                balance_after=float(user.balance),
                input_tokens=usage.input_tokens,
                output_tokens=usage.output_tokens)

    return cost
```

---

### Updated Handler Flow

**File:** `bot/telegram/handlers/claude.py` (update)

```python
@router.message(F.text)
async def handle_claude_message(message: types.Message, session: AsyncSession):
    """Handle text message with balance validation."""

    # ... existing code: get user, chat, thread, save message ...

    # NEW: Count tokens for context
    context_tokens = sum(
        await claude_provider.get_token_count(msg.content)
        for msg in context
    )

    # NEW: Estimate cost
    estimated_cost = CostEstimator.estimate_cost(
        input_tokens=context_tokens,
        max_output_tokens=config.CLAUDE_MAX_TOKENS,
        model="claude-sonnet-4.5"
    )

    # NEW: Validate balance
    try:
        await validate_user_balance(user.id, estimated_cost, session)
    except InsufficientBalanceError as e:
        await message.answer(
            f"❌ Insufficient balance\n\n"
            f"Your balance: ${e.balance:.2f}\n"
            f"Required: ${e.estimated_cost:.4f}\n\n"
            f"Use /deposit to add funds."
        )
        return

    # ... existing code: stream from Claude ...

    # NEW: Charge user for actual usage
    usage = await claude_provider.get_usage()
    cost = await charge_user_for_request(
        user_id=user.id,
        usage=usage,
        model=model_config.name,
        chat_id=message.chat.id,
        message_id=bot_message.message_id,
        session=session
    )

    logger.info("claude_handler.complete",
                user_id=user.id,
                cost=float(cost),
                balance_after=float(user.balance))
```

---

## Telegram Stars Integration

### Payment Flow

1. User sends `/deposit <amount_stars>` command
2. Bot generates invoice link
3. User pays via Telegram
4. Bot receives `pre_checkout_query` → validates
5. Bot receives `successful_payment` → credits balance
6. Transaction logged with `telegram_payment_charge_id`

### Configuration

**Stars to USD conversion rate:**
```python
# bot/config.py
TELEGRAM_STARS_TO_USD = Decimal("0.01")  # 1 Star = $0.01 USD
MINIMUM_DEPOSIT_STARS = 100  # Minimum deposit: 100 Stars ($1.00)
```

---

### Deposit Handler

**File:** `bot/telegram/handlers/payment.py` (new)

```python
from aiogram import Router, F
from aiogram.filters import Command
from aiogram.types import Message, PreCheckoutQuery, LabeledPrice
from sqlalchemy.ext.asyncio import AsyncSession
from decimal import Decimal

from db.repositories.user_repository import UserRepository
from db.repositories.transaction_repository import TransactionRepository
import config

router = Router(name="payment_handler")


@router.message(Command("deposit"))
async def handle_deposit_command(message: Message):
    """Handle /deposit command.

    Usage: /deposit <amount_in_stars>
    Example: /deposit 500  (deposits 500 Stars = $5.00)
    """
    try:
        # Parse amount
        parts = message.text.split()
        if len(parts) != 2:
            await message.answer(
                "Usage: /deposit <amount>\n"
                f"Example: /deposit 500 (deposits 500 Stars = ${500 * config.TELEGRAM_STARS_TO_USD})"
            )
            return

        amount_stars = int(parts[1])

        # Validate minimum
        if amount_stars < config.MINIMUM_DEPOSIT_STARS:
            await message.answer(
                f"❌ Minimum deposit: {config.MINIMUM_DEPOSIT_STARS} Stars "
                f"(${config.MINIMUM_DEPOSIT_STARS * config.TELEGRAM_STARS_TO_USD})"
            )
            return

        # Calculate USD equivalent
        amount_usd = amount_stars * config.TELEGRAM_STARS_TO_USD

        # Create invoice link
        invoice_link = await message.bot.create_invoice_link(
            title="Balance Deposit",
            description=f"Deposit {amount_stars} Stars (${amount_usd})",
            payload=f"deposit:{message.from_user.id}:{amount_stars}",
            provider_token="",  # Empty for Telegram Stars
            currency="XTR",  # Telegram Stars currency code
            prices=[LabeledPrice(label="Deposit", amount=amount_stars)]
        )

        await message.answer(
            f"💳 Deposit {amount_stars} Stars (${amount_usd})\n\n"
            f"Click to pay: {invoice_link}\n\n"
            f"After payment, your balance will be increased by ${amount_usd}."
        )

        logger.info("deposit.invoice_created",
                    user_id=message.from_user.id,
                    amount_stars=amount_stars,
                    amount_usd=float(amount_usd))

    except ValueError:
        await message.answer("❌ Invalid amount. Please enter a number.")
    except Exception as e:
        logger.error("deposit.failed", error=str(e))
        await message.answer("❌ Failed to create invoice. Please try again.")


@router.pre_checkout_query()
async def handle_pre_checkout(query: PreCheckoutQuery):
    """Handle pre-checkout validation."""
    # Parse payload
    parts = query.invoice_payload.split(":")
    if len(parts) != 3 or parts[0] != "deposit":
        await query.answer(ok=False, error_message="Invalid payment")
        return

    user_id = int(parts[1])
    amount_stars = int(parts[2])

    # Validate user
    if user_id != query.from_user.id:
        await query.answer(ok=False, error_message="User mismatch")
        return

    # Validate amount
    if amount_stars != query.total_amount:
        await query.answer(ok=False, error_message="Amount mismatch")
        return

    # Approve payment
    await query.answer(ok=True)

    logger.info("payment.pre_checkout_approved",
                user_id=user_id,
                amount_stars=amount_stars)


@router.message(F.successful_payment)
async def handle_successful_payment(message: Message, session: AsyncSession):
    """Handle successful payment and credit balance."""
    payment = message.successful_payment

    # Parse payload
    parts = payment.invoice_payload.split(":")
    user_id = int(parts[1])
    amount_stars = int(parts[2])

    # Calculate USD amount
    amount_usd = Decimal(amount_stars) * config.TELEGRAM_STARS_TO_USD

    # Get user
    user_repo = UserRepository(session)
    user = await user_repo.get_by_id(user_id)

    balance_before = user.balance

    # Credit balance
    user.balance += amount_usd

    # Create transaction record
    tx_repo = TransactionRepository(session)
    await tx_repo.create_transaction(
        user_id=user_id,
        type="deposit",
        amount=amount_usd,
        balance_before=balance_before,
        balance_after=user.balance,
        description=f"Telegram Stars deposit: {amount_stars} Stars",
        telegram_payment_charge_id=payment.telegram_payment_charge_id,
        telegram_stars_amount=amount_stars
    )

    await message.answer(
        f"✅ Payment successful!\n\n"
        f"Deposited: {amount_stars} Stars (${amount_usd})\n"
        f"New balance: ${user.balance:.2f}"
    )

    logger.info("payment.successful",
                user_id=user_id,
                amount_stars=amount_stars,
                amount_usd=float(amount_usd),
                balance_after=float(user.balance))
```

---

### Refund Handler

**File:** `bot/telegram/handlers/admin.py` (new)

```python
from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message
from sqlalchemy.ext.asyncio import AsyncSession
from db.repositories.user_repository import UserRepository
from db.repositories.transaction_repository import TransactionRepository
import config

router = Router(name="admin_handler")

# Load admin IDs from secret
ADMIN_IDS = set(int(x) for x in read_secret("admin_user_ids").split(","))


@router.message(Command("refund"))
async def handle_refund(message: Message, session: AsyncSession):
    """Refund a Telegram Stars payment.

    Usage: /refund <transaction_id>
    Admin only.
    """
    # Check admin
    if message.from_user.id not in ADMIN_IDS:
        await message.answer("❌ Unauthorized")
        return

    try:
        # Parse transaction ID
        parts = message.text.split()
        if len(parts) != 2:
            await message.answer("Usage: /refund <transaction_id>")
            return

        transaction_id = int(parts[1])

        # Get transaction
        tx_repo = TransactionRepository(session)
        transaction = await tx_repo.get_by_id(transaction_id)

        if not transaction:
            await message.answer("❌ Transaction not found")
            return

        if transaction.type != "deposit":
            await message.answer("❌ Only deposits can be refunded")
            return

        if not transaction.telegram_payment_charge_id:
            await message.answer("❌ Not a Telegram Stars payment")
            return

        # Refund via Telegram
        success = await message.bot.refund_star_payment(
            user_id=transaction.user_id,
            telegram_payment_charge_id=transaction.telegram_payment_charge_id
        )

        if not success:
            await message.answer("❌ Refund failed")
            return

        # Deduct from user balance
        user_repo = UserRepository(session)
        user = await user_repo.get_by_id(transaction.user_id)

        balance_before = user.balance
        user.balance -= transaction.amount

        # Log refund transaction
        await tx_repo.create_transaction(
            user_id=transaction.user_id,
            type="refund",
            amount=-transaction.amount,  # Negative (removing money)
            balance_before=balance_before,
            balance_after=user.balance,
            description=f"Refund of transaction #{transaction_id}",
            admin_user_id=message.from_user.id,
            admin_reason="Manual refund by admin"
        )

        await message.answer(
            f"✅ Refund successful\n\n"
            f"Transaction: #{transaction_id}\n"
            f"Amount: ${transaction.amount}\n"
            f"User balance: ${user.balance:.2f}"
        )

        logger.info("refund.successful",
                    transaction_id=transaction_id,
                    user_id=transaction.user_id,
                    amount=float(transaction.amount),
                    admin_id=message.from_user.id)

    except ValueError:
        await message.answer("❌ Invalid transaction ID")
    except Exception as e:
        logger.error("refund.failed", error=str(e))
        await message.answer("❌ Refund failed. See logs.")
```

---

## Admin Commands

### Balance Check

**Command:** `/balance [username|user_id]`

- Regular users: check own balance
- Admins: check any user's balance

```python
@router.message(Command("balance"))
async def handle_balance(message: Message, session: AsyncSession):
    """Check balance."""
    user_repo = UserRepository(session)

    if message.from_user.id in ADMIN_IDS and len(message.text.split()) > 1:
        # Admin checking other user
        target = message.text.split()[1]
        user = await user_repo.get_by_username_or_id(target)

        if not user:
            await message.answer(f"❌ User not found: {target}")
            return

        await message.answer(
            f"💰 Balance for {user.username or user.first_name}\n\n"
            f"User ID: {user.id}\n"
            f"Balance: ${user.balance:.2f}"
        )
    else:
        # User checking own balance
        user = await user_repo.get_by_id(message.from_user.id)
        await message.answer(f"💰 Your balance: ${user.balance:.2f}")
```

---

### Add Balance

**Command:** `/addbalance <username|user_id> <amount>`

Admin only. Adds to user's balance.

```python
@router.message(Command("addbalance"))
async def handle_add_balance(message: Message, session: AsyncSession):
    """Add balance to user (admin only)."""
    if message.from_user.id not in ADMIN_IDS:
        await message.answer("❌ Unauthorized")
        return

    try:
        parts = message.text.split()
        if len(parts) != 3:
            await message.answer("Usage: /addbalance <username|user_id> <amount>")
            return

        target = parts[1]
        amount = Decimal(parts[2])

        user_repo = UserRepository(session)
        user = await user_repo.get_by_username_or_id(target)

        if not user:
            await message.answer(f"❌ User not found: {target}")
            return

        balance_before = user.balance
        user.balance += amount

        tx_repo = TransactionRepository(session)
        await tx_repo.create_transaction(
            user_id=user.id,
            type="admin_adjustment",
            amount=amount,
            balance_before=balance_before,
            balance_after=user.balance,
            description=f"Balance adjustment by admin {message.from_user.username}",
            admin_user_id=message.from_user.id,
            admin_reason="Manual balance addition"
        )

        await message.answer(
            f"✅ Balance updated\n\n"
            f"User: {user.username or user.first_name}\n"
            f"Added: ${amount}\n"
            f"New balance: ${user.balance:.2f}"
        )

        logger.info("admin.balance_added",
                    admin_id=message.from_user.id,
                    user_id=user.id,
                    amount=float(amount))

    except ValueError:
        await message.answer("❌ Invalid amount")
    except Exception as e:
        logger.error("admin.add_balance_failed", error=str(e))
        await message.answer("❌ Failed to update balance")
```

---

### Set Balance

**Command:** `/setbalance <username|user_id> <amount>`

Admin only. Sets user's balance to specific amount.

```python
@router.message(Command("setbalance"))
async def handle_set_balance(message: Message, session: AsyncSession):
    """Set user balance to specific amount (admin only)."""
    if message.from_user.id not in ADMIN_IDS:
        await message.answer("❌ Unauthorized")
        return

    try:
        parts = message.text.split()
        if len(parts) != 3:
            await message.answer("Usage: /setbalance <username|user_id> <amount>")
            return

        target = parts[1]
        new_balance = Decimal(parts[2])

        user_repo = UserRepository(session)
        user = await user_repo.get_by_username_or_id(target)

        if not user:
            await message.answer(f"❌ User not found: {target}")
            return

        balance_before = user.balance
        adjustment = new_balance - balance_before
        user.balance = new_balance

        tx_repo = TransactionRepository(session)
        await tx_repo.create_transaction(
            user_id=user.id,
            type="admin_adjustment",
            amount=adjustment,
            balance_before=balance_before,
            balance_after=user.balance,
            description=f"Balance set by admin {message.from_user.username}",
            admin_user_id=message.from_user.id,
            admin_reason="Manual balance setting"
        )

        await message.answer(
            f"✅ Balance set\n\n"
            f"User: {user.username or user.first_name}\n"
            f"Old balance: ${balance_before:.2f}\n"
            f"New balance: ${new_balance:.2f}\n"
            f"Adjustment: ${adjustment:+.2f}"
        )

        logger.info("admin.balance_set",
                    admin_id=message.from_user.id,
                    user_id=user.id,
                    new_balance=float(new_balance))

    except ValueError:
        await message.answer("❌ Invalid amount")
    except Exception as e:
        logger.error("admin.set_balance_failed", error=str(e))
        await message.answer("❌ Failed to set balance")
```

---

## Cost Reporting

### Usage Command

**Command:** `/usage [period]`

Show user's API usage and costs for time period.

Periods: `today`, `week`, `month`, `all`

```python
@router.message(Command("usage"))
async def handle_usage(message: Message, session: AsyncSession):
    """Show usage statistics."""
    parts = message.text.split()
    period = parts[1] if len(parts) > 1 else "today"

    if period not in ("today", "week", "month", "all"):
        await message.answer("Usage: /usage [today|week|month|all]")
        return

    user_repo = UserRepository(session)
    user = await user_repo.get_by_id(message.from_user.id)

    tx_repo = TransactionRepository(session)
    charges = await tx_repo.get_user_charges(user.id, period)

    if not charges:
        await message.answer(f"No usage for period: {period}")
        return

    total_cost = sum(abs(tx.amount) for tx in charges)
    total_input_tokens = sum(tx.input_tokens or 0 for tx in charges)
    total_output_tokens = sum(tx.output_tokens or 0 for tx in charges)

    await message.answer(
        f"📊 Usage Report ({period})\n\n"
        f"Requests: {len(charges)}\n"
        f"Total cost: ${total_cost:.4f}\n"
        f"Input tokens: {total_input_tokens:,}\n"
        f"Output tokens: {total_output_tokens:,}\n\n"
        f"Current balance: ${user.balance:.2f}"
    )
```

---

## Implementation Plan

### Phase 2.1 Checklist

#### 1. Database Changes
- [ ] Add `balance` field to User model
- [ ] Create Transaction model
- [ ] Create TransactionRepository
- [ ] Generate and apply migration
- [ ] Test migration on clean database

#### 2. Cost Calculation
- [ ] Create CostEstimator class
- [ ] Implement pre-request estimation
- [ ] Implement post-request calculation
- [ ] Add balance validation function
- [ ] Tests for cost calculations

#### 3. Charge System
- [ ] Create charge_user_for_request function
- [ ] Update Claude handler with balance checks
- [ ] Add InsufficientBalanceError handling
- [ ] Log all charges
- [ ] Tests for charging flow

#### 4. Telegram Stars
- [ ] Create payment handlers (deposit, pre_checkout, successful_payment)
- [ ] Configure Stars to USD conversion rate
- [ ] Test payment flow in Telegram
- [ ] Implement refund handler
- [ ] Tests for payment flow

#### 5. Admin Tools
- [ ] Create admin_user_ids secret
- [ ] Implement /balance command
- [ ] Implement /addbalance command
- [ ] Implement /setbalance command
- [ ] Implement /refund command
- [ ] Tests for admin commands

#### 6. Cost Reporting
- [ ] Implement /usage command
- [ ] Add period filtering (today, week, month, all)
- [ ] Create usage statistics queries
- [ ] Tests for reporting

#### 7. Configuration
- [ ] Add Stars to USD conversion rate to config
- [ ] Add minimum deposit amount to config
- [ ] Create admin_user_ids secret file
- [ ] Update compose.yaml with new secrets

#### 8. Testing
- [ ] Unit tests for all billing functions
- [ ] Integration tests with database
- [ ] Manual testing with real Telegram Stars (test environment)
- [ ] Load testing for concurrent charges
- [ ] Test edge cases (negative balance, concurrent requests)

#### 9. Documentation
- [ ] Update CLAUDE.md with Phase 2.1 status
- [ ] Document payment flow for users
- [ ] Document admin commands
- [ ] Update bot-structure.md with new files

---

## Related Documents

- **[phase-1.3-claude-core.md](phase-1.3-claude-core.md)** - Phase 1.3: Core Claude integration
- **[phase-1.4-best-practices.md](phase-1.4-best-practices.md)** - Phase 1.4: Best practices
- **[phase-1.5-multimodal-tools.md](phase-1.5-multimodal-tools.md)** - Phase 1.5: Multimodal + Tools
- **[phase-1.2-database.md](phase-1.2-database.md)** - Database architecture
- **[phase-1.1-bot-structure.md](phase-1.1-bot-structure.md)** - File structure
- **[CLAUDE.md](../CLAUDE.md)** - Project overview

---

## Summary

Phase 2.1 implements a complete payment system with:

- **User balance** - USD balance per user with full audit trail
- **Cost validation** - Pre-request checks prevent overspending
- **Telegram Stars** - Native payment integration with deposits and refunds
- **Admin tools** - Balance management and payment administration
- **Cost reporting** - Per-user usage analytics

The system ensures accurate billing, prevents abuse, and provides full transparency through transaction logs.
