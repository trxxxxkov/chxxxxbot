"""Tests for multimodal context formatting.

Tests the ContextFormatter's ability to include images and PDFs
directly in message content using Anthropic's multimodal format.
"""

from unittest.mock import AsyncMock
from unittest.mock import MagicMock
from unittest.mock import patch

from db.models.message import Message as DBMessage
from db.models.message import MessageRole
from db.models.user_file import FileType
from db.models.user_file import UserFile
import pytest
from telegram.context.formatter import ContextFormatter


class TestMultimodalFormatting:
    """Tests for multimodal message formatting."""

    @pytest.fixture
    def formatter(self):
        """Create a formatter instance."""
        return ContextFormatter(chat_type="private")

    @pytest.fixture
    def mock_session(self):
        """Create a mock database session."""
        return AsyncMock()

    @pytest.fixture
    def user_message(self):
        """Create a sample user message."""
        msg = MagicMock(spec=DBMessage)
        msg.message_id = 123
        msg.from_user_id = 456
        msg.role = MessageRole.USER
        msg.text_content = "What's in this image?"
        msg.caption = None
        msg.forward_origin = None
        msg.reply_snippet = None
        msg.reply_sender_display = None
        msg.quote_data = None
        msg.sender_display = None
        msg.edit_count = 0
        msg.thinking_blocks = None
        return msg

    @pytest.fixture
    def assistant_message(self):
        """Create a sample assistant message."""
        msg = MagicMock(spec=DBMessage)
        msg.message_id = 124
        msg.from_user_id = None
        msg.role = MessageRole.ASSISTANT
        msg.text_content = "I see a cat."
        msg.caption = None
        msg.forward_origin = None
        msg.reply_snippet = None
        msg.reply_sender_display = None
        msg.quote_data = None
        msg.sender_display = None
        msg.edit_count = 0
        msg.thinking_blocks = None
        return msg

    @pytest.fixture
    def image_file(self):
        """Create a sample image file."""
        file = MagicMock(spec=UserFile)
        file.claude_file_id = "file_abc123"
        file.telegram_file_id = "tg_img_123"
        file.mime_type = "image/jpeg"
        file.file_type = FileType.IMAGE
        file.filename = "photo.jpg"
        return file

    @pytest.fixture
    def pdf_file(self):
        """Create a sample PDF file."""
        file = MagicMock(spec=UserFile)
        file.claude_file_id = "file_def456"
        file.telegram_file_id = "tg_pdf_456"
        file.mime_type = "application/pdf"
        file.file_type = FileType.PDF
        file.filename = "document.pdf"
        return file

    @pytest.mark.asyncio
    async def test_user_message_with_image(self, formatter, mock_session,
                                           user_message, image_file):
        """User message with image returns multimodal content."""
        mock_repo = AsyncMock()
        mock_repo.get_by_message_id.return_value = [image_file]

        with patch(
                "db.repositories.user_file_repository.UserFileRepository",
                return_value=mock_repo,
        ):
            result = await formatter.format_conversation_with_files(
                [user_message], mock_session)

        assert len(result) == 1
        msg = result[0]
        assert msg.role == "user"
        assert isinstance(msg.content, list)
        assert len(msg.content) == 2

        # First block should be image with Gemini metadata
        assert msg.content[0]["type"] == "image"
        assert msg.content[0]["source"]["type"] == "file"
        assert msg.content[0]["source"]["file_id"] == "file_abc123"
        assert msg.content[0]["telegram_file_id"] == "tg_img_123"
        assert msg.content[0]["mime_type"] == "image/jpeg"

        # Second block should be text
        assert msg.content[1]["type"] == "text"
        assert msg.content[1]["text"] == "What's in this image?"

    @pytest.mark.asyncio
    async def test_user_message_with_pdf(self, formatter, mock_session,
                                         user_message, pdf_file):
        """User message with PDF returns document content."""
        user_message.text_content = "Summarize this document"

        mock_repo = AsyncMock()
        mock_repo.get_by_message_id.return_value = [pdf_file]

        with patch(
                "db.repositories.user_file_repository.UserFileRepository",
                return_value=mock_repo,
        ):
            result = await formatter.format_conversation_with_files(
                [user_message], mock_session)

        assert len(result) == 1
        msg = result[0]
        assert isinstance(msg.content, list)

        # First block should be document with Gemini metadata
        assert msg.content[0]["type"] == "document"
        assert msg.content[0]["source"]["file_id"] == "file_def456"
        assert msg.content[0]["telegram_file_id"] == "tg_pdf_456"
        assert msg.content[0]["mime_type"] == "application/pdf"

    @pytest.mark.asyncio
    async def test_user_message_with_multiple_files(self, formatter,
                                                    mock_session, user_message,
                                                    image_file, pdf_file):
        """User message with multiple files includes all."""
        user_message.text_content = "Compare these"

        mock_repo = AsyncMock()
        mock_repo.get_by_message_id.return_value = [image_file, pdf_file]

        with patch(
                "db.repositories.user_file_repository.UserFileRepository",
                return_value=mock_repo,
        ):
            result = await formatter.format_conversation_with_files(
                [user_message], mock_session)

        msg = result[0]
        assert isinstance(msg.content, list)
        assert len(msg.content) == 3

        assert msg.content[0]["type"] == "image"
        assert msg.content[1]["type"] == "document"
        assert msg.content[2]["type"] == "text"

    @pytest.mark.asyncio
    async def test_user_message_without_files(self, formatter, mock_session,
                                              user_message):
        """User message without files returns simple text."""
        mock_repo = AsyncMock()
        mock_repo.get_by_message_id.return_value = []

        with patch(
                "db.repositories.user_file_repository.UserFileRepository",
                return_value=mock_repo,
        ):
            result = await formatter.format_conversation_with_files(
                [user_message], mock_session)

        msg = result[0]
        assert msg.role == "user"
        assert isinstance(msg.content, str)
        assert msg.content == "What's in this image?"

    @pytest.mark.asyncio
    async def test_assistant_message_not_queried(self, formatter, mock_session,
                                                 assistant_message):
        """Assistant messages don't query for files."""
        mock_repo = AsyncMock()
        mock_repo.get_by_message_id.return_value = []

        with patch(
                "db.repositories.user_file_repository.UserFileRepository",
                return_value=mock_repo,
        ):
            result = await formatter.format_conversation_with_files(
                [assistant_message], mock_session)

        msg = result[0]
        assert msg.role == "assistant"
        assert isinstance(msg.content, str)
        assert msg.content == "I see a cat."

        # Should not query for assistant messages
        mock_repo.get_by_message_id.assert_not_called()

    @pytest.mark.asyncio
    async def test_file_without_claude_id_or_telegram_id_skipped(
            self, formatter, mock_session, user_message):
        """Files without both claude_file_id and telegram_file_id are skipped."""
        bad_file = MagicMock(spec=UserFile)
        bad_file.claude_file_id = None  # No Claude ID
        bad_file.telegram_file_id = None  # No Telegram ID either
        bad_file.file_type = FileType.IMAGE

        mock_repo = AsyncMock()
        mock_repo.get_by_message_id.return_value = [bad_file]

        with patch(
                "db.repositories.user_file_repository.UserFileRepository",
                return_value=mock_repo,
        ):
            result = await formatter.format_conversation_with_files(
                [user_message], mock_session)

        msg = result[0]
        # Should return text only since file has no references
        assert isinstance(msg.content, list)
        assert len(msg.content) == 1
        assert msg.content[0]["type"] == "text"

    @pytest.mark.asyncio
    async def test_file_without_claude_id_included_with_telegram_id(
            self, formatter, mock_session, user_message):
        """Files without claude_file_id but with telegram_file_id are included.

        Google provider resolves files via telegram_file_id from Redis cache.
        """
        file_no_claude = MagicMock(spec=UserFile)
        file_no_claude.claude_file_id = None
        file_no_claude.telegram_file_id = "tg_file_123"
        file_no_claude.file_type = FileType.IMAGE
        file_no_claude.mime_type = "image/jpeg"

        mock_repo = AsyncMock()
        mock_repo.get_by_message_id.return_value = [file_no_claude]

        with patch(
                "db.repositories.user_file_repository.UserFileRepository",
                return_value=mock_repo,
        ):
            result = await formatter.format_conversation_with_files(
                [user_message], mock_session)

        msg = result[0]
        assert isinstance(msg.content, list)
        assert len(msg.content) == 2
        image_block = msg.content[0]
        assert image_block["type"] == "image"
        assert "source" not in image_block  # No Files API source
        assert image_block["telegram_file_id"] == "tg_file_123"

    @pytest.mark.asyncio
    async def test_conversation_preserves_order(self, formatter, mock_session,
                                                user_message, assistant_message,
                                                image_file):
        """Multiple messages are formatted in order."""
        mock_repo = AsyncMock()

        # Return image for user message, nothing for assistant
        async def mock_get_by_message_id(msg_id, file_types=None):
            if msg_id == user_message.message_id:
                return [image_file]
            return []

        mock_repo.get_by_message_id = mock_get_by_message_id

        with patch(
                "db.repositories.user_file_repository.UserFileRepository",
                return_value=mock_repo,
        ):
            result = await formatter.format_conversation_with_files(
                [user_message, assistant_message], mock_session)

        assert len(result) == 2
        assert result[0].role == "user"
        assert result[1].role == "assistant"
        assert isinstance(result[0].content, list)  # Has image
        assert isinstance(result[1].content, str)  # No image


class TestBuildMultimodalContent:
    """Tests for _build_multimodal_content method."""

    def test_image_content_format(self):
        """Image files produce correct content block."""
        formatter = ContextFormatter()

        image = MagicMock(spec=UserFile)
        image.claude_file_id = "file_123"
        image.telegram_file_id = "tg_img_123"
        image.mime_type = "image/jpeg"
        image.file_type = FileType.IMAGE

        blocks = formatter._build_multimodal_content([image], "caption")

        assert len(blocks) == 2
        assert blocks[0] == {
            "type": "image",
            "source": {
                "type": "file",
                "file_id": "file_123"
            },
            "telegram_file_id": "tg_img_123",
            "mime_type": "image/jpeg",
        }
        assert blocks[1] == {"type": "text", "text": "caption"}

    def test_pdf_content_format(self):
        """PDF files produce document content block."""
        formatter = ContextFormatter()

        pdf = MagicMock(spec=UserFile)
        pdf.claude_file_id = "file_456"
        pdf.telegram_file_id = "tg_pdf_456"
        pdf.mime_type = "application/pdf"
        pdf.file_type = FileType.PDF

        blocks = formatter._build_multimodal_content([pdf], "question")

        assert blocks[0] == {
            "type": "document",
            "source": {
                "type": "file",
                "file_id": "file_456"
            },
            "telegram_file_id": "tg_pdf_456",
            "mime_type": "application/pdf",
        }

    def test_empty_text_still_added(self):
        """Empty text content is not added."""
        formatter = ContextFormatter()

        image = MagicMock(spec=UserFile)
        image.claude_file_id = "file_123"
        image.telegram_file_id = "tg_img_123"
        image.mime_type = "image/jpeg"
        image.file_type = FileType.IMAGE

        blocks = formatter._build_multimodal_content([image], "")

        assert len(blocks) == 1
        assert blocks[0]["type"] == "image"

    def test_files_without_any_id_skipped(self):
        """Files without both claude_file_id and telegram_file_id are skipped."""
        formatter = ContextFormatter()

        bad_file = MagicMock(spec=UserFile)
        bad_file.claude_file_id = None
        bad_file.telegram_file_id = None
        bad_file.file_type = FileType.IMAGE

        blocks = formatter._build_multimodal_content([bad_file], "text")

        # Only text block should be present
        assert len(blocks) == 1
        assert blocks[0]["type"] == "text"

    def test_files_with_unavailable_claude_id_included(self):
        """Files with unavailable claude_file_id but telegram_file_id included."""
        formatter = ContextFormatter()

        file = MagicMock(spec=UserFile)
        file.claude_file_id = "unavailable:abc123"
        file.telegram_file_id = "tg_file_456"
        file.file_type = FileType.IMAGE
        file.mime_type = "image/jpeg"

        blocks = formatter._build_multimodal_content([file], "text")

        # Image + text blocks
        assert len(blocks) == 2
        assert blocks[0]["type"] == "image"
        assert "source" not in blocks[0]  # No Files API source
        assert blocks[0]["telegram_file_id"] == "tg_file_456"
