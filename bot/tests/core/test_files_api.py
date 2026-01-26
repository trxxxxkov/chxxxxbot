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


class TestRetryLogic:
    """Tests for retry logic on transient API errors."""

    @pytest.mark.asyncio
    @patch('core.claude.files_api.asyncio.sleep')
    @patch('core.claude.files_api.get_anthropic_client')
    async def test_upload_retry_on_500_error(self, mock_get_client, mock_sleep):
        """Test upload retries on InternalServerError (500)."""
        import anthropic

        mock_client = Mock()
        mock_file_response = Mock()
        mock_file_response.id = "file_retry_success"

        # First two calls fail with 500, third succeeds
        mock_response = Mock()
        mock_response.status_code = 500
        mock_client.beta.files.upload.side_effect = [
            anthropic.InternalServerError(message="Internal server error",
                                          response=mock_response,
                                          body=None),
            anthropic.InternalServerError(message="Internal server error",
                                          response=mock_response,
                                          body=None),
            mock_file_response,
        ]
        mock_get_client.return_value = mock_client

        result = await files_api.upload_to_files_api(file_bytes=b"test",
                                                     filename="test.jpg",
                                                     mime_type="image/jpeg")

        assert result == "file_retry_success"
        assert mock_client.beta.files.upload.call_count == 3
        assert mock_sleep.call_count == 2

    @pytest.mark.asyncio
    @patch('core.claude.files_api.asyncio.sleep')
    @patch('core.claude.files_api.get_anthropic_client')
    async def test_upload_no_retry_on_400_error(self, mock_get_client,
                                                mock_sleep):
        """Test upload does NOT retry on BadRequestError (400)."""
        import anthropic

        mock_client = Mock()
        mock_response = Mock()
        mock_response.status_code = 400
        mock_client.beta.files.upload.side_effect = anthropic.BadRequestError(
            message="Bad request", response=mock_response, body=None)
        mock_get_client.return_value = mock_client

        with pytest.raises(anthropic.BadRequestError):
            await files_api.upload_to_files_api(file_bytes=b"test",
                                                filename="test.jpg",
                                                mime_type="image/jpeg")

        # Should not retry on 400 error
        assert mock_client.beta.files.upload.call_count == 1
        assert mock_sleep.call_count == 0

    @pytest.mark.asyncio
    @patch('core.claude.files_api.asyncio.sleep')
    @patch('core.claude.files_api.get_anthropic_client')
    async def test_upload_exhausts_retries(self, mock_get_client, mock_sleep):
        """Test upload raises after exhausting all retries."""
        import anthropic

        mock_client = Mock()
        mock_response = Mock()
        mock_response.status_code = 500
        mock_client.beta.files.upload.side_effect = anthropic.InternalServerError(
            message="Internal server error", response=mock_response, body=None)
        mock_get_client.return_value = mock_client

        with pytest.raises(anthropic.InternalServerError):
            await files_api.upload_to_files_api(file_bytes=b"test",
                                                filename="test.jpg",
                                                mime_type="image/jpeg")

        # Should have tried MAX_RETRIES times
        assert mock_client.beta.files.upload.call_count == files_api.MAX_RETRIES
        # Sleep called between retries (MAX_RETRIES - 1 times)
        assert mock_sleep.call_count == files_api.MAX_RETRIES - 1

    @pytest.mark.asyncio
    @patch('core.claude.files_api.asyncio.sleep')
    @patch('core.claude.files_api.get_anthropic_client')
    async def test_download_retry_on_connection_error(self, mock_get_client,
                                                      mock_sleep):
        """Test download retries on APIConnectionError."""
        import anthropic

        mock_client = Mock()
        # First call fails, second succeeds
        mock_client.beta.files.download.side_effect = [
            anthropic.APIConnectionError(request=Mock()),
            b"file_content",
        ]
        mock_get_client.return_value = mock_client

        result = await files_api.download_from_files_api("file_test123")

        assert result == b"file_content"
        assert mock_client.beta.files.download.call_count == 2
        assert mock_sleep.call_count == 1

    @pytest.mark.asyncio
    @patch('core.claude.files_api.asyncio.sleep')
    @patch('core.claude.files_api.get_anthropic_client')
    async def test_delete_retry_on_rate_limit(self, mock_get_client,
                                              mock_sleep):
        """Test delete retries on RateLimitError."""
        import anthropic

        mock_client = Mock()
        mock_response = Mock()
        mock_response.status_code = 429
        # First call fails with rate limit, second succeeds
        mock_client.beta.files.delete.side_effect = [
            anthropic.RateLimitError(message="Rate limit",
                                     response=mock_response,
                                     body=None),
            None,  # Successful delete returns None
        ]
        mock_get_client.return_value = mock_client

        await files_api.delete_from_files_api("file_test123")

        assert mock_client.beta.files.delete.call_count == 2
        assert mock_sleep.call_count == 1


class TestRetryHelpers:
    """Tests for retry helper functions."""

    def test_is_retryable_error_internal_server_error(self):
        """Test InternalServerError is retryable."""
        import anthropic
        mock_response = Mock()
        mock_response.status_code = 500
        error = anthropic.InternalServerError(message="Internal",
                                              response=mock_response,
                                              body=None)
        assert files_api._is_retryable_error(error) is True

    def test_is_retryable_error_connection_error(self):
        """Test APIConnectionError is retryable."""
        import anthropic
        error = anthropic.APIConnectionError(request=Mock())
        assert files_api._is_retryable_error(error) is True

    def test_is_retryable_error_rate_limit(self):
        """Test RateLimitError is retryable."""
        import anthropic
        mock_response = Mock()
        mock_response.status_code = 429
        error = anthropic.RateLimitError(message="Rate limit",
                                         response=mock_response,
                                         body=None)
        assert files_api._is_retryable_error(error) is True

    def test_is_retryable_error_bad_request(self):
        """Test BadRequestError is NOT retryable."""
        import anthropic
        mock_response = Mock()
        mock_response.status_code = 400
        error = anthropic.BadRequestError(message="Bad request",
                                          response=mock_response,
                                          body=None)
        assert files_api._is_retryable_error(error) is False

    def test_calculate_retry_delay_increases(self):
        """Test delay increases with attempt number."""
        delay_0 = files_api._calculate_retry_delay(0)
        delay_1 = files_api._calculate_retry_delay(1)
        delay_2 = files_api._calculate_retry_delay(2)

        # Base delays (without jitter): 1, 2, 4
        # With jitter (±25%): 0.75-1.25, 1.5-2.5, 3-5
        assert 0.5 < delay_0 < 1.5
        assert 1.0 < delay_1 < 3.0
        assert 2.0 < delay_2 < 6.0

    def test_calculate_retry_delay_capped(self):
        """Test delay is capped at MAX_DELAY_SECONDS."""
        # Large attempt number
        delay = files_api._calculate_retry_delay(10)
        # Should be capped at MAX_DELAY_SECONDS ± 25%
        assert delay <= files_api.MAX_DELAY_SECONDS * 1.25
