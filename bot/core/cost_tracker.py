"""Cost tracking for subagent and tool executions.

This module provides a reusable CostTracker class that:
- Tracks API token usage (input, output, thinking)
- Tracks tool execution costs
- Calculates total cost
- Charges users via BalanceService

Supports extension via callbacks for metrics (Prometheus, logging, etc.)

NO __init__.py - use direct import:
    from core.cost_tracker import CostTracker
"""

from decimal import Decimal
from typing import Any, Callable, Optional, TYPE_CHECKING

from core.pricing import calculate_claude_cost
from utils.structured_logging import get_logger

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

logger = get_logger(__name__)


class CostTracker:  # pylint: disable=too-many-instance-attributes
    """Track API and tool costs for billing.

    Accumulates:
    - API token costs (input + output + thinking)
    - Tool execution costs (E2B sandbox, Vision API, etc.)

    Supports optional callbacks for metrics/monitoring integration.

    Example:
        tracker = CostTracker(model_id="claude-opus-4-5", user_id=123)
        tracker.add_api_usage(1000, 500, thinking_tokens=200)
        tracker.add_tool_cost("execute_python", Decimal("0.001"))
        total = tracker.calculate_total_cost()
        await tracker.finalize_and_charge(session, user_id, source="self_critique")
    """

    def __init__(
        self,
        model_id: str,
        user_id: int,
        on_api_usage: Optional[Callable[[int, int, int], None]] = None,
        on_tool_cost: Optional[Callable[[str, Decimal], None]] = None,
        on_finalize: Optional[Callable[[str, int, Decimal], None]] = None,
    ):
        """Initialize cost tracker.

        Args:
            model_id: Model identifier for pricing lookup.
            user_id: User ID for logging.
            on_api_usage: Optional callback(input, output, thinking) for metrics.
            on_tool_cost: Optional callback(tool_name, cost) for metrics.
            on_finalize: Optional callback(verdict, iterations, cost) for metrics.
        """
        self.model_id = model_id
        self.user_id = user_id

        self.total_input_tokens = 0
        self.total_output_tokens = 0
        self.total_thinking_tokens = 0
        self.tool_costs: list[tuple[str, Decimal]] = []

        # Optional callbacks for metrics
        self._on_api_usage = on_api_usage
        self._on_tool_cost = on_tool_cost
        self._on_finalize = on_finalize

    def add_api_usage(self,
                      input_tokens: int,
                      output_tokens: int,
                      thinking_tokens: int = 0) -> None:
        """Track API token usage.

        Args:
            input_tokens: Number of input tokens.
            output_tokens: Number of output tokens.
            thinking_tokens: Number of thinking tokens (extended thinking).
        """
        self.total_input_tokens += input_tokens
        self.total_output_tokens += output_tokens
        self.total_thinking_tokens += thinking_tokens

        # Call metrics callback if provided
        if self._on_api_usage:
            self._on_api_usage(input_tokens, output_tokens, thinking_tokens)

    def add_tool_cost(self, tool_name: str, cost: Decimal) -> None:
        """Track tool execution cost.

        Args:
            tool_name: Name of the tool executed.
            cost: Cost in USD.
        """
        self.tool_costs.append((tool_name, cost))

        # Call metrics callback if provided
        if self._on_tool_cost:
            self._on_tool_cost(tool_name, cost)

    def calculate_total_cost(self) -> Decimal:
        """Calculate total cost in USD.

        Returns:
            Total cost as Decimal (API tokens + tool costs).
        """
        token_cost = calculate_claude_cost(
            model_id=self.model_id,
            input_tokens=self.total_input_tokens,
            output_tokens=self.total_output_tokens,
            thinking_tokens=self.total_thinking_tokens,
        )
        tool_cost = sum(cost for _, cost in self.tool_costs)
        return token_cost + tool_cost

    def get_token_summary(self) -> dict[str, int]:
        """Get summary of token usage.

        Returns:
            Dictionary with input, output, thinking token counts.
        """
        return {
            "input": self.total_input_tokens,
            "output": self.total_output_tokens,
            "thinking": self.total_thinking_tokens,
        }

    def get_tool_cost_summary(self) -> dict[str, Any]:
        """Get summary of tool costs.

        Returns:
            Dictionary with tool costs and total.
        """
        return {
            "costs": [(name, float(cost)) for name, cost in self.tool_costs],
            "total": float(sum(cost for _, cost in self.tool_costs)),
        }

    async def finalize_and_charge(
        self,
        session: 'AsyncSession',
        user_id: int,
        source: str,
        verdict: str = "UNKNOWN",
        iterations: int = 1,
    ) -> Decimal:
        """Finalize tracking and charge user.

        Args:
            session: Database session.
            user_id: User to charge.
            source: Source identifier for billing description (e.g., "self_critique").
            verdict: Result verdict for logging/metrics.
            iterations: Number of iterations completed.

        Returns:
            Total cost charged in USD.
        """
        from services.factory import ServiceFactory

        total_cost = self.calculate_total_cost()
        services = ServiceFactory(session)

        tool_cost_sum = sum(cost for _, cost in self.tool_costs)
        description = (f"{source} ({self.model_id}): "
                       f"{self.total_input_tokens} in, "
                       f"{self.total_output_tokens} out, "
                       f"{self.total_thinking_tokens} thinking, "
                       f"tools: ${float(tool_cost_sum):.4f}")

        await services.balance.charge_user(
            user_id=user_id,
            amount=total_cost,
            description=description,
        )

        # Call finalize callback if provided
        if self._on_finalize:
            self._on_finalize(verdict, iterations, total_cost)

        logger.info(f"{source}.cost_charged",
                    user_id=user_id,
                    total_cost=float(total_cost),
                    input_tokens=self.total_input_tokens,
                    output_tokens=self.total_output_tokens,
                    thinking_tokens=self.total_thinking_tokens,
                    tool_costs=[(n, float(c)) for n, c in self.tool_costs],
                    verdict=verdict,
                    iterations=iterations)

        return total_cost
