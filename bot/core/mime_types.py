"""MIME type detection and normalization utilities.

Centralized MIME type handling for all file operations.
Uses python-magic (libmagic) for reliable detection from file content.

NO __init__.py - use direct import:
    from core.mime_types import detect_mime_type, normalize_mime_type
"""

import mimetypes
from typing import Optional

import magic
from utils.structured_logging import get_logger

logger = get_logger(__name__)

# MIME type normalization map (non-standard -> standard)
MIME_NORMALIZATION = {
    # JFIF variants -> JPEG
    'image/x-jfif': 'image/jpeg',
    'image/jfif': 'image/jpeg',
    'image/pjpeg': 'image/jpeg',
    'image/jpg': 'image/jpeg',
    'image/jpe': 'image/jpeg',
    # PNG variants
    'image/x-png': 'image/png',
    # WebP variants
    'image/x-webp': 'image/webp',
    # GIF variants
    'image/x-gif': 'image/gif',
    # Audio variants
    'audio/mp3': 'audio/mpeg',
    'audio/x-mp3': 'audio/mpeg',
    'audio/x-mpeg': 'audio/mpeg',
    'audio/x-wav': 'audio/wav',
    'audio/wave': 'audio/wav',
    'audio/x-flac': 'audio/flac',
    'audio/x-ogg': 'audio/ogg',
    # Video variants
    'video/x-mp4': 'video/mp4',
    'video/x-m4v': 'video/mp4',
    # Document variants
    'application/x-pdf': 'application/pdf',
    # Text variants from libmagic
    'text/x-python': 'text/x-python',
    'text/x-c': 'text/x-c',
    'text/x-c++': 'text/x-c++',
    'text/x-java': 'text/x-java',
    'text/x-script.python': 'text/x-python',
}

# Extension to MIME type mapping (fallback when libmagic returns generic types)
EXTENSION_MIME_MAP = {
    # Images
    '.jpg': 'image/jpeg',
    '.jpeg': 'image/jpeg',
    '.jfif': 'image/jpeg',
    '.jpe': 'image/jpeg',
    '.png': 'image/png',
    '.gif': 'image/gif',
    '.webp': 'image/webp',
    '.avif': 'image/avif',
    '.heic': 'image/heic',
    '.heif': 'image/heif',
    '.bmp': 'image/bmp',
    '.svg': 'image/svg+xml',
    '.ico': 'image/x-icon',
    '.tiff': 'image/tiff',
    '.tif': 'image/tiff',
    # Audio
    '.mp3': 'audio/mpeg',
    '.wav': 'audio/wav',
    '.flac': 'audio/flac',
    '.ogg': 'audio/ogg',
    '.oga': 'audio/ogg',
    '.opus': 'audio/opus',
    '.m4a': 'audio/mp4',
    '.aac': 'audio/aac',
    '.wma': 'audio/x-ms-wma',
    # Video
    '.mp4': 'video/mp4',
    '.m4v': 'video/mp4',
    '.mov': 'video/quicktime',
    '.avi': 'video/x-msvideo',
    '.mkv': 'video/x-matroska',
    '.webm': 'video/webm',
    '.wmv': 'video/x-ms-wmv',
    '.flv': 'video/x-flv',
    # Documents
    '.pdf': 'application/pdf',
    '.doc': 'application/msword',
    '.docx': 'application/vnd.openxmlformats-officedocument'
             '.wordprocessingml.document',
    '.xls': 'application/vnd.ms-excel',
    '.xlsx': 'application/vnd.openxmlformats-officedocument'
             '.spreadsheetml.sheet',
    '.ppt': 'application/vnd.ms-powerpoint',
    '.pptx': 'application/vnd.openxmlformats-officedocument'
             '.presentationml.presentation',
    # Text/Data - specific types that libmagic might miss
    '.json': 'application/json',
    '.jsonl': 'application/jsonl',
    '.ndjson': 'application/x-ndjson',
    '.yaml': 'application/yaml',
    '.yml': 'application/yaml',
    '.toml': 'application/toml',
    '.xml': 'application/xml',
    '.csv': 'text/csv',
    '.tsv': 'text/tab-separated-values',
    '.md': 'text/markdown',
    '.markdown': 'text/markdown',
    '.rst': 'text/x-rst',
    # Archives
    '.zip': 'application/zip',
    '.rar': 'application/x-rar-compressed',
    '.7z': 'application/x-7z-compressed',
    '.tar': 'application/x-tar',
    '.gz': 'application/gzip',
    '.bz2': 'application/x-bzip2',
    '.xz': 'application/x-xz',
}


def normalize_mime_type(mime_type: str) -> str:
    """Normalize MIME type to standard format.

    Converts non-standard MIME types to their standard equivalents.

    Args:
        mime_type: Original MIME type string.

    Returns:
        Normalized MIME type string.

    Examples:
        >>> normalize_mime_type('image/x-jfif')
        'image/jpeg'
        >>> normalize_mime_type('audio/mp3')
        'audio/mpeg'
    """
    if not mime_type:
        return 'application/octet-stream'

    normalized = mime_type.lower().strip()
    return MIME_NORMALIZATION.get(normalized, normalized)


def detect_mime_from_magic(file_bytes: bytes | bytearray) -> Optional[str]:
    """Detect MIME type using libmagic.

    Uses python-magic (libmagic) to detect file type from content.
    This is the most reliable method for binary files.

    Args:
        file_bytes: File content as bytes or bytearray.

    Returns:
        Detected MIME type or None if detection fails.

    Examples:
        >>> detect_mime_from_magic(open('photo.jpg', 'rb').read())
        'image/jpeg'
    """
    if not file_bytes:
        return None

    # Convert bytearray to bytes (libmagic requires bytes, not bytearray)
    # Also reject non-binary types like str, list, etc.
    if isinstance(file_bytes, bytearray):
        file_bytes = bytes(file_bytes)
    elif not isinstance(file_bytes, bytes):
        logger.warning("mime.magic_expected_bytes",
                       got_type=type(file_bytes).__name__)
        return None

    try:
        mime_type = magic.from_buffer(file_bytes, mime=True)
        if mime_type:
            return normalize_mime_type(mime_type)
        return None
    except Exception as e:
        logger.warning("mime.magic_detection_failed", error=str(e))
        return None


def detect_mime_from_extension(filename: str) -> Optional[str]:
    """Detect MIME type from file extension.

    Args:
        filename: File name with extension.

    Returns:
        MIME type or None if extension not recognized.

    Examples:
        >>> detect_mime_from_extension('data.jsonl')
        'application/jsonl'
    """
    if not filename:
        return None

    # Get extension (lowercase)
    ext = ''
    if '.' in filename:
        ext = '.' + filename.rsplit('.', 1)[-1].lower()

    # Check our map first (includes special cases like .jsonl)
    if ext in EXTENSION_MIME_MAP:
        return EXTENSION_MIME_MAP[ext]

    # Fall back to mimetypes module
    mime_type, _ = mimetypes.guess_type(filename)
    return mime_type


def detect_mime_type(
    filename: str,
    file_bytes: Optional[bytes] = None,
    declared_mime: Optional[str] = None,
) -> str:
    """Detect MIME type using multiple methods.

    Priority order:
    1. libmagic detection from content (most reliable)
    2. File extension (for specific types like .jsonl)
    3. Declared MIME type (normalized)
    4. Fallback to application/octet-stream

    Special handling:
    - If libmagic returns generic 'text/plain' but we have a specific
      extension like .jsonl, use the extension-based type instead.

    Args:
        filename: File name with extension.
        file_bytes: Optional file content for magic detection.
        declared_mime: Optional declared/provided MIME type.

    Returns:
        Detected MIME type string.

    Examples:
        >>> detect_mime_type('photo.jpg', jpeg_bytes)
        'image/jpeg'
        >>> detect_mime_type('data.jsonl', jsonl_bytes)
        'application/jsonl'
    """
    # 1. Try libmagic first (most reliable for binary files)
    if file_bytes:
        magic_mime = detect_mime_from_magic(file_bytes)
        if magic_mime:
            # If libmagic returns generic type, check extension for more
            # specific type. This handles:
            # - text/plain for .jsonl, .yaml files
            # - application/octet-stream for ZIP (libmagic buffer limitation)
            if magic_mime in ('text/plain', 'application/octet-stream'):
                ext_mime = detect_mime_from_extension(filename)
                if ext_mime and ext_mime not in ('text/plain',
                                                 'application/octet-stream'):
                    logger.debug("mime.extension_override",
                                 filename=filename,
                                 magic_mime=magic_mime,
                                 ext_mime=ext_mime)
                    return ext_mime

            logger.debug("mime.detected_from_magic",
                         filename=filename,
                         mime_type=magic_mime)
            return magic_mime

    # 2. Try extension
    ext_mime = detect_mime_from_extension(filename)
    if ext_mime:
        logger.debug("mime.detected_from_extension",
                     filename=filename,
                     mime_type=ext_mime)
        return ext_mime

    # 3. Normalize declared MIME type
    if declared_mime:
        normalized = normalize_mime_type(declared_mime)
        logger.debug("mime.using_declared",
                     filename=filename,
                     declared=declared_mime,
                     normalized=normalized)
        return normalized

    # 4. Fallback
    logger.debug("mime.fallback_to_octet_stream", filename=filename)
    return 'application/octet-stream'


def is_image_mime(mime_type: str) -> bool:
    """Check if MIME type represents an image.

    Args:
        mime_type: MIME type string.

    Returns:
        True if image MIME type.
    """
    normalized = normalize_mime_type(mime_type)
    return normalized.startswith('image/')


def is_audio_mime(mime_type: str) -> bool:
    """Check if MIME type represents audio.

    Args:
        mime_type: MIME type string.

    Returns:
        True if audio MIME type.
    """
    normalized = normalize_mime_type(mime_type)
    return normalized.startswith('audio/')


def is_video_mime(mime_type: str) -> bool:
    """Check if MIME type represents video.

    Args:
        mime_type: MIME type string.

    Returns:
        True if video MIME type.
    """
    normalized = normalize_mime_type(mime_type)
    return normalized.startswith('video/')


def is_pdf_mime(mime_type: str) -> bool:
    """Check if MIME type represents PDF.

    Args:
        mime_type: MIME type string.

    Returns:
        True if PDF MIME type.
    """
    normalized = normalize_mime_type(mime_type)
    return normalized == 'application/pdf'


def is_text_mime(mime_type: str) -> bool:
    """Check if MIME type represents text content.

    Args:
        mime_type: MIME type string.

    Returns:
        True if text MIME type.
    """
    normalized = normalize_mime_type(mime_type)
    return (normalized.startswith('text/') or normalized
            in ('application/json', 'application/jsonl', 'application/x-ndjson',
                'application/xml', 'application/yaml', 'application/toml'))
