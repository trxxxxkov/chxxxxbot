"""Topic naming service for LLM-generated topic titles.

Bot API 9.3 added topics in private chats. This service generates
meaningful topic names based on conversation context.

Workflow:
1. User creates topic in Telegram (auto-generated name from first letters)
2. User sends first message → Thread created with needs_topic_naming=True
3. Bot responds (user had balance) → maybe_name_topic() called
4. LLM generates title → charge user → bot.edit_forum_topic() applies it
5. Thread.needs_topic_naming = False

If bot doesn't respond (command or insufficient balance), topic keeps
the default Telegram name.

NO __init__.py - use direct import:
    from services.topic_naming import TopicNamingService
"""

from decimal import Decimal
from typing import Optional

from aiogram import Bot
from cache.user_cache import update_cached_balance
import config
from core.clients import get_anthropic_async_client
from core.pricing import calculate_claude_cost
from core.pricing import calculate_provider_cost
from core.models import TokenUsage
from db.models.thread import Thread
from services.factory import ServiceFactory
from sqlalchemy.ext.asyncio import AsyncSession
from utils.metrics import record_cost
from utils.metrics import record_llm_request
from utils.metrics import record_llm_tokens
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
- Length: 3-6 words (max 50 characters)
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

    def _get_naming_model(self, user_model_id: str | None) -> tuple[str, str]:
        """Get the cheapest model for topic naming based on user's provider.

        Args:
            user_model_id: User's current model (e.g. "google:pro").

        Returns:
            Tuple of (model_id_for_api, provider_name).
        """
        if user_model_id:
            try:
                from config import get_model  # pylint: disable=import-outside-toplevel
                model_config = get_model(user_model_id)
                if model_config.provider == "google":
                    # Use Flash-Lite for Google users (~40% cheaper)
                    return "gemini-2.0-flash-lite", "google"
            except KeyError:
                pass
        return self.model, "claude"

    async def generate_title(
        self,
        user_message: str,
        bot_response: str,
        user_model_id: str | None = None,
    ) -> tuple[str, int, int, str]:
        """Generate topic title from conversation context.

        Uses the cheapest model matching the user's provider:
        Claude users → Haiku, Google users → Flash-Lite.

        Args:
            user_message: First user message in the topic.
            bot_response: Bot's response to the message.
            user_model_id: User's current model for provider detection.

        Returns:
            Tuple of (title, input_tokens, output_tokens, provider).
        """
        model_id, provider = self._get_naming_model(user_model_id)

        # Truncate to save tokens (first 300 chars is enough for context)
        user_text = user_message[:300]
        bot_text = bot_response[:300]
        prompt_content = f"User: {user_text}\nBot: {bot_text}"

        if provider == "google":
            title, input_tokens, output_tokens = await self._generate_title_google(
                model_id, prompt_content)
        else:
            title, input_tokens, output_tokens = await self._generate_title_claude(
                model_id, prompt_content)

        # Remove quotes if LLM wrapped the title
        if title.startswith('"') and title.endswith('"'):
            title = title[1:-1]
        if title.startswith("'") and title.endswith("'"):
            title = title[1:-1]

        # Enforce max length (Telegram limit: 128, but we want shorter)
        title = title[:50]

        return title, input_tokens, output_tokens, provider

    async def _generate_title_claude(
        self,
        model_id: str,
        prompt_content: str,
    ) -> tuple[str, int, int]:
        """Generate title via Claude API."""
        client = get_anthropic_async_client()

        response = await client.messages.create(
            model=model_id,
            max_tokens=self.max_tokens,
            system=TOPIC_NAMING_SYSTEM_PROMPT,
            messages=[{
                "role": "user",
                "content": prompt_content,
            }],
        )

        title = response.content[0].text.strip()
        return title, response.usage.input_tokens, response.usage.output_tokens

    async def _generate_title_google(
        self,
        model_id: str,
        prompt_content: str,
    ) -> tuple[str, int, int]:
        """Generate title via Google Gemini API."""
        import asyncio  # pylint: disable=import-outside-toplevel
        from core.clients import get_google_client  # pylint: disable=import-outside-toplevel
        from google.genai import types as genai_types  # pylint: disable=import-outside-toplevel

        client = get_google_client()

        gen_config = genai_types.GenerateContentConfig(
            system_instruction=TOPIC_NAMING_SYSTEM_PROMPT,
            max_output_tokens=self.max_tokens,
            temperature=0.3,
        )

        def _sync_generate():
            return client.models.generate_content(
                model=model_id,
                contents=[{
                    "role": "user",
                    "parts": [{"text": prompt_content}],
                }],
                config=gen_config,
            )

        response = await asyncio.to_thread(_sync_generate)

        # Extract text
        title = ""
        if response.candidates and response.candidates[0].content:
            for part in response.candidates[0].content.parts:
                if part.text:
                    title += part.text
        title = title.strip()

        # Extract usage
        input_tokens = 0
        output_tokens = 0
        if hasattr(response, 'usage_metadata') and response.usage_metadata:
            meta = response.usage_metadata
            input_tokens = getattr(meta, 'prompt_token_count', 0) or 0
            output_tokens = getattr(meta, 'candidates_token_count', 0) or 0

        return title, input_tokens, output_tokens

    async def maybe_name_topic(
        self,
        bot: Bot,
        thread: Thread,
        user_message: str,
        bot_response: str,
        session: AsyncSession,
        user_model_id: str | None = None,
    ) -> Optional[str]:
        """Generate and apply topic name if needed.

        Called after bot's first response in a topic. Since the bot
        responded, user had sufficient balance for the main response,
        so we can proceed with topic naming (~$0.0003).

        Uses cheapest model matching user's provider:
        Claude users → Haiku (~$0.0006), Google users → Flash-Lite (~$0.00035).

        Args:
            bot: Telegram Bot instance.
            thread: Thread to name.
            user_message: First user message.
            bot_response: Bot's response.
            session: Database session.
            user_model_id: User's current model for provider detection.

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

        try:
            # Generate title (provider-aware)
            title, input_tokens, output_tokens, provider = (
                await self.generate_title(
                    user_message, bot_response,
                    user_model_id=user_model_id))

            # Calculate cost (provider-aware)
            naming_model, _ = self._get_naming_model(user_model_id)
            if provider == "claude":
                cost_usd = calculate_claude_cost(
                    model_id=naming_model,
                    input_tokens=input_tokens,
                    output_tokens=output_tokens,
                )
            else:
                # Google and other providers: simple pricing
                naming_model_full = (
                    "google:flash-lite" if provider == "google"
                    else user_model_id or "claude:haiku")
                cost_usd = calculate_provider_cost(
                    naming_model_full,
                    TokenUsage(
                        input_tokens=input_tokens,
                        output_tokens=output_tokens))

            logger.info(
                "topic_naming.title_generated",
                thread_id=thread.id,
                telegram_thread_id=thread.thread_id,
                title=title,
                provider=provider,
                model=naming_model,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                cost_usd=float(cost_usd),
            )

            # Record Prometheus metrics
            record_llm_request(model=naming_model, success=True)
            record_llm_tokens(
                model=naming_model,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                cache_read_tokens=0,
                cache_write_tokens=0,
            )
            record_cost(service="topic_naming", amount_usd=float(cost_usd))

            # Log cost BEFORE charge so Grafana sees it even if charge fails
            logger.info(
                "topic_naming.user_charged",
                user_id=user_id,
                cost_usd=float(cost_usd),
            )

            # Charge user
            try:
                services = ServiceFactory(session)

                balance_after = await services.balance.charge_user(
                    user_id=user_id,
                    amount=cost_usd,
                    description=(f"Topic naming: {input_tokens} input + "
                                 f"{output_tokens} output tokens"),
                    related_message_id=None,
                )

                # Update cached balance
                await update_cached_balance(user_id, balance_after)

                logger.info(
                    "topic_naming.charge_success",
                    user_id=user_id,
                    cost_usd=float(cost_usd),
                    balance_after=float(balance_after),
                )

            except Exception as charge_error:
                # CRITICAL: naming happened but we failed to charge
                logger.error(
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
            # External API error - don't break the main flow
            logger.info(
                "topic_naming.failed",
                thread_id=thread.id,
                telegram_thread_id=thread.thread_id,
                user_id=user_id,
                error=str(e),
                error_type=type(e).__name__,
            )
            # Keep needs_topic_naming=True to retry next time
            return None


from core.singleton import singleton


@singleton
def get_topic_naming_service() -> TopicNamingService:
    """Get or create TopicNamingService instance.

    Returns:
        TopicNamingService singleton.
    """
    return TopicNamingService()
