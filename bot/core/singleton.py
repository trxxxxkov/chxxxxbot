"""Singleton pattern utilities.

Provides consistent lazy initialization for service singletons.
Thread-safe through Python's GIL for simple cases.

Usage:
    from core.singleton import singleton

    @singleton
    def get_my_service() -> MyService:
        return MyService(config.SETTING)

    # First call creates instance
    service = get_my_service()

    # Subsequent calls return same instance
    same_service = get_my_service()
    assert service is same_service

    # Reset for testing
    get_my_service.reset()

NO __init__.py - use direct import:
    from core.singleton import singleton
"""

from functools import wraps
from typing import Callable, TypeVar

T = TypeVar('T')


def singleton(func: Callable[[], T]) -> Callable[[], T]:
    """Decorator for singleton getter functions.

    Caches the result of the first call and returns it
    for all subsequent calls. Adds a reset() method for testing.

    Args:
        func: Zero-argument function that creates the singleton instance.

    Returns:
        Wrapped function that returns cached instance.

    Example:
        @singleton
        def get_redis_client() -> Redis:
            return Redis(host='localhost', port=6379)

        client = get_redis_client()  # Creates instance
        same = get_redis_client()    # Returns cached instance
        assert client is same

        get_redis_client.reset()     # Clears cache (for tests)
    """
    instance = None

    @wraps(func)
    def wrapper() -> T:
        nonlocal instance
        if instance is None:
            instance = func()
        return instance

    def reset() -> None:
        """Reset singleton instance (for testing)."""
        nonlocal instance
        instance = None

    wrapper.reset = reset  # type: ignore[attr-defined]
    return wrapper
