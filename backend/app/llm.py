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
_JSON_VALIDATION_MARKERS = (
    "json_validate_failed",
    "failed to generate json",
    "invalid json",
)
_DAILY_QUOTA_MARKERS = (
    "tokens per day",
    "tpd",
    " per day",
    "daily limit",
    "requests per day",
    "rpd",
)
_RESET_HINT = re.compile(r"try again in\s*((?:\d+h)?(?:\d+m)?[\d.]*s)", re.IGNORECASE)
_USED = re.compile(r"Used\s+([\d,]+)")
_LIMIT = re.compile(r"Limit\s+([\d,]+)")
_REQUESTED = re.compile(r"Requested\s+([\d,]+)")


class LLMError(RuntimeError):
    pass


class LLMDailyLimitError(LLMError):
    """The account's daily token quota is spent, so retrying cannot succeed."""


class LLMJSONError(LLMError):
    """The model responded, but the response was not usable JSON."""


def _is_retryable(exc: Exception) -> bool:
    message = f"{type(exc).__name__}: {exc}".lower()
    status = getattr(exc, "status_code", None)
    if status == 429:
        return True
    if status is not None and int(status) >= 500:
        return True
    return any(marker in message for marker in _RETRYABLE_MARKERS)


def _is_json_validation_error(exc: Exception) -> bool:
    """True when the provider's own JSON validator rejected the generation.

    Groq sometimes returns ``json_validate_failed`` for output that is in fact
    valid JSON, so this is recovered by parsing the text ourselves rather than
    by retrying the same request.
    """
    message = f"{type(exc).__name__}: {exc}".lower()
    return any(marker in message for marker in _JSON_VALIDATION_MARKERS)


def _is_daily_quota_error(exc: Exception) -> bool:
    """True for per-day quota exhaustion, which is not worth retrying.

    A per-minute limit resets in seconds and retrying works. A daily limit does
    not: waiting a minute leaves the day's quota just as spent, so retrying only
    delays an inevitable failure.
    """
    message = f"{type(exc).__name__}: {exc}".lower()
    return any(marker in message for marker in _DAILY_QUOTA_MARKERS)


def _daily_limit_message(exc: Exception) -> str:
    text = str(exc)
    used = _USED.search(text)
    limit = _LIMIT.search(text)
    requested = _REQUESTED.search(text)
    hint = _RESET_HINT.search(text)

    parts = ["Groq daily token quota is exhausted"]
    if used and limit:
        used_value = int(used.group(1).replace(",", ""))
        limit_value = int(limit.group(1).replace(",", ""))
        remaining = max(limit_value - used_value, 0)
        parts[0] += (
            f": {used_value:,} of {limit_value:,} tokens used today "
            f"({used_value / limit_value:.0%}), about {remaining:,} remaining."
        )
    if requested:
        parts.append(f"This call needs {int(requested.group(1).replace(',', '')):,} tokens.")
    parts.append(
        "Daily quotas do not recover by waiting a few minutes, so this will not "
        "succeed on retry."
    )
    if hint:
        parts.append(
            f"The provider suggests waiting {hint.group(1)}, but if the quota is "
            "still spent then, either wait for the daily window to roll over or "
            "upgrade at https://console.groq.com/settings/billing"
        )
    return " ".join(parts)


def _retry_delay(exc: Exception, attempt: int, base: float, maximum: float) -> float:
    hint = _RETRY_AFTER_PATTERN.search(str(exc))
    if hint:
        return min(float(hint.group(1)) + 0.5, maximum)
    exponential = base * (2**attempt)
    return min(exponential + random.uniform(0, 0.75), maximum)


_TRAILING_COMMA = re.compile(r",(\s*[}\]])")


def parse_json(raw: str) -> Any:
    text = _JSON_FENCE.sub(r"\1", raw.strip()).strip()
    for candidate in (text, *_json_candidates(text)):
        try:
            return json.loads(candidate)
        except json.JSONDecodeError:
            repaired = _TRAILING_COMMA.sub(r"\1", candidate)
            if repaired != candidate:
                try:
                    return json.loads(repaired)
                except json.JSONDecodeError:
                    pass

    raise LLMJSONError(
        "Model output was not valid JSON. It began: " + repr(raw[:200])
    )


def _json_candidates(text: str) -> list[str]:
    """Progressively looser slices of a response that may be wrapped in prose."""
    candidates: list[str] = []
    for opener, closer in (("{", "}"), ("[", "]")):
        start = text.find(opener)
        end = text.rfind(closer)
        if start != -1 and end > start:
            candidates.append(text[start : end + 1])
    return candidates


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
        max_attempts = self.max_retries + 1
        last_error: Exception | None = None
        made = 0

        for attempt in range(max_attempts):
            made = attempt + 1
            try:
                response = self._client.chat.completions.create(**payload)
                return response.choices[0].message.content
            except Exception as exc:
                last_error = exc
                if _is_daily_quota_error(exc):
                    raise LLMDailyLimitError(_daily_limit_message(exc)) from exc
                if attempt == max_attempts - 1 or not _is_retryable(exc):
                    break
                delay = _retry_delay(
                    exc, attempt, self._retry_base_delay, self._retry_max_delay
                )
                logger.warning(
                    "LLM call failed (attempt %s/%s), retrying in %.1fs: %s",
                    made,
                    max_attempts,
                    delay,
                    exc,
                )
                time.sleep(delay)

        raise LLMError(
            f"Groq request failed after {made} attempt(s): {last_error}"
        ) from last_error

    def complete_json(self, system_prompt: str, user_prompt: str) -> Any:
        strict_error: Exception | None = None
        try:
            return parse_json(
                self.complete(system_prompt, user_prompt, json_mode=True)
            )
        except LLMError as exc:
            if not isinstance(exc, LLMJSONError) and not _is_json_validation_error(exc):
                raise
            strict_error = exc

        logger.warning(
            "Strict JSON mode produced no usable output (%s); "
            "retrying without response_format",
            type(strict_error).__name__,
        )
        fallback_prompt = (
            f"{user_prompt}\n\n"
            "Reply with a single valid JSON object and nothing else: "
            "no prose, no explanation, no markdown code fences."
        )
        try:
            return parse_json(self.complete(system_prompt, fallback_prompt))
        except LLMError as exc:
            raise LLMError(
                f"Model did not return usable JSON. Strict mode failed with "
                f"{type(strict_error).__name__}: {strict_error}. "
                f"Fallback failed with {type(exc).__name__}: {exc}"
            ) from exc
