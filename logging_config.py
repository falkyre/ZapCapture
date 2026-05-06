"""Centralized logging configuration for ZapCapture-NG.

Dual-output: RichHandler (console, colorized) + RotatingFileHandler (file, no ANSI).
File logs go to <project_root>/logs/ with 5MB rotation and 3 backups.

Usage in any module:
    from logging_config import get_logger
    logger = get_logger(__name__)
    logger.info("message")
    logger.debug("debug info — only visible with --verbose on console")

CLI: pass --verbose / -v / --debug / -d to elevate console to DEBUG level.
"""

import logging
import os
import sys
from logging.handlers import RotatingFileHandler

try:
    from rich.logging import RichHandler
except ImportError:
    RichHandler = None

LOG_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "logs")
LOG_FILE = os.path.join(LOG_DIR, "zapcapture.log")
MAX_BYTES = 5 * 1024 * 1024  # 5 MB
BACKUP_COUNT = 3

_CONSOLE_LEVEL_DEBUG = logging.DEBUG
_FILE_LEVEL_DEBUG = logging.DEBUG
_DEFAULT_CONSOLE_LEVEL = logging.INFO

_verbose_active = False


class ZapError(Exception):
    """Base exception for all ZapCapture domain errors."""

    def __init__(self, message: str, details: dict | None = None):
        super().__init__(message)
        self.details = details or {}


class ConfigError(ZapError):
    """Raised when configuration is invalid or missing."""


class FileError(ZapError):
    """Raised when file operations fail (read/write/copy)."""


class VideoError(ZapError):
    """Raised when video processing fails (decode/read/extract)."""


def setup_logging(verbose: bool = False) -> logging.Logger:
    """Configure root logger with console + file handlers.

    Args:
        verbose: When True, console handler logs at DEBUG level.
                 File handler always logs at DEBUG regardless.

    Returns:
        The root logger (also used as parent for all child loggers).
    """
    global _verbose_active

    _verbose_active = verbose

    root_logger = logging.getLogger()
    root_logger.setLevel(logging.DEBUG)  # Let handlers filter

    # Remove any existing handlers to avoid duplicates on re-init
    root_logger.handlers.clear()

    formatter = logging.Formatter(
        "%(asctime)s | %(name)-25s | %(filename)s:%(lineno)d | %(levelname)-8s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # --- Console handler (RichHandler if available) ---
    console_level = _CONSOLE_LEVEL_DEBUG if verbose else _DEFAULT_CONSOLE_LEVEL

    if RichHandler is not None:
        console_handler = RichHandler(
            level=console_level,
            rich_tracebacks=True,
            show_path=False,
            show_level=True,
            markup=False,
        )
    else:
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setLevel(console_level)

    console_handler.setFormatter(formatter)
    root_logger.addHandler(console_handler)

    # --- File handler (RotatingFileHandler, always DEBUG) ---
    os.makedirs(LOG_DIR, exist_ok=True)

    file_handler = RotatingFileHandler(
        LOG_FILE,
        maxBytes=MAX_BYTES,
        backupCount=BACKUP_COUNT,
        encoding="utf-8",
    )
    file_handler.setLevel(_FILE_LEVEL_DEBUG)
    # Plain Formatter — no ANSI color codes in file output
    file_handler.setFormatter(formatter)
    root_logger.addHandler(file_handler)

    return root_logger


def get_logger(name: str | None = None) -> logging.Logger:
    """Return a child logger under the configured root.

    Args:
        name: Logger name, typically ``__name__`` from the calling module.

    Returns:
        A logging.Logger instance.
    """
    return logging.getLogger(name)


def parse_verbose_arg(argv: list[str] | None = None) -> bool:
    """Parse sys.argv (or provided list) for --verbose / -v / --debug / -d flags.

    Returns True if any verbose flag is found.
    """
    if argv is None:
        argv = sys.argv[1:]
    verbose_flags = {"--verbose", "-v", "--debug", "-d"}
    return any(flag in argv for flag in verbose_flags)
