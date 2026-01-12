"""Tests for Files API client (Phase 1.5).

Tests file upload, deletion, and error handling for Claude Files API integration.
"""

from io import BytesIO
from unittest.mock import Mock
from unittest.mock import patch

# Import the module to test
import core.claude.files_api as files_api
import pytest


@pytest.fixture
def mock_anthropic_client():
    """Mock Anthropic client with Files API."""
    client = Mock()
    client.beta = Mock()
    client.beta.files = Mock()
    return client


@pytest.fixture(autouse=True)
def reset_client():
    """Reset global client before each test."""
    import core.clients
    core.clients._anthropic_sync_files = None
    yield
    core.clients._anthropic_sync_files = None


class TestUploadToFilesApi:
    """Tests for upload_to_files_api() function."""

    @pytest.mark.asyncio
    @patch('core.claude.files_api.get_anthropic_client')
    async def test_upload_success(self, mock_get_client):
        """Test successful file upload to Files API."""
        # Setup mock
        mock_client = Mock()
        mock_file_response = Mock()
        mock_file_response.id = "file_test123"
        mock_client.beta.files.upload.return_value = mock_file_response
        mock_get_client.return_value = mock_client

        # Test
        file_bytes = b"test content"
        filename = "test.jpg"
        mime_type = "image/jpeg"

        claude_file_id = await files_api.upload_to_files_api(
            file_bytes=file_bytes, filename=filename, mime_type=mime_type)

        # Verify
        assert claude_file_id == "file_test123"
        mock_client.beta.files.upload.assert_called_once()

        # Check that file was passed as tuple (filename, BytesIO, mime_type)
        call_args = mock_client.beta.files.upload.call_args
        assert call_args[1]['file'][0] == filename
        assert isinstance(call_args[1]['file'][1], BytesIO)

    @pytest.mark.asyncio
    @patch('core.claude.files_api.get_anthropic_client')
    async def test_upload_api_error(self, mock_get_client):
        """Test upload with generic exception."""
        import anthropic

        # Setup mock to raise anthropic.APIError
        mock_client = Mock()
        mock_client.beta.files.upload.side_effect = anthropic.APIError(
            message="Upload failed", request=Mock(), body=None)
        mock_get_client.return_value = mock_client

        # Test
        file_bytes = b"test content"
        filename = "test.jpg"
        mime_type = "image/jpeg"

        with pytest.raises(anthropic.APIError):
            await files_api.upload_to_files_api(file_bytes=file_bytes,
                                                filename=filename,
                                                mime_type=mime_type)

    @pytest.mark.asyncio
    @patch('core.claude.files_api.get_anthropic_client')
    async def test_upload_with_mime_detection(self, mock_get_client):
        """Test upload with automatic MIME type detection."""
        # Setup mock
        mock_client = Mock()
        mock_file_response = Mock()
        mock_file_response.id = "file_test456"
        mock_client.beta.files.upload.return_value = mock_file_response
        mock_get_client.return_value = mock_client

        # Test - JPEG magic bytes
        jpeg_bytes = b"\xff\xd8\xff\xe0\x00\x10JFIF"
        filename = "photo.jpg"

        claude_file_id = await files_api.upload_to_files_api(
            file_bytes=jpeg_bytes,
            filename=filename,
            mime_type=None  # Auto-detect
        )

        assert claude_file_id == "file_test456"
        mock_client.beta.files.upload.assert_called_once()


class TestDownloadFromFilesApi:
    """Tests for download_from_files_api() function."""

    @pytest.mark.asyncio
    @patch('core.claude.files_api.get_anthropic_client')
    async def test_download_success(self, mock_get_client):
        """Test successful file download."""
        mock_client = Mock()
        mock_client.beta.files.download.return_value = b"file_content"
        mock_get_client.return_value = mock_client

        result = await files_api.download_from_files_api("file_test123")

        assert result == b"file_content"
        mock_client.beta.files.download.assert_called_once_with(
            file_id="file_test123")

    @pytest.mark.asyncio
    @patch('core.claude.files_api.get_anthropic_client')
    async def test_download_not_found(self, mock_get_client):
        """Test download with NotFoundError."""
        import anthropic

        mock_client = Mock()
        mock_client.beta.files.download.side_effect = anthropic.NotFoundError(
            message="Not found", response=Mock(status_code=404), body=None)
        mock_get_client.return_value = mock_client

        with pytest.raises(anthropic.NotFoundError):
            await files_api.download_from_files_api("file_test123")


class TestDeleteFromFilesApi:
    """Tests for delete_from_files_api() function."""

    @pytest.mark.asyncio
    @patch('core.claude.files_api.get_anthropic_client')
    async def test_delete_success(self, mock_get_client):
        """Test successful file deletion."""
        mock_client = Mock()
        mock_get_client.return_value = mock_client

        await files_api.delete_from_files_api("file_test123")

        mock_client.beta.files.delete.assert_called_once_with(
            file_id="file_test123")

    @pytest.mark.asyncio
    @patch('core.claude.files_api.get_anthropic_client')
    async def test_delete_not_found(self, mock_get_client):
        """Test delete with NotFoundError (file doesn't exist)."""
        import anthropic

        mock_client = Mock()
        mock_client.beta.files.delete.side_effect = anthropic.NotFoundError(
            message="Not found", response=Mock(status_code=404), body=None)
        mock_get_client.return_value = mock_client

        # Should not raise exception (warning logged)
        await files_api.delete_from_files_api("file_test123")

    @pytest.mark.asyncio
    @patch('core.claude.files_api.get_anthropic_client')
    async def test_delete_api_error(self, mock_get_client):
        """Test delete with APIError exception."""
        import anthropic

        mock_client = Mock()
        mock_client.beta.files.delete.side_effect = anthropic.APIError(
            message="Delete failed", request=Mock(), body=None)
        mock_get_client.return_value = mock_client

        with pytest.raises(anthropic.APIError):
            await files_api.delete_from_files_api("file_test123")
