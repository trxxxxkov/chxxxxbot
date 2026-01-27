"""Topic naming service for LLM-generated topic titles.

Bot API 9.3 added topics in private chats. This service generates
meaningful topic names based on conversation context.

Workflow:
1. User creates topic in Telegram (auto-generated name)
2. User sends first message → Thread created with needs_topic_naming=True
3. Bot responds → maybe_name_topic() called
4. Check balance → if insufficient, skip LLM and keep default name
5. LLM generates title → charge user → bot.edit_forum_topic() applies it
6. Thread.needs_topic_naming = False

NO __init__.py - use direct import:
    from services.topic_naming import TopicNamingService
"""

from decimal import Decimal
from typing import Optional

from aiogram import Bot
from cache.user_cache import get_cached_user
from cache.user_cache import update_cached_balance
import config
from core.clients import get_anthropic_async_client
from core.pricing import calculate_claude_cost
from db.models.thread import Thread
from db.repositories.balance_operation_repository import \
    BalanceOperationRepository
from db.repositories.user_repository import UserRepository
from services.balance_service import BalanceService
from sqlalchemy.ext.asyncio import AsyncSession
from utils.metrics import record_claude_request
from utils.metrics import record_claude_tokens
from utils.metrics import record_cost
from utils.structured_logging import get_logger

logger = get_logger(__name__)

# System prompt for title generation
# Follows Claude 4 best practices: explicit instructions, examples, context
TOPIC_NAMING_SYSTEM_PROMPT = """Generate a short, descriptive title for a chat topic.

<context>
You are naming a Telegram chat topic based on the user's first message and the bot's response.
The title will be displayed in the Telegram UI as the topic name.
</context>

<requirements>
- Length: 2-6 words (max 50 characters)
- Language: Match the user's language
- Style: Concise noun phrase or short sentence
- Focus: Capture the main subject or task, not generic greetings
</requirements>

<examples>
User: "Помоги написать резюме для Junior Python разработчика"
Bot: "Конечно! Давайте создадим резюме..."
Title: "Резюме Junior Python"

User: "What's the difference between async and await in Python?"
Bot: "Great question! In Python, async/await..."
Title: "Python async/await"

User: "Сделай презентацию про машинное обучение для школьников"
Bot: "Отличная задача! Создам презентацию..."
Title: "ML презентация для школы"

User: "Привет! Как дела?"
Bot: "Привет! Всё отлично, чем могу помочь?"
Title: "Новый чат"

User: "Debug this React component that's not rendering"
Bot: "I see the issue. The component..."
Title: "React rendering bug"
</examples>

Output ONLY the title, nothing else."""


class TopicNamingService:
    """Service for generating and applying LLM-based topic names."""

    def __init__(
        self,
        model: Optional[str] = None,
        max_tokens: Optional[int] = None,
    ):
        """Initialize TopicNamingService.

        Args:
            model: Model to use for generation. Default: config.TOPIC_NAMING_MODEL
            max_tokens: Max tokens for title. Default: config.TOPIC_NAMING_MAX_TOKENS
        """
        self.model = model or config.TOPIC_NAMING_MODEL
        self.max_tokens = max_tokens or config.TOPIC_NAMING_MAX_TOKENS

    async def _check_balance(self, user_id: int) -> bool:
        """Check if user has positive balance for topic naming.

        Args:
            user_id: Telegram user ID.

        Returns:
            True if user can afford topic naming, False otherwise.
        """
        cached_user = await get_cached_user(user_id)
        if cached_user:
            return cached_user.balance > Decimal("0")

        # If not cached, assume we can proceed (will check in charge)
        return True

    async def generate_title(
        self,
        user_message: str,
        bot_response: str,
    ) -> tuple[str, int, int]:
        """Generate topic title from conversation context.

        Args:
            user_message: First user message in the topic.
            bot_response: Bot's response to the message.

        Returns:
            Tuple of (title, input_tokens, output_tokens).
        """
        # Truncate to save tokens (first 300 chars is enough for context)
        user_text = user_message[:300]
        bot_text = bot_response[:300]

        client = get_anthropic_async_client()

        response = await client.messages.create(
            model=self.model,
            max_tokens=self.max_tokens,
            system=TOPIC_NAMING_SYSTEM_PROMPT,
            messages=[{
                "role": "user",
                "content": f"User: {user_text}\nBot: {bot_text}"
            }],
        )

        title = response.content[0].text.strip()

        # Remove quotes if LLM wrapped the title
        if title.startswith('"') and title.endswith('"'):
            title = title[1:-1]
        if title.startswith("'") and title.endswith("'"):
            title = title[1:-1]

        # Enforce max length (Telegram limit: 128, but we want shorter)
        title = title[:50]

        # Extract token usage
        input_tokens = response.usage.input_tokens
        output_tokens = response.usage.output_tokens

        return title, input_tokens, output_tokens

    async def maybe_name_topic(
        self,
        bot: Bot,
        thread: Thread,
        user_message: str,
        bot_response: str,
        session: AsyncSession,
    ) -> Optional[str]:
        """Generate and apply topic name if needed.

        This operation:
        - Checks user balance before LLM call
        - Charges user for the API call
        - Records metrics for Grafana
        - Falls back to keeping default name if balance insufficient

        Args:
            bot: Telegram Bot instance.
            thread: Thread to name.
            user_message: First user message.
            bot_response: Bot's response.
            session: Database session.

        Returns:
            Generated title if applied, None otherwise.
        """
        # Check if naming is needed
        if not thread.needs_topic_naming:
            return None

        # Check if feature is enabled
        if not config.TOPIC_NAMING_ENABLED:
            logger.debug("topic_naming.disabled")
            return None

        # Check if this is a topic (has thread_id)
        if thread.thread_id is None:
            logger.debug("topic_naming.not_a_topic", thread_id=thread.id)
            thread.needs_topic_naming = False
            return None

        user_id = thread.user_id

        # Check balance before LLM call
        has_balance = await self._check_balance(user_id)
        if not has_balance:
            logger.info(
                "topic_naming.skipped_insufficient_balance",
                thread_id=thread.id,
                user_id=user_id,
            )
            # Keep default Telegram name, mark as done
            thread.needs_topic_naming = False
            return None

        try:
            # Generate title
            title, input_tokens, output_tokens = await self.generate_title(
                user_message, bot_response)

            # Calculate cost
            cost_usd = calculate_claude_cost(
                model_id=self.model,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
            )

            logger.info(
                "topic_naming.title_generated",
                thread_id=thread.id,
                telegram_thread_id=thread.thread_id,
                title=title,
                model=self.model,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                cost_usd=float(cost_usd),
            )

            # Record Prometheus metrics
            record_claude_request(model=self.model, success=True)
            record_claude_tokens(
                model=self.model,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                cache_read_tokens=0,
                cache_write_tokens=0,
            )
            record_cost(service="topic_naming", amount_usd=float(cost_usd))

            # Charge user
            try:
                user_repo = UserRepository(session)
                balance_op_repo = BalanceOperationRepository(session)
                balance_service = BalanceService(session, user_repo,
                                                 balance_op_repo)

                balance_after = await balance_service.charge_user(
                    user_id=user_id,
                    amount=cost_usd,
                    description=(f"Topic naming: {input_tokens} input + "
                                 f"{output_tokens} output tokens"),
                    related_message_id=None,
                )

                # Update cached balance
                await update_cached_balance(user_id, balance_after)

                logger.info(
                    "topic_naming.user_charged",
                    user_id=user_id,
                    cost_usd=float(cost_usd),
                    balance_after=float(balance_after),
                )

            except Exception as charge_error:
                # Log but continue - naming already happened
                logger.warning(
                    "topic_naming.charge_failed",
                    user_id=user_id,
                    cost_usd=float(cost_usd),
                    error=str(charge_error),
                )

            # Apply title via Telegram API
            await bot.edit_forum_topic(
                chat_id=thread.chat_id,
                message_thread_id=thread.thread_id,
                name=title,
            )

            logger.info(
                "topic_naming.title_applied",
                thread_id=thread.id,
                chat_id=thread.chat_id,
                telegram_thread_id=thread.thread_id,
                title=title,
            )

            # Update thread in database
            thread.title = title
            thread.needs_topic_naming = False

            return title

        except Exception as e:
            # Log error but don't break the main flow
            logger.warning(
                "topic_naming.failed",
                thread_id=thread.id,
                telegram_thread_id=thread.thread_id,
                user_id=user_id,
                error=str(e),
                error_type=type(e).__name__,
            )
            # Keep needs_topic_naming=True to retry next time
            return None


# Global service instance (can be overridden in tests)
_topic_naming_service: Optional[TopicNamingService] = None


def get_topic_naming_service() -> TopicNamingService:
    """Get or create TopicNamingService instance.

    Returns:
        TopicNamingService singleton.
    """
    global _topic_naming_service  # pylint: disable=global-statement

    if _topic_naming_service is None:
        _topic_naming_service = TopicNamingService()

    return _topic_naming_service
