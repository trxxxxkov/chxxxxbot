"""Custom exceptions for LLM providers.

This module defines custom exceptions for error handling across all LLM
providers. Allows consistent error handling and user-friendly error messages.

NO __init__.py - use direct import: from core.exceptions import LLMError
"""


class LLMError(Exception):
    """Base exception for all LLM-related errors.

    All custom LLM exceptions inherit from this class, allowing
    catch-all error handling when needed.
    """

    pass  # pylint: disable=unnecessary-pass


class RateLimitError(LLMError):
    """Rate limit exceeded (HTTP 429).

    Raised when the LLM provider returns a rate limit error. The client
    should wait before retrying (check retry-after header if available).

    Attributes:
        message: User-friendly error message.
        retry_after: Seconds to wait before retrying (if provided by API).
    """

    def __init__(self, message: str, retry_after: int = None):
        """Initialize RateLimitError.

        Args:
            message: Error message.
            retry_after: Seconds to wait before retry (optional).
        """
        super().__init__(message)
        self.retry_after = retry_after


class APIConnectionError(LLMError):
    """Failed to connect to LLM API.

    Raised when network connection to the API fails. This could be due to
    network issues, DNS resolution failures, or API service downtime.
    """

    pass  # pylint: disable=unnecessary-pass


class APITimeoutError(LLMError):
    """API request timed out.

    Raised when the API request exceeds the configured timeout. This could
    be due to slow network, API overload, or complex prompts taking too long.
    """

    pass  # pylint: disable=unnecessary-pass


class ContextWindowExceededError(LLMError):
    """Context exceeds model's context window.

    Raised when the total tokens (messages + system prompt) exceed the
    model's maximum context window size.

    Attributes:
        message: User-friendly error message.
        tokens_used: Total tokens in context.
        tokens_limit: Model's context window limit.
    """

    def __init__(self, message: str, tokens_used: int, tokens_limit: int):
        """Initialize ContextWindowExceededError.

        Args:
            message: Error message.
            tokens_used: Total tokens in context.
            tokens_limit: Model's context window limit.
        """
        super().__init__(message)
        self.tokens_used = tokens_used
        self.tokens_limit = tokens_limit


class InsufficientBalanceError(LLMError):
    """User has insufficient balance for request (Phase 2.1).

    Raised when user's balance is insufficient to complete the request
    based on estimated cost.

    Attributes:
        message: User-friendly error message.
        balance: User's current balance (USD).
        estimated_cost: Estimated cost of request (USD).
    """

    def __init__(self, message: str, balance: float, estimated_cost: float):
        """Initialize InsufficientBalanceError.

        Args:
            message: Error message.
            balance: User's current balance.
            estimated_cost: Estimated request cost.
        """
        super().__init__(message)
        self.balance = balance
        self.estimated_cost = estimated_cost


class InvalidModelError(LLMError):
    """Invalid or unsupported model specified.

    Raised when the requested model is not supported by the provider
    or doesn't exist.
    """

    pass  # pylint: disable=unnecessary-pass


class ToolValidationError(Exception):
    """Tool input validation failed.

    Raised when tool inputs fail validation (wrong file type, missing params).
    This is an expected condition, not a system error - should be logged as
    warning, not error. The error message is returned to Claude for correction.

    Attributes:
        message: User-friendly error message for Claude.
        tool_name: Name of the tool that failed validation.
    """

    def __init__(self, message: str, tool_name: str):
        """Initialize ToolValidationError.

        Args:
            message: Error message describing the validation failure.
            tool_name: Name of the tool that failed validation.
        """
        super().__init__(message)
        self.tool_name = tool_name
