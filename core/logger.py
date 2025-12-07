"""
Pattern Project - Logging System
Timestamped console output with rich formatting + file logging
"""

import logging
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional

from rich.console import Console
from rich.theme import Theme

# Custom theme for console output
THEME = Theme({
    "info": "cyan",
    "warning": "yellow",
    "error": "bold red",
    "success": "bold green",
    "timestamp": "dim white",
    "header": "bold magenta",
    "config": "dim cyan",
})

# Global console instance
console = Console(theme=THEME)

# Module-level logger instance
_logger: Optional[logging.Logger] = None
_log_file_path: Optional[Path] = None


def setup_logging(
    log_file_path: Path,
    level: str = "INFO",
    log_to_file: bool = True,
    log_to_console: bool = True
) -> logging.Logger:
    """
    Initialize the logging system.

    Args:
        log_file_path: Path to the diagnostic log file
        level: Logging level (DEBUG, INFO, WARNING, ERROR)
        log_to_file: Whether to write logs to file
        log_to_console: Whether to write logs to console (via rich)

    Returns:
        Configured logger instance
    """
    global _logger, _log_file_path

    # Create logs directory if needed
    log_file_path.parent.mkdir(parents=True, exist_ok=True)
    _log_file_path = log_file_path

    # Create logger
    _logger = logging.getLogger("pattern")
    _logger.setLevel(getattr(logging, level.upper()))
    _logger.handlers.clear()

    # File handler
    if log_to_file:
        file_handler = logging.FileHandler(log_file_path, encoding="utf-8")
        file_handler.setLevel(logging.DEBUG)  # File gets everything
        file_formatter = logging.Formatter(
            "[%(asctime)s] %(levelname)s - %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S"
        )
        file_handler.setFormatter(file_formatter)
        _logger.addHandler(file_handler)

    return _logger


def get_timestamp() -> str:
    """Get formatted timestamp for console output."""
    return datetime.now().strftime("%H:%M:%S")


def log(message: str, level: str = "info", prefix: str = "") -> None:
    """
    Log a message to both console and file.

    Args:
        message: The message to log
        level: Log level (info, warning, error, success)
        prefix: Optional emoji/prefix for console output
    """
    timestamp = get_timestamp()

    # Console output with rich formatting
    style = level if level in ("info", "warning", "error", "success") else "info"
    prefix_str = f"{prefix} " if prefix else ""
    console.print(f"[timestamp][{timestamp}][/timestamp] {prefix_str}{message}", style=style)

    # File output
    if _logger:
        log_level = getattr(logging, level.upper(), logging.INFO)
        _logger.log(log_level, f"{prefix_str}{message}")


def log_info(message: str, prefix: str = "") -> None:
    """Log an info message."""
    log(message, "info", prefix)


def log_success(message: str, prefix: str = "") -> None:
    """Log a success message."""
    log(message, "info", prefix or "✅")


def log_warning(message: str, prefix: str = "") -> None:
    """Log a warning message."""
    log(message, "warning", prefix or "⚠️")


def log_error(message: str, prefix: str = "") -> None:
    """Log an error message."""
    log(message, "error", prefix or "❌")


def log_header(title: str) -> None:
    """Print a section header."""
    separator = "=" * 60
    console.print(f"\n[header]{separator}[/header]")
    console.print(f"[header]{title}[/header]")
    console.print(f"[header]{separator}[/header]")

    if _logger:
        _logger.info(separator)
        _logger.info(title)
        _logger.info(separator)


def log_config(key: str, value: str, indent: int = 0) -> None:
    """Print a configuration value."""
    indent_str = "   " * indent
    console.print(f"[timestamp][{get_timestamp()}][/timestamp] [config]{indent_str}{key}: {value}[/config]")

    if _logger:
        _logger.info(f"{indent_str}{key}: {value}")


def log_startup_banner(version: str, project_name: str) -> None:
    """Print the startup banner."""
    separator = "=" * 60
    timestamp = get_timestamp()

    console.print(f"\n[timestamp][{timestamp}][/timestamp] [header]{separator}[/header]")
    console.print(f"[timestamp][{timestamp}][/timestamp] [header]🧠 {project_name} - v{version} - AI Companion System[/header]")
    console.print(f"[timestamp][{timestamp}][/timestamp] [header]{separator}[/header]")

    if _logger:
        _logger.info(separator)
        _logger.info(f"{project_name} - v{version} - AI Companion System")
        _logger.info(separator)


def log_section(title: str, emoji: str = "📋") -> None:
    """Print a section title."""
    timestamp = get_timestamp()
    console.print(f"\n[timestamp][{timestamp}][/timestamp] [header]{emoji} {title}:[/header]")

    if _logger:
        _logger.info(f"{title}:")


def log_subsection(message: str, emoji: str = "", indent: int = 1) -> None:
    """Print a subsection item."""
    timestamp = get_timestamp()
    indent_str = "   " * indent
    prefix = f"{emoji} " if emoji else ""
    console.print(f"[timestamp][{timestamp}][/timestamp] [config]{indent_str}{prefix}{message}[/config]")

    if _logger:
        _logger.info(f"{indent_str}{prefix}{message}")


def log_loading_start(item: str) -> None:
    """Print a loading indicator."""
    separator = "=" * 60
    console.print(f"\n[header]{separator}[/header]")
    console.print(f"[warning]⏳ LOADING {item.upper()}...[/warning]")
    console.print(f"[header]{separator}[/header]")
    console.print("[warning]⚠️ First-time setup may take 3-5 minutes[/warning]")
    console.print("[config]   Please be patient, this is NOT stuck![/config]")
    console.print(f"[header]{separator}[/header]\n")


def log_loading_complete(item: str, details: str = "") -> None:
    """Print loading complete message."""
    detail_str = f" ({details})" if details else ""
    log_success(f"{item} loaded successfully{detail_str}")


def log_ready() -> None:
    """Print the ready message."""
    separator = "=" * 60
    timestamp = get_timestamp()
    console.print(f"\n[header]{separator}[/header]")
    console.print(f"[timestamp][{timestamp}][/timestamp] [success]✅ PATTERN PROJECT READY[/success]")
    console.print(f"[header]{separator}[/header]\n")

    if _logger:
        _logger.info(separator)
        _logger.info("PATTERN PROJECT READY")
        _logger.info(separator)
