"""Tests for MIME type detection using python-magic (libmagic).

Tests for core.mime_types module which handles:
- libmagic-based detection from file content
- Extension-based detection as fallback
- MIME type normalization
- File type classification helpers

NO __init__.py - use direct import:
    from tests.core.test_mime_types import TestDetectMimeFromMagic
"""

from core.mime_types import detect_mime_from_extension
from core.mime_types import detect_mime_from_magic
from core.mime_types import detect_mime_type
from core.mime_types import EXTENSION_MIME_MAP
from core.mime_types import is_audio_mime
from core.mime_types import is_image_mime
from core.mime_types import is_pdf_mime
from core.mime_types import is_text_mime
from core.mime_types import is_video_mime
from core.mime_types import normalize_mime_type
import pytest

# Real file signatures for testing libmagic
JPEG_BYTES = b'\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01'
PNG_BYTES = b'\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR'
GIF_BYTES = b'GIF89a\x01\x00\x01\x00\x80\x00\x00'
PDF_BYTES = b'%PDF-1.4\n%\xe2\xe3\xcf\xd3\n'
ZIP_BYTES = b'PK\x03\x04\x14\x00\x00\x00\x08\x00'
TEXT_BYTES = b'Hello, World!\nThis is plain text.\n'
JSON_BYTES = b'{"key": "value", "number": 123}'
JSONL_BYTES = b'{"id": 1, "score": 0.5}\n{"id": 2, "score": 0.7}\n'


class TestDetectMimeFromMagic:
    """Tests for libmagic-based MIME detection."""

    def test_jpeg_detection(self):
        """Test JPEG detection from content."""
        result = detect_mime_from_magic(JPEG_BYTES)
        assert result == 'image/jpeg'

    def test_png_detection(self):
        """Test PNG detection from content."""
        result = detect_mime_from_magic(PNG_BYTES)
        assert result == 'image/png'

    def test_gif_detection(self):
        """Test GIF detection from content."""
        result = detect_mime_from_magic(GIF_BYTES)
        assert result == 'image/gif'

    def test_pdf_detection(self):
        """Test PDF detection from content."""
        result = detect_mime_from_magic(PDF_BYTES)
        assert result == 'application/pdf'

    def test_zip_returns_octet_stream_from_buffer(self):
        """Test that ZIP detection from buffer returns octet-stream.

        Known libmagic limitation: ZIP files read from buffer return
        application/octet-stream because ZIP's Central Directory is
        at the end of the file. This is handled by extension fallback
        in detect_mime_type().
        """
        result = detect_mime_from_magic(ZIP_BYTES)
        # libmagic returns octet-stream for ZIP from buffer
        assert result == 'application/octet-stream'

    def test_text_detection(self):
        """Test plain text detection from content."""
        result = detect_mime_from_magic(TEXT_BYTES)
        assert result == 'text/plain'

    def test_json_detected_as_json(self):
        """Test that JSON is detected as application/json by libmagic."""
        result = detect_mime_from_magic(JSON_BYTES)
        assert result == 'application/json'

    def test_jsonl_detected_as_ndjson(self):
        """Test that JSONL is detected as application/x-ndjson by libmagic.

        libmagic properly detects newline-delimited JSON format.
        """
        result = detect_mime_from_magic(JSONL_BYTES)
        assert result == 'application/x-ndjson'

    def test_empty_bytes_returns_none(self):
        """Test that empty bytes return None."""
        assert detect_mime_from_magic(b'') is None
        assert detect_mime_from_magic(None) is None

    def test_bytearray_input_works(self):
        """Test that bytearray input is converted to bytes and works.

        Regression test: E2B sandbox returns bytearray instead of bytes,
        which libmagic doesn't accept directly. We convert it.
        """
        # bytearray should work the same as bytes
        png_bytearray = bytearray(PNG_BYTES)
        assert detect_mime_from_magic(png_bytearray) == 'image/png'

        jpeg_bytearray = bytearray(JPEG_BYTES)
        assert detect_mime_from_magic(jpeg_bytearray) == 'image/jpeg'

    def test_non_bytes_input_returns_none(self):
        """Test that non-binary input returns None gracefully.

        Regression test: reject types that can't represent binary data.
        """
        # String instead of bytes
        assert detect_mime_from_magic("hello world") is None
        # List instead of bytes
        assert detect_mime_from_magic([1, 2, 3]) is None
        # Dict instead of bytes
        assert detect_mime_from_magic({"data": "test"}) is None


class TestDetectMimeFromExtension:
    """Tests for extension-based MIME detection."""

    def test_jsonl_extension(self):
        """Test JSONL extension detection.

        Regression test: .jsonl files need extension-based detection
        because libmagic returns text/plain.
        """
        assert detect_mime_from_extension('data.jsonl') == 'application/jsonl'
        assert detect_mime_from_extension('DATA.JSONL') == 'application/jsonl'

    def test_json_extension(self):
        """Test JSON extension detection."""
        assert detect_mime_from_extension('config.json') == 'application/json'

    def test_yaml_extensions(self):
        """Test YAML extension detection."""
        assert detect_mime_from_extension('config.yaml') == 'application/yaml'
        assert detect_mime_from_extension('config.yml') == 'application/yaml'

    def test_image_extensions(self):
        """Test image extension detection."""
        assert detect_mime_from_extension('photo.jpg') == 'image/jpeg'
        assert detect_mime_from_extension('photo.jpeg') == 'image/jpeg'
        assert detect_mime_from_extension('image.png') == 'image/png'
        assert detect_mime_from_extension('anim.gif') == 'image/gif'
        assert detect_mime_from_extension('image.webp') == 'image/webp'
        assert detect_mime_from_extension('photo.heic') == 'image/heic'

    def test_audio_extensions(self):
        """Test audio extension detection."""
        assert detect_mime_from_extension('song.mp3') == 'audio/mpeg'
        assert detect_mime_from_extension('audio.wav') == 'audio/wav'
        assert detect_mime_from_extension('audio.flac') == 'audio/flac'

    def test_video_extensions(self):
        """Test video extension detection."""
        assert detect_mime_from_extension('video.mp4') == 'video/mp4'
        assert detect_mime_from_extension('video.mov') == 'video/quicktime'
        assert detect_mime_from_extension('video.webm') == 'video/webm'

    def test_archive_extensions(self):
        """Test archive extension detection."""
        assert detect_mime_from_extension('file.zip') == 'application/zip'
        assert detect_mime_from_extension('file.tar') == 'application/x-tar'
        assert detect_mime_from_extension('file.gz') == 'application/gzip'
        assert detect_mime_from_extension(
            'file.7z') == 'application/x-7z-compressed'

    def test_case_insensitive(self):
        """Test that extension detection is case-insensitive."""
        assert detect_mime_from_extension('FILE.JSONL') == 'application/jsonl'
        assert detect_mime_from_extension('IMAGE.PNG') == 'image/png'
        assert detect_mime_from_extension('VIDEO.MP4') == 'video/mp4'

    def test_no_extension_returns_none(self):
        """Test files without extension."""
        assert detect_mime_from_extension('Makefile') is None
        assert detect_mime_from_extension('README') is None

    def test_empty_filename_returns_none(self):
        """Test empty filename."""
        assert detect_mime_from_extension('') is None
        assert detect_mime_from_extension(None) is None


class TestDetectMimeType:
    """Tests for combined MIME detection."""

    def test_libmagic_priority_for_binary(self):
        """Test that libmagic takes priority for binary files."""
        # Even with wrong extension, libmagic detects correct type
        result = detect_mime_type('wrong.txt', file_bytes=PNG_BYTES)
        assert result == 'image/png'

    def test_libmagic_detects_jsonl(self):
        """Test that libmagic properly detects JSONL as x-ndjson.

        libmagic recognizes JSONL/NDJSON format and returns
        the correct MIME type.
        """
        result = detect_mime_type('data.jsonl', file_bytes=JSONL_BYTES)
        assert result == 'application/x-ndjson'

    def test_json_with_extension(self):
        """Test JSON detection with extension override."""
        result = detect_mime_type('config.json', file_bytes=JSON_BYTES)
        assert result == 'application/json'

    def test_yaml_with_extension(self):
        """Test YAML detection with extension override."""
        yaml_bytes = b'key: value\nlist:\n  - item1\n  - item2\n'
        result = detect_mime_type('config.yaml', file_bytes=yaml_bytes)
        assert result == 'application/yaml'

    def test_extension_fallback_without_content(self):
        """Test extension fallback when no content provided."""
        result = detect_mime_type('video.mp4')
        assert result == 'video/mp4'

    def test_declared_mime_fallback(self):
        """Test fallback to declared MIME when nothing else matches."""
        result = detect_mime_type('unknown_file',
                                  declared_mime='application/custom')
        assert result == 'application/custom'

    def test_octet_stream_fallback(self):
        """Test fallback to octet-stream when nothing matches."""
        result = detect_mime_type('unknown_file')
        assert result == 'application/octet-stream'

    def test_real_world_jsonl_scenario(self):
        """Test real-world scenario: user uploads JSONL file.

        Regression test for bug where user uploaded .jsonl file
        and it got application/octet-stream MIME type.
        Now libmagic properly detects it as x-ndjson.
        """
        result = detect_mime_type('score_diffs_18_01_2026.jsonl',
                                  file_bytes=JSONL_BYTES,
                                  declared_mime=None)
        # libmagic detects JSONL as application/x-ndjson
        assert result == 'application/x-ndjson'
        assert result != 'application/octet-stream'
        assert result != 'text/plain'

    def test_video_with_mock_content(self):
        """Test that video extension works even with mock content.

        In tests, mock content might be text-like, but extension
        should still be checked first after libmagic.
        """
        # Real video would have binary content detected by libmagic
        result = detect_mime_type('clip.mp4', file_bytes=None)
        assert result == 'video/mp4'

    def test_audio_detection(self):
        """Test audio file detection by extension."""
        result = detect_mime_type('song.mp3')
        assert result == 'audio/mpeg'

    def test_zip_detected_via_extension_fallback(self):
        """Test ZIP detection via extension when libmagic fails.

        libmagic returns octet-stream for ZIP from buffer, but the
        combined detect_mime_type() function correctly falls back to
        extension-based detection.
        """
        result = detect_mime_type('archive.zip', file_bytes=ZIP_BYTES)
        assert result == 'application/zip'


class TestNormalizeMimeType:
    """Tests for MIME type normalization."""

    def test_jfif_normalization(self):
        """Test JFIF variants normalize to JPEG."""
        assert normalize_mime_type('image/x-jfif') == 'image/jpeg'
        assert normalize_mime_type('image/jfif') == 'image/jpeg'
        assert normalize_mime_type('image/pjpeg') == 'image/jpeg'
        assert normalize_mime_type('image/jpg') == 'image/jpeg'

    def test_mp3_normalization(self):
        """Test MP3 variants normalize to audio/mpeg."""
        assert normalize_mime_type('audio/mp3') == 'audio/mpeg'
        assert normalize_mime_type('audio/x-mp3') == 'audio/mpeg'

    def test_standard_types_unchanged(self):
        """Test that standard types remain unchanged."""
        assert normalize_mime_type('image/jpeg') == 'image/jpeg'
        assert normalize_mime_type('image/png') == 'image/png'
        assert normalize_mime_type('application/json') == 'application/json'

    def test_empty_returns_octet_stream(self):
        """Test that empty input returns octet-stream."""
        assert normalize_mime_type('') == 'application/octet-stream'
        assert normalize_mime_type(None) == 'application/octet-stream'

    def test_case_insensitive(self):
        """Test that normalization is case-insensitive."""
        assert normalize_mime_type('IMAGE/X-JFIF') == 'image/jpeg'
        assert normalize_mime_type('Audio/MP3') == 'audio/mpeg'


class TestMimeTypeHelpers:
    """Tests for MIME type classification helpers."""

    def test_is_image_mime(self):
        """Test image MIME detection."""
        assert is_image_mime('image/jpeg') is True
        assert is_image_mime('image/png') is True
        assert is_image_mime('image/x-jfif') is True  # Normalized
        assert is_image_mime('image/heic') is True
        assert is_image_mime('application/pdf') is False
        assert is_image_mime('text/plain') is False

    def test_is_audio_mime(self):
        """Test audio MIME detection."""
        assert is_audio_mime('audio/mpeg') is True
        assert is_audio_mime('audio/mp3') is True  # Normalized
        assert is_audio_mime('audio/wav') is True
        assert is_audio_mime('video/mp4') is False

    def test_is_video_mime(self):
        """Test video MIME detection."""
        assert is_video_mime('video/mp4') is True
        assert is_video_mime('video/webm') is True
        assert is_video_mime('audio/mpeg') is False

    def test_is_pdf_mime(self):
        """Test PDF MIME detection."""
        assert is_pdf_mime('application/pdf') is True
        assert is_pdf_mime('application/x-pdf') is True  # Normalized
        assert is_pdf_mime('application/json') is False

    def test_is_text_mime(self):
        """Test text MIME detection."""
        assert is_text_mime('text/plain') is True
        assert is_text_mime('text/html') is True
        assert is_text_mime('application/json') is True
        assert is_text_mime('application/jsonl') is True
        assert is_text_mime('application/yaml') is True
        assert is_text_mime('image/png') is False


class TestExtensionMapCompleteness:
    """Tests for extension map completeness."""

    def test_common_data_extensions_present(self):
        """Test that common data file extensions are in the map."""
        required_extensions = [
            '.json',
            '.jsonl',
            '.ndjson',
            '.yaml',
            '.yml',
            '.toml',
            '.xml',
            '.csv',
            '.tsv',
            '.md',
        ]
        for ext in required_extensions:
            assert ext in EXTENSION_MIME_MAP, f"Missing extension: {ext}"

    def test_common_image_extensions_present(self):
        """Test that common image extensions are in the map."""
        required_extensions = [
            '.jpg',
            '.jpeg',
            '.jfif',
            '.png',
            '.gif',
            '.webp',
            '.bmp',
            '.heic',
            '.avif',
        ]
        for ext in required_extensions:
            assert ext in EXTENSION_MIME_MAP, f"Missing extension: {ext}"

    def test_common_audio_extensions_present(self):
        """Test that common audio extensions are in the map."""
        required_extensions = [
            '.mp3',
            '.wav',
            '.flac',
            '.ogg',
            '.m4a',
            '.aac',
        ]
        for ext in required_extensions:
            assert ext in EXTENSION_MIME_MAP, f"Missing extension: {ext}"

    def test_common_video_extensions_present(self):
        """Test that common video extensions are in the map."""
        required_extensions = [
            '.mp4',
            '.mov',
            '.avi',
            '.mkv',
            '.webm',
        ]
        for ext in required_extensions:
            assert ext in EXTENSION_MIME_MAP, f"Missing extension: {ext}"

    def test_common_archive_extensions_present(self):
        """Test that common archive extensions are in the map."""
        required_extensions = [
            '.zip',
            '.tar',
            '.gz',
            '.7z',
            '.rar',
            '.bz2',
            '.xz',
        ]
        for ext in required_extensions:
            assert ext in EXTENSION_MIME_MAP, f"Missing extension: {ext}"
