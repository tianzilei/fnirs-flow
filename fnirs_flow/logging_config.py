"""Logging configuration for fnirs-flow."""

from __future__ import annotations

import json
import logging
import logging.handlers
import os
import sys
from pathlib import Path


def setup_logging(
    level: str | None = None,
    log_file: str | Path | None = None,
    json_format: bool = False,
    max_bytes: int = 10 * 1024 * 1024,  # 10MB
    backup_count: int = 5,
) -> None:
    """Setup logging configuration for fnirs-flow.

    Args:
        level: Log level (DEBUG, INFO, WARNING, ERROR, CRITICAL)
        log_file: Optional log file path
        json_format: Whether to use JSON format (for production)
        max_bytes: Maximum log file size before rotation (default 10MB)
        backup_count: Number of backup files to keep (default 5)
    """
    # Get log level from environment or parameter
    if level is None:
        level = os.environ.get("FNIRS_LOG_LEVEL", "INFO")

    # Configure root logger
    root_logger = logging.getLogger("fnirs_flow")
    root_logger.setLevel(getattr(logging, level.upper(), logging.INFO))

    # Remove and close existing handlers so repeated reconfiguration does not
    # leak file descriptors (especially RotatingFileHandler streams).
    for handler in root_logger.handlers[:]:
        root_logger.removeHandler(handler)
        handler.close()

    # Console handler
    console_handler = logging.StreamHandler(sys.stderr)
    console_handler.setLevel(logging.DEBUG)

    formatter: logging.Formatter
    if json_format:
        formatter = _JsonFormatter()
    else:
        formatter = logging.Formatter(
            "%(asctime)s - %(name)s - %(levelname)s - %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )

    console_handler.setFormatter(formatter)
    root_logger.addHandler(console_handler)

    # File handler with rotation (optional)
    if log_file:
        log_path = Path(log_file)
        log_path.parent.mkdir(parents=True, exist_ok=True)

        file_handler = logging.handlers.RotatingFileHandler(
            log_path,
            maxBytes=max_bytes,
            backupCount=backup_count,
            encoding="utf-8",
        )
        file_handler.setLevel(logging.DEBUG)
        file_handler.setFormatter(formatter)
        root_logger.addHandler(file_handler)

    # Prevent propagation to root logger
    root_logger.propagate = False


class _JsonFormatter(logging.Formatter):
    """JSON log formatter for structured logging."""

    def format(self, record: logging.LogRecord) -> str:
        """Format log record as JSON."""
        log_data = {
            "timestamp": self.formatTime(record, self.datefmt),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "module": record.module,
            "function": record.funcName,
            "line": record.lineno,
        }

        # Add exception info if present
        if record.exc_info and record.exc_info[0] is not None and record.exc_info[1]:
            log_data["exception"] = {
                "type": record.exc_info[0].__name__,
                "message": str(record.exc_info[1]),
            }

        # Add extra fields
        for key, value in record.__dict__.items():
            if key not in (
                "name", "msg", "args", "created", "relativeCreated",
                "levelname", "levelno", "pathname", "filename",
                "module", "exc_info", "exc_text", "stack_info",
                "lineno", "funcName", "msecs", "message",
            ):
                log_data[key] = value

        return json.dumps(log_data, default=str)


def get_logger(name: str) -> logging.Logger:
    """Get a logger with the given name.

    Args:
        name: Logger name (typically __name__)

    Returns:
        Logger instance
    """
    return logging.getLogger(f"fnirs_flow.{name}")


# Default logging setup
def init_logging() -> None:
    """Initialize logging with default configuration."""
    setup_logging(
        level=os.environ.get("FNIRS_LOG_LEVEL", "INFO"),
        log_file=os.environ.get("FNIRS_LOG_FILE"),
        json_format=os.environ.get("FNIRS_LOG_JSON", "").lower() in ("1", "true", "yes"),
    )
