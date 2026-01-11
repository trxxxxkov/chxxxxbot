"""Tests for application configuration.

This module contains comprehensive tests for config.py, testing
database URL construction, secrets reading, and environment variable
handling.

NO __init__.py - use direct import:
    pytest tests/test_config.py
"""

from pathlib import Path
from unittest.mock import patch

from config import get_database_url
import pytest


def test_get_database_url_with_defaults(tmp_path, monkeypatch):
    """Test get_database_url with default environment values.

    Verifies that default values are used when environment variables
    are not set: postgres:5432, postgres user, postgres database.

    Args:
        tmp_path: pytest fixture providing temporary directory.
        monkeypatch: pytest fixture for mocking environment.
    """
    # Create temporary secret file
    secret_file = tmp_path / "postgres_password"
    secret_file.write_text("test_password", encoding='utf-8')

    # Mock secret path
    with patch('config.Path') as mock_path:
        mock_path.return_value.read_text.return_value = "test_password"

        # Clear environment variables to use defaults
        monkeypatch.delenv("DATABASE_HOST", raising=False)
        monkeypatch.delenv("DATABASE_PORT", raising=False)
        monkeypatch.delenv("DATABASE_USER", raising=False)
        monkeypatch.delenv("DATABASE_NAME", raising=False)

        url = get_database_url()

        assert url == "postgresql+asyncpg://postgres:test_password@postgres:5432/postgres"


def test_get_database_url_reads_password_secret(tmp_path):
    """Test that password is read from Docker secret file.

    Verifies reading from /run/secrets/postgres_password.

    Args:
        tmp_path: pytest fixture providing temporary directory.
    """
    test_password = "secure_password_123"

    with patch('config.Path') as mock_path:
        mock_instance = mock_path.return_value
        mock_instance.read_text.return_value = test_password

        url = get_database_url()

        # Verify secret file path
        mock_path.assert_called_once_with("/run/secrets/postgres_password")
        mock_instance.read_text.assert_called_once_with(encoding='utf-8')

        # Verify password in URL
        assert f":{test_password}@" in url


def test_get_database_url_strips_whitespace(tmp_path):
    """Test that password whitespace is stripped.

    Docker secrets often have trailing newlines that must be removed.

    Args:
        tmp_path: pytest fixture providing temporary directory.
    """
    password_with_whitespace = "  password123  \n"

    with patch('config.Path') as mock_path:
        mock_path.return_value.read_text.return_value = password_with_whitespace

        url = get_database_url()

        # Password should be stripped
        assert ":password123@" in url
        assert "  " not in url
        assert "\n" not in url


def test_get_database_url_with_env_overrides(tmp_path, monkeypatch):
    """Test get_database_url with environment variable overrides.

    Verifies that environment variables override defaults.

    Args:
        tmp_path: pytest fixture providing temporary directory.
        monkeypatch: pytest fixture for mocking environment.
    """
    with patch('config.Path') as mock_path:
        mock_path.return_value.read_text.return_value = "env_password"

        # Set custom environment variables
        monkeypatch.setenv("DATABASE_HOST", "custom-db.example.com")
        monkeypatch.setenv("DATABASE_PORT", "5433")
        monkeypatch.setenv("DATABASE_USER", "custom_user")
        monkeypatch.setenv("DATABASE_NAME", "custom_db")

        url = get_database_url()

        expected = "postgresql+asyncpg://custom_user:env_password@custom-db.example.com:5433/custom_db"
        assert url == expected


def test_get_database_url_missing_secret_file():
    """Test that FileNotFoundError is raised if secret file missing.

    Verifies proper error handling when Docker secret not mounted.
    """
    with patch('config.Path') as mock_path:
        mock_path.return_value.read_text.side_effect = FileNotFoundError(
            "Secret file not found")

        with pytest.raises(FileNotFoundError):
            get_database_url()


def test_get_database_url_empty_password():
    """Test handling of empty password in secret file.

    Verifies that empty password (after stripping) is used as-is.
    """
    with patch('config.Path') as mock_path, \
         patch('config.os.getenv') as mock_getenv:
        mock_path.return_value.read_text.return_value = "   \n  "
        # Mock os.getenv to return default values
        mock_getenv.side_effect = lambda key, default="": {
            "DATABASE_HOST": "postgres",
            "DATABASE_PORT": "5432",
            "DATABASE_USER": "postgres",
            "DATABASE_NAME": "postgres",
        }.get(key, default)

        url = get_database_url()

        # Empty password after strip
        assert ":@postgres:" in url


def test_get_database_url_special_chars_in_password():
    """Test password with special characters.

    Note: asyncpg handles URL encoding internally, so we test
    that special characters are preserved in the URL string.
    """
    special_password = "p@ssw0rd!#$%"

    with patch('config.Path') as mock_path:
        mock_path.return_value.read_text.return_value = special_password

        url = get_database_url()

        # Special characters should be in URL (asyncpg handles encoding)
        assert special_password in url


def test_get_database_url_asyncpg_driver():
    """Test that URL uses asyncpg driver.

    Verifies postgresql+asyncpg:// protocol for async operations.
    """
    with patch('config.Path') as mock_path:
        mock_path.return_value.read_text.return_value = "password"

        url = get_database_url()

        assert url.startswith("postgresql+asyncpg://")


def test_get_database_url_format():
    """Test complete URL format validation.

    Verifies URL structure: protocol://user:pass@host:port/database
    """
    with patch('config.Path') as mock_path:
        mock_path.return_value.read_text.return_value = "testpass"

        url = get_database_url()

        # Check format
        assert url.startswith("postgresql+asyncpg://")
        assert "@" in url  # Separator between credentials and host
        assert ":" in url.split("@")[0]  # Colon between user and password
        assert ":" in url.split("@")[1]  # Colon between host and port
        assert "/" in url.split("@")[1]  # Slash before database name


def test_get_database_url_port_as_string(monkeypatch):
    """Test that port from environment is used as string.

    Verifies port number handling from getenv (returns string).

    Args:
        monkeypatch: pytest fixture for mocking environment.
    """
    with patch('config.Path') as mock_path:
        mock_path.return_value.read_text.return_value = "password"

        monkeypatch.setenv("DATABASE_PORT", "5433")

        url = get_database_url()

        assert ":5433/" in url
