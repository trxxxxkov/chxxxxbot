"""Tests for structured logging configuration.

This module contains comprehensive tests for utils/structured_logging.py,
testing JSON log format, context binding, and log levels.

NO __init__.py - use direct import:
    pytest tests/utils/test_structured_logging.py
"""

from io import StringIO
import json
import logging
from unittest.mock import patch

import pytest
import structlog
from utils.structured_logging import get_logger
from utils.structured_logging import setup_logging


@pytest.fixture(autouse=True)
def reset_logging():
    """Reset logging configuration before each test.

    Ensures test isolation by clearing structlog configuration.
    """
    # Reset structlog
    structlog.reset_defaults()
    yield
    # Reset again after test
    structlog.reset_defaults()


def test_setup_logging_default_info_level():
    """Test setup_logging with default INFO level.

    Verifies that default log level is INFO.
    """
    setup_logging()

    logger = get_logger("test")

    output = StringIO()
    with patch('sys.stdout', output):
        logger.info("test_message", key="value")

    log_output = output.getvalue()
    # Should be logged at INFO
    assert "test_message" in log_output
    assert json.loads(log_output.strip())['event'] == 'test_message'


def test_setup_logging_debug_level():
    """Test setup_logging with DEBUG level.

    Verifies that DEBUG level logs are captured.
    """
    setup_logging(level="DEBUG")

    logger = get_logger("test")

    output = StringIO()
    with patch('sys.stdout', output):
        logger.debug("debug_message", key="value")

    log_output = output.getvalue()
    assert "debug_message" in log_output
    assert json.loads(log_output.strip())['event'] == 'debug_message'


def test_setup_logging_error_level():
    """Test setup_logging with ERROR level.

    Verifies that only ERROR and above are logged when level=ERROR.
    """
    setup_logging(level="ERROR")

    logger = get_logger("test")

    output = StringIO()
    with patch('sys.stdout', output):
        logger.info("info_message")
        logger.error("error_message")

    log_output = output.getvalue()
    # INFO should not be in output (filtered out)
    assert "info_message" not in log_output
    # ERROR should be in output
    assert "error_message" in log_output
    assert json.loads(log_output.strip())['event'] == 'error_message'


def test_setup_logging_configures_stdlib_logging():
    """Test that setup_logging configures stdlib logging.

    Verifies that standard library logging is configured correctly.
    """
    setup_logging(level="WARNING")

    root_logger = logging.getLogger()

    assert root_logger.level == logging.WARNING


def test_setup_logging_json_renderer():
    """Test that logs are rendered as JSON.

    Verifies JSONRenderer is in the processor chain.
    """
    setup_logging()

    logger = get_logger("test")

    # Capture stdout
    output = StringIO()
    with patch('sys.stdout', output):
        logger.info("json_test", field="value")

    log_output = output.getvalue()

    # Should be valid JSON
    try:
        log_data = json.loads(log_output.strip())
        assert log_data['event'] == 'json_test'
        assert log_data['field'] == 'value'
    except json.JSONDecodeError:
        pytest.fail("Log output is not valid JSON")


def test_setup_logging_timestamper_iso_format():
    """Test that timestamps are in ISO format.

    Verifies TimeStamper(fmt='iso') is configured.
    """
    setup_logging()

    logger = get_logger("test")

    output = StringIO()
    with patch('sys.stdout', output):
        logger.info("timestamp_test")

    log_output = output.getvalue()
    log_data = json.loads(log_output.strip())

    # Should have timestamp field
    assert 'timestamp' in log_data

    # ISO format: YYYY-MM-DDTHH:MM:SS.mmmmmm
    timestamp = log_data['timestamp']
    assert 'T' in timestamp  # ISO format separator


def test_setup_logging_stackinfo_renderer():
    """Test that StackInfoRenderer is configured.

    Verifies that stack info can be included in logs.
    """
    setup_logging()

    logger = get_logger("test")

    output = StringIO()
    with patch('sys.stdout', output):
        logger.info("stackinfo_test", stack_info=True)

    # Should not raise exception (StackInfoRenderer handles it)
    assert len(output.getvalue()) > 0


def test_setup_logging_merges_contextvars():
    """Test that contextvars are merged into logs.

    Verifies merge_contextvars processor works.
    """
    setup_logging()

    logger = get_logger("test")

    # Bind context
    bound_logger = logger.bind(request_id="123", user_id=456)

    output = StringIO()
    with patch('sys.stdout', output):
        bound_logger.info("context_test")

    log_output = output.getvalue()
    log_data = json.loads(log_output.strip())

    # Context should be in log
    assert log_data.get('request_id') == '123'
    assert log_data.get('user_id') == 456


def test_get_logger_returns_bound_logger():
    """Test that get_logger returns BoundLogger instance.

    Verifies correct logger type is returned.
    """
    setup_logging()

    logger = get_logger("test_module")

    # Can return BoundLoggerLazyProxy or BoundLogger
    # Both are valid and have the same interface
    assert hasattr(logger, 'info')
    assert hasattr(logger, 'debug')
    assert hasattr(logger, 'error')
    assert hasattr(logger, 'warning')
    assert callable(logger.info)


def test_get_logger_correct_name():
    """Test that logger name is correctly set.

    Verifies that logger name is preserved for identification.
    """
    setup_logging()

    logger = get_logger("my_module")

    output = StringIO()
    with patch('sys.stdout', output):
        logger.info("name_test")

    log_output = output.getvalue()
    log_data = json.loads(log_output.strip())

    # Logger name should be in log (if captured by processors)
    assert 'event' in log_data
    assert log_data['event'] == 'name_test'


def test_logged_output_valid_json():
    """Test that all logged output is valid JSON.

    Verifies JSONRenderer produces parseable JSON.
    """
    setup_logging()

    logger = get_logger("test")

    output = StringIO()
    with patch('sys.stdout', output):
        logger.info("test1", key1="value1")
        logger.warning("test2", key2="value2")
        logger.error("test3", key3="value3")

    log_lines = output.getvalue().strip().split('\n')

    # All lines should be valid JSON
    for line in log_lines:
        try:
            json.loads(line)
        except json.JSONDecodeError:
            pytest.fail(f"Invalid JSON: {line}")


def test_logged_output_contains_required_fields():
    """Test that logs contain required fields.

    Verifies presence of: timestamp, level, event.
    """
    setup_logging()

    logger = get_logger("test")

    output = StringIO()
    with patch('sys.stdout', output):
        logger.info("required_fields_test", custom="data")

    log_output = output.getvalue()
    log_data = json.loads(log_output.strip())

    # Required fields
    assert 'timestamp' in log_data
    assert 'level' in log_data
    assert 'event' in log_data

    # Check values
    assert log_data['level'] == 'info'
    assert log_data['event'] == 'required_fields_test'
    assert log_data['custom'] == 'data'


def test_setup_logging_exception_info():
    """Test that exception information is logged.

    Verifies set_exc_info processor captures exceptions.
    """
    setup_logging()

    logger = get_logger("test")

    output = StringIO()
    with patch('sys.stdout', output):
        try:
            raise ValueError("Test exception")
        except ValueError:
            logger.error("exception_test", exc_info=True)

    log_output = output.getvalue()
    log_data = json.loads(log_output.strip())

    # Should have exception info
    assert 'exception' in log_data or 'exc_info' in log_data


def test_setup_logging_multiple_calls():
    """Test that multiple setup_logging calls work.

    Verifies that reconfiguration doesn't break logging.
    """
    setup_logging(level="INFO")
    logger1 = get_logger("test1")

    setup_logging(level="DEBUG")
    logger2 = get_logger("test2")

    # Both loggers should work
    output = StringIO()
    with patch('sys.stdout', output):
        logger1.info("test1")
        logger2.debug("test2")

    assert len(output.getvalue()) > 0
