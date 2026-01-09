"""Tests for Files API client (Phase 1.5).

Tests file upload, deletion, and error handling for Claude Files API integration.
"""

from io import BytesIO
from unittest.mock import MagicMock
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
    files_api._client = None
    yield
    files_api._client = None


class TestGetClient:
    """Tests for get_client() function."""

    @patch('core.claude.files_api.read_secret')
    @patch('core.claude.files_api.anthropic.Anthropic')
    def test_get_client_creates_new_client(self, mock_anthropic,
                                           mock_read_secret):
        """Test that get_client creates a new client on first call."""
        mock_read_secret.return_value = "test_api_key"
        mock_instance = Mock()
        mock_anthropic.return_value = mock_instance

        client = files_api.get_client()

        mock_read_secret.assert_called_once_with("anthropic_api_key")
        mock_anthropic.assert_called_once_with(
            api_key="test_api_key",
            default_headers={"anthropic-beta": "files-api-2025-04-14"})
        assert client == mock_instance

    @patch('core.claude.files_api.read_secret')
    @patch('core.claude.files_api.anthropic.Anthropic')
    def test_get_client_returns_cached_client(self, mock_anthropic,
                                              mock_read_secret):
        """Test that get_client returns cached client on subsequent calls."""
        mock_read_secret.return_value = "test_api_key"
        mock_instance = Mock()
        mock_anthropic.return_value = mock_instance

        # First call
        client1 = files_api.get_client()
        # Second call
        client2 = files_api.get_client()

        # Should only create once
        assert mock_anthropic.call_count == 1
        assert client1 == client2


class TestUploadToFilesApi:
    """Tests for upload_to_files_api() function."""

    @pytest.mark.asyncio
    @patch('core.claude.files_api.get_client')
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

        # Check that file was passed as tuple (filename, BytesIO)
        call_args = mock_client.beta.files.upload.call_args
        assert call_args[1]['file'][0] == filename
        assert isinstance(call_args[1]['file'][1], BytesIO)

    @pytest.mark.asyncio
    @patch('core.claude.files_api.get_client')
    async def test_upload_api_error(self, mock_get_client):
        """Test upload with generic exception."""
        # Setup mock to raise generic Exception
        mock_client = Mock()
        mock_client.beta.files.upload.side_effect = Exception("Upload failed")
        mock_get_client.return_value = mock_client

        # Test
        file_bytes = b"test content"
        filename = "test.jpg"
        mime_type = "image/jpeg"

        with pytest.raises(Exception, match="Upload failed"):
            await files_api.upload_to_files_api(file_bytes=file_bytes,
                                                filename=filename,
                                                mime_type=mime_type)


class TestDeleteFromFilesApi:
    """Tests for delete_from_files_api() function."""

    @pytest.mark.asyncio
    @patch('core.claude.files_api.get_client')
    async def test_delete_success(self, mock_get_client):
        """Test successful file deletion."""
        mock_client = Mock()
        mock_get_client.return_value = mock_client

        await files_api.delete_from_files_api("file_test123")

        mock_client.beta.files.delete.assert_called_once_with(
            file_id="file_test123")

    @pytest.mark.asyncio
    @patch('core.claude.files_api.get_client')
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
    @patch('core.claude.files_api.get_client')
    async def test_delete_api_error(self, mock_get_client):
        """Test delete with generic exception."""
        mock_client = Mock()
        mock_client.beta.files.delete.side_effect = Exception("Delete failed")
        mock_get_client.return_value = mock_client

        with pytest.raises(Exception, match="Delete failed"):
            await files_api.delete_from_files_api("file_test123")
