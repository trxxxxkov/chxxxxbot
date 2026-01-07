# Claude Integration

**Status:** Phase 1.3 ✅ COMPLETE | Next: Phase 1.4 (Multimodal + Tools)

Comprehensive plan for integrating Claude API with streaming, multimodal support, tools, and payment system.

---

## Table of Contents

- [Overview](#overview)
- [Phase 1.3: Core Integration](#phase-13-core-integration)
- [Phase 1.4: Multimodal + Tools](#phase-14-multimodal--tools)
- [Phase 2.1: Payment System](#phase-21-payment-system)
- [Architecture](#architecture)
- [Implementation Plan](#implementation-plan)
- [API Documentation Links](#api-documentation-links)

---

## Overview

### Goals

1. **Phase 1.3 (Core):** Basic text conversations with Claude (streaming)
2. **Phase 1.4 (Multimodal + Tools):** Images, voice, files, code execution, image generation
3. **Phase 2.1 (Payment):** Telegram Stars, user balance, cost blocking

### Principles

- **Streaming-first:** All providers must support streaming (no buffering)
- **Token-based context:** Use all messages that fit in model's context window
- **Modular tools:** Easy to add new tools without rewriting code
- **Cost tracking:** Every API call tracked for billing
- **Comprehensive logging:** Full observability for LLM agent debugging

---

## Phase 1.3: Core Integration

### Scope

**In scope:**
- Text-only conversations
- Real-time streaming (no buffering - each chunk immediately to Telegram)
- Thread-based context (all messages that fit in token window)
- Global system prompt (one for all users)
- Basic cost tracking (input/output tokens)
- Comprehensive logging (all API calls, timing, errors)
- Error handling (rate limits, timeouts, API errors)
- Long message splitting (> 4096 chars)

**Out of scope:**
- Multimodal (images, voice, files)
- Tools (code execution, image generation)
- Payment system (balance blocking)
- Prompt caching
- User-selectable models (one model hardcoded)
- Per-thread system prompts

---

### Architecture

#### File Structure

```
bot/core/
├── base.py                     # Abstract LLMProvider interface
├── exceptions.py               # Custom exceptions
├── models.py                   # Pydantic models (Request, Response, Usage)
└── claude/
    ├── client.py               # Claude API client
    ├── config.py               # Model configs, pricing, limits
    └── context.py              # Context management, token counting
```

---

### Components

#### 1. Base Provider Interface (`bot/core/base.py`)

Abstract class for all LLM providers.

```python
from abc import ABC, abstractmethod
from typing import AsyncIterator, Optional
from core.models import LLMRequest, LLMResponse, TokenUsage

class LLMProvider(ABC):
    """Abstract interface for LLM providers."""

    @abstractmethod
    async def stream_message(
        self,
        request: LLMRequest
    ) -> AsyncIterator[str]:
        """Stream response tokens.

        Yields:
            Text chunks as they arrive (no buffering).
        """
        pass

    @abstractmethod
    async def get_token_count(self, text: str) -> int:
        """Count tokens in text."""
        pass

    @abstractmethod
    async def get_usage(self) -> TokenUsage:
        """Get last request token usage."""
        pass
```

**Key design decisions:**
- Streaming-only (no non-streaming method)
- Returns `AsyncIterator[str]` - raw text chunks
- Token counting method for context management
- Usage tracking separate from streaming

---

#### 2. Data Models (`bot/core/models.py`)

```python
from pydantic import BaseModel
from typing import List, Optional

class Message(BaseModel):
    """Single message in conversation."""
    role: str  # "user" or "assistant"
    content: str

class LLMRequest(BaseModel):
    """Request to LLM provider."""
    messages: List[Message]
    system_prompt: Optional[str] = None
    model: str
    max_tokens: int = 4096
    temperature: float = 1.0

class TokenUsage(BaseModel):
    """Token usage stats."""
    input_tokens: int
    output_tokens: int
    cache_read_tokens: int = 0  # For Phase 1.4
    cache_creation_tokens: int = 0  # For Phase 1.4

class LLMResponse(BaseModel):
    """Complete response metadata."""
    content: str
    usage: TokenUsage
    model: str
    stop_reason: str  # "end_turn", "max_tokens", "stop_sequence"
```

---

#### 3. Claude Client (`bot/core/claude/client.py`)

Main implementation of Claude API integration.

**Responsibilities:**
- Initialize Anthropic SDK client
- Stream messages using `client.messages.stream()`
- Track token usage
- Handle errors (429, timeouts, API errors)
- Log all operations

**Key methods:**
```python
class ClaudeProvider(LLMProvider):
    def __init__(self, api_key: str):
        self.client = anthropic.AsyncAnthropic(api_key=api_key)
        self.last_usage: Optional[TokenUsage] = None
        self.logger = get_logger(__name__)

    async def stream_message(self, request: LLMRequest) -> AsyncIterator[str]:
        """Stream response from Claude API."""
        # Convert LLMRequest to Anthropic format
        # Use async with client.messages.stream() as stream
        # Yield text chunks as they arrive
        # Track usage after stream completes
        pass
```

**Error handling:**
- `anthropic.RateLimitError` (429) → log, re-raise with user-friendly message
- `anthropic.APIConnectionError` → log, re-raise
- `anthropic.APITimeoutError` → log, re-raise
- Generic exceptions → log with full traceback, re-raise

**Logging:**
```python
logger.info("claude.stream.start",
            model=request.model,
            message_count=len(request.messages),
            system_prompt_length=len(request.system_prompt or ""))

# During streaming
logger.debug("claude.stream.chunk", chunk_length=len(text))

# After completion
logger.info("claude.stream.complete",
            model=request.model,
            input_tokens=usage.input_tokens,
            output_tokens=usage.output_tokens,
            duration_ms=duration)
```

---

#### 4. Context Management (`bot/core/claude/context.py`)

Manages conversation context with token limits.

**Key logic:**
```python
class ContextManager:
    def __init__(self, provider: LLMProvider):
        self.provider = provider

    async def build_context(
        self,
        messages: List[Message],  # From MessageRepository
        model_context_window: int  # e.g., 200000 for claude-sonnet-4.5
    ) -> List[Message]:
        """Build context that fits in model's window.

        Algorithm:
        1. Count tokens for all messages (newest to oldest)
        2. Include messages until hitting context_window limit
        3. Return messages in chronological order (oldest first)

        Args:
            messages: All messages from thread (oldest first)
            model_context_window: Max tokens for model

        Returns:
            Messages that fit in context window
        """
        # Start from newest message
        # Count tokens backwards
        # Stop when exceeding limit
        # Return in original order
        pass
```

**Token counting:**
- Use Claude tokenizer (from `anthropic` SDK or estimate)
- Count system prompt separately
- Reserve tokens for response (model's max_tokens)
- Reserve ~10% buffer for safety

**Example:**
```
Context window: 200,000 tokens
System prompt: 500 tokens
Reserved for output: 4,096 tokens
Buffer (10%): 20,000 tokens
---
Available for history: 175,404 tokens
```

---

#### 5. Configuration (`bot/core/claude/config.py`)

Model configurations and pricing.

```python
from dataclasses import dataclass

@dataclass
class ModelConfig:
    """Configuration for a Claude model."""
    name: str
    display_name: str
    context_window: int  # Max input tokens
    max_output_tokens: int  # Max output tokens
    input_price_per_mtok: float  # Price per million input tokens (USD)
    output_price_per_mtok: float  # Price per million output tokens (USD)

# Global model registry
CLAUDE_MODELS = {
    "claude-sonnet-4.5": ModelConfig(
        name="claude-sonnet-4-5-20250929",
        display_name="Claude Sonnet 4.5",
        context_window=200_000,
        max_output_tokens=8_192,
        input_price_per_mtok=3.0,   # Check actual pricing
        output_price_per_mtok=15.0  # Check actual pricing
    ),
    # More models can be added later
}

# Default model for Phase 1.3
DEFAULT_MODEL = "claude-sonnet-4.5"

# Global system prompt (same for all users)
GLOBAL_SYSTEM_PROMPT = """You are a helpful AI assistant..."""
```

**Note:** Pricing will be verified during implementation by checking official Anthropic documentation.

---

#### 6. Custom Exceptions (`bot/core/exceptions.py`)

```python
class LLMError(Exception):
    """Base exception for LLM errors."""
    pass

class RateLimitError(LLMError):
    """Rate limit exceeded (429)."""
    pass

class APIConnectionError(LLMError):
    """Failed to connect to API."""
    pass

class APITimeoutError(LLMError):
    """API request timed out."""
    pass

class ContextWindowExceededError(LLMError):
    """Context exceeds model's window."""
    pass

class InsufficientBalanceError(LLMError):
    """User has insufficient balance (Phase 2.1)."""
    pass
```

---

### Telegram Integration

#### Handler: Claude Conversation (`bot/telegram/handlers/claude.py`)

Replaces echo handler. Handles all text messages.

**Flow:**
1. Receive message from user
2. Save user message to database (MessageRepository)
3. Get thread history (MessageRepository.get_thread_messages)
4. Build context (ContextManager.build_context)
5. Start streaming from Claude
6. Send initial empty message to Telegram
7. Update message as chunks arrive (edit_text)
8. Save final response to database
9. Log usage (input/output tokens)

**Pseudo-code:**
```python
@router.message(F.text)
async def handle_claude_message(
    message: types.Message,
    session: AsyncSession
):
    # 1. Save user message
    user_repo = UserRepository(session)
    user, _ = await user_repo.get_or_create(...)

    msg_repo = MessageRepository(session)
    await msg_repo.create_message(
        chat_id=message.chat.id,
        message_id=message.message_id,
        from_user_id=user.id,
        text_content=message.text,
        ...
    )

    # 2. Get thread
    thread_repo = ThreadRepository(session)
    thread, _ = await thread_repo.get_or_create_thread(...)

    # 3. Get history
    history = await msg_repo.get_thread_messages(thread.id)

    # 4. Build context
    context_mgr = ContextManager(claude_provider)
    context = await context_mgr.build_context(
        messages=history,
        model_context_window=200_000
    )

    # 5. Stream from Claude
    request = LLMRequest(
        messages=context,
        system_prompt=GLOBAL_SYSTEM_PROMPT,
        model=DEFAULT_MODEL
    )

    # 6. Send typing indicator
    await message.bot.send_chat_action(message.chat.id, "typing")

    # 7. Stream response
    response_text = ""
    bot_message = None

    async for chunk in claude_provider.stream_message(request):
        response_text += chunk

        # Split if exceeds Telegram limit
        if len(response_text) > 4000:
            # Send current part
            if bot_message is None:
                bot_message = await message.answer(response_text[:4000])
            else:
                await bot_message.edit_text(response_text[:4000])

            # Continue with rest
            response_text = response_text[4000:]
        else:
            # Update message
            if bot_message is None:
                bot_message = await message.answer(response_text)
            else:
                await bot_message.edit_text(response_text)

    # 8. Save response
    usage = await claude_provider.get_usage()
    await msg_repo.create_message(
        chat_id=message.chat.id,
        message_id=bot_message.message_id,
        from_user_id=None,  # Bot message
        thread_id=thread.id,
        text_content=response_text,
        input_tokens=usage.input_tokens,
        output_tokens=usage.output_tokens
    )
```

**Error handling:**
- Catch all LLM exceptions
- Send user-friendly error message
- Log full error with traceback

**Long message handling:**
- If response > 4096 chars: send multiple messages
- Keep editing first message until 4096 limit
- Send additional messages for overflow

---

### Secrets and Configuration

#### New Secret: `claude_api_key`

**File:** `secrets/claude_api_key`

**Usage in code:**
```python
# In main.py
def read_secret(name: str) -> str:
    path = Path(f"/run/secrets/{name}")
    return path.read_text(encoding='utf-8').strip()

claude_api_key = read_secret("claude_api_key")
```

#### Updated `config.py`

Add Claude-specific settings:
```python
# Claude settings
CLAUDE_DEFAULT_MODEL = "claude-sonnet-4-5-20250929"
CLAUDE_MAX_TOKENS = 4096
CLAUDE_TEMPERATURE = 1.0
CLAUDE_TIMEOUT = 60  # seconds
```

---

### Database Changes

No schema changes needed! Existing models already support:
- `Message.input_tokens` - Claude input tokens
- `Message.output_tokens` - Claude output tokens
- `Thread.system_prompt` - Per-thread prompts (Phase 1.4)
- `Thread.model_name` - Model selection (Phase 1.4)

---

### Testing Strategy

**Unit tests:**
- `test_claude_client.py` - Mock Anthropic API, test streaming
- `test_context_manager.py` - Token counting, context building
- `test_provider_interface.py` - Interface compliance

**Integration tests:**
- `test_claude_integration.py` - Real API calls (with test key)
- `test_telegram_handler.py` - Mock Telegram, test flow

**Manual testing:**
- Real conversations with bot
- Long context threads (test token limits)
- Long responses (test message splitting)
- Error scenarios (invalid API key, rate limits)

---

### Implementation Checklist

- [ ] Create `bot/core/base.py` - LLMProvider interface
- [ ] Create `bot/core/models.py` - Pydantic models
- [ ] Create `bot/core/exceptions.py` - Custom exceptions
- [ ] Create `bot/core/claude/config.py` - Model configs
- [ ] Create `bot/core/claude/context.py` - Context management
- [ ] Create `bot/core/claude/client.py` - Claude API client
- [ ] Create `bot/telegram/handlers/claude.py` - Handler
- [ ] Update `bot/telegram/loader.py` - Register handler
- [ ] Update `bot/config.py` - Claude settings
- [ ] Update `bot/main.py` - Read claude_api_key secret
- [ ] Add `anthropic` to dependencies (Dockerfile)
- [ ] Create `secrets/claude_api_key` file
- [ ] Write tests (unit + integration)
- [ ] Manual testing with real API
- [ ] Update documentation

---

## Phase 1.4: Multimodal + Tools

### Scope

**Multimodal support:**
- Images (vision) - user sends photo, Claude analyzes
- Voice messages - transcribe + process
- Arbitrary files - process via tools

**Tools framework:**
- Abstract Tool interface
- Tool registry (easy to add/remove tools)
- Code execution tool (isolated Docker container)
- Image generation tool (external API)
- File processing tools

**Optimizations:**
- Prompt caching (cache system prompt)
- Extended thinking (for complex reasoning tasks)

**Documentation phase:**
- Read full Claude API documentation
- Document each API feature with link
- Note best practices and patterns
- Update this document with links

---

### Multimodal Architecture

#### Vision (Images)

**Flow:**
1. User sends photo to Telegram
2. Download photo from Telegram
3. Encode to base64 (or use URL if available)
4. Add to Claude API request as image content block
5. Claude analyzes image
6. Save image metadata in Message.attachments (JSONB)

**API format:**
```python
{
    "role": "user",
    "content": [
        {
            "type": "image",
            "source": {
                "type": "base64",
                "media_type": "image/jpeg",
                "data": "..."
            }
        },
        {
            "type": "text",
            "text": "What's in this image?"
        }
    ]
}
```

#### Voice Messages

**Flow:**
1. User sends voice message to Telegram
2. Download voice file
3. Transcribe using external API (Whisper API or similar)
4. Send transcribed text to Claude
5. Save audio metadata in Message.attachments

**Alternative:** Use Claude's audio support if available (check API docs)

#### Arbitrary Files

**Flow:**
1. User sends file to Telegram
2. Download file
3. Process file using appropriate tool:
   - Code files → code execution tool
   - Documents → text extraction tool
   - Data files → analysis tool
4. Include processed content in Claude request

---

### Tools Framework

#### Abstract Tool Interface

```python
from abc import ABC, abstractmethod
from typing import Any, Dict

class Tool(ABC):
    """Abstract tool interface."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Tool name for Claude."""
        pass

    @property
    @abstractmethod
    def description(self) -> str:
        """Tool description for Claude."""
        pass

    @property
    @abstractmethod
    def input_schema(self) -> Dict[str, Any]:
        """JSON schema for tool input."""
        pass

    @abstractmethod
    async def execute(self, **kwargs) -> str:
        """Execute tool and return result."""
        pass
```

#### Tool Registry

```python
class ToolRegistry:
    """Central registry for all tools."""

    def __init__(self):
        self._tools: Dict[str, Tool] = {}

    def register(self, tool: Tool):
        """Register a tool."""
        self._tools[tool.name] = tool

    def get_tool_schemas(self) -> List[Dict]:
        """Get tool schemas for Claude API."""
        return [
            {
                "name": tool.name,
                "description": tool.description,
                "input_schema": tool.input_schema
            }
            for tool in self._tools.values()
        ]

    async def execute_tool(self, name: str, **kwargs) -> str:
        """Execute a tool by name."""
        tool = self._tools.get(name)
        if not tool:
            raise ValueError(f"Unknown tool: {name}")
        return await tool.execute(**kwargs)
```

#### Example Tool: Code Execution

```python
class CodeExecutionTool(Tool):
    """Execute code in isolated container."""

    @property
    def name(self) -> str:
        return "execute_code"

    @property
    def description(self) -> str:
        return "Execute Python code in isolated container"

    @property
    def input_schema(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "code": {
                    "type": "string",
                    "description": "Python code to execute"
                }
            },
            "required": ["code"]
        }

    async def execute(self, code: str) -> str:
        """Execute code in Docker container."""
        # Use Docker API to run code
        # Return stdout/stderr
        # Handle errors
        pass
```

---

### Tool Execution Flow

1. Claude requests tool use during streaming
2. Pause streaming, extract tool request
3. Execute tool via ToolRegistry
4. Send tool result back to Claude
5. Claude continues streaming with tool result

**API flow:**
```python
async for event in stream:
    if event.type == "content_block_delta":
        # Regular text chunk
        yield event.delta.text

    elif event.type == "tool_use":
        # Claude wants to use a tool
        tool_name = event.name
        tool_input = event.input

        # Execute tool
        result = await tool_registry.execute_tool(
            tool_name,
            **tool_input
        )

        # Continue conversation with tool result
        # (requires new API call to Claude)
```

---

### Prompt Caching

**Goal:** Cache system prompt to reduce costs and latency

**Implementation:**
```python
# Mark system prompt for caching
request = {
    "model": "claude-sonnet-4-5-20250929",
    "max_tokens": 4096,
    "system": [
        {
            "type": "text",
            "text": GLOBAL_SYSTEM_PROMPT,
            "cache_control": {"type": "ephemeral"}
        }
    ],
    "messages": [...]
}
```

**Benefits:**
- Reduced input tokens (cached system prompt not counted)
- Faster response (no need to reprocess system prompt)
- Lower cost (cache read tokens cheaper than input tokens)

**Cache lifetime:** Check Claude API docs for exact duration (typically 5 minutes)

---

### Extended Thinking

**Goal:** Better reasoning for complex tasks

**Implementation:**
```python
request = {
    "model": "claude-sonnet-4-5-20250929",
    "max_tokens": 4096,
    "thinking": {
        "type": "enabled",
        "budget_tokens": 2000  # Tokens for internal thinking
    },
    "messages": [...]
}
```

**Use cases:**
- Complex code generation
- Multi-step reasoning
- Mathematical proofs
- Detailed analysis

---

### Documentation Process for Phase 1.4

**Workflow:**
1. User provides link to Claude API docs page
2. Read entire page using WebFetch or WebSearch
3. Discuss page content with user
4. Document adopted patterns in this file under "API Documentation Links"
5. Link to page with summary of what was adopted
6. Repeat for all pages

**Pages to cover:**
- Messages API
- Streaming
- Vision (images)
- Tool use
- Prompt caching
- Extended thinking
- Error handling
- Best practices

---

## Phase 2.1: Payment System

### Scope

**User balance:**
- Add `balance` field to User model (Decimal, USD)
- Track all costs in real-time
- Block requests if balance insufficient

**Telegram Stars integration:**
- Payment flow (user deposits via Stars)
- Stars → USD conversion
- Invoice generation
- Refund mechanism (by transaction_id)

**Admin features:**
- Privileged users list (in Docker secrets)
- Commands: `/balance`, `/addbalance`, `/setbalance`
- Balance management by username or user_id

**Cost tracking:**
- Every API call logged with cost
- Per-user cost aggregation
- Cost reporting (per day, per month, per user)

---

### Database Changes

#### User Model Updates

```python
# Add to bot/db/models/user.py
from decimal import Decimal
from sqlalchemy import Numeric

class User(Base, TimestampMixin):
    # ... existing fields ...

    balance: Mapped[Decimal] = mapped_column(
        Numeric(10, 2),  # 10 digits, 2 decimals (e.g., 9999999.99)
        nullable=False,
        default=0.00,
        doc="User balance in USD"
    )
```

#### New Model: Transaction

Track all balance changes.

```python
class Transaction(Base, TimestampMixin):
    """Balance transaction (deposit, charge, refund)."""

    __tablename__ = "transactions"

    id: Mapped[int] = mapped_column(
        Integer().with_variant(BigInteger, "postgresql"),
        primary_key=True,
        autoincrement=True
    )

    user_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False
    )

    type: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        doc="deposit, charge, refund, admin_adjustment"
    )

    amount: Mapped[Decimal] = mapped_column(
        Numeric(10, 2),
        nullable=False,
        doc="Amount in USD (positive or negative)"
    )

    balance_after: Mapped[Decimal] = mapped_column(
        Numeric(10, 2),
        nullable=False,
        doc="User balance after transaction"
    )

    description: Mapped[str] = mapped_column(
        Text,
        nullable=True,
        doc="Transaction description"
    )

    # For Telegram Stars deposits
    telegram_payment_charge_id: Mapped[Optional[str]] = mapped_column(
        String(255),
        nullable=True,
        doc="Telegram payment charge ID (for refunds)"
    )

    # For LLM API charges
    message_id: Mapped[Optional[int]] = mapped_column(
        Integer,
        nullable=True,
        doc="Message that caused this charge"
    )

    # Admin adjustments
    admin_user_id: Mapped[Optional[int]] = mapped_column(
        BigInteger,
        nullable=True,
        doc="Admin who made adjustment"
    )
```

---

### Cost Calculation

#### Pre-request Cost Estimation

Before sending request to Claude:

```python
async def estimate_cost(
    context_tokens: int,
    max_output_tokens: int,
    model: str
) -> Decimal:
    """Estimate minimum cost for request.

    Uses input tokens (known) + assume max output tokens (worst case).
    """
    config = CLAUDE_MODELS[model]

    input_cost = (context_tokens / 1_000_000) * config.input_price_per_mtok
    output_cost = (max_output_tokens / 1_000_000) * config.output_price_per_mtok

    return Decimal(input_cost + output_cost)
```

#### Balance Validation

```python
async def validate_balance(
    user: User,
    estimated_cost: Decimal
) -> bool:
    """Check if user has sufficient balance."""
    return user.balance >= estimated_cost
```

#### Actual Cost Tracking

After request completes:

```python
async def charge_user(
    user: User,
    usage: TokenUsage,
    model: str,
    message_id: int,
    session: AsyncSession
):
    """Charge user for actual usage."""
    config = CLAUDE_MODELS[model]

    input_cost = (usage.input_tokens / 1_000_000) * config.input_price_per_mtok
    output_cost = (usage.output_tokens / 1_000_000) * config.output_price_per_mtok
    total_cost = Decimal(input_cost + output_cost)

    # Update user balance
    user.balance -= total_cost

    # Create transaction record
    transaction = Transaction(
        user_id=user.id,
        type="charge",
        amount=-total_cost,
        balance_after=user.balance,
        description=f"Claude API call ({usage.input_tokens} in, {usage.output_tokens} out)",
        message_id=message_id
    )

    session.add(transaction)
    await session.flush()
```

---

### Telegram Stars Integration

#### Payment Flow

1. User sends `/deposit <amount>` command (amount in Stars)
2. Bot generates invoice using `create_invoice_link()`
3. User pays via Telegram
4. Bot receives `pre_checkout_query` → validate
5. Bot receives `successful_payment` → credit balance
6. Log transaction with `telegram_payment_charge_id`

**Code sketch:**
```python
@router.message(Command("deposit"))
async def handle_deposit(message: types.Message):
    # Parse amount
    amount_stars = int(message.text.split()[1])

    # Create invoice
    invoice_link = await message.bot.create_invoice_link(
        title="Balance Deposit",
        description=f"Deposit {amount_stars} Stars",
        payload=f"deposit:{message.from_user.id}",
        provider_token="",  # Empty for Telegram Stars
        currency="XTR",  # Telegram Stars
        prices=[types.LabeledPrice(label="Deposit", amount=amount_stars)]
    )

    await message.answer(f"Pay here: {invoice_link}")

@router.pre_checkout_query()
async def handle_pre_checkout(query: types.PreCheckoutQuery):
    # Validate payment
    await query.answer(ok=True)

@router.message(F.successful_payment)
async def handle_successful_payment(message: types.Message):
    # Credit user balance
    amount_stars = message.successful_payment.total_amount
    amount_usd = amount_stars * STARS_TO_USD_RATE  # Define conversion rate

    user.balance += Decimal(amount_usd)

    # Log transaction
    transaction = Transaction(
        user_id=user.id,
        type="deposit",
        amount=Decimal(amount_usd),
        balance_after=user.balance,
        description=f"Telegram Stars deposit ({amount_stars} stars)",
        telegram_payment_charge_id=message.successful_payment.telegram_payment_charge_id
    )
```

#### Refund Flow

Admin command: `/refund <transaction_id>`

```python
@router.message(Command("refund"))
async def handle_refund(message: types.Message):
    # Verify admin
    if message.from_user.id not in ADMIN_IDS:
        return await message.answer("Unauthorized")

    # Get transaction
    transaction_id = int(message.text.split()[1])
    transaction = await transaction_repo.get_by_id(transaction_id)

    if not transaction.telegram_payment_charge_id:
        return await message.answer("Not a Stars payment")

    # Refund via Telegram
    await message.bot.refund_star_payment(
        user_id=transaction.user_id,
        telegram_payment_charge_id=transaction.telegram_payment_charge_id
    )

    # Deduct from user balance
    user.balance -= transaction.amount

    # Log refund transaction
    refund_tx = Transaction(
        user_id=user.id,
        type="refund",
        amount=-transaction.amount,
        balance_after=user.balance,
        description=f"Refund of transaction {transaction_id}"
    )
```

---

### Admin Commands

**Privileged users:** Store in `secrets/admin_user_ids` (comma-separated)

#### `/balance [username|user_id]`

Check balance of any user.

```python
@router.message(Command("balance"))
async def handle_balance(message: types.Message, session: AsyncSession):
    if message.from_user.id not in ADMIN_IDS:
        # Regular user - show own balance
        user = await user_repo.get_by_telegram_id(message.from_user.id)
        return await message.answer(f"Balance: ${user.balance:.2f}")

    # Admin - show target user balance
    target = message.text.split()[1]  # username or user_id
    user = await user_repo.get_by_username_or_id(target)
    await message.answer(f"User {target} balance: ${user.balance:.2f}")
```

#### `/addbalance <username|user_id> <amount>`

Add to user's balance.

```python
@router.message(Command("addbalance"))
async def handle_add_balance(message: types.Message, session: AsyncSession):
    if message.from_user.id not in ADMIN_IDS:
        return await message.answer("Unauthorized")

    target, amount = message.text.split()[1:3]
    amount_usd = Decimal(amount)

    user = await user_repo.get_by_username_or_id(target)
    user.balance += amount_usd

    transaction = Transaction(
        user_id=user.id,
        type="admin_adjustment",
        amount=amount_usd,
        balance_after=user.balance,
        description=f"Admin adjustment by {message.from_user.username}",
        admin_user_id=message.from_user.id
    )

    session.add(transaction)
    await message.answer(f"Added ${amount_usd} to {target}. New balance: ${user.balance:.2f}")
```

#### `/setbalance <username|user_id> <amount>`

Set user's balance to specific amount.

```python
@router.message(Command("setbalance"))
async def handle_set_balance(message: types.Message, session: AsyncSession):
    if message.from_user.id not in ADMIN_IDS:
        return await message.answer("Unauthorized")

    target, amount = message.text.split()[1:3]
    new_balance = Decimal(amount)

    user = await user_repo.get_by_username_or_id(target)
    old_balance = user.balance
    user.balance = new_balance

    transaction = Transaction(
        user_id=user.id,
        type="admin_adjustment",
        amount=new_balance - old_balance,
        balance_after=user.balance,
        description=f"Balance set by {message.from_user.username}",
        admin_user_id=message.from_user.id
    )

    session.add(transaction)
    await message.answer(f"Set {target} balance to ${new_balance:.2f} (was ${old_balance:.2f})")
```

---

### Cost Reporting

**User command:** `/usage [period]`

Show cost breakdown for time period (today, week, month, all).

```python
@router.message(Command("usage"))
async def handle_usage(message: types.Message, session: AsyncSession):
    user = await user_repo.get_by_telegram_id(message.from_user.id)

    # Parse period
    period = message.text.split()[1] if len(message.text.split()) > 1 else "today"

    # Query transactions
    transactions = await transaction_repo.get_user_charges(
        user_id=user.id,
        period=period
    )

    total_cost = sum(abs(tx.amount) for tx in transactions if tx.type == "charge")

    await message.answer(
        f"Usage for {period}:\n"
        f"Total cost: ${total_cost:.2f}\n"
        f"Requests: {len(transactions)}\n"
        f"Current balance: ${user.balance:.2f}"
    )
```

---

## Architecture

### Overall System Design

```
User (Telegram)
    ↓
Telegram Handler (bot/telegram/handlers/claude.py)
    ↓
[Check balance] → UserRepository
    ↓
Context Manager (bot/core/claude/context.py)
    ↓
LLM Provider (bot/core/claude/client.py)
    ↓
Claude API (streaming)
    ↓
[Stream chunks] → Telegram (edit message)
    ↓
[Save response] → MessageRepository
    ↓
[Charge user] → TransactionRepository
```

---

### Key Design Decisions

1. **Streaming without buffering:** Each chunk immediately sent to Telegram
   - Better UX (user sees response in real-time)
   - No latency between Claude and user

2. **Token-based context window:** Include all messages that fit
   - Maximizes context utilization
   - Automatic handling of long threads
   - No arbitrary message limits

3. **Global system prompt (Phase 1.3):** One prompt for all users
   - Simpler implementation
   - Easier to cache (Phase 1.4)
   - Per-thread prompts deferred to Phase 1.4

4. **Pre-request cost validation:** Estimate before sending
   - Prevents overspending
   - Uses worst-case (max output tokens)
   - Actual charge after completion

5. **Transaction log:** All balance changes tracked
   - Full audit trail
   - Easy refunds (by transaction_id)
   - Cost analytics

6. **Modular tools:** Easy to add new tools
   - Abstract Tool interface
   - Central ToolRegistry
   - Each tool independent

---

## API Documentation Links

**Note:** This section will be populated during Phase 1.4 as we read through Claude API documentation.

Format for each entry:
```
### [Page Title]

**Link:** https://docs.anthropic.com/...

**What we adopted:**
- Feature/pattern 1
- Feature/pattern 2

**What we skipped:**
- Feature we didn't implement

**Implementation notes:**
- Code location: bot/core/...
- Key decisions: ...
```

---

## Implementation Plan

### Phase 1.3 Implementation Steps

1. **Setup infrastructure:**
   - Create `bot/core/` directory structure
   - Add `anthropic` to Dockerfile dependencies
   - Create `secrets/claude_api_key`

2. **Implement core components:**
   - `bot/core/base.py` - Abstract provider
   - `bot/core/models.py` - Data models
   - `bot/core/exceptions.py` - Custom exceptions
   - `bot/core/claude/config.py` - Model configs
   - `bot/core/claude/context.py` - Context management
   - `bot/core/claude/client.py` - Claude client

3. **Implement Telegram handler:**
   - `bot/telegram/handlers/claude.py` - Main handler
   - Update `bot/telegram/loader.py` - Register handler
   - Update `bot/main.py` - Initialize Claude provider

4. **Testing:**
   - Unit tests for each component
   - Integration test with real API
   - Manual testing with real conversations

5. **Documentation:**
   - Update CLAUDE.md with status
   - Update this document with implementation notes

### Phase 1.4 Implementation Steps

1. **Read Claude API documentation:**
   - Messages API
   - Streaming
   - Vision
   - Tool use
   - Prompt caching
   - Extended thinking
   - (Document each page in "API Documentation Links" section)

2. **Implement multimodal:**
   - Vision support (images)
   - Voice message handling
   - File processing

3. **Implement tools:**
   - Abstract Tool interface
   - ToolRegistry
   - Code execution tool
   - Image generation tool

4. **Implement optimizations:**
   - Prompt caching
   - Extended thinking

5. **Testing and documentation**

### Phase 2.1 Implementation Steps

1. **Database changes:**
   - Add `balance` to User model
   - Create Transaction model
   - Migration script

2. **Cost tracking:**
   - Pre-request estimation
   - Balance validation
   - Post-request charging

3. **Telegram Stars:**
   - Payment flow handlers
   - Refund mechanism

4. **Admin commands:**
   - Privileged users list
   - Balance management commands

5. **Testing and documentation**

---

## Summary

This document defines the complete plan for Claude integration across three phases:

- **Phase 1.3 (Core):** Text conversations with streaming
- **Phase 1.4 (Multimodal + Tools):** Vision, voice, files, tools, optimizations
- **Phase 2.1 (Payment):** Balance, Stars, admin commands

Key principles:
- Streaming-first (no buffering)
- Token-based context (use full window)
- Modular architecture (easy to extend)
- Comprehensive logging (for debugging)
- Cost tracking (every API call)

---

## Phase 1.3 Implementation Summary

**Status:** ✅ COMPLETE (2026-01-07)

### What Was Implemented

**Core Files Created:**
- `bot/core/base.py` - Abstract LLMProvider interface
- `bot/core/models.py` - Pydantic models (Message, LLMRequest, TokenUsage, LLMResponse)
- `bot/core/exceptions.py` - Custom exceptions hierarchy
- `bot/core/claude/client.py` - ClaudeProvider implementing streaming
- `bot/core/claude/context.py` - ContextManager for token-based context building
- `bot/telegram/handlers/claude.py` - Main message handler with streaming

**Configuration:**
- Model: Claude Sonnet 4.5 (`claude-sonnet-4-5-20250929`)
- Context window: 200K tokens
- Max output: 64K tokens
- Pricing: $3/MTok input, $15/MTok output
- All config consolidated in `bot/config.py`

**Features Implemented:**
1. ✅ Real-time streaming (no buffering - each chunk sent immediately)
2. ✅ Token-based context management (all messages that fit in window)
3. ✅ Thread-based conversation history
4. ✅ Global system prompt
5. ✅ Cost tracking (input/output tokens per message)
6. ✅ Comprehensive structured logging
7. ✅ Error handling (rate limits, timeouts, connection errors, context overflow)
8. ✅ Optimized message updates (avoid redundant edits)

### Bugs Fixed During Implementation

All bugs documented with regression tests:

1. **User.telegram_id AttributeError**
   - Issue: Handler accessed non-existent `user.telegram_id` attribute
   - Fix: Changed to `user.id` in logging
   - Test: `test_claude_handler_uses_user_id_not_telegram_id()`

2. **ChatRepository parameter name**
   - Issue: Passed `type` instead of `chat_type` to get_or_create()
   - Fix: Changed parameter name to `chat_type`
   - Test: `test_claude_handler_uses_correct_chat_type_parameter()`

3. **Missing role parameter**
   - Issue: MessageRepository.create_message() requires `role` parameter
   - Fix: Added `role=MessageRole.USER/ASSISTANT` to all create_message() calls
   - Test: `test_claude_handler_passes_role_to_create_message()`

4. **Wrong execution order**
   - Issue: Tried to save message before creating thread (missing thread_id)
   - Fix: Moved thread creation before message saving
   - Test: `test_claude_handler_creates_thread_before_saving_message()`

5. **Incorrect model name**
   - Issue: Used legacy `claude-sonnet-4-5-20250514` (returns 404)
   - Fix: Updated to current `claude-sonnet-4-5-20250929`
   - Test: Manual verification with real API

### Test Coverage

**Regression Tests:** 4 tests in `tests/core/test_claude_handler_integration.py`
- All tests passing ✅
- Each test validates one bug fix
- Tests use proper async mocking
- Tests ensure bugs never recur

### Next Steps

Phase 1.3 is complete. Ready for **Phase 1.4: Multimodal + Tools**

Key Phase 1.4 features:
- Vision (image processing)
- Voice messages (transcription)
- File handling
- Tools (code execution, image generation)
- Prompt caching
- Extended thinking
