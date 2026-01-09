"""Tests for UserFileRepository (Phase 1.5).

Tests all CRUD operations for user_files table.
"""

from datetime import datetime
from datetime import timedelta
from datetime import timezone

from db.models.message import MessageRole
from db.models.user_file import FileSource
from db.models.user_file import FileType
from db.models.user_file import UserFile
from db.repositories.message_repository import MessageRepository
from db.repositories.user_file_repository import UserFileRepository
import pytest


@pytest.fixture
async def sample_message(test_session):
    """Create a sample message for testing."""
    message_repo = MessageRepository(test_session)
    message = await message_repo.create_message(
        chat_id=123456,
        message_id=999001,
        thread_id=1,
        from_user_id=123,
        date=int(datetime.now(timezone.utc).timestamp()),
        role=MessageRole.USER,
        text_content="Test message with file")
    await test_session.flush()
    return message


@pytest.mark.asyncio
class TestUserFileRepository:
    """Test suite for UserFileRepository."""

    async def test_create_file(self, test_session):
        """Test creating a new file record."""
        repo = UserFileRepository(test_session)
        expires_at = datetime.now(timezone.utc) + timedelta(hours=24)

        file = await repo.create(message_id=999001,
                                 claude_file_id="file_test123",
                                 filename="test.jpg",
                                 file_type=FileType.IMAGE,
                                 mime_type="image/jpeg",
                                 file_size=1024,
                                 expires_at=expires_at,
                                 source=FileSource.USER,
                                 telegram_file_id="telegram_123",
                                 file_metadata={
                                     "width": 800,
                                     "height": 600
                                 })

        assert file.id is not None
        assert file.claude_file_id == "file_test123"
        assert file.filename == "test.jpg"
        assert file.file_type == FileType.IMAGE
        assert file.source == FileSource.USER

    async def test_get_by_claude_file_id(self, test_session, sample_message):
        """Test retrieving file by Claude file ID."""
        repo = UserFileRepository(test_session)
        expires_at = datetime.now(timezone.utc) + timedelta(hours=24)

        # Create file
        created_file = await repo.create(message_id=sample_message.message_id,
                                         claude_file_id="file_unique123",
                                         filename="test.jpg",
                                         file_type=FileType.IMAGE,
                                         mime_type="image/jpeg",
                                         file_size=1024,
                                         expires_at=expires_at,
                                         source=FileSource.USER)
        await test_session.flush()

        # Retrieve
        file = await repo.get_by_claude_file_id("file_unique123")

        assert file is not None
        assert file.id == created_file.id
        assert file.claude_file_id == "file_unique123"

    async def test_get_by_message_id(self, test_session, sample_message):
        """Test retrieving files by message ID."""
        repo = UserFileRepository(test_session)
        expires_at = datetime.now(timezone.utc) + timedelta(hours=24)

        # Create multiple files for same message
        await repo.create(message_id=sample_message.message_id,
                          claude_file_id="file_1",
                          filename="file1.jpg",
                          file_type=FileType.IMAGE,
                          mime_type="image/jpeg",
                          file_size=1024,
                          expires_at=expires_at,
                          source=FileSource.USER)
        await repo.create(message_id=sample_message.message_id,
                          claude_file_id="file_2",
                          filename="file2.jpg",
                          file_type=FileType.IMAGE,
                          mime_type="image/jpeg",
                          file_size=2048,
                          expires_at=expires_at,
                          source=FileSource.USER)
        await test_session.flush()

        # Retrieve
        files = await repo.get_by_message_id(sample_message.message_id)

        assert len(files) == 2
        assert files[0].claude_file_id == "file_1"
        assert files[1].claude_file_id == "file_2"

    async def test_get_expired_files(self, test_session, sample_message):
        """Test retrieving expired files."""
        repo = UserFileRepository(test_session)

        # Create expired file
        past_time = datetime.now(timezone.utc) - timedelta(hours=1)
        await repo.create(message_id=sample_message.message_id,
                          claude_file_id="file_expired",
                          filename="expired.jpg",
                          file_type=FileType.IMAGE,
                          mime_type="image/jpeg",
                          file_size=1024,
                          expires_at=past_time,
                          source=FileSource.USER)

        # Create non-expired file
        future_time = datetime.now(timezone.utc) + timedelta(hours=24)
        await repo.create(message_id=sample_message.message_id,
                          claude_file_id="file_active",
                          filename="active.jpg",
                          file_type=FileType.IMAGE,
                          mime_type="image/jpeg",
                          file_size=1024,
                          expires_at=future_time,
                          source=FileSource.USER)
        await test_session.flush()

        # Retrieve expired
        expired = await repo.get_expired_files()

        assert len(expired) >= 1
        assert any(f.claude_file_id == "file_expired" for f in expired)
        assert not any(f.claude_file_id == "file_active" for f in expired)

    async def test_get_by_file_type(self, test_session, sample_message):
        """Test retrieving files by type."""
        repo = UserFileRepository(test_session)
        expires_at = datetime.now(timezone.utc) + timedelta(hours=24)

        # Create files of different types
        await repo.create(message_id=sample_message.message_id,
                          claude_file_id="file_image",
                          filename="image.jpg",
                          file_type=FileType.IMAGE,
                          mime_type="image/jpeg",
                          file_size=1024,
                          expires_at=expires_at,
                          source=FileSource.USER)
        await repo.create(message_id=sample_message.message_id,
                          claude_file_id="file_pdf",
                          filename="document.pdf",
                          file_type=FileType.PDF,
                          mime_type="application/pdf",
                          file_size=2048,
                          expires_at=expires_at,
                          source=FileSource.USER)
        await test_session.flush()

        # Retrieve images
        images = await repo.get_by_file_type(FileType.IMAGE)

        assert any(f.claude_file_id == "file_image" for f in images)
        assert not any(f.claude_file_id == "file_pdf" for f in images)
