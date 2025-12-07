"""
Pattern Project - Anthropic Claude Client
Client for Claude API (frontier reasoning)
"""

from typing import Optional, List, Dict, Any
from dataclasses import dataclass

from core.logger import log_info, log_error, log_success


@dataclass
class AnthropicResponse:
    """Response from Anthropic API."""
    text: str
    input_tokens: int
    output_tokens: int
    success: bool
    error: Optional[str] = None
    stop_reason: Optional[str] = None


class AnthropicClient:
    """
    Client for Anthropic Claude API.

    Provides access to Claude models for high-quality reasoning
    and conversation.
    """

    def __init__(
        self,
        api_key: str,
        model: str = "claude-sonnet-4-20250514",
        max_tokens: int = 4096,
        timeout: int = 120
    ):
        """
        Initialize the Anthropic client.

        Args:
            api_key: Anthropic API key
            model: Model to use
            max_tokens: Maximum tokens to generate
            timeout: Request timeout in seconds
        """
        self.api_key = api_key
        self.model = model
        self.max_tokens = max_tokens
        self.timeout = timeout
        self._client = None

    def _get_client(self):
        """Lazy-load the Anthropic client."""
        if self._client is None:
            try:
                import anthropic
                self._client = anthropic.Anthropic(
                    api_key=self.api_key,
                    timeout=self.timeout
                )
            except ImportError:
                raise ImportError("anthropic package not installed. Run: pip install anthropic")
        return self._client

    def is_available(self) -> bool:
        """Check if Anthropic API is configured and accessible."""
        if not self.api_key:
            return False
        try:
            # Just check if we can create a client
            self._get_client()
            return True
        except Exception:
            return False

    def chat(
        self,
        messages: List[Dict[str, str]],
        system_prompt: Optional[str] = None,
        max_tokens: Optional[int] = None,
        temperature: float = 0.7,
        stop_sequences: Optional[List[str]] = None
    ) -> AnthropicResponse:
        """
        Send a chat completion request.

        Args:
            messages: List of {"role": "user"|"assistant", "content": "..."}
            system_prompt: Optional system prompt
            max_tokens: Maximum tokens to generate (uses default if None)
            temperature: Sampling temperature
            stop_sequences: Optional list of stop sequences

        Returns:
            AnthropicResponse with generated text
        """
        if max_tokens is None:
            max_tokens = self.max_tokens

        try:
            client = self._get_client()

            # Build request parameters
            request_params = {
                "model": self.model,
                "max_tokens": max_tokens,
                "temperature": temperature,
                "messages": messages
            }

            if system_prompt:
                request_params["system"] = system_prompt

            if stop_sequences:
                request_params["stop_sequences"] = stop_sequences

            # Make the request
            response = client.messages.create(**request_params)

            # Extract text from response
            text = ""
            for block in response.content:
                if hasattr(block, "text"):
                    text += block.text

            return AnthropicResponse(
                text=text,
                input_tokens=response.usage.input_tokens,
                output_tokens=response.usage.output_tokens,
                success=True,
                stop_reason=response.stop_reason
            )

        except Exception as e:
            error_msg = str(e)

            # Handle specific error types
            if "authentication" in error_msg.lower() or "api key" in error_msg.lower():
                error_msg = "Invalid API key"
            elif "rate" in error_msg.lower():
                error_msg = "Rate limit exceeded"
            elif "overloaded" in error_msg.lower():
                error_msg = "API overloaded, try again later"

            return AnthropicResponse(
                text="",
                input_tokens=0,
                output_tokens=0,
                success=False,
                error=error_msg
            )

    def generate(
        self,
        prompt: str,
        system_prompt: Optional[str] = None,
        max_tokens: Optional[int] = None,
        temperature: float = 0.7
    ) -> AnthropicResponse:
        """
        Simple text generation from a prompt.

        Args:
            prompt: The user prompt
            system_prompt: Optional system prompt
            max_tokens: Maximum tokens to generate
            temperature: Sampling temperature

        Returns:
            AnthropicResponse with generated text
        """
        messages = [{"role": "user", "content": prompt}]
        return self.chat(
            messages=messages,
            system_prompt=system_prompt,
            max_tokens=max_tokens,
            temperature=temperature
        )

    def validate_connection(self) -> tuple[bool, str]:
        """
        Validate the API connection.

        Returns:
            Tuple of (is_valid, status_message)
        """
        if not self.api_key:
            return False, "API key not configured"

        try:
            # Make a minimal request to validate
            response = self.generate(
                prompt="Say 'OK' and nothing else.",
                max_tokens=10,
                temperature=0
            )

            if response.success:
                return True, f"Connected to Anthropic API ({self.model})"
            else:
                return False, f"API error: {response.error}"

        except Exception as e:
            return False, f"Connection error: {e}"


# Global client instance
_anthropic_client: Optional[AnthropicClient] = None


def get_anthropic_client() -> AnthropicClient:
    """Get the global Anthropic client instance."""
    global _anthropic_client
    if _anthropic_client is None:
        from config import ANTHROPIC_API_KEY, ANTHROPIC_MODEL, ANTHROPIC_MAX_TOKENS
        _anthropic_client = AnthropicClient(
            api_key=ANTHROPIC_API_KEY,
            model=ANTHROPIC_MODEL,
            max_tokens=ANTHROPIC_MAX_TOKENS
        )
    return _anthropic_client


def init_anthropic_client(
    api_key: str,
    model: str = "claude-sonnet-4-20250514",
    max_tokens: int = 4096
) -> AnthropicClient:
    """Initialize the global Anthropic client."""
    global _anthropic_client
    _anthropic_client = AnthropicClient(
        api_key=api_key,
        model=model,
        max_tokens=max_tokens
    )
    return _anthropic_client
