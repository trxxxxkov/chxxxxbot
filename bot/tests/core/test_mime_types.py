"""Tests for MIME type detection and normalization.

Tests for core.mime_types module which handles:
- Magic byte detection for binary files (images, PDFs)
- Extension-based detection for text files
- MIME type normalization
- File type classification helpers

NO __init__.py - use direct import:
    from tests.core.test_mime_types import test_jsonl_extension_detection
"""

from core.mime_types import detect_mime_from_content
from core.mime_types import detect_mime_from_extension
from core.mime_types import detect_mime_from_magic
from core.mime_types import detect_mime_type
from core.mime_types import EXTENSION_MIME_MAP
from core.mime_types import is_audio_mime
from core.mime_types import is_image_mime
from core.mime_types import is_pdf_mime
from core.mime_types import is_video_mime
from core.mime_types import normalize_mime_type
import pytest


class TestDetectMimeFromMagic:
    """Tests for magic byte detection."""

    def test_jpeg_magic_bytes(self):
        """Test JPEG detection from magic bytes."""
        jpeg_bytes = b'\xff\xd8\xff\xe0\x00\x10JFIF'
        assert detect_mime_from_magic(jpeg_bytes) == 'image/jpeg'

    def test_png_magic_bytes(self):
        """Test PNG detection from magic bytes."""
        png_bytes = b'\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR'
        assert detect_mime_from_magic(png_bytes) == 'image/png'

    def test_gif_magic_bytes(self):
        """Test GIF detection from magic bytes."""
        gif87_bytes = b'GIF87a\x01\x00\x01\x00'
        gif89_bytes = b'GIF89a\x01\x00\x01\x00'
        assert detect_mime_from_magic(gif87_bytes) == 'image/gif'
        assert detect_mime_from_magic(gif89_bytes) == 'image/gif'

    def test_webp_magic_bytes(self):
        """Test WebP detection from magic bytes."""
        webp_bytes = b'RIFF\x00\x00\x00\x00WEBP'
        assert detect_mime_from_magic(webp_bytes) == 'image/webp'

    def test_pdf_magic_bytes(self):
        """Test PDF detection from magic bytes."""
        pdf_bytes = b'%PDF-1.4\n%'
        assert detect_mime_from_magic(pdf_bytes) == 'application/pdf'

    def test_zip_magic_bytes(self):
        """Test ZIP detection from magic bytes."""
        zip_bytes = b'PK\x03\x04\x14\x00\x00\x00'
        assert detect_mime_from_magic(zip_bytes) == 'application/zip'

    def test_text_content_not_detected_by_magic(self):
        """Test that text content is NOT detected by magic bytes.

        Text detection is now done by detect_mime_from_content(),
        not detect_mime_from_magic().
        """
        text_bytes = b'Hello, World!'
        assert detect_mime_from_magic(text_bytes) is None

    def test_empty_bytes(self):
        """Test that empty bytes return None."""
        assert detect_mime_from_magic(b'') is None
        assert detect_mime_from_magic(None) is None


class TestDetectMimeFromContent:
    """Tests for text content detection."""

    def test_json_content_detection(self):
        """Test JSON content detection."""
        json_bytes = b'{"key": "value", "number": 123}'
        assert detect_mime_from_content(json_bytes) == 'application/json'

    def test_json_array_detection(self):
        """Test JSON array detection."""
        json_bytes = b'[{"id": 1}, {"id": 2}]'
        assert detect_mime_from_content(json_bytes) == 'application/json'

    def test_jsonl_content_detection(self):
        """Test JSONL (JSON Lines) content detection.

        Regression test: .jsonl files should be detected by content,
        not just extension.
        """
        jsonl_bytes = b'{"id": 1, "score": 0.5}\n{"id": 2, "score": 0.7}\n'
        assert detect_mime_from_content(jsonl_bytes) == 'application/jsonl'

    def test_xml_content_detection(self):
        """Test XML content detection."""
        xml_bytes = b'<?xml version="1.0"?>\n<root><item>test</item></root>'
        assert detect_mime_from_content(xml_bytes) == 'application/xml'

    def test_html_content_detection(self):
        """Test HTML content detection."""
        html_bytes = b'<!DOCTYPE html>\n<html><head></head><body></body></html>'
        assert detect_mime_from_content(html_bytes) == 'text/html'

    def test_yaml_content_detection(self):
        """Test YAML content detection."""
        yaml_bytes = b'---\nkey: value\nlist:\n  - item1\n  - item2\n'
        assert detect_mime_from_content(yaml_bytes) == 'application/yaml'

    def test_plain_text_detection(self):
        """Test plain text detection."""
        text_bytes = b'Hello, World!\nThis is plain text.'
        assert detect_mime_from_content(text_bytes) == 'text/plain'

    def test_binary_content_returns_none(self):
        """Test that binary content returns None."""
        binary_bytes = b'\x00\x01\x02\x03\x04'
        assert detect_mime_from_content(binary_bytes) is None

    def test_empty_bytes_returns_none(self):
        """Test that empty bytes return None."""
        assert detect_mime_from_content(b'') is None
        assert detect_mime_from_content(None) is None


class TestDetectMimeFromExtension:
    """Tests for extension-based MIME detection."""

    def test_jsonl_extension(self):
        """Test JSONL extension detection.

        Regression test: .jsonl files were uploaded with application/octet-stream
        because extension was not in EXTENSION_MIME_MAP.
        """
        assert detect_mime_from_extension('data.jsonl') == 'application/jsonl'
        assert detect_mime_from_extension('DATA.JSONL') == 'application/jsonl'

    def test_ndjson_extension(self):
        """Test NDJSON extension detection."""
        assert detect_mime_from_extension(
            'data.ndjson') == 'application/x-ndjson'

    def test_json_extension(self):
        """Test JSON extension detection."""
        assert detect_mime_from_extension('config.json') == 'application/json'

    def test_yaml_extensions(self):
        """Test YAML extension detection."""
        assert detect_mime_from_extension('config.yaml') == 'application/yaml'
        assert detect_mime_from_extension('config.yml') == 'application/yaml'

    def test_markdown_extensions(self):
        """Test Markdown extension detection."""
        assert detect_mime_from_extension('README.md') == 'text/markdown'
        assert detect_mime_from_extension('doc.markdown') == 'text/markdown'

    def test_python_extension(self):
        """Test Python extension detection."""
        assert detect_mime_from_extension('script.py') == 'text/x-python'

    def test_javascript_extensions(self):
        """Test JavaScript/TypeScript extension detection."""
        assert detect_mime_from_extension('app.js') == 'text/javascript'
        assert detect_mime_from_extension('app.jsx') == 'text/javascript'
        assert detect_mime_from_extension('app.ts') == 'text/typescript'
        assert detect_mime_from_extension('app.tsx') == 'text/typescript'

    def test_image_extensions(self):
        """Test image extension detection."""
        assert detect_mime_from_extension('photo.jpg') == 'image/jpeg'
        assert detect_mime_from_extension('photo.jpeg') == 'image/jpeg'
        assert detect_mime_from_extension('photo.jfif') == 'image/jpeg'
        assert detect_mime_from_extension('image.png') == 'image/png'
        assert detect_mime_from_extension('anim.gif') == 'image/gif'
        assert detect_mime_from_extension('image.webp') == 'image/webp'

    def test_audio_extensions(self):
        """Test audio extension detection."""
        assert detect_mime_from_extension('song.mp3') == 'audio/mpeg'
        assert detect_mime_from_extension('audio.wav') == 'audio/wav'
        assert detect_mime_from_extension('audio.ogg') == 'audio/ogg'
        assert detect_mime_from_extension('audio.flac') == 'audio/flac'

    def test_video_extensions(self):
        """Test video extension detection."""
        assert detect_mime_from_extension('video.mp4') == 'video/mp4'
        assert detect_mime_from_extension('video.mov') == 'video/quicktime'
        assert detect_mime_from_extension('video.webm') == 'video/webm'

    def test_document_extensions(self):
        """Test document extension detection."""
        assert detect_mime_from_extension('doc.pdf') == 'application/pdf'
        assert detect_mime_from_extension('doc.txt') == 'text/plain'
        assert detect_mime_from_extension('data.csv') == 'text/csv'
        assert detect_mime_from_extension(
            'data.tsv') == 'text/tab-separated-values'

    def test_config_extensions(self):
        """Test config file extension detection."""
        assert detect_mime_from_extension('config.ini') == 'text/plain'
        assert detect_mime_from_extension('config.cfg') == 'text/plain'
        assert detect_mime_from_extension('app.conf') == 'text/plain'
        assert detect_mime_from_extension('app.log') == 'text/plain'

    def test_code_extensions(self):
        """Test programming language extension detection."""
        assert detect_mime_from_extension('main.c') == 'text/x-c'
        assert detect_mime_from_extension('main.cpp') == 'text/x-c++'
        assert detect_mime_from_extension('Main.java') == 'text/x-java'
        assert detect_mime_from_extension('main.go') == 'text/x-go'
        assert detect_mime_from_extension('main.rs') == 'text/x-rust'
        assert detect_mime_from_extension('script.rb') == 'text/x-ruby'
        assert detect_mime_from_extension('index.php') == 'text/x-php'
        assert detect_mime_from_extension('query.sql') == 'application/sql'
        assert detect_mime_from_extension('script.sh') == 'application/x-sh'

    def test_case_insensitive(self):
        """Test that extension detection is case-insensitive."""
        assert detect_mime_from_extension('FILE.JSONL') == 'application/jsonl'
        assert detect_mime_from_extension('FILE.Jsonl') == 'application/jsonl'
        assert detect_mime_from_extension('IMAGE.PNG') == 'image/png'
        assert detect_mime_from_extension('VIDEO.MP4') == 'video/mp4'

    def test_no_extension(self):
        """Test files without extension."""
        assert detect_mime_from_extension('Makefile') is None
        assert detect_mime_from_extension('README') is None

    def test_empty_filename(self):
        """Test empty filename."""
        assert detect_mime_from_extension('') is None
        assert detect_mime_from_extension(None) is None


class TestDetectMimeType:
    """Tests for combined MIME detection."""

    def test_magic_bytes_priority(self):
        """Test that magic bytes take priority over extension."""
        # PNG file with wrong extension
        png_bytes = b'\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR'
        result = detect_mime_type('image.jpg', file_bytes=png_bytes)
        assert result == 'image/png'

    def test_extension_fallback(self):
        """Test fallback to extension when no magic bytes match."""
        text_content = b'{"key": "value"}\n{"key": "value2"}'
        result = detect_mime_type('data.jsonl', file_bytes=text_content)
        assert result == 'application/jsonl'

    def test_declared_mime_fallback(self):
        """Test fallback to declared MIME when nothing else matches."""
        result = detect_mime_type('unknown_file',
                                  file_bytes=b'random data',
                                  declared_mime='text/plain')
        assert result == 'text/plain'

    def test_octet_stream_fallback(self):
        """Test fallback to octet-stream for binary data."""
        # Binary data (contains null bytes) should fall back to octet-stream
        result = detect_mime_type('unknown_file',
                                  file_bytes=b'\x00\x01\x02\x03binary\x04\x05')
        assert result == 'application/octet-stream'

    def test_text_content_detected(self):
        """Test that text content is detected even without extension."""
        result = detect_mime_type('unknown_file', file_bytes=b'random data')
        assert result == 'text/plain'

    def test_jsonl_without_magic_bytes(self):
        """Test JSONL detection works without magic bytes.

        Regression test: JSONL files have no magic bytes, so detection
        must rely on extension.
        """
        jsonl_content = b'{"id": 1, "name": "test"}\n{"id": 2, "name": "test2"}'
        result = detect_mime_type('scores.jsonl', file_bytes=jsonl_content)
        assert result == 'application/jsonl'

    def test_real_world_jsonl_scenario(self):
        """Test real-world scenario: user uploads JSONL file.

        Regression test for bug where user uploaded score_diffs_18_01_2026.jsonl
        and it got application/octet-stream MIME type.
        """
        jsonl_content = b'{"score": 0.5, "diff": 0.1}\n{"score": 0.7, "diff": 0.2}'
        result = detect_mime_type(
            'score_diffs_18_01_2026.jsonl',
            file_bytes=jsonl_content,
            declared_mime=None  # Telegram may not provide MIME
        )
        assert result == 'application/jsonl'
        assert result != 'application/octet-stream'

    def test_extension_priority_over_content(self):
        """Test that extension takes priority over text content detection.

        Regression test: A .mp4 file with mock text content should still
        be detected as video/mp4 by extension, not as text/plain.
        """
        # Mock video file with text content (happens in tests)
        result = detect_mime_type(
            'clip.mp4',
            file_bytes=b'video_data',  # Text-like mock content
            declared_mime='video/mp4')
        assert result == 'video/mp4'

    def test_extension_priority_for_audio(self):
        """Test that extension takes priority for audio files."""
        result = detect_mime_type('song.mp3',
                                  file_bytes=b'audio_data',
                                  declared_mime='audio/mpeg')
        assert result == 'audio/mpeg'

    def test_content_fallback_for_unknown_extension(self):
        """Test content detection when extension is unknown."""
        # File with no recognizable extension
        result = detect_mime_type('unknown_file',
                                  file_bytes=b'{"key": "value"}')
        assert result == 'application/json'


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
        assert normalize_mime_type('audio/x-mpeg') == 'audio/mpeg'

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
        assert is_image_mime('image/x-jfif') is True  # Should normalize
        assert is_image_mime('application/pdf') is False
        assert is_image_mime('text/plain') is False

    def test_is_audio_mime(self):
        """Test audio MIME detection."""
        assert is_audio_mime('audio/mpeg') is True
        assert is_audio_mime('audio/mp3') is True  # Should normalize
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
        assert is_pdf_mime('application/x-pdf') is True  # Should normalize
        assert is_pdf_mime('application/json') is False


class TestExtensionMapCompleteness:
    """Tests for extension map completeness."""

    def test_common_text_extensions_present(self):
        """Test that common text file extensions are in the map."""
        required_extensions = [
            '.txt',
            '.csv',
            '.tsv',
            '.json',
            '.jsonl',
            '.xml',
            '.html',
            '.md',
            '.yaml',
            '.yml',
            '.toml',
            '.py',
            '.js',
            '.ts',
            '.css',
            '.sql',
            '.sh',
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
