"""Centralized secret management utilities.

Single source of truth for reading Docker secrets.

NO __init__.py - use direct import:
    from core.secrets import read_secret
"""

from pathlib import Path
from typing import Optional

from utils.structured_logging import get_logger

logger = get_logger(__name__)

# Cache for secrets (read once, reuse)
_secrets_cache: dict[str, str] = {}


def read_secret(secret_name: str, required: bool = True) -> Optional[str]:
    """Read a Docker secret from /run/secrets/.

    Secrets are cached after first read for performance.

    Args:
        secret_name: Name of the secret file (e.g., 'anthropic_api_key').
        required: If True, raises FileNotFoundError when secret missing.

    Returns:
        Secret value as string, or None if not found and not required.

    Raises:
        FileNotFoundError: If required secret is not found.

    Examples:
        >>> api_key = read_secret('anthropic_api_key')
        >>> optional_key = read_secret('optional_key', required=False)
    """
    # Check cache first
    if secret_name in _secrets_cache:
        return _secrets_cache[secret_name]

    secret_path = Path(f"/run/secrets/{secret_name}")

    if not secret_path.exists():
        if required:
            logger.error("secrets.not_found",
                         secret_name=secret_name,
                         path=str(secret_path))
            raise FileNotFoundError(f"Required secret not found: {secret_name}")
        else:
            logger.debug("secrets.optional_not_found", secret_name=secret_name)
            return None

    try:
        secret_value = secret_path.read_text(encoding="utf-8").strip()
        _secrets_cache[secret_name] = secret_value
        logger.debug("secrets.loaded", secret_name=secret_name)
        return secret_value
    except Exception as e:
        logger.error("secrets.read_failed",
                     secret_name=secret_name,
                     error=str(e))
        if required:
            raise
        return None


def clear_cache() -> None:
    """Clear the secrets cache.

    Useful for testing or when secrets need to be reloaded.
    """
    global _secrets_cache  # pylint: disable=global-statement
    _secrets_cache = {}
    logger.debug("secrets.cache_cleared")
