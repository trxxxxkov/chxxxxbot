"""Centralized API client factories.

Single source of truth for creating API clients with proper configuration.
Handles lazy initialization, beta headers, and consistent patterns.

NO __init__.py - use direct import:
    from core.clients import get_anthropic_client, get_openai_client
"""

from typing import Optional

import anthropic
from anthropic import AsyncAnthropic

from core.secrets import read_secret
from utils.structured_logging import get_logger

logger = get_logger(__name__)

# Cached clients (initialized lazily)
_anthropic_sync: Optional[anthropic.Anthropic] = None
_anthropic_async: Optional[AsyncAnthropic] = None
_anthropic_sync_files: Optional[anthropic.Anthropic] = None
_anthropic_async_files: Optional[AsyncAnthropic] = None
_openai_client = None
_openai_async_client = None
_google_client = None

# Beta headers for Files API
FILES_API_BETA_HEADER = "files-api-2025-04-14"


def get_anthropic_client(
    use_files_api: bool = False,
) -> anthropic.Anthropic:
    """Get synchronous Anthropic client.

    Args:
        use_files_api: If True, includes Files API beta header.

    Returns:
        Configured Anthropic client.
    """
    global _anthropic_sync, _anthropic_sync_files  # pylint: disable=global-statement

    if use_files_api:
        if _anthropic_sync_files is None:
            api_key = read_secret("anthropic_api_key")
            _anthropic_sync_files = anthropic.Anthropic(
                api_key=api_key,
                default_headers={"anthropic-beta": FILES_API_BETA_HEADER}
            )
            logger.info("clients.anthropic_sync_files.initialized")
        return _anthropic_sync_files
    else:
        if _anthropic_sync is None:
            api_key = read_secret("anthropic_api_key")
            _anthropic_sync = anthropic.Anthropic(api_key=api_key)
            logger.info("clients.anthropic_sync.initialized")
        return _anthropic_sync


def get_anthropic_async_client(
    use_files_api: bool = False,
) -> AsyncAnthropic:
    """Get asynchronous Anthropic client.

    Args:
        use_files_api: If True, includes Files API beta header.

    Returns:
        Configured AsyncAnthropic client.
    """
    global _anthropic_async, _anthropic_async_files  # pylint: disable=global-statement

    if use_files_api:
        if _anthropic_async_files is None:
            api_key = read_secret("anthropic_api_key")
            _anthropic_async_files = AsyncAnthropic(
                api_key=api_key,
                default_headers={"anthropic-beta": FILES_API_BETA_HEADER}
            )
            logger.info("clients.anthropic_async_files.initialized")
        return _anthropic_async_files
    else:
        if _anthropic_async is None:
            api_key = read_secret("anthropic_api_key")
            _anthropic_async = AsyncAnthropic(api_key=api_key)
            logger.info("clients.anthropic_async.initialized")
        return _anthropic_async


def get_openai_client():
    """Get synchronous OpenAI client.

    Returns:
        Configured OpenAI client.
    """
    global _openai_client  # pylint: disable=global-statement

    if _openai_client is None:
        import openai  # pylint: disable=import-outside-toplevel
        api_key = read_secret("openai_api_key")
        _openai_client = openai.OpenAI(api_key=api_key)
        logger.info("clients.openai_sync.initialized")

    return _openai_client


def get_openai_async_client():
    """Get asynchronous OpenAI client.

    Returns:
        Configured AsyncOpenAI client.
    """
    global _openai_async_client  # pylint: disable=global-statement

    if _openai_async_client is None:
        import openai  # pylint: disable=import-outside-toplevel
        api_key = read_secret("openai_api_key")
        _openai_async_client = openai.AsyncOpenAI(api_key=api_key)
        logger.info("clients.openai_async.initialized")

    return _openai_async_client


def get_google_client():
    """Get Google GenAI client.

    Returns:
        Configured Google client.
    """
    global _google_client  # pylint: disable=global-statement

    if _google_client is None:
        from google import genai  # pylint: disable=import-outside-toplevel
        api_key = read_secret("google_api_key")
        _google_client = genai.Client(api_key=api_key)
        logger.info("clients.google.initialized")

    return _google_client


def get_e2b_api_key() -> str:
    """Get E2B API key.

    Returns:
        E2B API key string.
    """
    return read_secret("e2b_api_key")


def clear_all_clients() -> None:
    """Clear all cached clients.

    Useful for testing or cleanup.
    """
    global _anthropic_sync, _anthropic_async  # pylint: disable=global-statement
    global _anthropic_sync_files, _anthropic_async_files  # pylint: disable=global-statement
    global _openai_client, _openai_async_client  # pylint: disable=global-statement
    global _google_client  # pylint: disable=global-statement

    _anthropic_sync = None
    _anthropic_async = None
    _anthropic_sync_files = None
    _anthropic_async_files = None
    _openai_client = None
    _openai_async_client = None
    _google_client = None

    logger.info("clients.all_cleared")
