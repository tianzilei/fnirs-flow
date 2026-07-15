"""Tests for logging_config module."""

from __future__ import annotations

import json
import logging
from pathlib import Path

import pytest

from fnirs_flow.logging_config import (
    _JsonFormatter,
    get_logger,
    init_logging,
    setup_logging,
)


@pytest.fixture(autouse=True)
def cleanup_logging():
    """Clean up logging handlers after each test."""
    yield
    logger = logging.getLogger("fnirs_flow")
    for handler in logger.handlers[:]:
        logger.removeHandler(handler)
        handler.close()
    logger.propagate = True


class TestSetupLogging:
    """Tests for setup_logging function."""

    def test_default_setup(self) -> None:
        """Test default logging setup."""
        setup_logging()

        logger = logging.getLogger("fnirs_flow")
        assert logger.level == logging.INFO
        assert len(logger.handlers) >= 1

    def test_custom_level(self) -> None:
        """Test custom log level."""
        setup_logging(level="DEBUG")

        logger = logging.getLogger("fnirs_flow")
        assert logger.level == logging.DEBUG

    def test_invalid_level_defaults_to_info(self) -> None:
        """Test that invalid level defaults to INFO."""
        setup_logging(level="INVALID")

        logger = logging.getLogger("fnirs_flow")
        assert logger.level == logging.INFO

    def test_json_format(self) -> None:
        """Test JSON format option."""
        setup_logging(json_format=True)

        logger = logging.getLogger("fnirs_flow")
        assert len(logger.handlers) >= 1
        assert isinstance(logger.handlers[0].formatter, _JsonFormatter)

    def test_file_handler(self, tmp_path: Path) -> None:
        """Test file handler creation."""
        log_file = tmp_path / "test.log"
        setup_logging(log_file=log_file)

        logger = logging.getLogger("fnirs_flow")
        assert len(logger.handlers) >= 2  # Console + File

    def test_file_handler_creates_directory(self, tmp_path: Path) -> None:
        """Test that file handler creates parent directory."""
        log_file = tmp_path / "logs" / "test.log"
        setup_logging(log_file=log_file)

        assert log_file.parent.exists()

    def test_env_variable_level(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test log level from environment variable."""
        monkeypatch.setenv("FNIRS_LOG_LEVEL", "DEBUG")
        setup_logging()

        logger = logging.getLogger("fnirs_flow")
        assert logger.level == logging.DEBUG


class TestJsonFormatter:
    """Tests for _JsonFormatter class."""

    def test_format_basic_record(self) -> None:
        """Test formatting a basic log record."""
        formatter = _JsonFormatter()
        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="test.py",
            lineno=10,
            msg="Test message",
            args=(),
            exc_info=None,
        )

        result = formatter.format(record)
        data = json.loads(result)

        assert data["level"] == "INFO"
        assert data["message"] == "Test message"
        assert data["logger"] == "test"
        assert data["line"] == 10

    def test_format_record_with_exception(self) -> None:
        """Test formatting a log record with exception info."""
        formatter = _JsonFormatter()

        try:
            raise ValueError("Test error")
        except ValueError:
            import sys
            exc_info = sys.exc_info()

        record = logging.LogRecord(
            name="test",
            level=logging.ERROR,
            pathname="test.py",
            lineno=20,
            msg="Error occurred",
            args=(),
            exc_info=exc_info,
        )

        result = formatter.format(record)
        data = json.loads(result)

        assert data["level"] == "ERROR"
        assert "exception" in data
        assert data["exception"]["type"] == "ValueError"
        assert data["exception"]["message"] == "Test error"

    def test_format_record_with_extra_fields(self) -> None:
        """Test formatting a log record with extra fields."""
        formatter = _JsonFormatter()
        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="test.py",
            lineno=30,
            msg="Test message",
            args=(),
            exc_info=None,
        )
        record.custom_field = "custom_value"

        result = formatter.format(record)
        data = json.loads(result)

        assert data["custom_field"] == "custom_value"


class TestGetLogger:
    """Tests for get_logger function."""

    def test_returns_logger_with_prefix(self) -> None:
        """Test that get_logger returns logger with fnirs_flow prefix."""
        logger = get_logger("test_module")
        assert logger.name == "fnirs_flow.test_module"

    def test_returns_logger_instance(self) -> None:
        """Test that get_logger returns a Logger instance."""
        logger = get_logger("test")
        assert isinstance(logger, logging.Logger)


class TestInitLogging:
    """Tests for init_logging function."""

    def test_init_with_defaults(self) -> None:
        """Test init_logging with default settings."""
        init_logging()

        logger = logging.getLogger("fnirs_flow")
        assert logger.level == logging.INFO

    def test_init_with_env_variables(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test init_logging with environment variables."""
        monkeypatch.setenv("FNIRS_LOG_LEVEL", "WARNING")
        monkeypatch.setenv("FNIRS_LOG_JSON", "true")

        init_logging()

        logger = logging.getLogger("fnirs_flow")
        assert logger.level == logging.WARNING

    def test_init_with_file(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test init_logging with log file."""
        log_file = tmp_path / "test.log"
        monkeypatch.setenv("FNIRS_LOG_FILE", str(log_file))

        init_logging()

        logger = logging.getLogger("fnirs_flow")
        assert len(logger.handlers) >= 2
