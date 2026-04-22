"""
LLM Client: Groq API Wrapper
=============================
Production-grade Groq API client with JSON mode, retry logic,
and exponential backoff for rate limits (HTTP 429).
"""

import json
import time
import logging
from typing import Optional, Dict, Any

import requests

from .config import GROQ_API_KEY, SILICONFLOW_API_KEY, LLM_MODEL, LLM_BASE_URL

logger = logging.getLogger(__name__)


class GroqClient:
    """Groq LLM client with retry, backoff, and JSON mode support.

    Usage:
        client = GroqClient()
        result = client.call("Translate 'hello' to French. Output JSON: {\"result\": \"...\"}")
        # result == {"result": "bonjour"}
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        model: Optional[str] = None,
        base_url: Optional[str] = None,
        max_retries: int = 3,
        timeout: int = 30,
    ):
        self.base_url = (base_url or LLM_BASE_URL).rstrip("/")

        # Select key based on provider (Northern Standard preference)
        if "siliconflow" in self.base_url.lower():
            self.api_key = api_key or SILICONFLOW_API_KEY
        else:
            self.api_key = api_key or GROQ_API_KEY

        self.model = model or LLM_MODEL
        self._llm_url = f"{self.base_url}/chat/completions"
        self.max_retries = max_retries
        self.timeout = timeout
        self._call_count = 0
        self._error_count = 0
        self._last_error: str = ""

        if not self.api_key:
            logger.error(
                f"❌ LLMClient: No API key provided for {self.base_url}")
            raise ValueError(f"API Key for {self.base_url} is required")

        logger.info(
            f"✅ LLMClient initialised (model={self.model}, base={self.base_url})")

    @property
    def stats(self) -> Dict[str, int]:
        """Return call/error statistics."""
        return {
            "llm_calls": self._call_count,
            "llm_errors": self._error_count,
        }

    def call(self, prompt: str, temperature: float = 0.0) -> Dict[str, Any]:
        """Send a prompt to Groq and return parsed JSON response.

        Args:
            prompt: The user prompt string.
            temperature: Sampling temperature (0.0 = deterministic).

        Returns:
            Parsed JSON dict from LLM response, or empty dict on failure.
        """
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": self.model,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": temperature,
            "response_format": {"type": "json_object"},
        }

        for attempt in range(self.max_retries):
            try:
                self._call_count += 1
                res = requests.post(
                    self._llm_url,
                    headers=headers,
                    json=payload,
                    timeout=self.timeout,
                )

                if res.status_code == 429:
                    wait = 5 * (attempt + 1)
                    self._last_error = f"HTTP 429 from {self.base_url}"
                    logger.warning(
                        f"LLM 429 Rate Limit. Waiting {wait}s... (attempt {attempt+1})")
                    time.sleep(wait)
                    continue

                if res.status_code != 200:
                    self._last_error = f"HTTP {res.status_code}: {res.text[:200]}"
                    logger.warning(
                        f"LLM HTTP {res.status_code}: {res.text[:200]}")
                    self._error_count += 1
                    continue

                content = res.json()[
                    "choices"][0]["message"]["content"].strip()
                return json.loads(content)

            except json.JSONDecodeError as e:
                self._last_error = f"JSON decode error: {e}"
                logger.warning(
                    f"LLM JSON parse error (attempt {attempt+1}): {e}")
                self._error_count += 1
                time.sleep(1)
            except requests.exceptions.Timeout:
                self._last_error = "Request timeout"
                logger.warning(
                    f"LLM timeout (attempt {attempt+1}/{self.max_retries})")
                self._error_count += 1
                time.sleep(2)
            except Exception as e:
                self._last_error = f"{type(e).__name__}: {e}"
                logger.warning(
                    f"LLM API error (attempt {attempt+1}): {type(e).__name__}: {e}")
                self._error_count += 1
                time.sleep(2)

        return {}

    def call_with_delay(self, prompt: str, delay: float = 0.3, **kwargs) -> Dict[str, Any]:
        """Call with a post-request delay to avoid rate limits.

        Args:
            prompt: The user prompt string.
            delay: Seconds to wait after each call.
            **kwargs: Additional kwargs passed to self.call().

        Returns:
            Parsed JSON dict.
        """
        try:
            result = self.call(prompt, **kwargs)
            if not result:
                provider_error = self._last_error or "Failed to get a valid response after retries."
                raise TimeoutError(
                    f"LLM request failed after retries (base={self.base_url}, model={self.model}). {provider_error}"
                )
            time.sleep(delay)
            return result
        except TimeoutError as e:
            logger.error(f"LLM call failed with timeout: {str(e)}")
            raise RuntimeError(f"LLM API Error: {str(e)}") from e
        except Exception as e:
            logger.error(f"LLM call failed with error: {str(e)}")
            raise RuntimeError(f"LLM API Error: {str(e)}") from e
