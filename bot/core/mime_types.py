"""MIME type detection and normalization utilities.

Centralized MIME type handling for all file operations.
Supports detection from file extension, magic bytes, and normalization.

NO __init__.py - use direct import:
    from core.mime_types import detect_mime_type, normalize_mime_type
"""

import mimetypes
from typing import Optional

from utils.structured_logging import get_logger

logger = get_logger(__name__)

# Magic byte signatures for common image formats
IMAGE_SIGNATURES = {
    b'\xff\xd8\xff': 'image/jpeg',  # JPEG/JFIF
    b'\x89PNG\r\n\x1a\n': 'image/png',  # PNG
    b'GIF87a': 'image/gif',  # GIF87a
    b'GIF89a': 'image/gif',  # GIF89a
    b'RIFF': 'image/webp',  # WebP (needs additional check)
    b'\x00\x00\x00': 'image/avif',  # AVIF (needs additional check)
    b'BM': 'image/bmp',  # BMP
}

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
}

# Extension to MIME type mapping (fallback)
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
    '.txt': 'text/plain',
    '.csv': 'text/csv',
    '.json': 'application/json',
    '.xml': 'application/xml',
    '.html': 'text/html',
    '.htm': 'text/html',
    '.md': 'text/markdown',
    '.py': 'text/x-python',
    '.js': 'text/javascript',
    '.ts': 'text/typescript',
    '.zip': 'application/zip',
    '.rar': 'application/x-rar-compressed',
    '.7z': 'application/x-7z-compressed',
    '.tar': 'application/x-tar',
    '.gz': 'application/gzip',
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


def detect_mime_from_magic(file_bytes: bytes) -> Optional[str]:
    """Detect MIME type from file magic bytes.

    Checks file signature (magic bytes) to determine actual file type.

    Args:
        file_bytes: File content bytes.

    Returns:
        Detected MIME type or None if not recognized.

    Examples:
        >>> detect_mime_from_magic(b'\\xff\\xd8\\xff\\xe0...')
        'image/jpeg'
    """
    if not file_bytes:
        return None

    # Check JPEG (multiple variants)
    if file_bytes[:3] == b'\xff\xd8\xff':
        return 'image/jpeg'

    # Check PNG
    if file_bytes[:8] == b'\x89PNG\r\n\x1a\n':
        return 'image/png'

    # Check GIF
    if file_bytes[:6] in (b'GIF87a', b'GIF89a'):
        return 'image/gif'

    # Check WebP (RIFF....WEBP)
    if file_bytes[:4] == b'RIFF' and file_bytes[8:12] == b'WEBP':
        return 'image/webp'

    # Check BMP
    if file_bytes[:2] == b'BM':
        return 'image/bmp'

    # Check PDF
    if file_bytes[:4] == b'%PDF':
        return 'application/pdf'

    # Check ZIP (and Office documents)
    if file_bytes[:4] == b'PK\x03\x04':
        return 'application/zip'

    return None


def detect_mime_from_extension(filename: str) -> Optional[str]:
    """Detect MIME type from file extension.

    Args:
        filename: File name with extension.

    Returns:
        MIME type or None if extension not recognized.

    Examples:
        >>> detect_mime_from_extension('photo.jfif')
        'image/jpeg'
    """
    if not filename:
        return None

    # Get extension (lowercase)
    ext = ''
    if '.' in filename:
        ext = '.' + filename.rsplit('.', 1)[-1].lower()

    # Check our map first (includes JFIF and other special cases)
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
    1. Magic bytes detection (most reliable for images)
    2. File extension
    3. Declared MIME type (normalized)
    4. Fallback to application/octet-stream

    Args:
        filename: File name with extension.
        file_bytes: Optional file content for magic byte detection.
        declared_mime: Optional declared/provided MIME type.

    Returns:
        Detected MIME type string.

    Examples:
        >>> detect_mime_type('photo.jfif', b'\\xff\\xd8\\xff...')
        'image/jpeg'
        >>> detect_mime_type('document.pdf')
        'application/pdf'
    """
    detected = None

    # 1. Try magic bytes first (most reliable)
    if file_bytes:
        detected = detect_mime_from_magic(file_bytes)
        if detected:
            logger.debug("mime.detected_from_magic",
                         filename=filename,
                         mime_type=detected)
            return detected

    # 2. Try extension
    detected = detect_mime_from_extension(filename)
    if detected:
        logger.debug("mime.detected_from_extension",
                     filename=filename,
                     mime_type=detected)
        return detected

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
