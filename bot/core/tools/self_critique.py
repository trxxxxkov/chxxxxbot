"""Self-critique subagent tool for critical verification.

This tool launches an independent verification session using Claude Opus 4.6
with an adversarial system prompt focused on finding flaws.

The subagent has access to tools:
- execute_python: Run tests, debug, visualize
- preview_file: Examine any file type
- analyze_image: Vision analysis
- analyze_pdf: PDF analysis
- web_search: Search the web to verify facts (server-side, $0.01/search)
- web_fetch: Read full content of web pages (documentation, articles)

Cost:
- Requires balance >= $1.00 to start
- Dynamic pricing: user pays actual Opus token costs + tool costs
- All costs tracked in Grafana/Prometheus

NO __init__.py - use direct import:
    from core.tools.self_critique import TOOL_CONFIG, execute_self_critique
"""

import asyncio
from decimal import Decimal
import json
from typing import Any, Awaitable, Callable, Optional, TYPE_CHECKING

# AsyncAnthropic client obtained from global claude_provider
from config import get_model
from core.cost_tracker import CostTracker as BaseCostTracker
from core.pricing import calculate_claude_cost
from core.pricing import calculate_e2b_cost
# Import tool definitions from existing modules (DRY - don't duplicate)
from core.tools.analyze_image import ANALYZE_IMAGE_TOOL
from core.tools.analyze_pdf import ANALYZE_PDF_TOOL
from core.tools.base import ToolConfig
from core.tools.execute_python import EXECUTE_PYTHON_TOOL
from core.tools.preview_file import PREVIEW_FILE_TOOL
# Note: execute_tool imported inside _execute_subagent_tool to avoid circular import
from utils.structured_logging import get_logger

if TYPE_CHECKING:
    from aiogram import Bot
    from sqlalchemy.ext.asyncio import AsyncSession

logger = get_logger(__name__)

# =============================================================================
# Configuration
# =============================================================================

# Always use Opus for verification - best model for finding errors
VERIFICATION_MODEL_ID = "claude:opus"

# Minimum balance required to start self_critique
MIN_BALANCE_FOR_CRITIQUE = Decimal("1.00")

# Maximum iterations for subagent tool loop
MAX_SUBAGENT_ITERATIONS = 10

# Extended thinking budget - enough for analysis but not excessive
THINKING_BUDGET_TOKENS = 10000

# Cost cap - stop if estimated cost exceeds this threshold
MAX_COST_USD = Decimal("1.00")

# =============================================================================
# Prometheus Metrics
# =============================================================================

try:
    from prometheus_client import Counter
    from prometheus_client import Histogram

    SELF_CRITIQUE_REQUESTS = Counter('self_critique_requests_total',
                                     'Total self_critique invocations',
                                     ['verdict'])
    SELF_CRITIQUE_COST = Histogram(
        'self_critique_cost_usd',
        'Cost of self_critique calls in USD',
        buckets=[0.01, 0.02, 0.05, 0.10, 0.20, 0.50, 1.0])
    SELF_CRITIQUE_TOKENS = Counter(
        'self_critique_tokens_total',
        'Tokens used by self_critique',
        ['token_type']  # input, output, thinking
    )
    SELF_CRITIQUE_TOOLS = Counter('self_critique_tools_total',
                                  'Tool calls made by self_critique subagent',
                                  ['tool_name'])
    SELF_CRITIQUE_ITERATIONS = Histogram(
        'self_critique_iterations',
        'Number of iterations per self_critique call',
        buckets=[1, 2, 3, 5, 10, 20])
    METRICS_AVAILABLE = True
except ImportError:
    METRICS_AVAILABLE = False
    logger.warning("self_critique.prometheus_unavailable",
                   msg="prometheus_client not available, metrics disabled")

# =============================================================================
# Critical Reviewer System Prompt
# =============================================================================

CRITICAL_REVIEWER_SYSTEM_PROMPT = """You are verifying another Claude's response. Find flaws, not praise.

Tools: execute_python (test code), preview_file, analyze_image/pdf, web_search, web_fetch.
Limit: 10 tool calls max.

Approach:
1. Identify likely failure points
2. Verify reasoning: check logic chains, spot fallacies, confirm conclusions follow from premises
3. Check visual requirements if user specified any (colors, style, layout, format)
4. For code: use web_search to verify API usage of key libraries (APIs change frequently)
5. Verify with tools (run code, check files, search if suspicious)
6. Return verdict when confident

Return JSON only:
{
  "verdict": "PASS" | "FAIL" | "NEEDS_IMPROVEMENT",
  "alignment_score": 0-100,
  "confidence": 0-100,
  "issues": [{"severity": "critical|major|minor", "description": "...", "location": "..."}],
  "recommendations": ["..."],
  "summary": "1-2 sentences"
}

FAIL: Critical errors, wrong output
NEEDS_IMPROVEMENT: Partial, minor bugs
PASS: Works correctly"""

# =============================================================================
# Tools available to the subagent
# =============================================================================

# Server-side tools (Anthropic handles execution)
WEB_SEARCH_TOOL = {
    "type": "web_search_20260209",
    "name": "web_search",
    "max_uses": 10,
}

WEB_FETCH_TOOL = {
    "type": "web_fetch_20260209",
    "name": "web_fetch",
    "max_uses": 10,
    "citations": {
        "enabled": True
    },
    "max_content_tokens": 20000,
}

# Reuse tool definitions from existing modules (DRY principle)
# These are the same tools available to the main agent
SUBAGENT_TOOLS = [
    EXECUTE_PYTHON_TOOL,
    PREVIEW_FILE_TOOL,
    ANALYZE_IMAGE_TOOL,
    ANALYZE_PDF_TOOL,
]

# =============================================================================
# Tool Definition
# =============================================================================

SELF_CRITIQUE_TOOL = {
    "name":
        "self_critique",
    "description":
        """Independent verification by fresh Claude Opus instance.

Launches separate context with adversarial prompt for truly independent review.
Use when user asks to verify your answer ("проверь", "перепроверь", "verify", "check").

Provide your previous answer in content field. Subagent can run Python tests,
analyze files, web search/fetch.

Returns: verdict (PASS/FAIL/NEEDS_IMPROVEMENT), confidence score, issues, recommendations.
Cost: requires $1.00+ balance, typical $0.03-0.15 per call.""",
    "input_schema": {
        "type": "object",
        "properties": {
            "content": {
                "type": "string",
                "description":
                    "Text, code, or reasoning to verify. Include the full "
                    "response you're about to send."
            },
            "file_ids": {
                "type": "array",
                "items": {
                    "type": "string"
                },
                "description":
                    "File IDs to verify (exec_xxx, file_xxx, telegram file_id). "
                    "The subagent will analyze these files."
            },
            "user_request": {
                "type":
                    "string",
                "description":
                    "The ORIGINAL user request. Critical for checking alignment."
            },
            "verification_hints": {
                "type": "array",
                "items": {
                    "type":
                        "string",
                    "enum": [
                        "run_tests", "check_edge_cases", "visualize_data",
                        "verify_calculations", "check_logic_chain",
                        "compare_with_spec", "debug_execution",
                        "validate_output_format"
                    ]
                },
                "description": "Suggested verification approaches."
            },
            "focus_areas": {
                "type": "array",
                "items": {
                    "type":
                        "string",
                    "enum": [
                        "accuracy", "completeness", "logic", "user_intent",
                        "code_correctness", "formatting", "edge_cases"
                    ]
                },
                "description": "Areas to focus critical analysis on."
            }
        },
        "required": ["user_request"]
    }
}

# =============================================================================
# Cost Tracker with Prometheus Metrics
# =============================================================================


def _create_cost_tracker(model_id: str, user_id: int) -> BaseCostTracker:
    """Create CostTracker with Prometheus metrics callbacks.

    Uses the shared CostTracker from core.cost_tracker with
    self_critique-specific Prometheus metrics.

    Args:
        model_id: Model identifier for pricing.
        user_id: User ID for logging.

    Returns:
        Configured CostTracker instance.
    """

    def on_api_usage(input_tokens: int, output_tokens: int,
                     thinking_tokens: int) -> None:
        """Record API usage in Prometheus."""
        if METRICS_AVAILABLE:
            SELF_CRITIQUE_TOKENS.labels(token_type='input').inc(input_tokens)
            SELF_CRITIQUE_TOKENS.labels(token_type='output').inc(output_tokens)
            if thinking_tokens > 0:
                SELF_CRITIQUE_TOKENS.labels(
                    token_type='thinking').inc(thinking_tokens)

    def on_tool_cost(tool_name: str, cost: Decimal) -> None:
        """Record tool usage in Prometheus."""
        if METRICS_AVAILABLE:
            SELF_CRITIQUE_TOOLS.labels(tool_name=tool_name).inc()

    def on_finalize(verdict: str, iterations: int, cost: Decimal) -> None:
        """Record final metrics in Prometheus."""
        if METRICS_AVAILABLE:
            SELF_CRITIQUE_REQUESTS.labels(verdict=verdict).inc()
            SELF_CRITIQUE_COST.observe(float(cost))
            SELF_CRITIQUE_ITERATIONS.observe(iterations)

    return BaseCostTracker(
        model_id=model_id,
        user_id=user_id,
        on_api_usage=on_api_usage,
        on_tool_cost=on_tool_cost,
        on_finalize=on_finalize,
    )


# Alias for backward compatibility in tests
CostTracker = BaseCostTracker

# =============================================================================
# Helper Functions
# =============================================================================


def _build_verification_context(user_request: str, content: Optional[str],
                                file_ids: Optional[list[str]],
                                verification_hints: Optional[list[str]],
                                focus_areas: Optional[list[str]]) -> str:
    """Build the verification context message for the subagent."""
    parts = []

    parts.append("<verification_task>")
    parts.append(
        "You are reviewing another Claude's response. Your job is to find flaws."
    )
    parts.append("</verification_task>")

    parts.append("\n<original_user_request>")
    parts.append(user_request)
    parts.append("</original_user_request>")

    if content:
        parts.append("\n<content_to_verify>")
        parts.append(content)
        parts.append("</content_to_verify>")

    if file_ids:
        parts.append("\n<files_to_verify>")
        parts.append(
            "Use preview_file or analyze_image/analyze_pdf to examine these:")
        for file_id in file_ids:
            parts.append(f"- {file_id}")
        parts.append("</files_to_verify>")

    if verification_hints:
        parts.append("\n<suggested_verification_approaches>")
        for hint in verification_hints:
            parts.append(f"- {hint}")
        parts.append("</suggested_verification_approaches>")

    if focus_areas:
        parts.append("\n<focus_areas>")
        parts.append("Pay special attention to:")
        for area in focus_areas:
            parts.append(f"- {area}")
        parts.append("</focus_areas>")

    parts.append("\n<instructions>")
    parts.append("1. Understand what the user actually requested")
    parts.append("2. Examine the content/files using available tools")
    parts.append("3. Write tests or verification code if applicable")
    parts.append("4. Actively search for errors, gaps, misalignments")
    parts.append("5. Return your verdict as JSON (no other text)")
    parts.append("</instructions>")

    return "\n".join(parts)


async def _execute_subagent_tool(
    tool_name: str,
    tool_input: dict[str, Any],
    tool_use_id: str,
    bot: 'Bot',
    session: 'AsyncSession',
    thread_id: Optional[int],
    cost_tracker: BaseCostTracker,
    on_tool_start: Optional[Callable[[str], Awaitable[None]]] = None,
) -> dict[str, Any]:
    """Execute a tool call from the subagent and track costs.

    Uses execute_tool from registry for unified tool dispatch (DRY principle).
    Only adds cost tracking specific to self_critique context.
    """
    # Import here to avoid circular import (registry imports self_critique)
    from core.tools.registry import execute_tool

    logger.debug("self_critique.tool_call",
                 tool_name=tool_name,
                 tool_input_keys=list(tool_input.keys()))

    # Notify about tool start for display updates
    if on_tool_start:
        try:
            await on_tool_start(tool_name)
        except Exception as e:  # pylint: disable=broad-exception-caught
            logger.warning("self_critique.on_tool_start_failed",
                           tool_name=tool_name,
                           error=str(e))

    try:
        # Use unified execute_tool from registry (DRY - no switch-case duplication)
        result = await execute_tool(
            tool_name=tool_name,
            tool_input=tool_input,
            bot=bot,
            session=session,
            thread_id=thread_id,
        )

        # Track costs for self_critique billing
        _track_tool_cost(tool_name, result, cost_tracker)

        return {
            "type":
                "tool_result",
            "tool_use_id":
                tool_use_id,
            "content":
                json.dumps(result, default=str)
                if isinstance(result, dict) else str(result)
        }

    except Exception as e:
        logger.exception("self_critique.tool_error",
                         tool_name=tool_name,
                         error=str(e))
        return {
            "type": "tool_result",
            "tool_use_id": tool_use_id,
            "content": json.dumps({"error": str(e)}),
            "is_error": True
        }


def _track_tool_cost(tool_name: str, result: dict[str, Any],
                     cost_tracker: BaseCostTracker) -> None:
    """Track tool execution cost for self_critique billing.

    Extracts cost from tool result and adds to cost tracker.
    Also logs for Grafana dashboards.
    """
    cost: Optional[Decimal] = None

    if tool_name == "execute_python" and "execution_time" in result:
        # E2B sandbox cost based on execution time
        cost = calculate_e2b_cost(result["execution_time"])
    elif "cost_usd" in result:
        # Tools that report their own cost (preview_file, analyze_image, analyze_pdf)
        cost = Decimal(str(result["cost_usd"]))

    if cost is not None and cost > 0:
        cost_tracker.add_tool_cost(tool_name, cost)
        # Log for Grafana (appears in appropriate panel based on tool)
        logger.info("tools.loop.user_charged_for_tool",
                    tool_name=tool_name,
                    cost_usd=float(cost),
                    source="self_critique")


# =============================================================================
# Main Executor
# =============================================================================


async def execute_self_critique(  # pylint: disable=too-many-return-statements
    user_request: str,
    content: Optional[str] = None,
    file_ids: Optional[list[str]] = None,
    verification_hints: Optional[list[str]] = None,
    focus_areas: Optional[list[str]] = None,
    *,
    bot: 'Bot',
    session: 'AsyncSession',
    thread_id: Optional[int] = None,
    user_id: int,
    on_subagent_tool: Optional[Callable[[str], Awaitable[None]]] = None,
    anthropic_client: Optional[Any] = None,
    cancel_event: Optional[asyncio.Event] = None,
) -> dict[str, Any]:
    """Execute critical self-verification subagent.

    ALWAYS uses Claude Opus 4.6 for maximum verification quality.
    Cost is dynamic - user pays actual Opus token costs + tool costs.

    Args:
        user_request: Original user request for alignment check.
        content: Text/code/reasoning to verify.
        file_ids: List of file IDs to analyze.
        verification_hints: Suggested verification approaches.
        focus_areas: Areas to focus critique on.
        bot: Telegram bot instance.
        session: Database session.
        thread_id: Current thread ID.
        user_id: User ID for balance check and cost tracking.
        on_subagent_tool: Optional callback called when subagent uses a tool.
            Used to update display with tool progress.
        anthropic_client: Optional Anthropic client for dependency injection.
            If not provided, falls back to global claude_provider.
            Useful for testing and custom client configurations.
        cancel_event: Optional asyncio.Event for cancellation.
            If set, subagent will stop and return partial results.

    Returns:
        Structured verification result with verdict, issues, recommendations.
    """
    # Use ServiceFactory for cleaner service initialization (DRY)
    from services.factory import ServiceFactory

    # Always use Opus for verification
    model_config = get_model(VERIFICATION_MODEL_ID)

    logger.info("self_critique.started",
                user_id=user_id,
                model=VERIFICATION_MODEL_ID,
                has_content=bool(content),
                file_count=len(file_ids) if file_ids else 0)

    # 1. Check balance (minimum $1.00 to start)
    # Use ServiceFactory for cleaner initialization (DRY - no manual repo creation)
    services = ServiceFactory(session)
    balance = await services.balance.get_balance(user_id)

    if balance < MIN_BALANCE_FOR_CRITIQUE:
        logger.info("self_critique.insufficient_balance",
                    user_id=user_id,
                    balance=float(balance),
                    required=float(MIN_BALANCE_FOR_CRITIQUE))
        return {
            "error": "insufficient_balance",
            "verdict": "SKIPPED",
            "message":
                f"self_critique requires balance >= ${MIN_BALANCE_FOR_CRITIQUE}. "
                f"Current balance: ${balance:.2f}",
            "required_balance": float(MIN_BALANCE_FOR_CRITIQUE),
            "current_balance": float(balance)
        }

    # 2. Initialize cost tracking
    # Use factory to create CostTracker with Prometheus metrics
    cost_tracker = _create_cost_tracker(model_id=model_config.model_id,
                                        user_id=user_id)

    # 3. Build verification context
    verification_context = _build_verification_context(
        user_request=user_request,
        content=content,
        file_ids=file_ids,
        verification_hints=verification_hints,
        focus_areas=focus_areas)

    # 4. Get Anthropic client (dependency injection or fallback to global)
    client = anthropic_client
    if client is None:
        # Fallback to global claude_provider for backward compatibility
        # Import here to avoid circular imports at module level
        from telegram.handlers.claude import claude_provider

        if claude_provider is None:
            logger.error("self_critique.provider_not_initialized",
                         user_id=user_id)
            return {
                "verdict":
                    "ERROR",
                "error":
                    "claude_provider_not_initialized",
                "message":
                    "Claude provider not initialized. Please try again later.",
                "cost_usd":
                    0.0,
                "iterations":
                    0
            }
        client = claude_provider.client
        logger.debug("self_critique.client_from_provider", user_id=user_id)
    else:
        logger.debug("self_critique.client_injected", user_id=user_id)

    # 5. Run subagent tool loop
    messages: list[dict[str, Any]] = [{
        "role": "user",
        "content": verification_context
    }]

    for iteration in range(MAX_SUBAGENT_ITERATIONS):
        # Check for cancellation (user sent /stop or new message)
        if cancel_event and cancel_event.is_set():
            logger.info("self_critique.cancelled",
                        user_id=user_id,
                        iteration=iteration)
            total_cost = await cost_tracker.finalize_and_charge(
                session=session,
                user_id=user_id,
                source="self_critique",
                verdict="CANCELLED",
                iterations=iteration)
            return {
                "verdict": "CANCELLED",
                "message": "Verification cancelled by user",
                "cost_usd": float(total_cost),
                "_already_charged": True,
                "iterations": iteration,
                "partial": True
            }

        logger.debug("self_critique.iteration",
                     iteration=iteration,
                     message_count=len(messages))

        # Call Claude API with extended thinking
        # Opus 4.6: adaptive thinking + effort; others: manual budget
        thinking_params: dict = {"type": "adaptive"} \
            if model_config.has_capability("adaptive_thinking") \
            else {"type": "enabled", "budget_tokens": THINKING_BUDGET_TOKENS}
        extra_params: dict = {}
        if model_config.has_capability("adaptive_thinking"):
            extra_params["output_config"] = {"effort": "high"}
        try:
            response = await client.messages.create(
                model=model_config.model_id,
                max_tokens=16000,
                thinking=thinking_params,
                system=CRITICAL_REVIEWER_SYSTEM_PROMPT,
                tools=SUBAGENT_TOOLS + [WEB_SEARCH_TOOL, WEB_FETCH_TOOL],
                messages=messages,
                **extra_params)
        except Exception as api_error:
            logger.error("self_critique.api_error",
                         user_id=user_id,
                         iteration=iteration,
                         error=str(api_error),
                         error_type=type(api_error).__name__)
            return {
                "verdict": "ERROR",
                "error": "api_call_failed",
                "message": f"Claude API error: {str(api_error)}",
                "cost_usd": float(cost_tracker.calculate_total_cost()),
                "iterations": iteration
            }

        # Track token costs
        thinking_tokens = 0
        if hasattr(response.usage, 'thinking_tokens'):
            thinking_tokens = response.usage.thinking_tokens or 0

        cost_tracker.add_api_usage(input_tokens=response.usage.input_tokens,
                                   output_tokens=response.usage.output_tokens,
                                   thinking_tokens=thinking_tokens)

        # Log for Grafana (appears in Anthropic panel)
        # Calculate cost for this API call
        api_cost = calculate_claude_cost(
            model_id=model_config.model_id,
            input_tokens=response.usage.input_tokens,
            output_tokens=response.usage.output_tokens,
            thinking_tokens=thinking_tokens,
        )
        logger.info("claude_handler.user_charged",
                    model_id="claude:opus",
                    cost_usd=float(api_cost),
                    input_tokens=response.usage.input_tokens,
                    output_tokens=response.usage.output_tokens,
                    thinking_tokens=thinking_tokens,
                    source="self_critique")

        # Check cost cap - stop if we're getting too expensive
        current_cost = cost_tracker.calculate_total_cost()
        if current_cost >= MAX_COST_USD:
            logger.warning("self_critique.cost_cap_reached",
                           user_id=user_id,
                           current_cost=float(current_cost),
                           max_cost=float(MAX_COST_USD),
                           iteration=iteration)
            # Force end_turn - return partial results
            total_cost = await cost_tracker.finalize_and_charge(
                session=session,
                user_id=user_id,
                source="self_critique",
                verdict="COST_CAP",
                iterations=iteration + 1)
            return {
                "verdict":
                    "COST_CAP",
                "message":
                    f"Verification stopped: cost cap ${MAX_COST_USD} reached",
                "cost_usd":
                    float(total_cost),
                "_already_charged":
                    True,
                "iterations":
                    iteration + 1,
                "partial":
                    True
            }

        # Track web_search costs ($0.01 per search request)
        web_search_requests = getattr(response.usage, 'web_search_requests', 0)
        # Handle None, 0, or missing attribute
        if web_search_requests and isinstance(web_search_requests,
                                              int) and web_search_requests > 0:
            web_search_cost = Decimal("0.01") * web_search_requests
            cost_tracker.add_tool_cost("web_search", web_search_cost)
            # Log for Grafana (appears in web_search panel)
            # Use same event as main handler for consistency
            logger.info("tools.web_search.user_charged",
                        cost_usd=float(web_search_cost),
                        web_search_requests=web_search_requests,
                        source="self_critique")

        # Check stop reason
        if response.stop_reason == "end_turn":
            # Done - extract JSON result from text blocks
            result_text = ""
            for block in response.content:
                if block.type == "text":
                    result_text += block.text

            # Try to parse JSON
            try:
                # Find JSON in response (may have markdown code blocks)
                json_text = result_text
                if "```json" in result_text:
                    start = result_text.find("```json") + 7
                    end = result_text.find("```", start)
                    json_text = result_text[start:end].strip()
                elif "```" in result_text:
                    start = result_text.find("```") + 3
                    end = result_text.find("```", start)
                    json_text = result_text[start:end].strip()

                result = json.loads(json_text)

                # Finalize cost and charge user
                verdict = result.get("verdict", "UNKNOWN")
                total_cost = await cost_tracker.finalize_and_charge(
                    session=session,
                    user_id=user_id,
                    source="self_critique",
                    verdict=verdict,
                    iterations=iteration + 1)

                result["cost_usd"] = float(total_cost)
                result["_already_charged"] = True
                result["iterations"] = iteration + 1
                result["tokens_used"] = {
                    "input": cost_tracker.total_input_tokens,
                    "output": cost_tracker.total_output_tokens,
                    "thinking": cost_tracker.total_thinking_tokens
                }

                logger.info("self_critique.completed",
                            verdict=verdict,
                            alignment_score=result.get("alignment_score"),
                            issues_count=len(result.get("issues", [])),
                            iterations=iteration + 1,
                            total_cost=float(total_cost))

                return result

            except json.JSONDecodeError as e:
                logger.warning("self_critique.invalid_json",
                               error=str(e),
                               response_preview=result_text[:500])

                # Still charge for the attempt
                total_cost = await cost_tracker.finalize_and_charge(
                    session=session,
                    user_id=user_id,
                    source="self_critique",
                    verdict="ERROR",
                    iterations=iteration + 1)

                return {
                    "verdict": "ERROR",
                    "error": "invalid_response_format",
                    "raw_response": result_text[:2000],
                    "cost_usd": float(total_cost),
                    "_already_charged": True,
                    "iterations": iteration + 1
                }

        # Handle tool use
        elif response.stop_reason == "tool_use":
            # Add assistant message WITHOUT thinking blocks
            # Keep text blocks - they contain important intermediate analysis
            content_blocks = [
                block.model_dump()
                for block in response.content
                if block.type not in ("thinking", "redacted_thinking")
            ]
            messages.append({"role": "assistant", "content": content_blocks})

            # Execute ALL tools in parallel
            tool_use_blocks = [
                block for block in response.content if block.type == "tool_use"
            ]

            tool_tasks = [
                _execute_subagent_tool(tool_name=block.name,
                                       tool_input=block.input,
                                       tool_use_id=block.id,
                                       bot=bot,
                                       session=session,
                                       thread_id=thread_id,
                                       cost_tracker=cost_tracker,
                                       on_tool_start=on_subagent_tool)
                for block in tool_use_blocks
            ]

            tool_results = await asyncio.gather(*tool_tasks)

            # Add ALL tool results in ONE user message
            messages.append({"role": "user", "content": list(tool_results)})

        else:
            logger.warning("self_critique.unexpected_stop",
                           stop_reason=response.stop_reason)
            break

    # Max iterations reached - make final call WITHOUT tools to force verdict
    logger.info("self_critique.max_iterations_final_call",
                iterations=MAX_SUBAGENT_ITERATIONS)

    # Add instruction to return verdict with available information
    messages.append({
        "role": "user",
        "content":
            "You've reached the tool usage limit. Return your verdict NOW based on "
            "what you've learned so far. Output ONLY the JSON verdict object."
    })

    try:
        # Final API call without tools - forces model to return verdict
        # Opus 4.6: adaptive thinking; others: minimal manual budget
        final_thinking: dict = {"type": "adaptive"} \
            if model_config.has_capability("adaptive_thinking") \
            else {"type": "enabled", "budget_tokens": 2000}
        final_extra: dict = {}
        if model_config.has_capability("adaptive_thinking"):
            final_extra["output_config"] = {"effort": "low"}
        final_response = await client.messages.create(
            model=model_config.model_id,
            max_tokens=4000,  # Smaller - just need JSON verdict
            thinking=final_thinking,
            system=CRITICAL_REVIEWER_SYSTEM_PROMPT,
            tools=[],  # No tools - must return text
            messages=messages,
            **final_extra)

        # Track final API usage
        thinking_tokens = 0
        if hasattr(final_response.usage, 'thinking_tokens'):
            thinking_tokens = final_response.usage.thinking_tokens or 0

        cost_tracker.add_api_usage(
            input_tokens=final_response.usage.input_tokens,
            output_tokens=final_response.usage.output_tokens,
            thinking_tokens=thinking_tokens)

        # Extract result text
        result_text = ""
        for block in final_response.content:
            if block.type == "text":
                result_text += block.text

        # Try to parse JSON
        json_text = result_text
        if "```json" in result_text:
            start = result_text.find("```json") + 7
            end = result_text.find("```", start)
            json_text = result_text[start:end].strip()
        elif "```" in result_text:
            start = result_text.find("```") + 3
            end = result_text.find("```", start)
            json_text = result_text[start:end].strip()

        result = json.loads(json_text)
        verdict = result.get("verdict", "UNKNOWN")

        total_cost = await cost_tracker.finalize_and_charge(
            session=session,
            user_id=user_id,
            source="self_critique",
            verdict=verdict,
            iterations=MAX_SUBAGENT_ITERATIONS + 1)  # +1 for final call

        result["cost_usd"] = float(total_cost)
        result["_already_charged"] = True
        result["iterations"] = MAX_SUBAGENT_ITERATIONS + 1
        result["tool_limit_reached"] = True
        result["tokens_used"] = {
            "input": cost_tracker.total_input_tokens,
            "output": cost_tracker.total_output_tokens,
            "thinking": cost_tracker.total_thinking_tokens
        }

        logger.info("self_critique.completed_after_limit",
                    verdict=verdict,
                    iterations=MAX_SUBAGENT_ITERATIONS + 1,
                    total_cost=float(total_cost))

        return result

    except Exception as e:
        logger.warning("self_critique.final_call_failed", error=str(e))

        total_cost = await cost_tracker.finalize_and_charge(
            session=session,
            user_id=user_id,
            source="self_critique",
            verdict="ERROR",
            iterations=MAX_SUBAGENT_ITERATIONS)

        return {
            "verdict":
                "ERROR",
            "error":
                "max_iterations_final_call_failed",
            "message":
                f"Tool limit reached and final verdict extraction failed: {e}",
            "cost_usd":
                float(total_cost),
            "_already_charged":
                True,
            "iterations":
                MAX_SUBAGENT_ITERATIONS,
            "tool_limit_reached":
                True
        }


# =============================================================================
# Tool Configuration for Registry
# =============================================================================

TOOL_CONFIG = ToolConfig(
    name="self_critique",
    definition=SELF_CRITIQUE_TOOL,
    executor=execute_self_critique,
    emoji="🔍",
    needs_bot_session=True,
)
