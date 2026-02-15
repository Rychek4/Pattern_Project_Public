"""
Sentence splitter for streaming TTS.

Handles:
- Sentence boundary detection (. ! ?)
- Code block detection and skipping
- Buffering partial sentences
- Edge cases (abbreviations, decimals, ellipsis)
"""

import re
from typing import Optional, List, Tuple
from dataclasses import dataclass, field


# Common abbreviations that shouldn't end sentences
ABBREVIATIONS = {
    "mr", "mrs", "ms", "dr", "prof", "sr", "jr", "vs", "etc", "inc", "ltd",
    "st", "ave", "blvd", "rd", "apt", "no", "vol", "pg", "pp", "fig", "al",
    "e.g", "i.e", "cf", "viz", "approx", "dept", "est", "govt", "misc"
}


@dataclass
class SentenceBuffer:
    """
    Buffers streaming text and extracts complete sentences.

    Tracks code blocks to skip them for TTS.
    """
    _buffer: str = ""
    _in_code_block: bool = False
    _code_block_content: str = ""

    def add_chunk(self, chunk: str) -> List[Tuple[str, bool]]:
        """
        Add a text chunk and return any complete sentences.

        Args:
            chunk: New text chunk from LLM stream

        Returns:
            List of (text, is_speakable) tuples.
            is_speakable=False for code blocks, True for regular sentences.
        """
        results = []

        for char in chunk:
            self._buffer += char

            # Check for code block markers
            if self._buffer.endswith("```"):
                if self._in_code_block:
                    # Ending a code block
                    self._in_code_block = False
                    # Return the code block as non-speakable
                    code_content = self._code_block_content
                    self._code_block_content = ""
                    # Remove the ``` from buffer
                    self._buffer = self._buffer[:-3]
                    if code_content:
                        results.append((f"```{code_content}```", False))
                    self._buffer = ""
                else:
                    # Starting a code block
                    self._in_code_block = True
                    # Flush any pending text before the code block
                    pre_code = self._buffer[:-3].strip()
                    if pre_code:
                        # Check if there's a complete sentence before code block
                        sentences = self._extract_sentences(pre_code)
                        results.extend(sentences)
                    self._buffer = ""
                continue

            # If in code block, accumulate but don't process
            if self._in_code_block:
                self._code_block_content += char
                self._buffer = ""
                continue

            # Check for sentence boundaries
            if self._is_sentence_boundary():
                sentence = self._buffer.strip()
                if sentence:
                    results.append((sentence, True))
                self._buffer = ""

        return results

    def _is_sentence_boundary(self) -> bool:
        """Check if buffer ends at a sentence boundary."""
        text = self._buffer.strip()
        if not text:
            return False

        # Must end with sentence-ending punctuation
        if not text[-1] in '.!?':
            return False

        # Handle ellipsis - not a boundary unless followed by space+capital
        if text.endswith('...'):
            return False

        # Handle multiple punctuation (e.g., "What?!" or "No!!")
        # These ARE boundaries
        if len(text) >= 2 and text[-2] in '.!?':
            return True

        # Check for abbreviations (e.g., "Dr." "Mr." "etc.")
        if text[-1] == '.':
            # Find the last word
            words = text.split()
            if words:
                last_word = words[-1].rstrip('.').lower()
                if last_word in ABBREVIATIONS:
                    return False

                # Check for decimal numbers (e.g., "3.14" or "$99.99")
                if len(words) >= 1:
                    # Look at the text right before the period
                    pre_period = text[:-1]
                    # If it ends with a digit, might be a decimal
                    if pre_period and pre_period[-1].isdigit():
                        # Check if this looks like a decimal (digit.digit pattern)
                        # Match patterns like "3.14" but not "in 2023."
                        match = re.search(r'\d+\.\d*$', text[:-1] + '.')
                        if match:
                            return False

        return True

    def _extract_sentences(self, text: str) -> List[Tuple[str, bool]]:
        """Extract all complete sentences from text."""
        results = []

        # Use regex to split on sentence boundaries
        # This handles cases where we have multiple sentences
        pattern = r'(?<=[.!?])\s+'
        parts = re.split(pattern, text)

        for i, part in enumerate(parts):
            part = part.strip()
            if part:
                # Last part might be incomplete
                if i == len(parts) - 1 and not part[-1] in '.!?':
                    self._buffer = part + " "
                else:
                    results.append((part, True))

        return results

    def flush(self) -> List[Tuple[str, bool]]:
        """
        Flush any remaining buffered content.

        Call this when the stream ends to get any trailing text.
        """
        results = []

        # Handle incomplete code block
        if self._in_code_block and self._code_block_content:
            results.append((f"```{self._code_block_content}", False))
            self._code_block_content = ""
            self._in_code_block = False

        # Handle remaining buffer
        remaining = self._buffer.strip()
        if remaining:
            results.append((remaining, True))

        self._buffer = ""
        return results

    def clear(self):
        """Reset the buffer state."""
        self._buffer = ""
        self._in_code_block = False
        self._code_block_content = ""


def split_for_tts(text: str) -> List[Tuple[str, bool]]:
    """
    Split complete text into sentences for TTS.

    Convenience function for non-streaming use.

    Args:
        text: Complete text to split

    Returns:
        List of (sentence, is_speakable) tuples
    """
    buffer = SentenceBuffer()
    results = buffer.add_chunk(text)
    results.extend(buffer.flush())
    return results
