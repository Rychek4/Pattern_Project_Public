"""
Pattern Project - KoboldCpp Client
HTTP client for local LLM via KoboldCpp API
"""

import requests
from typing import Optional, List, Dict, Any
from dataclasses import dataclass

from core.logger import log_info, log_error, log_success, log_warning


@dataclass
class KoboldResponse:
    """Response from KoboldCpp API."""
    text: str
    tokens_generated: int
    success: bool
    error: Optional[str] = None


class KoboldClient:
    """
    Client for KoboldCpp API.

    KoboldCpp provides a local LLM inference server compatible with
    the KoboldAI API specification.
    """

    def __init__(
        self,
        api_url: str = "http://127.0.0.1:5001",
        max_context: int = 4096,
        max_length: int = 512,
        timeout: int = 120
    ):
        """
        Initialize the KoboldCpp client.

        Args:
            api_url: Base URL for KoboldCpp API
            max_context: Maximum context length
            max_length: Maximum generation length
            timeout: Request timeout in seconds
        """
        self.api_url = api_url.rstrip("/")
        self.max_context = max_context
        self.max_length = max_length
        self.timeout = timeout
        self._model_name: Optional[str] = None

    def is_available(self) -> bool:
        """Check if KoboldCpp is available and responding."""
        try:
            response = requests.get(
                f"{self.api_url}/api/v1/model",
                timeout=5
            )
            if response.status_code == 200:
                data = response.json()
                self._model_name = data.get("result", "Unknown")
                return True
            return False
        except Exception:
            return False

    def get_model_name(self) -> Optional[str]:
        """Get the currently loaded model name."""
        if self._model_name is None:
            self.is_available()
        return self._model_name

    def generate(
        self,
        prompt: str,
        max_length: Optional[int] = None,
        temperature: float = 0.7,
        top_p: float = 0.9,
        top_k: int = 40,
        rep_pen: float = 1.1,
        stop_sequences: Optional[List[str]] = None
    ) -> KoboldResponse:
        """
        Generate text completion.

        Args:
            prompt: The prompt to complete
            max_length: Maximum tokens to generate (uses default if None)
            temperature: Sampling temperature
            top_p: Top-p (nucleus) sampling
            top_k: Top-k sampling
            rep_pen: Repetition penalty
            stop_sequences: List of sequences to stop generation

        Returns:
            KoboldResponse with generated text
        """
        if max_length is None:
            max_length = self.max_length

        payload = {
            "prompt": prompt,
            "max_length": max_length,
            "temperature": temperature,
            "top_p": top_p,
            "top_k": top_k,
            "rep_pen": rep_pen,
            "max_context_length": self.max_context
        }

        if stop_sequences:
            payload["stop_sequence"] = stop_sequences

        try:
            response = requests.post(
                f"{self.api_url}/api/v1/generate",
                json=payload,
                timeout=self.timeout
            )

            if response.status_code == 200:
                data = response.json()
                results = data.get("results", [])

                if results:
                    text = results[0].get("text", "")
                    return KoboldResponse(
                        text=text.strip(),
                        tokens_generated=len(text.split()),  # Approximate
                        success=True
                    )

                return KoboldResponse(
                    text="",
                    tokens_generated=0,
                    success=False,
                    error="No results in response"
                )

            return KoboldResponse(
                text="",
                tokens_generated=0,
                success=False,
                error=f"HTTP {response.status_code}: {response.text}"
            )

        except requests.Timeout:
            return KoboldResponse(
                text="",
                tokens_generated=0,
                success=False,
                error="Request timed out"
            )
        except requests.ConnectionError:
            return KoboldResponse(
                text="",
                tokens_generated=0,
                success=False,
                error="Connection failed - is KoboldCpp running?"
            )
        except Exception as e:
            return KoboldResponse(
                text="",
                tokens_generated=0,
                success=False,
                error=str(e)
            )

    def chat(
        self,
        messages: List[Dict[str, str]],
        system_prompt: Optional[str] = None,
        max_length: Optional[int] = None,
        temperature: float = 0.7
    ) -> KoboldResponse:
        """
        Chat-style completion with message history.

        Formats messages into a prompt suitable for instruct-tuned models.

        Args:
            messages: List of {"role": "user"|"assistant", "content": "..."}
            system_prompt: Optional system prompt
            max_length: Maximum tokens to generate
            temperature: Sampling temperature

        Returns:
            KoboldResponse with generated text
        """
        # Format as Llama-3 instruct format
        prompt_parts = []

        if system_prompt:
            prompt_parts.append(f"<|begin_of_text|><|start_header_id|>system<|end_header_id|>\n\n{system_prompt}<|eot_id|>")
        else:
            prompt_parts.append("<|begin_of_text|>")

        for msg in messages:
            role = msg["role"]
            content = msg["content"]

            if role == "user":
                prompt_parts.append(f"<|start_header_id|>user<|end_header_id|>\n\n{content}<|eot_id|>")
            elif role == "assistant":
                prompt_parts.append(f"<|start_header_id|>assistant<|end_header_id|>\n\n{content}<|eot_id|>")

        # Add the assistant header for the response
        prompt_parts.append("<|start_header_id|>assistant<|end_header_id|>\n\n")

        prompt = "".join(prompt_parts)

        return self.generate(
            prompt=prompt,
            max_length=max_length,
            temperature=temperature,
            stop_sequences=["<|eot_id|>", "<|end_of_text|>"]
        )

    def validate_connection(self) -> tuple[bool, str]:
        """
        Validate the connection and return status.

        Returns:
            Tuple of (is_valid, status_message)
        """
        try:
            if self.is_available():
                model = self.get_model_name()
                return True, f"Connected to KoboldCpp ({model})"
            return False, "KoboldCpp not responding"
        except Exception as e:
            return False, f"Connection error: {e}"


# Global client instance
_kobold_client: Optional[KoboldClient] = None


def get_kobold_client() -> KoboldClient:
    """Get the global KoboldCpp client instance."""
    global _kobold_client
    if _kobold_client is None:
        from config import KOBOLD_API_URL, KOBOLD_MAX_CONTEXT, KOBOLD_MAX_LENGTH
        _kobold_client = KoboldClient(
            api_url=KOBOLD_API_URL,
            max_context=KOBOLD_MAX_CONTEXT,
            max_length=KOBOLD_MAX_LENGTH
        )
    return _kobold_client


def init_kobold_client(
    api_url: str,
    max_context: int = 4096,
    max_length: int = 512
) -> KoboldClient:
    """Initialize the global KoboldCpp client."""
    global _kobold_client
    _kobold_client = KoboldClient(
        api_url=api_url,
        max_context=max_context,
        max_length=max_length
    )
    return _kobold_client
