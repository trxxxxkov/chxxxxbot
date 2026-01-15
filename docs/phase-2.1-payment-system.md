# Phase 2.1: Payment System (Telegram Stars Integration)

**Status:** ✅ Complete (2026-01-10)

## Overview

Implementation of a complete payment system where users pay for bot usage through Telegram Stars. All API costs (LLM models, tools, external APIs) are tracked and charged to user balance.

**Key principles:**
- Users pay for themselves (starter balance: $0.10)
- Honest billing: charge exactly what was spent
- Pre-purchase model: buy balance with Stars, then spend on API calls
- Soft balance check: allow requests while balance > 0 (can go negative once)
- Admin tools for privileged users (manual balance adjustment, margin configuration)
- Full refund support within 30 days

## Telegram Stars API Review

### Documentation Sources
- [Bot Payments for Digital Goods](https://core.telegram.org/bots/payments-stars)
- [Telegram Bot API - Payments](https://core.telegram.org/bots/api#payments)
- [All about Telegram Stars](https://durovscode.com/about-telegram-stars)
- [Terms of Service for Telegram Stars](https://telegram.org/tos/stars)

### Key API Methods

#### sendInvoice
Create and send payment invoice to user.

**Critical parameters:**
- `currency`: **"XTR"** (Telegram Stars - mandatory for digital goods)
- `provider_token`: **""** (empty string for Stars)
- `title`: Product name (1-32 chars)
- `description`: Product description (1-255 chars)
- `payload`: Bot-defined invoice payload (1-128 bytes) - use for order identification
- `prices`: Array of LabeledPrice objects (price breakdown)

**Example:**
```python
await bot.send_invoice(
    chat_id=user_id,
    title="Balance Top-up",
    description=f"Add ${usd_amount:.2f} to your bot balance",
    payload=f"topup_{user_id}_{timestamp}",
    provider_token="",  # Empty for Stars
    currency="XTR",  # Telegram Stars currency code
    prices=[{"label": "Balance", "amount": stars_amount}],
    photo_url="https://example.com/stars.png",  # Optional
)
```

#### PreCheckoutQuery Handler
Telegram sends this before processing payment. Bot MUST answer to proceed.

**Flow:**
1. Receive `PreCheckoutQuery` update
2. Validate `invoice_payload` and `total_amount`
3. Check user eligibility (not banned, etc.)
4. Answer with `answerPreCheckoutQuery(ok=True)` to approve
5. Or `answerPreCheckoutQuery(ok=False, error_message="...")` to reject

**IMPORTANT:** Answering pre-checkout query does NOT mean payment is completed!

#### SuccessfulPayment Handler
Telegram sends this AFTER payment is completed. Only now deliver goods.

**Critical fields:**
- `telegram_payment_charge_id`: **MUST SAVE** for refunds
- `total_amount`: Total paid in smallest currency units (Stars)
- `invoice_payload`: Your bot-defined payload from sendInvoice

**Flow:**
1. Receive `Message` update with `successful_payment` field
2. Extract `telegram_payment_charge_id` - save to database
3. Calculate USD amount using conversion formula
4. Add balance to user account
5. Create payment record in database
6. Send confirmation with transaction_id for future refunds

#### refundStarPayment
Issue a refund for a Telegram Stars payment.

**Parameters:**
- `user_id`: User who made the payment
- `telegram_payment_charge_id`: Transaction ID from SuccessfulPayment

**Returns:** True on success

**Refund policy (per requirements):**
- Maximum 30 days since payment
- User must have balance >= refund amount
- After refund: deduct amount from user balance, return Stars

### Commission Structure

Based on official documentation and requirements:

| Commission | Symbol | Rate | Description |
|------------|--------|------|-------------|
| Telegram withdrawal fee | k1 | 0.35 (35%) | When bot owner withdraws Stars to USD |
| Topics in private chats | k2 | 0.15 (15%) | Bot API 9.3 feature commission |
| Owner margin | k3 | 0.0 - dynamic | Configurable by privileged users |

**Constraint:** k1 + k2 + k3 ≤ 1.0

**Current market rate:** $0.013 per Star (~$13 per 1000 Stars)

## Conversion Formula

### Step 1: Calculate nominal USD value
```
x = stars_amount * STARS_TO_USD_RATE
```
Where:
- `stars_amount`: Stars paid by user
- `STARS_TO_USD_RATE`: Market rate ($0.013)
- `x`: Nominal USD value WITHOUT commissions

### Step 2: Apply commission formula
```
y = x * (1 - k1 - k2 - k3)
```
Where:
- `y`: Final USD balance credited to user
- `k1`: 0.35 (Telegram withdrawal commission)
- `k2`: 0.15 (Topics in private chats commission)
- `k3`: Owner margin (default 0.0, configurable by privileged users)

### Example Calculation

User buys 100 Stars with k3 = 0.0:

```
x = 100 * 0.013 = $1.30
y = 1.30 * (1 - 0.35 - 0.15 - 0.0)
y = 1.30 * 0.50 = $0.65
```

User receives $0.65 balance for 100 Stars.

With k3 = 0.10 (10% margin):
```
y = 1.30 * (1 - 0.35 - 0.15 - 0.10)
y = 1.30 * 0.40 = $0.52
```

User receives $0.52 balance for 100 Stars.

## Database Schema

### 1. Extend User Model

Add balance tracking to existing `users` table:

```python
# bot/db/models/user.py

class User(Base, TimestampMixin):
    # ... existing fields ...

    balance: Mapped[Decimal] = mapped_column(
        Numeric(precision=10, scale=4),
        nullable=False,
        default=0.1000,  # $0.10 starter balance
        comment="User balance in USD"
    )

# Migration: ALTER TABLE users ADD COLUMN balance NUMERIC(10, 4) NOT NULL DEFAULT 0.1000;
# Migration: CREATE INDEX idx_users_balance ON users(balance);  -- For queries "WHERE balance > 0"
```

**Rationale:**
- `Numeric(10, 4)`: Up to $999,999.9999 with 4 decimal precision
- Default `0.1000`: $0.10 starter balance for new users
- Index on balance: Fast filtering for blocked users

### 2. New Table: payments

Track all payment transactions (top-ups via Stars).

```python
# bot/db/models/payment.py

from enum import Enum
from decimal import Decimal
from datetime import datetime
from sqlalchemy import String, Numeric, ForeignKey, CheckConstraint, Index
from sqlalchemy.orm import Mapped, mapped_column, relationship
from bot.db.models.base import Base, TimestampMixin


class PaymentStatus(str, Enum):
    """Payment transaction status."""
    COMPLETED = "completed"   # Payment successful, balance credited
    REFUNDED = "refunded"     # Payment refunded, balance deducted


class Payment(Base, TimestampMixin):
    """Payment transaction record (Telegram Stars top-up).

    Stores all information needed for:
    - Balance tracking
    - Refund processing
    - Payment history
    - Financial reporting
    """
    __tablename__ = "payments"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)

    # User who made the payment
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="User who made the payment"
    )

    # Telegram payment identifier (for refunds)
    telegram_payment_charge_id: Mapped[str] = mapped_column(
        String(255),
        unique=True,
        nullable=False,
        index=True,
        comment="Telegram payment charge ID from SuccessfulPayment"
    )

    # Payment amounts
    stars_amount: Mapped[int] = mapped_column(
        nullable=False,
        comment="Amount paid in Telegram Stars"
    )

    nominal_usd_amount: Mapped[Decimal] = mapped_column(
        Numeric(precision=10, scale=4),
        nullable=False,
        comment="Nominal USD value (stars * rate) without commissions"
    )

    credited_usd_amount: Mapped[Decimal] = mapped_column(
        Numeric(precision=10, scale=4),
        nullable=False,
        comment="USD amount credited to user balance (after commissions)"
    )

    # Commission breakdown
    commission_k1: Mapped[Decimal] = mapped_column(
        Numeric(precision=5, scale=4),
        nullable=False,
        comment="Telegram withdrawal fee (k1)"
    )

    commission_k2: Mapped[Decimal] = mapped_column(
        Numeric(precision=5, scale=4),
        nullable=False,
        comment="Topics in private chats fee (k2)"
    )

    commission_k3: Mapped[Decimal] = mapped_column(
        Numeric(precision=5, scale=4),
        nullable=False,
        comment="Owner margin (k3)"
    )

    # Status and refund tracking
    status: Mapped[PaymentStatus] = mapped_column(
        default=PaymentStatus.COMPLETED,
        nullable=False,
        index=True,
        comment="Payment status"
    )

    refunded_at: Mapped[datetime | None] = mapped_column(
        nullable=True,
        comment="When payment was refunded (if applicable)"
    )

    # Invoice metadata
    invoice_payload: Mapped[str] = mapped_column(
        String(128),
        nullable=False,
        comment="Invoice payload from sendInvoice"
    )

    # Relationships
    user: Mapped["User"] = relationship("User", back_populates="payments")
    balance_operations: Mapped[list["BalanceOperation"]] = relationship(
        "BalanceOperation",
        back_populates="related_payment",
        cascade="all, delete-orphan"
    )

    __table_args__ = (
        CheckConstraint("stars_amount > 0", name="check_stars_positive"),
        CheckConstraint("nominal_usd_amount > 0", name="check_nominal_positive"),
        CheckConstraint("credited_usd_amount > 0", name="check_credited_positive"),
        CheckConstraint("commission_k1 >= 0 AND commission_k1 <= 1", name="check_k1_range"),
        CheckConstraint("commission_k2 >= 0 AND commission_k2 <= 1", name="check_k2_range"),
        CheckConstraint("commission_k3 >= 0 AND commission_k3 <= 1", name="check_k3_range"),
        CheckConstraint(
            "commission_k1 + commission_k2 + commission_k3 <= 1.0001",  # Float precision tolerance
            name="check_total_commission"
        ),
        Index("idx_payments_user_created", "user_id", "created_at"),  # For user payment history
        Index("idx_payments_status_refunded", "status", "refunded_at"),  # For refund queries
    )

    def __repr__(self) -> str:
        return (
            f"<Payment(id={self.id}, user_id={self.user_id}, "
            f"stars={self.stars_amount}, usd=${self.credited_usd_amount}, "
            f"status={self.status.value})>"
        )

    def can_refund(self, refund_period_days: int = 30) -> bool:
        """Check if this payment can be refunded.

        Args:
            refund_period_days: Maximum days since payment for refund eligibility.

        Returns:
            True if payment is eligible for refund.
        """
        if self.status != PaymentStatus.COMPLETED:
            return False

        from datetime import datetime, timezone, timedelta
        now = datetime.now(timezone.utc)
        max_refund_date = self.created_at + timedelta(days=refund_period_days)

        return now <= max_refund_date
```

### 3. New Table: balance_operations

Complete audit log of all balance changes.

```python
# bot/db/models/balance_operation.py

from enum import Enum
from decimal import Decimal
from sqlalchemy import String, Numeric, ForeignKey, Text, Index
from sqlalchemy.orm import Mapped, mapped_column, relationship
from bot.db.models.base import Base, TimestampMixin


class OperationType(str, Enum):
    """Type of balance operation."""
    PAYMENT = "payment"           # Balance added via Stars payment
    USAGE = "usage"               # Balance spent on API calls
    REFUND = "refund"             # Balance deducted due to payment refund
    ADMIN_TOPUP = "admin_topup"   # Balance adjusted by privileged user


class BalanceOperation(Base, TimestampMixin):
    """Audit log for all user balance changes.

    Every balance modification MUST create a record here for:
    - Transparency (users can see where money went)
    - Debugging (trace balance issues)
    - Financial reporting (total revenue, usage patterns)
    """
    __tablename__ = "balance_operations"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)

    # User whose balance changed
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="User whose balance was modified"
    )

    # Operation type and amount
    operation_type: Mapped[OperationType] = mapped_column(
        nullable=False,
        index=True,
        comment="Type of operation"
    )

    amount: Mapped[Decimal] = mapped_column(
        Numeric(precision=10, scale=4),
        nullable=False,
        comment="Amount added (positive) or deducted (negative)"
    )

    # Balance snapshot (for auditing)
    balance_before: Mapped[Decimal] = mapped_column(
        Numeric(precision=10, scale=4),
        nullable=False,
        comment="User balance before operation"
    )

    balance_after: Mapped[Decimal] = mapped_column(
        Numeric(precision=10, scale=4),
        nullable=False,
        comment="User balance after operation"
    )

    # Related entities (optional foreign keys)
    related_payment_id: Mapped[int | None] = mapped_column(
        ForeignKey("payments.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
        comment="Related payment (for PAYMENT/REFUND operations)"
    )

    related_message_id: Mapped[int | None] = mapped_column(
        ForeignKey("messages.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
        comment="Related message (for USAGE operations)"
    )

    # Admin topup tracking
    admin_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        comment="Admin who performed the topup (for ADMIN_TOPUP)"
    )

    # Human-readable description
    description: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        comment="Human-readable operation description"
    )

    # Relationships
    user: Mapped["User"] = relationship(
        "User",
        foreign_keys=[user_id],
        back_populates="balance_operations"
    )
    related_payment: Mapped["Payment"] = relationship(
        "Payment",
        back_populates="balance_operations"
    )
    related_message: Mapped["Message"] = relationship("Message")
    admin_user: Mapped["User"] = relationship(
        "User",
        foreign_keys=[admin_user_id]
    )

    __table_args__ = (
        Index("idx_operations_user_created", "user_id", "created_at"),  # User history
        Index("idx_operations_type_created", "operation_type", "created_at"),  # Analytics
    )

    def __repr__(self) -> str:
        return (
            f"<BalanceOperation(id={self.id}, user_id={self.user_id}, "
            f"type={self.operation_type.value}, amount=${self.amount}, "
            f"balance={self.balance_before} -> {self.balance_after})>"
        )
```

### 4. Update Relationship in User Model

```python
# bot/db/models/user.py

class User(Base, TimestampMixin):
    # ... existing fields ...

    # New relationships
    payments: Mapped[list["Payment"]] = relationship(
        "Payment",
        back_populates="user",
        cascade="all, delete-orphan",
        order_by="desc(Payment.created_at)"
    )

    balance_operations: Mapped[list["BalanceOperation"]] = relationship(
        "BalanceOperation",
        foreign_keys="BalanceOperation.user_id",
        back_populates="user",
        cascade="all, delete-orphan",
        order_by="desc(BalanceOperation.created_at)"
    )
```

## Configuration

### Bot Settings (config.py)

```python
# bot/config.py

# ============================================================================
# PAYMENT SYSTEM CONFIGURATION
# ============================================================================

# Stars to USD conversion rate (market rate, before commissions)
STARS_TO_USD_RATE: float = 0.013  # $0.013 per Star (~$13 per 1000 Stars)

# Commission rates
TELEGRAM_WITHDRAWAL_FEE: float = 0.35  # k1: 35% - Telegram withdrawal commission
TELEGRAM_TOPICS_FEE: float = 0.15      # k2: 15% - Topics in private chats commission
DEFAULT_OWNER_MARGIN: float = 0.0      # k3: 0% - Default owner margin (configurable)

# Balance settings
STARTER_BALANCE_USD: float = 0.10  # New users get $0.10 starter balance
MINIMUM_BALANCE_FOR_REQUEST: float = 0.0  # Allow requests while balance > 0

# Refund settings
REFUND_PERIOD_DAYS: int = 30  # Maximum days for refund eligibility

# Predefined Stars packages (for /buy command)
STARS_PACKAGES: list[dict[str, int | str]] = [
    {"stars": 10, "label": "Micro"},
    {"stars": 50, "label": "Starter"},
    {"stars": 100, "label": "Basic"},
    {"stars": 250, "label": "Standard"},
    {"stars": 500, "label": "Premium"},
]

# Custom amount range
MIN_CUSTOM_STARS: int = 1
MAX_CUSTOM_STARS: int = 2500

# Payment invoice customization
PAYMENT_INVOICE_TITLE: str = "Bot Balance Top-up"
PAYMENT_INVOICE_DESCRIPTION_TEMPLATE: str = (
    "Add ${usd_amount:.2f} to your bot balance\n"
    "Pay {stars_amount} Telegram Stars"
)
PAYMENT_INVOICE_PHOTO_URL: str = ""  # Optional: URL to payment image

# Privileged users (loaded from secrets)
PRIVILEGED_USERS: set[int] = set()  # Populated from secrets/privileged_users.txt
```

### Secrets Management

Add new secret file for privileged users:

```bash
# secrets/privileged_users.txt
# List of Telegram user IDs with admin privileges (one per line or space/comma separated)
# These users can:
# - Use /topup command to adjust any user's balance
# - Use /set_margin command to configure owner margin (k3)

123456789
987654321
555666777
```

## Implementation Stages

### Stage 1: Database Schema ✅ Complete
1. ✅ Create Payment model (`bot/db/models/payment.py`)
2. ✅ Create BalanceOperation model (`bot/db/models/balance_operation.py`)
3. ✅ Update User model (add balance field, relationships)
4. ✅ Create Alembic migration
5. ✅ Apply migration
6. ✅ Write unit tests for models

### Stage 2: Repositories ✅ Complete
1. ✅ Create PaymentRepository (`bot/db/repositories/payment_repository.py`)
2. ✅ Create BalanceOperationRepository (`bot/db/repositories/balance_operation_repository.py`)
3. ✅ Write unit tests for repositories

### Stage 3: Services ✅ Complete
1. ✅ Create PaymentService (`bot/services/payment_service.py`)
2. ✅ Create BalanceService (`bot/services/balance_service.py`)
3. ✅ Write unit tests for services
4. ✅ Test commission calculation edge cases

### Stage 4: Configuration ✅ Complete
1. ✅ Add payment settings to `bot/config.py`
2. ✅ Create `secrets/privileged_users.txt`
3. ✅ Load privileged users in `bot/main.py`

### Stage 5: Payment Handlers ✅ Complete
1. ✅ Create `bot/telegram/handlers/payment.py`
2. ✅ Implement /buy command with packages
3. ✅ Implement custom Stars amount flow (FSM)
4. ✅ Implement pre-checkout query handler
5. ✅ Implement successful payment handler
6. ✅ Implement /refund command
7. ✅ Implement /balance command
8. ✅ Implement /paysupport command (required by Telegram)
9. ✅ Register handlers in loader

### Stage 6: Admin Commands ✅ Complete
1. ✅ Implement /topup command (privileged users only)
2. ✅ Implement /set_margin command (privileged users only)
3. ✅ Test privilege checking

### Stage 7: Balance Middleware ✅ Complete
1. ✅ Create BalanceMiddleware (`bot/telegram/middlewares/balance_middleware.py`)
2. ✅ Register middleware in loader
3. ✅ Test blocking logic

#### BalanceMiddleware Details

**Location:** `bot/telegram/middlewares/balance_middleware.py`

**Purpose:** Block requests to paid features (Claude API, tools) if user's balance is insufficient (balance ≤ 0).

**Free Commands (no balance check):**
```python
FREE_COMMANDS = {
    "/start",      # Bot introduction
    "/help",       # Help text
    "/buy",        # Balance purchase
    "/balance",    # Balance inquiry
    "/refund",     # Request refund
    "/paysupport", # Payment support
    "/topup",      # Admin: manual topup
    "/set_margin", # Admin: configure margin
    "/model",      # Model selection
}
```

**Middleware Flow:**
```
1. Check if event is Message or CallbackQuery
2. Skip payment messages (successful_payment)
3. Skip bot/system messages
4. Check if command is in FREE_COMMANDS → Allow
5. For paid requests:
   - Get session from DatabaseMiddleware
   - Check balance via BalanceService.can_make_request()
   - If user doesn't exist → Auto-register with starter balance
   - If balance ≤ 0 → Block with error message
   - If balance > 0 → Allow request
6. Fail-open on errors (allow request if check fails)
```

**Error Message (when blocked):**
```
❌ Insufficient balance

Current balance: $0.00

To use paid features, please top up your balance.
Use /buy to purchase balance with Telegram Stars.
```

**Logging:**
- `balance_middleware.free_command` - Free command allowed
- `balance_middleware.request_allowed` - Paid request passed balance check
- `balance_middleware.request_blocked` - Request blocked (insufficient balance)
- `balance_middleware.auto_registered` - New user auto-registered
- `balance_middleware.check_error` - Error during balance check (fail-open)

### Stage 8: Cost Tracking Integration ✅ Complete
1. ✅ Update Claude handler to charge user after response
2. ✅ Update tool handlers to charge user after execution
3. ✅ Test cost calculation and charging
4. ✅ Verify balance deduction

### Stage 9: Integration Testing ✅ Complete
1. ✅ Test full payment flow end-to-end (tests/integration/test_payment_flow.py)
2. ✅ Test refund flow (expiry, insufficient balance, duplicates)
3. ✅ Test balance middleware blocking (tests/telegram/middlewares/test_balance_middleware.py)
4. ✅ Test admin commands (tests/integration/test_admin_commands.py)
5. ✅ Test edge cases (duplicate payments, expired refunds, soft balance check)
6. ✅ All 484 tests passing (46 integration tests + 438 existing tests)

### Stage 10: Documentation & Production ✅ Complete
1. ✅ Update README.md with payment system commands
2. ✅ Update CLAUDE.md (mark Phase 2.1 as complete)
3. ✅ Create production secrets (privileged_users.txt)
4. 🚀 Ready for deployment
5. 📊 Monitor logs for payment events

**Total estimated time:** 12-18 hours

## Files to Create/Modify

### New Files (17 files)

**Models:**
- `bot/db/models/payment.py`
- `bot/db/models/balance_operation.py`

**Repositories:**
- `bot/db/repositories/payment_repository.py`
- `bot/db/repositories/balance_operation_repository.py`

**Services:**
- `bot/services/payment_service.py`
- `bot/services/balance_service.py`

**Handlers:**
- `bot/telegram/handlers/payment.py`

**Middlewares:**
- `bot/telegram/middlewares/balance_middleware.py`

**Tests:**
- `tests/db/models/test_payment.py`
- `tests/db/models/test_balance_operation.py`
- `tests/db/repositories/test_payment_repository.py`
- `tests/db/repositories/test_balance_operation_repository.py`
- `tests/services/test_payment_service.py`
- `tests/services/test_balance_service.py`
- `tests/integration/test_payment_flow.py`
- `tests/middlewares/test_balance_middleware.py`

**Migration:**
- `postgres/alembic/versions/2026_01_10_2010-317c14d820cd_add_payment_system_tables.py`

**Note:** Payment system migration uses date-based naming (`YYYY_MM_DD_HHMM-<hash>`) instead of sequential numbering due to concurrent development branch merging.

**Secrets:**
- `secrets/privileged_users.txt`

### Modified Files (5 files)

- `bot/db/models/user.py` - Add balance field and relationships
- `bot/config.py` - Add payment settings
- `bot/main.py` - Load privileged users
- `bot/telegram/handlers/claude.py` - Add cost charging
- `bot/telegram/loader.py` - Register payment handlers and middleware

## Summary

Phase 2.1 implements a complete payment system with:

- **User balance** - USD balance per user with $0.10 starter
- **Telegram Stars integration** - Native payment with proper commission handling
- **Commission formula** - y = x * (1 - k1 - k2 - k3) where x = stars * rate
- **Soft balance check** - Allow requests while balance > 0 (can go negative once)
- **Refund support** - Within 30 days if sufficient balance
- **Admin tools** - /topup and /set_margin for privileged users
- **Full audit trail** - All balance changes logged in balance_operations table

**Key features:**
- Predefined Stars packages (10, 50, 100, 250, 500) + custom amount (1-2500)
- Transaction ID returned for refunds
- Balance history with /balance command
- Privileged users list in secrets
- Payment support via /paysupport command (Telegram requirement)

**Commission structure (configurable):**
- k1 = 0.35 (Telegram withdrawal)
- k2 = 0.15 (Topics in private chats)
- k3 = 0.0+ (Owner margin, configurable)
- Constraint: k1 + k2 + k3 ≤ 1.0
