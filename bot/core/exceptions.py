"""Custom exceptions for the bot.

This module defines custom exceptions for error handling:
- BotError: Base class with log_level and user_message
- LLMError: LLM-specific errors (rate limit, timeout, etc.)
- ToolValidationError: Tool input validation failures

Phase 4.3: Standardized error classification system.

NO __init__.py - use direct import:
    from core.exceptions import LLMError, BotError, ToolExecutionError
"""


class BotError(Exception):
    """Base class for all bot errors.

    Phase 4.3: Provides consistent error handling with:
    - recoverable: Whether to retry or fail permanently
    - user_message: Safe message to show to user
    - log_level: Appropriate logging level

    Usage:
        try:
            await do_something()
        except BotError as e:
            logger.log(e.log_level, "error", error=str(e))
            await message.answer(e.user_message)
    """

    recoverable: bool = True
    user_message: str = "An error occurred. Please try again."
    log_level: str = "warning"

    def __init__(self, message: str = None):
        """Initialize BotError.

        Args:
            message: Technical error message (for logs).
        """
        super().__init__(message or self.user_message)


class LLMError(BotError):
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


class OverloadedError(LLMError):
    """API server is overloaded (HTTP 529).

    Raised when the API returns an overloaded error after retry attempts
    are exhausted. This is a transient condition — the user should retry later.
    """

    recoverable = True
    user_message = "⏳ Claude is currently overloaded. Please try again in a minute."
    log_level = "warning"


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


# ============================================================================
# Phase 4.3: Additional error types for consistent handling
# ============================================================================


class ToolExecutionError(BotError):
    """Tool failed to execute.

    Raised when a tool execution fails (external API error, timeout, etc.).
    This is recoverable - user can try again.
    """

    recoverable = True
    user_message = "Tool execution failed. Please try again."
    log_level = "warning"

    def __init__(self, message: str, tool_name: str):
        """Initialize ToolExecutionError.

        Args:
            message: Technical error message.
            tool_name: Name of the tool that failed.
        """
        super().__init__(message)
        self.tool_name = tool_name


class ExternalAPIError(BotError):
    """External API error (not LLM).

    Raised when external services (E2B, Gemini, etc.) fail.
    May be recoverable depending on the error.
    """

    recoverable = True
    user_message = "External service temporarily unavailable. Please try again."
    log_level = "warning"

    def __init__(self, message: str, service: str):
        """Initialize ExternalAPIError.

        Args:
            message: Technical error message.
            service: Name of the failed service.
        """
        super().__init__(message)
        self.service = service


class CacheError(BotError):
    """Redis cache operation failed.

    Raised when cache operations fail. Operations should continue
    with database fallback.
    """

    recoverable = True
    user_message = "Please try again."
    log_level = "warning"


class DatabaseError(BotError):
    """Database operation failed.

    Raised when database operations fail. This is a more serious
    error that may not be recoverable.
    """

    recoverable = False
    user_message = "Service temporarily unavailable. Please try again later."
    log_level = "error"


class ConfigurationError(BotError):
    """Configuration or setup error.

    Raised when configuration is missing or invalid.
    Not recoverable without admin intervention.
    """

    recoverable = False
    user_message = "Service configuration error. Please contact administrator."
    log_level = "error"


class ConcurrencyError(BotError):
    """Concurrency limit exceeded.

    Raised when user exceeds concurrent request limit.
    Recoverable after other requests complete.
    """

    recoverable = True
    user_message = "Too many requests. Please wait for current request to finish."
    log_level = "info"  # Expected behavior, not an error


class FileProcessingError(BotError):
    """File processing failed.

    Raised when file upload, download, or processing fails.
    """

    recoverable = True
    user_message = "Failed to process file. Please try again."
    log_level = "warning"

    def __init__(self, message: str, filename: str = None):
        """Initialize FileProcessingError.

        Args:
            message: Technical error message.
            filename: Name of the file that failed.
        """
        super().__init__(message)
        self.filename = filename
