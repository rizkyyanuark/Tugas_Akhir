"""
LLM Adapter: Async OpenRouter Wrapper (Qwen 3.6 Plus)
======================================================
Production-grade async LLM client with:
  - OpenRouter API via openai SDK
  - Exponential backoff for rate limits
  - Opik observability instrumentation
  - JSON mode for structured output
"""

import json
import asyncio
import logging
import time
from typing import Dict, Optional, Any, List

from openai import AsyncOpenAI

from .config import (
    OPENROUTER_API_KEY,
    OPENROUTER_BASE_URL,
    OPENROUTER_MODEL,
    LLM_MAX_TOKENS,
    LLM_TEMPERATURE,
    OPIK_URL,
    OPIK_WORKSPACE,
    OPIK_PROJECT,
)

logger = logging.getLogger(__name__)

# Try to import Opik for observability (optional dependency)
try:
    import opik
    _opik_available = True
    logger.info(f"✅ Opik available for LLM tracing ({OPIK_URL})")
except ImportError:
    _opik_available = False
    logger.info("ℹ️ Opik not installed. LLM calls will not be traced.")


class LLMAdapter:
    """Async OpenRouter LLM adapter with retry and Opik tracing.

    Usage:
        llm = LLMAdapter()
        response = await llm.chat("Explain deep learning")
        keywords = await llm.extract_json(prompt)
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        model: Optional[str] = None,
        max_retries: int = 3,
    ):
        self.api_key = api_key or OPENROUTER_API_KEY
        self.model = model or OPENROUTER_MODEL
        self.max_retries = max_retries
        self._call_count = 0
        self._total_tokens = 0

        self.client = AsyncOpenAI(
            base_url=OPENROUTER_BASE_URL,
            api_key=self.api_key,
        )

        # Initialise Opik client if available
        self._opik_client = None
        if _opik_available:
            try:
                self._opik_client = opik.Opik(
                    url=OPIK_URL,
                    workspace=OPIK_WORKSPACE,
                    project_name=OPIK_PROJECT,
                )
                logger.info(f"✅ Opik client connected (project={OPIK_PROJECT})")
            except Exception as e:
                logger.warning(f"⚠️ Opik init failed: {e}. Tracing disabled.")

        logger.info(f"✅ LLMAdapter initialised (model={self.model})")

    async def chat(
        self,
        user_prompt: str,
        system_prompt: Optional[str] = None,
        max_tokens: Optional[int] = None,
        temperature: Optional[float] = None,
        json_mode: bool = False,
    ) -> str:
        """Send a chat completion request with retry logic.

        Args:
            user_prompt: User message content.
            system_prompt: Optional system message.
            max_tokens: Override default max tokens.
            temperature: Override default temperature.
            json_mode: If True, request JSON response format.

        Returns:
            LLM response text.
        """
        messages: List[Dict[str, str]] = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": user_prompt})

        kwargs: Dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "max_tokens": max_tokens or LLM_MAX_TOKENS,
            "temperature": temperature if temperature is not None else LLM_TEMPERATURE,
        }
        if json_mode:
            kwargs["response_format"] = {"type": "json_object"}

        for attempt in range(self.max_retries):
            try:
                self._call_count += 1
                t0 = time.time()

                response = await self.client.chat.completions.create(**kwargs)

                content = response.choices[0].message.content or ""
                usage = response.usage
                latency = time.time() - t0

                # Track tokens
                input_tokens = usage.prompt_tokens if usage else 0
                output_tokens = usage.completion_tokens if usage else 0
                self._total_tokens += input_tokens + output_tokens

                logger.debug(
                    f"LLM call #{self._call_count}: {input_tokens}+{output_tokens} tokens, "
                    f"{latency:.2f}s"
                )

                # Log to Opik
                self._trace_to_opik(
                    name="llm_chat",
                    input_text=user_prompt[:200],
                    output_text=content[:200],
                    metadata={
                        "model": self.model,
                        "input_tokens": input_tokens,
                        "output_tokens": output_tokens,
                        "latency_s": round(latency, 3),
                        "attempt": attempt + 1,
                    },
                )

                return content.strip()

            except Exception as e:
                error_str = str(e)
                if "429" in error_str or "rate" in error_str.lower():
                    wait = 3 * (attempt + 1)
                    logger.warning(f"Rate limited. Waiting {wait}s (attempt {attempt+1})...")
                    await asyncio.sleep(wait)
                else:
                    logger.error(f"LLM error (attempt {attempt+1}): {type(e).__name__}: {e}")
                    await asyncio.sleep(1)

        logger.error(f"LLM failed after {self.max_retries} retries")
        return ""

    async def extract_json(
        self,
        user_prompt: str,
        system_prompt: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Send a prompt and parse JSON response.

        Args:
            user_prompt: Prompt requesting JSON output.
            system_prompt: Optional system message.

        Returns:
            Parsed JSON dict, or empty dict on failure.
        """
        raw = await self.chat(
            user_prompt=user_prompt,
            system_prompt=system_prompt,
            json_mode=True,
            temperature=0.0,
        )
        if not raw:
            return {}

        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            # Try to extract JSON from markdown code block
            if "```json" in raw:
                raw = raw.split("```json")[1].split("```")[0].strip()
                try:
                    return json.loads(raw)
                except json.JSONDecodeError:
                    pass
            logger.warning(f"Failed to parse JSON from LLM response: {raw[:200]}")
            return {}

    def _trace_to_opik(
        self,
        name: str,
        input_text: str,
        output_text: str,
        metadata: Optional[Dict] = None,
    ):
        """Log a trace to Opik (fire-and-forget)."""
        if self._opik_client:
            try:
                self._opik_client.log_trace(
                    name=name,
                    input={"prompt": input_text},
                    output={"response": output_text},
                    metadata=metadata or {},
                )
            except Exception as e:
                logger.debug(f"Opik trace failed: {e}")

    @property
    def stats(self) -> Dict[str, int]:
        return {
            "llm_calls": self._call_count,
            "total_tokens": self._total_tokens,
        }
