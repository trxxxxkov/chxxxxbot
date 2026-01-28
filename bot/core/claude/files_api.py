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

import asyncio
from io import BytesIO
import random
from typing import Optional

import anthropic

# Retry configuration for transient API errors
MAX_RETRIES = 3
BASE_DELAY_SECONDS = 1.0
MAX_DELAY_SECONDS = 10.0
from core.clients import get_anthropic_client
from core.mime_types import detect_mime_type
from core.mime_types import is_audio_mime
from core.mime_types import is_image_mime
from core.mime_types import is_pdf_mime
from core.mime_types import is_video_mime
from core.mime_types import normalize_mime_type
from utils.metrics import record_file_upload
from utils.structured_logging import get_logger

logger = get_logger(__name__)


def _is_retryable_error(error: Exception) -> bool:
    """Check if error is retryable (transient API error).

    Args:
        error: Exception to check.

    Returns:
        True if error is retryable (5xx, connection, rate limit).
    """
    if isinstance(error, anthropic.InternalServerError):
        return True
    if isinstance(error, anthropic.APIConnectionError):
        return True
    if isinstance(error, anthropic.RateLimitError):
        return True
    if isinstance(error, anthropic.APIStatusError):
        # Retry on 5xx errors
        return error.status_code >= 500
    return False


def _calculate_retry_delay(attempt: int) -> float:
    """Calculate delay with exponential backoff and jitter.

    Args:
        attempt: Current attempt number (0-indexed).

    Returns:
        Delay in seconds before next retry.
    """
    # Exponential backoff: 1s, 2s, 4s, ...
    delay = BASE_DELAY_SECONDS * (2**attempt)
    # Cap at max delay
    delay = min(delay, MAX_DELAY_SECONDS)
    # Add jitter (±25%)
    jitter = delay * 0.25 * (2 * random.random() - 1)
    return delay + jitter


def _get_file_type_from_mime(mime_type: str) -> str:
    """Infer file type from MIME type for metrics.

    Args:
        mime_type: MIME type (e.g., 'image/jpeg', 'application/pdf').

    Returns:
        File type category: 'image', 'pdf', 'audio', 'video', or 'document'.
    """
    normalized = normalize_mime_type(mime_type)
    if is_image_mime(normalized):
        return 'image'
    elif is_pdf_mime(normalized):
        return 'pdf'
    elif is_audio_mime(normalized):
        return 'audio'
    elif is_video_mime(normalized):
        return 'video'
    else:
        return 'document'


async def upload_to_files_api(
    file_bytes: bytes,
    filename: str,
    mime_type: Optional[str] = None,
) -> str:
    """Upload file to Claude Files API with retry on transient errors.

    Args:
        file_bytes: File content as bytes.
        filename: Original filename (used for extension-based MIME detection).
        mime_type: Optional declared MIME type (will be auto-detected if None).

    Returns:
        Claude file ID string.

    Raises:
        anthropic.APIError: If upload fails after all retries.
    """
    # Auto-detect MIME type from content and filename
    detected_mime = detect_mime_type(
        filename=filename,
        file_bytes=file_bytes,
        declared_mime=mime_type,
    )

    logger.info("files_api.upload_start",
                filename=filename,
                declared_mime=mime_type,
                detected_mime=detected_mime,
                size_bytes=len(file_bytes))

    # Use centralized client factory
    client = get_anthropic_client(use_files_api=True)

    last_error = None

    for attempt in range(MAX_RETRIES):
        try:
            # FileTypes accepts tuple: (filename, file_content, mime_type)
            # Run in thread pool to avoid blocking event loop
            def _sync_upload():
                return client.beta.files.upload(file=(filename,
                                                      BytesIO(file_bytes),
                                                      detected_mime))

            file_response = await asyncio.to_thread(_sync_upload)

            logger.info("files_api.upload_success",
                        filename=filename,
                        claude_file_id=file_response.id,
                        mime_type=detected_mime,
                        size_bytes=len(file_bytes),
                        attempt=attempt + 1)

            # Record metric
            file_type = _get_file_type_from_mime(detected_mime)
            record_file_upload(file_type=file_type)

            return file_response.id

        except anthropic.APIError as e:
            last_error = e

            if not _is_retryable_error(e) or attempt == MAX_RETRIES - 1:
                # Non-retryable error or last attempt - log and raise
                logger.info("files_api.upload_failed",
                            filename=filename,
                            mime_type=mime_type,
                            error=str(e),
                            status_code=getattr(e, 'status_code', None),
                            attempt=attempt + 1,
                            max_retries=MAX_RETRIES)
                raise

            # Retryable error - wait and retry
            delay = _calculate_retry_delay(attempt)
            logger.info("files_api.upload_retry",
                        filename=filename,
                        error=str(e),
                        status_code=getattr(e, 'status_code', None),
                        attempt=attempt + 1,
                        max_retries=MAX_RETRIES,
                        retry_delay_seconds=round(delay, 2))
            await asyncio.sleep(delay)

    # Should not reach here, but just in case
    raise last_error  # type: ignore


async def download_from_files_api(claude_file_id: str) -> bytes:
    """Download file from Claude Files API with retry on transient errors.

    Args:
        claude_file_id: Claude file ID (e.g., 'file_abc123').

    Returns:
        File content as bytes.

    Raises:
        anthropic.NotFoundError: If file not found.
        anthropic.APIError: If download fails after all retries.
    """
    logger.info("files_api.download_start", claude_file_id=claude_file_id)

    # Use centralized client factory
    client = get_anthropic_client(use_files_api=True)

    last_error = None

    for attempt in range(MAX_RETRIES):
        try:
            # Files API method: download() (official SDK method)
            # Run in thread pool to avoid blocking event loop
            def _sync_download():
                return client.beta.files.download(file_id=claude_file_id)

            content = await asyncio.to_thread(_sync_download)

            logger.info("files_api.download_success",
                        claude_file_id=claude_file_id,
                        size_bytes=len(content),
                        attempt=attempt + 1)

            return content

        except anthropic.NotFoundError:
            # NotFoundError is not retryable - file doesn't exist
            logger.info("files_api.download_not_found",
                        claude_file_id=claude_file_id)
            raise

        except anthropic.APIError as e:
            last_error = e

            if not _is_retryable_error(e) or attempt == MAX_RETRIES - 1:
                # Non-retryable error or last attempt - log and raise
                logger.info("files_api.download_failed",
                            claude_file_id=claude_file_id,
                            error=str(e),
                            status_code=getattr(e, 'status_code', None),
                            attempt=attempt + 1,
                            max_retries=MAX_RETRIES)
                raise

            # Retryable error - wait and retry
            delay = _calculate_retry_delay(attempt)
            logger.info("files_api.download_retry",
                        claude_file_id=claude_file_id,
                        error=str(e),
                        status_code=getattr(e, 'status_code', None),
                        attempt=attempt + 1,
                        max_retries=MAX_RETRIES,
                        retry_delay_seconds=round(delay, 2))
            await asyncio.sleep(delay)

    # Should not reach here, but just in case
    raise last_error  # type: ignore


async def delete_from_files_api(claude_file_id: str) -> None:
    """Delete file from Files API with retry on transient errors."""
    logger.info("files_api.delete_start", claude_file_id=claude_file_id)

    # Use centralized client factory
    client = get_anthropic_client(use_files_api=True)

    last_error = None

    for attempt in range(MAX_RETRIES):
        try:
            # Run in thread pool to avoid blocking event loop
            def _sync_delete():
                return client.beta.files.delete(file_id=claude_file_id)

            await asyncio.to_thread(_sync_delete)

            logger.info("files_api.delete_success",
                        claude_file_id=claude_file_id,
                        attempt=attempt + 1)
            return

        except anthropic.NotFoundError:
            # NotFoundError is acceptable for delete - file already gone
            logger.debug("files_api.delete_not_found",
                         claude_file_id=claude_file_id)
            return

        except anthropic.APIError as e:
            last_error = e

            if not _is_retryable_error(e) or attempt == MAX_RETRIES - 1:
                # Non-retryable error or last attempt - log and raise
                logger.info("files_api.delete_failed",
                            claude_file_id=claude_file_id,
                            error=str(e),
                            status_code=getattr(e, 'status_code', None),
                            attempt=attempt + 1,
                            max_retries=MAX_RETRIES)
                raise

            # Retryable error - wait and retry
            delay = _calculate_retry_delay(attempt)
            logger.info("files_api.delete_retry",
                        claude_file_id=claude_file_id,
                        error=str(e),
                        status_code=getattr(e, 'status_code', None),
                        attempt=attempt + 1,
                        max_retries=MAX_RETRIES,
                        retry_delay_seconds=round(delay, 2))
            await asyncio.sleep(delay)

    # Should not reach here, but just in case
    raise last_error  # type: ignore


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

            logger.info("files_api.cleanup_file_failed",
                        file_id=file.id,
                        claude_file_id=file.claude_file_id,
                        filename=file.filename,
                        error=str(e))

    logger.info("files_api.cleanup_complete",
                expired_count=expired_count,
                deleted_count=deleted_count,
                failed_count=failed_count)

    return {
        "expired_count": expired_count,
        "deleted_count": deleted_count,
        "failed_count": failed_count,
    }
