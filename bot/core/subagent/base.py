"""Base class for LLM subagents with tool loop.

This module provides a reusable foundation for creating subagents that:
- Run Claude API with extended thinking
- Execute tools in parallel
- Track costs and charge users
- Handle iteration limits and cost caps

NO __init__.py - use direct import:
    from core.subagent.base import BaseSubagent, SubagentResult
"""

from abc import ABC
from abc import abstractmethod
import asyncio
from dataclasses import dataclass
from dataclasses import field
from decimal import Decimal
import json
from typing import Any, Awaitable, Callable, Optional, TYPE_CHECKING

from core.cost_tracker import CostTracker
from core.pricing import calculate_claude_cost
from core.pricing import calculate_e2b_cost
from utils.structured_logging import get_logger

if TYPE_CHECKING:
    from aiogram import Bot
    from anthropic import AsyncAnthropic
    from sqlalchemy.ext.asyncio import AsyncSession

logger = get_logger(__name__)

# Re-export CostTracker for convenience
__all__ = ['BaseSubagent', 'SubagentResult', 'SubagentConfig', 'CostTracker']


@dataclass
class SubagentResult:
    """Result of subagent execution."""

    verdict: str
    cost_usd: float
    iterations: int
    data: dict[str, Any] = field(default_factory=dict)
    error: Optional[str] = None
    partial: bool = False

    @property
    def success(self) -> bool:
        """Check if subagent completed successfully."""
        return self.error is None and self.verdict not in ("ERROR", "COST_CAP")


@dataclass
class SubagentConfig:  # pylint: disable=too-many-instance-attributes
    """Configuration for a subagent."""

    model_id: str
    system_prompt: str
    tools: list[dict[str, Any]]
    max_iterations: int = 8
    thinking_budget_tokens: int = 10000
    max_tokens: int = 16000
    cost_cap_usd: Decimal = Decimal("0.50")
    min_balance_usd: Decimal = Decimal("0.50")


class BaseSubagent(ABC):  # pylint: disable=too-many-instance-attributes
    """Base class for LLM subagents with tool loop.

    Provides reusable infrastructure for:
    - Running Claude API with extended thinking
    - Executing tools in parallel
    - Tracking costs and charging users
    - Handling iteration limits and cost caps

    Subclasses must implement:
    - _execute_tool(): Execute a single tool call
    - _parse_result(): Parse the final response into structured result

    Example:
        class SelfCritiqueSubagent(BaseSubagent):
            def __init__(self, ...):
                config = SubagentConfig(
                    model_id="claude-opus-4-5-20251101",
                    system_prompt=CRITICAL_REVIEWER_PROMPT,
                    tools=VERIFICATION_TOOLS,
                )
                super().__init__(config, client, bot, session, user_id)

            async def _execute_tool(self, tool_name, tool_input, tool_use_id):
                # Custom tool execution logic
                ...

            def _parse_result(self, response_text):
                # Parse JSON verdict
                return json.loads(response_text)
    """

    def __init__(
        self,
        config: SubagentConfig,
        client: 'AsyncAnthropic',
        bot: 'Bot',
        session: 'AsyncSession',
        user_id: int,
        on_tool_start: Optional[Callable[[str], Awaitable[None]]] = None,
    ):
        """Initialize subagent.

        Args:
            config: Subagent configuration.
            client: Anthropic API client.
            bot: Telegram bot instance.
            session: Database session.
            user_id: User ID for billing and logging.
            on_tool_start: Optional callback when a tool starts executing.
        """
        self.config = config
        self.client = client
        self.bot = bot
        self.session = session
        self.user_id = user_id
        self.on_tool_start = on_tool_start

        self.cost_tracker = CostTracker(
            model_id=config.model_id,
            user_id=user_id,
        )
        self._source_name = self.__class__.__name__.lower()

    async def run(self, initial_message: str) -> SubagentResult:
        """Run the subagent tool loop.

        Args:
            initial_message: The initial user message to process.

        Returns:
            SubagentResult with verdict, cost, and parsed data.
        """
        # Check balance first
        balance_result = await self._check_balance()
        if balance_result is not None:
            return balance_result

        messages: list[dict[str, Any]] = [{
            "role": "user",
            "content": initial_message
        }]

        for iteration in range(self.config.max_iterations):
            logger.debug(f"{self._source_name}.iteration",
                         iteration=iteration,
                         message_count=len(messages))

            # Call Claude API
            try:
                response = await self._call_api(messages)
            except Exception as e:
                logger.error(f"{self._source_name}.api_error",
                             user_id=self.user_id,
                             iteration=iteration,
                             error=str(e))
                return SubagentResult(
                    verdict="ERROR",
                    cost_usd=float(self.cost_tracker.calculate_total_cost()),
                    iterations=iteration,
                    error=f"API error: {str(e)}",
                )

            # Track token costs
            self._track_api_usage(response)

            # Check cost cap
            cost_cap_result = await self._check_cost_cap(iteration)
            if cost_cap_result is not None:
                return cost_cap_result

            # Track web_search costs if present
            self._track_web_search_costs(response)

            # Handle response
            if response.stop_reason == "end_turn":
                return await self._handle_end_turn(response, iteration)

            elif response.stop_reason == "tool_use":
                await self._handle_tool_use(response, messages)

            else:
                logger.warning(f"{self._source_name}.unexpected_stop",
                               stop_reason=response.stop_reason)
                break

        # Max iterations reached
        return await self._handle_max_iterations()

    async def _check_balance(self) -> Optional[SubagentResult]:
        """Check if user has sufficient balance."""
        from services.factory import ServiceFactory

        services = ServiceFactory(self.session)
        balance = await services.balance.get_balance(self.user_id)

        if balance < self.config.min_balance_usd:
            logger.info(f"{self._source_name}.insufficient_balance",
                        user_id=self.user_id,
                        balance=float(balance),
                        required=float(self.config.min_balance_usd))
            return SubagentResult(
                verdict="SKIPPED",
                cost_usd=0.0,
                iterations=0,
                error="insufficient_balance",
                data={
                    "message":
                        f"Requires balance >= ${self.config.min_balance_usd}. "
                        f"Current: ${balance:.2f}",
                    "required_balance": float(self.config.min_balance_usd),
                    "current_balance": float(balance),
                },
            )
        return None

    async def _call_api(self, messages: list[dict[str, Any]]) -> Any:
        """Call Claude API with extended thinking."""
        return await self.client.messages.create(
            model=self.config.model_id,
            max_tokens=self.config.max_tokens,
            thinking={
                "type": "enabled",
                "budget_tokens": self.config.thinking_budget_tokens
            },
            system=self.config.system_prompt,
            tools=self.config.tools,
            messages=messages,
        )

    def _track_api_usage(self, response: Any) -> None:
        """Track API token usage from response."""
        thinking_tokens = 0
        if hasattr(response.usage, 'thinking_tokens'):
            thinking_tokens = response.usage.thinking_tokens or 0

        self.cost_tracker.add_api_usage(
            input_tokens=response.usage.input_tokens,
            output_tokens=response.usage.output_tokens,
            thinking_tokens=thinking_tokens,
        )

        # Log for monitoring
        api_cost = calculate_claude_cost(
            model_id=self.config.model_id,
            input_tokens=response.usage.input_tokens,
            output_tokens=response.usage.output_tokens,
            thinking_tokens=thinking_tokens,
        )
        logger.info("claude_handler.user_charged",
                    model_id=self.config.model_id,
                    cost_usd=float(api_cost),
                    input_tokens=response.usage.input_tokens,
                    output_tokens=response.usage.output_tokens,
                    thinking_tokens=thinking_tokens,
                    source=self._source_name)

    def _track_web_search_costs(self, response: Any) -> None:
        """Track web_search costs from response."""
        web_search_requests = getattr(response.usage, 'web_search_requests', 0)
        if web_search_requests and isinstance(web_search_requests,
                                              int) and web_search_requests > 0:
            web_search_cost = Decimal("0.01") * web_search_requests
            self.cost_tracker.add_tool_cost("web_search", web_search_cost)
            logger.info("tools.web_search.user_charged",
                        cost_usd=float(web_search_cost),
                        web_search_requests=web_search_requests,
                        source=self._source_name)

    async def _check_cost_cap(self, iteration: int) -> Optional[SubagentResult]:
        """Check if cost cap has been reached."""
        current_cost = self.cost_tracker.calculate_total_cost()
        if current_cost >= self.config.cost_cap_usd:
            logger.warning(f"{self._source_name}.cost_cap_reached",
                           user_id=self.user_id,
                           current_cost=float(current_cost),
                           max_cost=float(self.config.cost_cap_usd),
                           iteration=iteration)

            total_cost = await self.cost_tracker.finalize_and_charge(
                session=self.session,
                user_id=self.user_id,
                source=self._source_name,
                verdict="COST_CAP",
                iterations=iteration + 1,
            )

            return SubagentResult(
                verdict="COST_CAP",
                cost_usd=float(total_cost),
                iterations=iteration + 1,
                error=f"Cost cap ${self.config.cost_cap_usd} reached",
                partial=True,
            )
        return None

    async def _handle_end_turn(self, response: Any,
                               iteration: int) -> SubagentResult:
        """Handle end_turn response - extract and parse result."""
        result_text = ""
        for block in response.content:
            if block.type == "text":
                result_text += block.text

        try:
            parsed_data = self._parse_result(result_text)
            verdict = parsed_data.get("verdict", "UNKNOWN")

            total_cost = await self.cost_tracker.finalize_and_charge(
                session=self.session,
                user_id=self.user_id,
                source=self._source_name,
                verdict=verdict,
                iterations=iteration + 1,
            )

            logger.info(f"{self._source_name}.completed",
                        verdict=verdict,
                        iterations=iteration + 1,
                        total_cost=float(total_cost))

            return SubagentResult(
                verdict=verdict,
                cost_usd=float(total_cost),
                iterations=iteration + 1,
                data={
                    **parsed_data,
                    "tokens_used":
                        self.cost_tracker.get_token_summary(),
                },
            )

        except Exception as e:
            logger.warning(f"{self._source_name}.parse_error",
                           error=str(e),
                           response_preview=result_text[:500])

            total_cost = await self.cost_tracker.finalize_and_charge(
                session=self.session,
                user_id=self.user_id,
                source=self._source_name,
                verdict="ERROR",
                iterations=iteration + 1,
            )

            return SubagentResult(
                verdict="ERROR",
                cost_usd=float(total_cost),
                iterations=iteration + 1,
                error="invalid_response_format",
                data={"raw_response": result_text[:2000]},
            )

    async def _handle_tool_use(self, response: Any,
                               messages: list[dict[str, Any]]) -> None:
        """Handle tool_use response - execute tools and add results."""
        # Add assistant message
        messages.append({
            "role": "assistant",
            "content": [block.model_dump() for block in response.content]
        })

        # Execute all tools in parallel
        tool_use_blocks = [
            block for block in response.content if block.type == "tool_use"
        ]

        tool_tasks = [
            self._execute_tool_with_tracking(
                tool_name=block.name,
                tool_input=block.input,
                tool_use_id=block.id,
            ) for block in tool_use_blocks
        ]

        tool_results = await asyncio.gather(*tool_tasks)

        # Add all tool results in one user message
        messages.append({"role": "user", "content": list(tool_results)})

    async def _execute_tool_with_tracking(
        self,
        tool_name: str,
        tool_input: dict[str, Any],
        tool_use_id: str,
    ) -> dict[str, Any]:
        """Execute tool and track costs."""
        logger.debug(f"{self._source_name}.tool_call",
                     tool_name=tool_name,
                     tool_input_keys=list(tool_input.keys()))

        # Notify callback if present
        if self.on_tool_start:
            try:
                await self.on_tool_start(tool_name)
            except Exception as e:
                logger.warning(f"{self._source_name}.on_tool_start_failed",
                               tool_name=tool_name,
                               error=str(e))

        try:
            result = await self._execute_tool(tool_name, tool_input,
                                              tool_use_id)

            # Track costs
            self._track_tool_cost(tool_name, result)

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
            logger.exception(f"{self._source_name}.tool_error",
                             tool_name=tool_name,
                             error=str(e))
            return {
                "type": "tool_result",
                "tool_use_id": tool_use_id,
                "content": json.dumps({"error": str(e)}),
                "is_error": True
            }

    def _track_tool_cost(self, tool_name: str, result: dict[str, Any]) -> None:
        """Track tool execution cost."""
        cost: Optional[Decimal] = None

        if tool_name == "execute_python" and "execution_time" in result:
            cost = calculate_e2b_cost(result["execution_time"])
        elif "cost_usd" in result:
            cost = Decimal(str(result["cost_usd"]))

        if cost is not None and cost > 0:
            self.cost_tracker.add_tool_cost(tool_name, cost)
            logger.info("tools.loop.user_charged_for_tool",
                        tool_name=tool_name,
                        cost_usd=float(cost),
                        source=self._source_name)

    async def _handle_max_iterations(self) -> SubagentResult:
        """Handle max iterations reached."""
        logger.warning(f"{self._source_name}.max_iterations",
                       iterations=self.config.max_iterations)

        total_cost = await self.cost_tracker.finalize_and_charge(
            session=self.session,
            user_id=self.user_id,
            source=self._source_name,
            verdict="ERROR",
            iterations=self.config.max_iterations,
        )

        return SubagentResult(
            verdict="ERROR",
            cost_usd=float(total_cost),
            iterations=self.config.max_iterations,
            error="max_iterations_reached",
            data={
                "message":
                    f"Did not complete within {self.config.max_iterations} iterations"
            },
        )

    @abstractmethod
    async def _execute_tool(
        self,
        tool_name: str,
        tool_input: dict[str, Any],
        tool_use_id: str,
    ) -> dict[str, Any]:
        """Execute a single tool call.

        Must be implemented by subclasses to provide custom tool execution.

        Args:
            tool_name: Name of the tool to execute.
            tool_input: Input parameters for the tool.
            tool_use_id: Unique ID for this tool use.

        Returns:
            Tool execution result as dictionary.
        """

    @abstractmethod
    def _parse_result(self, response_text: str) -> dict[str, Any]:
        """Parse the final response into structured result.

        Must be implemented by subclasses to provide custom parsing.

        Args:
            response_text: Raw text response from the model.

        Returns:
            Parsed result dictionary. Must include "verdict" key.
        """
