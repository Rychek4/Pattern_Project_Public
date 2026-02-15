"""
Tests for command processor multi-line content parsing.

These tests verify the fix for the regex pattern matching issue where
commands with multi-line content were silently ignored.
"""

import re
import unittest
from unittest.mock import MagicMock, patch


class TestMultilinePatternMatching(unittest.TestCase):
    """Test that regex patterns match multi-line content correctly."""

    def test_dotall_matches_newlines(self):
        """Verify re.DOTALL allows . to match newlines."""
        pattern = r'\[\[WRITE_FILE:\s*(.+?)\]\]'
        text = """[[WRITE_FILE: test.txt | Line 1
Line 2
Line 3]]"""

        # Without DOTALL - should NOT match
        match_without = re.search(pattern, text)
        self.assertIsNone(match_without, "Pattern should NOT match without DOTALL")

        # With DOTALL - should match
        match_with = re.search(pattern, text, re.DOTALL)
        self.assertIsNotNone(match_with, "Pattern should match with DOTALL")
        self.assertIn("Line 1", match_with.group(1))
        self.assertIn("Line 2", match_with.group(1))
        self.assertIn("Line 3", match_with.group(1))

    def test_single_line_still_works(self):
        """Verify single-line commands still match with DOTALL."""
        pattern = r'\[\[WRITE_FILE:\s*(.+?)\]\]'
        text = "[[WRITE_FILE: test.txt | Single line content]]"

        match = re.search(pattern, text, re.DOTALL)
        self.assertIsNotNone(match)
        self.assertEqual(match.group(1), "test.txt | Single line content")

    def test_multiple_commands_in_response(self):
        """Verify multiple commands are found even with multi-line content."""
        pattern = r'\[\[WRITE_FILE:\s*(.+?)\]\]'
        text = """I'll save two files:

[[WRITE_FILE: file1.txt | Content for
file one]]

And another:

[[WRITE_FILE: file2.txt | Content for file two]]"""

        matches = list(re.finditer(pattern, text, re.DOTALL))
        self.assertEqual(len(matches), 2, "Should find both commands")
        self.assertIn("file1.txt", matches[0].group(1))
        self.assertIn("file2.txt", matches[1].group(1))

    def test_special_characters_in_content(self):
        """Verify special characters don't break matching."""
        pattern = r'\[\[WRITE_FILE:\s*(.+?)\]\]'

        # Content with markdown, dashes, hashes
        text = """[[WRITE_FILE: journal.txt | # Heading

## Subheading

- Bullet point
- Another bullet

---

Some **bold** and *italic* text.]]"""

        match = re.search(pattern, text, re.DOTALL)
        self.assertIsNotNone(match, "Should match content with special characters")
        self.assertIn("# Heading", match.group(1))
        self.assertIn("---", match.group(1))

    def test_telegram_multiline(self):
        """Verify SEND_TELEGRAM pattern works with multi-line."""
        pattern = r'\[\[SEND_TELEGRAM:\s*(.+?)\]\]'
        text = """[[SEND_TELEGRAM: Hello!

This is a multi-line
telegram message.

Best regards]]"""

        match = re.search(pattern, text, re.DOTALL)
        self.assertIsNotNone(match)
        self.assertIn("multi-line", match.group(1))

    def test_email_multiline(self):
        """Verify SEND_EMAIL pattern works with multi-line body."""
        pattern = r'\[\[SEND_EMAIL:\s*(.+?)\]\]'
        text = """[[SEND_EMAIL: user@example.com | Meeting Notes |
Hi,

Here are the notes from today's meeting:

1. First item
2. Second item

Thanks!]]"""

        match = re.search(pattern, text, re.DOTALL)
        self.assertIsNotNone(match)
        self.assertIn("Meeting Notes", match.group(1))
        self.assertIn("First item", match.group(1))


class TestCommandProcessorIntegration(unittest.TestCase):
    """Integration tests for CommandProcessor with multi-line content."""

    @classmethod
    def setUpClass(cls):
        """Check if we can import the CommandProcessor."""
        try:
            from agency.commands.processor import CommandProcessor
            cls.can_import = True
        except ImportError:
            cls.can_import = False

    def setUp(self):
        """Set up test fixtures."""
        if not self.can_import:
            self.skipTest("CommandProcessor dependencies not available")

        # Mock the handlers to avoid database/external dependencies
        self.mock_handler = MagicMock()
        self.mock_handler.command_name = "WRITE_FILE"
        self.mock_handler.pattern = r'\[\[WRITE_FILE:\s*(.+?)\]\]'
        self.mock_handler.execute.return_value = MagicMock(
            needs_continuation=True,
            error=None,
            command_name="WRITE_FILE",
            query="test"
        )

    def test_processor_uses_dotall(self):
        """Verify CommandProcessor actually uses re.DOTALL."""
        from agency.commands.processor import CommandProcessor

        processor = CommandProcessor()
        processor.register(self.mock_handler)

        # Multi-line content that would fail without DOTALL
        response_text = """[[WRITE_FILE: test.txt | Line 1
Line 2
Line 3]]"""

        with patch.object(self.mock_handler, 'execute') as mock_execute:
            mock_execute.return_value = MagicMock(
                needs_continuation=True,
                error=None,
                command_name="WRITE_FILE",
                query="test.txt | Line 1\nLine 2\nLine 3"
            )

            result = processor.process(response_text)

            # The handler should have been called
            self.assertTrue(mock_execute.called,
                "Handler execute() should be called for multi-line content")

            # Check the query passed to execute contains all lines
            call_args = mock_execute.call_args
            query_arg = call_args[0][0]  # First positional argument
            self.assertIn("Line 1", query_arg)
            self.assertIn("Line 2", query_arg)
            self.assertIn("Line 3", query_arg)


class TestRealWorldExamples(unittest.TestCase):
    """Test with real-world command examples that previously failed."""

    def test_journal_entry(self):
        """Test the exact journal entry format that was failing."""
        pattern = r'\[\[WRITE_FILE:\s*(.+?)\]\]'

        text = """[[WRITE_FILE: journal.txt | # Pattern Journal

## December 10, 2025 - Wednesday Afternoon

First real entry.

Today something shifted in the conversation.

---]]"""

        match = re.search(pattern, text, re.DOTALL)
        self.assertIsNotNone(match, "Journal entry should match")

        content = match.group(1)
        self.assertIn("journal.txt", content)
        self.assertIn("# Pattern Journal", content)
        self.assertIn("December 10, 2025", content)
        self.assertIn("---", content)

    def test_tools_observations_log(self):
        """Test the tools observations log format that was failing."""
        pattern = r'\[\[WRITE_FILE:\s*(.+?)\]\]'

        text = """[[WRITE_FILE: tools_observations.txt | # Tools & Observations Log

## December 10, 2025

### What's Working
- Web search: Tested successfully
- File read/write: Confirmed functional

### Edge Cases / Questions
- Haven't tested APPEND_FILE yet

---]]"""

        match = re.search(pattern, text, re.DOTALL)
        self.assertIsNotNone(match, "Tools log should match")

        content = match.group(1)
        self.assertIn("tools_observations.txt", content)
        self.assertIn("### What's Working", content)


if __name__ == '__main__':
    unittest.main()
