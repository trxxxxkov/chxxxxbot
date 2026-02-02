"""Deep thinking tool for extended reasoning on complex problems.

This tool enables Claude to perform deep analysis with Extended Thinking
when the default (non-thinking) mode is insufficient for the task.

Key differences from self_critique:
- Uses CURRENT user's model (not always Opus)
- Streams thinking in real-time to user (expandable blockquote)
- No balance requirement (included in normal usage)
- Returns reasoning for Claude to incorporate into response

NO __init__.py - use direct import:
    from core.tools.extended_think import TOOL_CONFIG, execute_extended_think
"""

from dataclasses import dataclass
from decimal import Decimal
from typing import (Any, AsyncIterator, Awaitable, Callable, Optional,
                    TYPE_CHECKING)

from config import get_model
from core.models import StreamEvent
from core.pricing import calculate_claude_cost
from core.tools.base import ToolConfig
from utils.structured_logging import get_logger

if TYPE_CHECKING:
    from anthropic import AsyncAnthropic

logger = get_logger(__name__)

# =============================================================================
# Configuration
# =============================================================================

# Extended thinking budget - enough for deep analysis
THINKING_BUDGET_TOKENS = 16000

# Max output tokens - includes thinking, not just text output
MAX_OUTPUT_TOKENS = 16000

# =============================================================================
# Prometheus Metrics
# =============================================================================

try:
    from prometheus_client import Counter
    from prometheus_client import Histogram

    EXTENDED_THINK_REQUESTS = Counter('extended_think_requests_total',
                                      'Total extended_think invocations',
                                      ['focus'])
    EXTENDED_THINK_COST = Histogram(
        'extended_think_cost_usd',
        'Cost of extended_think calls in USD',
        buckets=[0.001, 0.005, 0.01, 0.02, 0.05, 0.1, 0.2])
    EXTENDED_THINK_THINKING_TOKENS = Histogram(
        'extended_think_thinking_tokens',
        'Thinking tokens used per call',
        buckets=[1000, 2000, 5000, 10000, 15000, 20000])
    METRICS_AVAILABLE = True
except ImportError:
    METRICS_AVAILABLE = False

# =============================================================================
# Tool Definition
# =============================================================================

EXTENDED_THINK_TOOL = {
    "name":
        "extended_think",
    "description":
        """Activate deep reasoning mode before writing any code beyond trivial snippets.

Call this tool FIRST when asked to:
- Write code involving physics, math, simulations, numerical methods
- Implement algorithms, data structures, state machines
- Create visualizations, animations, charts with calculations
- Debug issues or find root causes
- Design architecture or make technical decisions

When in doubt whether a task is trivial, call this tool. The overhead is small
but catching errors early saves much more time. Only skip for truly simple
tasks like "print hello world" or "add two numbers".

Examples that require extended_think:
- "visualize three-body problem" → physics simulation, numerical integration
- "implement LRU cache" → data structure design
- "create animated chart" → calculation + visualization logic""",
    "input_schema": {
        "type": "object",
        "properties": {
            "problem": {
                "type": "string",
                "description": "Problem statement requiring deep analysis"
            },
            "context": {
                "type":
                    "string",
                "description":
                    "Relevant context: code snippets, data, constraints"
            },
            "focus": {
                "type": "string",
                "enum": [
                    "correctness", "optimization", "edge_cases", "architecture",
                    "debugging"
                ],
                "description": "Primary analysis focus"
            }
        },
        "required": ["problem"]
    }
}

# =============================================================================
# Streaming Result Dataclass
# =============================================================================


@dataclass
class DeepThinkResult:
    """Result of extended_think execution."""

    thinking: str  # Full thinking text
    conclusion: str  # Final conclusion/answer
    thinking_tokens: int
    output_tokens: int
    cost_usd: Decimal


# =============================================================================
# Main Executor (Streaming)
# =============================================================================


async def execute_extended_think_stream(
    problem: str,
    context: Optional[str] = None,
    focus: Optional[str] = None,
    *,
    model_id: str,
    anthropic_client: "AsyncAnthropic",
    cancel_event: Optional[Any] = None,
) -> AsyncIterator[StreamEvent]:
    """Execute deep thinking with streaming.

    Yields StreamEvent objects:
    - thinking_delta: Chunks of thinking text (for expandable blockquote)
    - text_delta: Chunks of conclusion text
    - stream_complete: Final event with usage stats

    Args:
        problem: Problem statement to analyze.
        context: Optional context (code, data).
        focus: Analysis focus area.
        model_id: User's current model (e.g., "claude:sonnet").
        anthropic_client: Anthropic API client.
        cancel_event: Optional cancellation event.

    Yields:
        StreamEvent objects for real-time display.
    """
    model_config = get_model(model_id)

    logger.info(
        "extended_think.started",
        model=model_id,
        problem_length=len(problem),
        has_context=bool(context),
        focus=focus,
    )

    # Build user message
    user_message = f"<problem>\n{problem}\n</problem>"
    if context:
        user_message += f"\n\n<context>\n{context}\n</context>"
    if focus:
        user_message += f"\n\n<focus>{focus}</focus>"

    # System prompt for reasoning - thinking is the only output
    system_prompt = """Analyze the problem step by step. Consider edge cases and verify your logic."""

    # Prepare API parameters
    api_params = {
        "model": model_config.model_id,
        "max_tokens": MAX_OUTPUT_TOKENS,
        "thinking": {
            "type": "enabled",
            "budget_tokens": THINKING_BUDGET_TOKENS
        },
        "system": system_prompt,
        "messages": [{
            "role": "user",
            "content": user_message
        }],
    }

    thinking_text = ""
    conclusion_text = ""
    thinking_tokens = 0
    input_tokens = 0
    output_tokens = 0

    thinking_done = False

    try:
        async with anthropic_client.messages.stream(**api_params) as stream:
            async for event in stream:
                # Check cancellation
                if cancel_event and cancel_event.is_set():
                    logger.info("extended_think.cancelled")
                    break

                # Handle thinking delta
                if (event.type == "content_block_delta" and
                        hasattr(event.delta, "thinking")):
                    chunk = event.delta.thinking
                    thinking_text += chunk
                    logger.debug("extended_think.thinking_chunk",
                                 chunk_len=len(chunk),
                                 total_thinking_len=len(thinking_text))
                    yield StreamEvent(type="thinking_delta", content=chunk)

                # Text delta = thinking is done, stop immediately
                # Don't wait for conclusion generation (saves ~50 seconds)
                elif (event.type == "content_block_delta" and
                      hasattr(event.delta, "text")):
                    logger.info("extended_think.thinking_done_stopping",
                                thinking_length=len(thinking_text))
                    thinking_done = True
                    break

            # Get usage - if we broke early, estimate from thinking text
            if thinking_done:
                # Estimate: ~4 chars per token for thinking
                output_tokens = len(thinking_text) // 4
                input_tokens = 200  # Approximate input (system + user message)
            else:
                final_message = await stream.get_final_message()
                input_tokens = final_message.usage.input_tokens
                output_tokens = final_message.usage.output_tokens
                thinking_tokens = getattr(final_message.usage,
                                          'thinking_tokens', 0) or 0

    except Exception as e:
        logger.exception("extended_think.stream_error", error=str(e))
        yield StreamEvent(type="stream_complete",
                          content="",
                          usage={
                              "error": str(e),
                              "thinking": thinking_text,
                              "conclusion": conclusion_text,
                          })
        return

    # Calculate cost
    cost = calculate_claude_cost(
        model_id=model_config.model_id,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        thinking_tokens=thinking_tokens,
    )

    # Record metrics
    if METRICS_AVAILABLE:
        EXTENDED_THINK_REQUESTS.labels(focus=focus or "none").inc()
        EXTENDED_THINK_COST.observe(float(cost))
        EXTENDED_THINK_THINKING_TOKENS.observe(thinking_tokens)

    logger.info(
        "extended_think.complete",
        thinking_tokens=thinking_tokens,
        output_tokens=output_tokens,
        cost_usd=float(cost),
        thinking_length=len(thinking_text),
        conclusion_length=len(conclusion_text),
    )

    # Final event with full result
    yield StreamEvent(type="stream_complete",
                      content=conclusion_text,
                      usage={
                          "thinking": thinking_text,
                          "conclusion": conclusion_text,
                          "thinking_tokens": thinking_tokens,
                          "input_tokens": input_tokens,
                          "output_tokens": output_tokens,
                          "cost_usd": float(cost),
                      })


# =============================================================================
# Non-Streaming Executor (for tool registry)
# =============================================================================


async def execute_extended_think(
        problem: str,
        context: Optional[str] = None,
        focus: Optional[str] = None,
        *,
        model_id: str = "claude:sonnet",
        user_id: Optional[int] = None,
        thread_id: Optional[int] = None,
        on_thinking_chunk: Optional[Callable[[str], Awaitable[None]]] = None,
        anthropic_client: Optional["AsyncAnthropic"] = None,
        cancel_event: Optional[Any] = None,
        **kwargs,  # Accept extra kwargs from tool executor
) -> dict[str, Any]:
    """Execute deep thinking tool.

    This is the entry point called by tool executor. It:
    1. Streams thinking chunks via on_thinking_chunk callback
    2. Returns the conclusion for Claude to use

    Args:
        problem: Problem statement to analyze.
        context: Optional context (code, data).
        focus: Analysis focus area.
        model_id: User's current model.
        user_id: User ID for logging.
        thread_id: Thread ID for logging.
        on_thinking_chunk: Callback for streaming thinking to UI.
        anthropic_client: Anthropic API client.
        cancel_event: Optional cancellation event.

    Returns:
        Dict with conclusion, thinking summary, and cost.
    """
    logger.info(
        "extended_think.executor.called",
        problem_length=len(problem),
        has_context=bool(context),
        focus=focus,
        model_id=model_id,
        user_id=user_id,
        thread_id=thread_id,
        has_thinking_callback=on_thinking_chunk is not None,
    )

    # Get model config for actual model_id (needed for DB logging)
    model_config = get_model(model_id)

    # Get Anthropic client
    client = anthropic_client
    if client is None:
        from telegram.handlers.claude import claude_provider
        if claude_provider is None:
            logger.error("extended_think.executor.no_provider")
            return {
                "error": "Claude provider not initialized",
                "conclusion": "",
            }
        client = claude_provider.client

    thinking_text = ""
    conclusion_text = ""
    cost_usd = 0.0
    thinking_tokens = 0
    input_tokens = 0
    output_tokens = 0

    async for event in execute_extended_think_stream(
            problem=problem,
            context=context,
            focus=focus,
            model_id=model_id,
            anthropic_client=client,
            cancel_event=cancel_event,
    ):
        if event.type == "thinking_delta":
            thinking_text += event.content
            # Stream thinking to UI in real-time
            if on_thinking_chunk:
                logger.debug("extended_think.calling_callback",
                             chunk_len=len(event.content))
                await on_thinking_chunk(event.content)

        elif event.type == "text_delta":
            conclusion_text += event.content

        elif event.type == "stream_complete":
            if event.usage:
                cost_usd = event.usage.get("cost_usd", 0.0)
                thinking_tokens = event.usage.get("thinking_tokens", 0)
                input_tokens = event.usage.get("input_tokens", 0)
                output_tokens = event.usage.get("output_tokens", 0)

    logger.info(
        "extended_think.executor.complete",
        thinking_length=len(thinking_text),
        conclusion_length=len(conclusion_text),
        thinking_tokens=thinking_tokens,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cost_usd=cost_usd,
        user_id=user_id,
        thread_id=thread_id,
    )

    # Return result for Claude
    # Thinking is shown in UI, only conclusion goes to Claude
    return {
        "conclusion": conclusion_text,
        "thinking_summary": f"Analyzed with {thinking_tokens} thinking tokens",
        "cost_usd": cost_usd,
        "thinking_tokens": thinking_tokens,
        "output_tokens":
            output_tokens,  # For format_result (without _ to survive clean_result)
        "_thinking_text": thinking_text,  # Internal, for logging
        # DB logging metadata (tool_executor checks for _model_id)
        "_model_id": model_config.model_id,
        "_input_tokens": input_tokens,
        "_output_tokens": output_tokens,
        "_cache_read_tokens": 0,  # extended_think doesn't use caching
        "_cache_creation_tokens": 0,
    }


# =============================================================================
# Result Formatter
# =============================================================================


def format_extended_think_result(tool_input: dict[str, Any],
                                 result: dict[str, Any]) -> str:
    """Format extended_think result for system message.

    Shows brief summary (full thinking visible in expandable blockquote).
    Note: Anthropic counts thinking as output_tokens, but we display as "thinking tokens"
    for user clarity.
    """
    if result.get("error"):
        return f"[🧠 extended_think failed: {result['error']}]"

    # Use output_tokens (without underscore - survives clean_result filtering)
    # Display as "thinking tokens" for user, but internally it's output tokens
    thinking_tokens = result.get("output_tokens", 0)
    cost = result.get("cost_usd", 0)

    return f"[🧠 extended_think: {thinking_tokens} thinking tokens, ${cost:.4f}]"


# =============================================================================
# Tool Config
# =============================================================================

TOOL_CONFIG = ToolConfig(
    name="extended_think",
    definition=EXTENDED_THINK_TOOL,
    executor=execute_extended_think,
    emoji="🧠",
    needs_bot_session=False,
    format_result=format_extended_think_result,
)
