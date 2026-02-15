"""
Pattern Project - Tool Use Error Types
Structured error handling for AI command feedback
"""

from enum import Enum
from dataclasses import dataclass
from typing import Optional


class ToolErrorType(Enum):
    """
    Categories of tool use errors for AI feedback.

    These types help the AI understand what went wrong and how to correct it.
    """
    FORMAT_ERROR = "format"      # Wrong syntax/structure
    VALIDATION = "validation"    # Invalid values provided
    INVALID_INPUT = "invalid"    # Invalid input data
    NOT_FOUND = "not_found"      # Resource doesn't exist
    PARSE_ERROR = "parse"        # Couldn't parse/interpret input
    SYSTEM_ERROR = "system"      # Database/internal failure
    RATE_LIMITED = "rate_limit"  # Rate limit exceeded


@dataclass
class ToolError:
    """
    Structured error with context for AI feedback.

    Provides rich error information so the AI can:
    - Understand what went wrong
    - See the expected format
    - Learn from an example
    - Retry with correct syntax

    Attributes:
        error_type: Category of the error
        message: Human-readable error description
        expected_format: The correct syntax (optional)
        example: A working example (optional)
    """
    error_type: ToolErrorType
    message: str
    expected_format: Optional[str] = None
    example: Optional[str] = None

    def format_for_ai(self) -> str:
        """
        Format error message for AI continuation prompt.

        Returns:
            Multi-line formatted error with context
        """
        lines = [f"Error ({self.error_type.value}): {self.message}"]
        if self.expected_format:
            lines.append(f"  Expected format: {self.expected_format}")
        if self.example:
            lines.append(f"  Example: {self.example}")
        return "\n".join(lines)

    def __str__(self) -> str:
        """String representation falls back to formatted message."""
        return self.format_for_ai()
