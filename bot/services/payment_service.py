"""Payment service for Telegram Stars integration.

This module handles all payment operations including:
- Commission calculation using the formula y = x * (1 - k1 - k2 - k3)
- Invoice creation
- Successful payment processing
- Refund logic with validation
- Balance crediting and deduction
"""

from datetime import datetime
from datetime import timezone
from decimal import Decimal
from decimal import ROUND_HALF_UP

from aiogram import Bot
from aiogram.types import LabeledPrice
from config import DEFAULT_OWNER_MARGIN
from config import PAYMENT_INVOICE_DESCRIPTION_TEMPLATE
from config import PAYMENT_INVOICE_TITLE
from config import REFUND_PERIOD_DAYS
from config import STARS_TO_USD_RATE
from config import TELEGRAM_TOPICS_FEE
from config import TELEGRAM_WITHDRAWAL_FEE
from db.models.balance_operation import BalanceOperation
from db.models.balance_operation import OperationType
from db.models.payment import Payment
from db.models.payment import PaymentStatus
from db.repositories.balance_operation_repository import \
    BalanceOperationRepository
from db.repositories.payment_repository import PaymentRepository
from db.repositories.user_repository import UserRepository
from sqlalchemy.ext.asyncio import AsyncSession
import structlog

logger = structlog.get_logger(__name__)


class PaymentService:
    """Service for managing Telegram Stars payments.

    Handles the complete payment lifecycle:
    1. Invoice creation with commission calculation
    2. Payment processing and balance crediting
    3. Refund validation and execution
    4. Audit trail creation for all operations
    """

    def __init__(
        self,
        session: AsyncSession,
        user_repo: UserRepository,
        payment_repo: PaymentRepository,
        balance_op_repo: BalanceOperationRepository,
    ):
        """Initialize payment service.

        Args:
            session: Database session for transaction management.
            user_repo: User repository for balance updates.
            payment_repo: Payment repository for payment records.
            balance_op_repo: Balance operation repository for audit trail.
        """
        self.session = session
        self.user_repo = user_repo
        self.payment_repo = payment_repo
        self.balance_op_repo = balance_op_repo

    def calculate_usd_amount(
        self,
        stars_amount: int,
        owner_margin: float = DEFAULT_OWNER_MARGIN,
    ) -> tuple[Decimal, Decimal, Decimal, Decimal, Decimal]:
        """Calculate USD amount credited to user after commissions.

        Commission Formula:
            x = stars_amount * STARS_TO_USD_RATE
            y = x * (1 - k1 - k2 - k3)

        Where:
            x: Nominal USD value (before commissions)
            y: Credited USD amount (after commissions)
            k1: Telegram withdrawal fee (0.35)
            k2: Topics in private chats fee (0.15)
            k3: Owner margin (0.0+, configurable)

        Args:
            stars_amount: Amount of Stars paid by user.
            owner_margin: Owner margin (k3), must satisfy k1+k2+k3 <= 1.0.

        Returns:
            Tuple of:
                - nominal_usd: x (nominal USD value WITHOUT commissions)
                - credited_usd: y (USD credited to user balance)
                - k1: Telegram withdrawal fee rate
                - k2: Topics in private chats fee rate
                - k3: Owner margin rate

        Raises:
            ValueError: If commission rates are invalid.
        """
        # Validate commission rates
        k1 = Decimal(str(TELEGRAM_WITHDRAWAL_FEE))
        k2 = Decimal(str(TELEGRAM_TOPICS_FEE))
        k3 = Decimal(str(owner_margin))

        if not (0 <= k3 <= 1):
            logger.error(
                "payment.invalid_k3",
                k3=float(k3),
                msg="Owner margin k3 must be in range [0, 1]",
            )
            raise ValueError(f"Owner margin k3={k3} must be in range [0, 1]")

        total_commission = k1 + k2 + k3
        if total_commission > Decimal(
                "1.0001"):  # Tolerance for float precision
            logger.error(
                "payment.total_commission_exceeded",
                k1=float(k1),
                k2=float(k2),
                k3=float(k3),
                total=float(total_commission),
                msg="Total commission k1+k2+k3 exceeds 1.0",
            )
            raise ValueError(
                f"Total commission k1+k2+k3={total_commission} exceeds 1.0")

        # Calculate nominal USD amount (without commissions)
        rate = Decimal(str(STARS_TO_USD_RATE))
        nominal_usd = Decimal(stars_amount) * rate

        # Apply commission formula: y = x * (1 - k1 - k2 - k3)
        credited_usd = nominal_usd * (Decimal("1.0") - k1 - k2 - k3)

        # Round to 4 decimal places (cents with 2 extra digits precision)
        nominal_usd = nominal_usd.quantize(Decimal("0.0001"),
                                           rounding=ROUND_HALF_UP)
        credited_usd = credited_usd.quantize(Decimal("0.0001"),
                                             rounding=ROUND_HALF_UP)

        logger.info(
            "payment.usd_calculated",
            stars_amount=stars_amount,
            nominal_usd=float(nominal_usd),
            credited_usd=float(credited_usd),
            k1=float(k1),
            k2=float(k2),
            k3=float(k3),
            formula=f"{credited_usd} = {nominal_usd} * (1 - {k1} - {k2} - {k3})",
        )

        return nominal_usd, credited_usd, k1, k2, k3

    async def send_invoice(
        self,
        bot: Bot,
        user_id: int,
        stars_amount: int,
        owner_margin: float = DEFAULT_OWNER_MARGIN,
        chat_id: int | None = None,
        message_thread_id: int | None = None,
    ) -> None:
        """Send payment invoice to user.

        Args:
            bot: Bot instance for sending invoice.
            user_id: Telegram user ID.
            stars_amount: Amount of Stars for payment.
            owner_margin: Owner margin (k3) for this invoice.
            chat_id: Chat ID where to send invoice (defaults to user_id).
            message_thread_id: Thread ID for topic chats (optional).

        Raises:
            ValueError: If stars_amount is invalid or user not found.
        """
        if stars_amount <= 0:
            logger.error(
                "payment.invalid_stars_amount",
                user_id=user_id,
                stars_amount=stars_amount,
            )
            raise ValueError(f"Invalid stars_amount: {stars_amount}")

        # Calculate USD amount
        nominal_usd, credited_usd, k1, k2, k3 = self.calculate_usd_amount(
            stars_amount, owner_margin)

        # Generate unique invoice payload
        timestamp = int(datetime.now(timezone.utc).timestamp())
        invoice_payload = f"topup_{user_id}_{timestamp}_{stars_amount}"

        # Create invoice description
        description = PAYMENT_INVOICE_DESCRIPTION_TEMPLATE.format(
            usd_amount=credited_usd,
            stars_amount=stars_amount,
        )

        # Send invoice to user
        # Use provided chat_id or default to user_id (private chat)
        target_chat_id = chat_id if chat_id is not None else user_id

        # Prepare invoice kwargs
        invoice_kwargs = {
            "chat_id": target_chat_id,
            "title": PAYMENT_INVOICE_TITLE,
            "description": description,
            "payload": invoice_payload,
            "provider_token": "",  # Empty for Telegram Stars
            "currency": "XTR",  # Telegram Stars currency code
            "prices": [LabeledPrice(label="Balance", amount=stars_amount)],
        }

        # Add message_thread_id if specified (for topic chats)
        if message_thread_id is not None:
            invoice_kwargs["message_thread_id"] = message_thread_id

        await bot.send_invoice(**invoice_kwargs)

        logger.info(
            "payment.invoice_sent",
            user_id=user_id,
            chat_id=target_chat_id,
            message_thread_id=message_thread_id,
            stars_amount=stars_amount,
            nominal_usd=float(nominal_usd),
            credited_usd=float(credited_usd),
            invoice_payload=invoice_payload,
            commissions=f"k1={k1}, k2={k2}, k3={k3}",
        )

    async def process_successful_payment(
        self,
        user_id: int,
        telegram_payment_charge_id: str,
        stars_amount: int,
        invoice_payload: str,
        owner_margin: float = DEFAULT_OWNER_MARGIN,
    ) -> Payment:
        """Process successful payment and credit user balance.

        CRITICAL: Only call this after receiving SuccessfulPayment update!

        This method:
        1. Validates payment (no duplicates)
        2. Calculates USD amounts with commissions
        3. Credits user balance
        4. Creates payment record
        5. Creates audit trail (BalanceOperation)

        Args:
            user_id: Telegram user ID.
            telegram_payment_charge_id: Telegram payment charge ID for refunds.
            stars_amount: Amount of Stars paid.
            invoice_payload: Invoice payload from sendInvoice.
            owner_margin: Owner margin (k3) used for this payment.

        Returns:
            Created Payment record.

        Raises:
            ValueError: If payment is invalid or duplicate.
        """
        logger.info(
            "payment.processing_started",
            user_id=user_id,
            charge_id=telegram_payment_charge_id,
            stars_amount=stars_amount,
        )

        # Check for duplicate payment
        existing = await self.payment_repo.get_by_charge_id(
            telegram_payment_charge_id)
        if existing:
            logger.error(
                "payment.duplicate_detected",
                user_id=user_id,
                charge_id=telegram_payment_charge_id,
                existing_payment_id=existing.id,
                msg="CRITICAL: Duplicate payment attempt detected!",
            )
            raise ValueError(
                f"Payment {telegram_payment_charge_id} already processed")

        # Get user
        user = await self.user_repo.get_by_id(user_id)
        if not user:
            logger.error("payment.user_not_found",
                         user_id=user_id,
                         msg="User not found")
            raise ValueError(f"User {user_id} not found")

        # Calculate USD amounts
        nominal_usd, credited_usd, k1, k2, k3 = self.calculate_usd_amount(
            stars_amount, owner_margin)

        # Create payment record FIRST (for FK constraint)
        payment = Payment(
            user_id=user_id,
            telegram_payment_charge_id=telegram_payment_charge_id,
            stars_amount=stars_amount,
            nominal_usd_amount=nominal_usd,
            credited_usd_amount=credited_usd,
            commission_k1=k1,
            commission_k2=k2,
            commission_k3=k3,
            status=PaymentStatus.COMPLETED,
            invoice_payload=invoice_payload,
        )
        self.session.add(payment)
        await self.session.flush()  # Get payment.id

        # Credit user balance
        balance_before = user.balance
        user.balance += credited_usd
        balance_after = user.balance

        # Create balance operation record (audit trail)
        operation = BalanceOperation(
            user_id=user_id,
            operation_type=OperationType.PAYMENT,
            amount=credited_usd,
            balance_before=balance_before,
            balance_after=balance_after,
            related_payment_id=payment.id,
            description=(
                f"Balance top-up: {stars_amount} Stars → ${credited_usd} "
                f"(nominal ${nominal_usd}, k1={k1}, k2={k2}, k3={k3})"),
        )
        self.session.add(operation)

        # Commit transaction
        await self.session.commit()

        logger.info(
            "payment.processed_successfully",
            payment_id=payment.id,
            user_id=user_id,
            stars_amount=stars_amount,
            nominal_usd=float(nominal_usd),
            credited_usd=float(credited_usd),
            balance_before=float(balance_before),
            balance_after=float(balance_after),
            charge_id=telegram_payment_charge_id,
            msg="Payment processed and balance credited",
        )

        return payment

    async def process_refund(
        self,
        user_id: int,
        telegram_payment_charge_id: str,
    ) -> Payment:
        """Process payment refund.

        Validates refund eligibility and processes refund:
        1. Check payment exists and is COMPLETED
        2. Check refund period (< REFUND_PERIOD_DAYS)
        3. Check user has enough balance
        4. Deduct balance and update payment status
        5. Create audit trail (BalanceOperation)

        Note: Caller must call bot.refund_star_payment() separately!

        Args:
            user_id: Telegram user ID requesting refund.
            telegram_payment_charge_id: Transaction ID to refund.

        Returns:
            Updated Payment record with status=REFUNDED.

        Raises:
            ValueError: If refund is not possible.
        """
        logger.info(
            "payment.refund_started",
            user_id=user_id,
            charge_id=telegram_payment_charge_id,
        )

        # Get payment
        payment = await self.payment_repo.get_by_charge_id(
            telegram_payment_charge_id)
        if not payment:
            logger.warning(
                "payment.refund_payment_not_found",
                user_id=user_id,
                charge_id=telegram_payment_charge_id,
            )
            raise ValueError(f"Payment {telegram_payment_charge_id} not found")

        # Validate ownership
        if payment.user_id != user_id:
            logger.warning(
                "payment.refund_ownership_mismatch",
                user_id=user_id,
                payment_user_id=payment.user_id,
                charge_id=telegram_payment_charge_id,
                msg="User trying to refund someone else's payment!",
            )
            raise ValueError(
                f"Payment {telegram_payment_charge_id} does not belong to user {user_id}"
            )

        # Check status
        if payment.status != PaymentStatus.COMPLETED:
            logger.warning(
                "payment.refund_invalid_status",
                payment_id=payment.id,
                status=payment.status.value,
                msg="Cannot refund payment with non-COMPLETED status",
            )
            raise ValueError(
                f"Payment {payment.id} has status {payment.status.value}, cannot refund"
            )

        # Check refund period
        if not payment.can_refund(REFUND_PERIOD_DAYS):
            logger.warning(
                "payment.refund_period_expired",
                payment_id=payment.id,
                created_at=payment.created_at.isoformat(),
                refund_period_days=REFUND_PERIOD_DAYS,
            )
            raise ValueError(
                f"Payment {payment.id} is older than "
                f"{REFUND_PERIOD_DAYS} days, refund period expired")

        # Check user balance
        user = await self.user_repo.get_by_id(user_id)
        if not user:
            logger.error("payment.refund_user_not_found", user_id=user_id)
            raise ValueError(f"User {user_id} not found")

        if user.balance < payment.credited_usd_amount:
            logger.warning(
                "payment.refund_insufficient_balance",
                user_id=user_id,
                balance=float(user.balance),
                required=float(payment.credited_usd_amount),
                msg="User has insufficient balance for refund",
            )
            raise ValueError(
                f"Insufficient balance for refund: "
                f"need ${payment.credited_usd_amount}, have ${user.balance}")

        # Deduct balance
        balance_before = user.balance
        user.balance -= payment.credited_usd_amount
        balance_after = user.balance

        # Update payment status
        payment.status = PaymentStatus.REFUNDED
        payment.refunded_at = datetime.now(timezone.utc)

        # Create balance operation record (audit trail)
        operation = BalanceOperation(
            user_id=user_id,
            operation_type=OperationType.REFUND,
            amount=-payment.credited_usd_amount,  # Negative = deduction
            balance_before=balance_before,
            balance_after=balance_after,
            related_payment_id=payment.id,
            description=(
                f"Refund: {payment.stars_amount} Stars payment refunded, "
                f"${payment.credited_usd_amount} deducted"),
        )
        self.session.add(operation)

        # Commit transaction
        await self.session.commit()

        logger.info(
            "payment.refund_processed",
            payment_id=payment.id,
            user_id=user_id,
            stars_amount=payment.stars_amount,
            refunded_usd=float(payment.credited_usd_amount),
            balance_before=float(balance_before),
            balance_after=float(balance_after),
            charge_id=telegram_payment_charge_id,
            msg="Refund processed and balance deducted",
        )

        return payment
