import json
import logging
import random
import re
import time
from typing import Any

from groq import Groq

from app.config import get_settings

logger = logging.getLogger("research_agent")

_JSON_FENCE = re.compile(r"```(?:json)?\s*(.+?)\s*```", re.DOTALL)
_RETRY_AFTER_PATTERN = re.compile(r"try again in\s*([\d.]+)\s*s", re.IGNORECASE)
_RETRYABLE_MARKERS = (
    "rate_limit",
    "rate limit",
    "tokens per minute",
    "tpm",
    "429",
    "overloaded",
    "timeout",
    "timed out",
    "connection",
)


class LLMError(RuntimeError):
    pass


def _is_retryable(exc: Exception) -> bool:
    message = f"{type(exc).__name__}: {exc}".lower()
    status = getattr(exc, "status_code", None)
    if status == 429:
        return True
    if status is not None and int(status) >= 500:
        return True
    return any(marker in message for marker in _RETRYABLE_MARKERS)


def _retry_delay(exc: Exception, attempt: int, base: float, maximum: float) -> float:
    hint = _RETRY_AFTER_PATTERN.search(str(exc))
    if hint:
        return min(float(hint.group(1)) + 0.5, maximum)
    exponential = base * (2**attempt)
    return min(exponential + random.uniform(0, 0.75), maximum)


def parse_json(raw: str) -> Any:
    text = _JSON_FENCE.sub(r"\1", raw.strip()).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    starts = [pos for pos in (text.find("{"), text.find("[")) if pos != -1]
    end = max(text.rfind("}"), text.rfind("]"))
    if not starts or end == -1:
        raise LLMError(f"Model output was not valid JSON: {raw[:300]}")
    try:
        return json.loads(text[min(starts) : end + 1])
    except json.JSONDecodeError as exc:
        raise LLMError(f"Model output was not valid JSON: {raw[:300]}") from exc


class LLMClient:
    def __init__(self) -> None:
        settings = get_settings()
        self.model = settings.groq_model
        self.temperature = settings.llm_temperature
        self.max_retries = settings.llm_max_retries
        self._retry_base_delay = settings.llm_retry_base_delay
        self._retry_max_delay = settings.llm_retry_max_delay
        self._client = Groq(
            api_key=settings.groq_api_key, max_retries=0, timeout=120.0
        )

    def complete(
        self,
        system_prompt: str,
        user_prompt: str,
        *,
        temperature: float | None = None,
        json_mode: bool = False,
        max_tokens: int | None = None,
    ) -> str:
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": self.temperature if temperature is None else temperature,
        }
        if json_mode:
            payload["response_format"] = {"type": "json_object"}
        if max_tokens is not None:
            payload["max_tokens"] = max_tokens

        content = self._request_with_retry(payload)
        if not content:
            raise LLMError("Groq returned an empty response")
        return content.strip()

    def _request_with_retry(self, payload: dict[str, Any]) -> str:
        attempts = self.max_retries + 1
        last_error: Exception | None = None

        for attempt in range(attempts):
            try:
                response = self._client.chat.completions.create(**payload)
                return response.choices[0].message.content
            except Exception as exc:
                last_error = exc
                if attempt == attempts - 1 or not _is_retryable(exc):
                    break
                delay = _retry_delay(
                    exc, attempt, self._retry_base_delay, self._retry_max_delay
                )
                logger.warning(
                    "LLM call failed (attempt %s/%s), retrying in %.1fs: %s",
                    attempt + 1,
                    attempts,
                    delay,
                    exc,
                )
                time.sleep(delay)

        raise LLMError(
            f"Groq request failed after {attempts} attempt(s): {last_error}"
        ) from last_error

    def complete_json(self, system_prompt: str, user_prompt: str) -> Any:
        return parse_json(self.complete(system_prompt, user_prompt, json_mode=True))
