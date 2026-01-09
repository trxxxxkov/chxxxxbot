"""Files API client for Claude multimodal support.

This module provides functions to interact with Claude Files API:
- Upload files (images, PDFs, documents)
- Delete files
- Cleanup expired files (cron job)

Files API lifecycle:
- User uploads file → Bot downloads → upload_to_files_api() → claude_file_id
- File stored in Files API for 24h (FILES_API_TTL_HOURS)
- cleanup_expired_files() cron job deletes expired files

Beta feature: anthropic-beta: files-api-2025-04-14

NO __init__.py - use direct import:
    from core.files_api import upload_to_files_api, delete_from_files_api
"""

from io import BytesIO
from pathlib import Path
from typing import Optional

import anthropic
from utils.structured_logging import get_logger

logger = get_logger(__name__)


def read_secret(secret_name: str) -> str:
    """Read secret from Docker secrets."""
    secret_path = Path(f"/run/secrets/{secret_name}")
    return secret_path.read_text(encoding="utf-8").strip()


# Synchronous client for Files API (beta feature)
_client: Optional[anthropic.Anthropic] = None


def get_client() -> anthropic.Anthropic:
    """Get or create Files API client."""
    global _client  # pylint: disable=global-statement
    if _client is None:
        api_key = read_secret("anthropic_api_key")
        _client = anthropic.Anthropic(
            api_key=api_key,
            default_headers={"anthropic-beta": "files-api-2025-04-14"})
        logger.info("files_api.client_initialized")
    return _client


async def upload_to_files_api(file_bytes: bytes, filename: str,
                              mime_type: str) -> str:
    """Upload file to Claude Files API."""
    try:
        logger.info("files_api.upload_start",
                    filename=filename,
                    mime_type=mime_type,
                    size_bytes=len(file_bytes))

        client = get_client()
        # FileTypes accepts tuple: (filename, file_content)
        file_response = client.beta.files.upload(file=(filename,
                                                       BytesIO(file_bytes)))

        logger.info("files_api.upload_success",
                    filename=filename,
                    claude_file_id=file_response.id,
                    size_bytes=len(file_bytes))

        return file_response.id

    except anthropic.APIError as e:
        logger.error("files_api.upload_failed",
                     filename=filename,
                     mime_type=mime_type,
                     error=str(e),
                     status_code=getattr(e, 'status_code', None),
                     exc_info=True)
        raise


async def download_from_files_api(claude_file_id: str) -> bytes:
    """Download file from Claude Files API.

    Args:
        claude_file_id: Claude file ID (e.g., 'file_abc123').

    Returns:
        File content as bytes.

    Raises:
        anthropic.NotFoundError: If file not found.
        anthropic.APIError: If download fails.
    """
    try:
        logger.info("files_api.download_start", claude_file_id=claude_file_id)

        client = get_client()
        content = client.beta.files.retrieve_content(file_id=claude_file_id)

        logger.info("files_api.download_success",
                    claude_file_id=claude_file_id,
                    size_bytes=len(content))

        return content

    except anthropic.NotFoundError:
        logger.error("files_api.download_not_found",
                     claude_file_id=claude_file_id)
        raise

    except anthropic.APIError as e:
        logger.error("files_api.download_failed",
                     claude_file_id=claude_file_id,
                     error=str(e),
                     status_code=getattr(e, 'status_code', None),
                     exc_info=True)
        raise


async def delete_from_files_api(claude_file_id: str) -> None:
    """Delete file from Files API."""
    try:
        logger.info("files_api.delete_start", claude_file_id=claude_file_id)

        client = get_client()
        client.beta.files.delete(file_id=claude_file_id)

        logger.info("files_api.delete_success", claude_file_id=claude_file_id)

    except anthropic.NotFoundError:
        logger.warning("files_api.delete_not_found",
                       claude_file_id=claude_file_id)

    except anthropic.APIError as e:
        logger.error("files_api.delete_failed",
                     claude_file_id=claude_file_id,
                     error=str(e),
                     status_code=getattr(e, 'status_code', None),
                     exc_info=True)
        raise


async def cleanup_expired_files(user_file_repo) -> dict:
    """Cleanup expired files from Files API and database."""
    logger.info("files_api.cleanup_start")

    expired_files = await user_file_repo.get_expired_files()
    expired_count = len(expired_files)

    logger.info("files_api.cleanup_found", expired_count=expired_count)

    if expired_count == 0:
        return {
            "expired_count": 0,
            "deleted_count": 0,
            "failed_count": 0,
        }

    deleted_count = 0
    failed_count = 0

    for file in expired_files:
        try:
            await delete_from_files_api(file.claude_file_id)
            await user_file_repo.delete(file.id)
            deleted_count += 1

            logger.info("files_api.cleanup_file_deleted",
                        file_id=file.id,
                        claude_file_id=file.claude_file_id,
                        filename=file.filename)

        except Exception as e:  # pylint: disable=broad-exception-caught
            failed_count += 1

            logger.error("files_api.cleanup_file_failed",
                         file_id=file.id,
                         claude_file_id=file.claude_file_id,
                         filename=file.filename,
                         error=str(e),
                         exc_info=True)

    logger.info("files_api.cleanup_complete",
                expired_count=expired_count,
                deleted_count=deleted_count,
                failed_count=failed_count)

    return {
        "expired_count": expired_count,
        "deleted_count": deleted_count,
        "failed_count": failed_count,
    }
