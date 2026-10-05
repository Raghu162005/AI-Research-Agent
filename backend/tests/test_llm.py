import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import os

os.environ.setdefault("GROQ_API_KEY", "test-key")
os.environ.setdefault("TAVILY_API_KEY", "test-key")

from app.llm import (
    LLMClient,
    _is_daily_quota_error,
    _is_json_validation_error,
    _is_retryable,
    _retry_delay,
    parse_json,
)


class FakeRateLimit(Exception):
    status_code = 429

    def __str__(self) -> str:
        return (
            "Error code: 429 - Rate limit reached for model. Limit 8000, Used 3036, "
            "Requested 5917. Please try again in 7.1475s."
        )


class FakeBadRequest(Exception):
    status_code = 400

    def __str__(self) -> str:
        return "Error code: 400 - invalid model"


class FakeJsonValidation(Exception):
    """Groq's validator rejecting generation. Real one shipped valid JSON."""

    status_code = 400

    def __str__(self) -> str:
        return (
            "Error code: 400 - {'error': {'message': "
            '"Failed to generate JSON. Please adjust your prompt.", '
            "'type': 'invalid_request_error', 'code': 'json_validate_failed', "
            "'failed_generation': '{\"executive_summary\":\"fine\",\"sections\":[]}'}}"
        )


class FakeServerError(Exception):
    status_code = 503

    def __str__(self) -> str:
        return "service unavailable"


class FakeDailyQuota(Exception):
    """Tokens-per-day exhaustion. Retrying is pointless, unlike a 429 TPM."""

    status_code = 429

    def __str__(self) -> str:
        return (
            "Error code: 429 - {'error': {'message': 'Rate limit reached for model "
            "`openai/gpt-oss-120b` on tokens per day (TPD): Limit 200000, "
            "Used 196481, Requested 5670. Please try again in 15m29.232s.', "
            "'type': 'tokens', 'code': 'rate_limit_exceeded'}}"
        )


class FakeResponse:
    def __init__(self, content: str) -> None:
        message = type("Msg", (), {})()
        message.content = content
        choice = type("Choice", (), {})()
        choice.message = message
        self.choices = [choice]


class ScriptedCompletions:
    def __init__(self, failures, success="ok") -> None:
        self.failure_list = failures
        self.failure_count = failures if isinstance(failures, int) else len(failures)
        self.success = success
        self.calls = 0

    def create(self, **kwargs):
        self.calls += 1
        if self.calls <= self.failure_count:
            index = min(self.calls, len(self.failure_list)) - 1
            raise self.failure_list[index]
        return FakeResponse(self.success)


def scripted_client(failures, success="ok"):
    client = LLMClient()
    client._retry_base_delay = 0.01
    client._retry_max_delay = 0.05
    completions = ScriptedCompletions(failures, success)
    client._client = type(
        "FakeGroq", (), {"chat": type("Chat", (), {"completions": completions})()}
    )()
    return client, completions


def main() -> None:
    passed = failed = 0

    def check(label: str, condition: bool, detail: str = "") -> None:
        nonlocal passed, failed
        if condition:
            passed += 1
            print(f"PASS {label}")
        else:
            failed += 1
            print(f"FAIL {label}{(' -> ' + detail) if detail else ''}")

    print("=== retry classification ===")
    check("429 retryable", _is_retryable(FakeRateLimit()))
    check("400 not retryable", not _is_retryable(FakeBadRequest()))
    check("5xx retryable", _is_retryable(FakeServerError()))

    print("\n=== backoff ===")
    hint = _retry_delay(FakeRateLimit(), 0, 2.0, 45.0)
    check(f"respects provider hint ({hint:.2f}s)", 7.0 <= hint <= 8.0)
    base = _retry_delay(FakeServerError(), 0, 2.0, 45.0)
    check(f"exponential base ({base:.2f}s)", 2.0 <= base <= 2.8)
    capped = _retry_delay(FakeServerError(), 5, 2.0, 45.0)
    check(f"capped at max ({capped:.2f}s)", capped <= 45.0)

    print("\n=== retry behaviour ===")
    client, completions = scripted_client([FakeRateLimit(), FakeRateLimit()], "  recovered  ")
    result = client.complete("sys", "user")
    check(f"recovers after 2 rate limits (calls={completions.calls})", completions.calls == 3)
    check("strips whitespace", result == "recovered")

    client, completions = scripted_client([FakeRateLimit()] * 99)
    raised = ""
    try:
        client.complete("sys", "user")
    except Exception as exc:
        raised = str(exc)
    check(
        f"raises after exhausting retries (calls={completions.calls})",
        completions.calls == client.max_retries + 1 and "after" in raised,
    )

    client, completions = scripted_client([FakeBadRequest()], "never")
    raised = ""
    try:
        client.complete("sys", "user")
    except Exception as exc:
        raised = str(exc)
    check(f"does not retry non-retryable (calls={completions.calls})", completions.calls == 1)
    check("surfaces original error", "400" in raised)

    print("\n=== daily quota (TPD) is not retryable ===")
    check("TPD detected", _is_daily_quota_error(FakeDailyQuota()))
    check("TPM not misread as daily", not _is_daily_quota_error(FakeRateLimit()))
    check("json error not a daily quota", not _is_daily_quota_error(FakeJsonValidation()))

    client, completions = scripted_client([FakeDailyQuota()])
    raised = ""
    raised_type = ""
    try:
        client.complete("sys", "user", json_mode=True)
    except Exception as exc:
        raised = str(exc)
        raised_type = type(exc).__name__
    check("daily quota makes exactly one call", completions.calls == 1, f"calls={completions.calls}")
    check("raises the specific daily-limit type", raised_type == "LLMDailyLimitError", raised_type)
    check("message states the quota numbers", "196,481 of 200,000" in raised, raised[:100])
    check("message shows percentage used", "98%" in raised, raised[:120])
    check("message shows remaining budget", "3,519 remaining" in raised, raised[:140])
    check("message states the call size", "5,670 tokens" in raised, raised[:170])
    check("message explains retrying is futile", "will not succeed on retry" in raised, raised[:220])
    check("message parses the 15m29.232s hint", "15m29.232s" in raised, raised[-200:])
    check("message links to billing", "console.groq.com/settings/billing" in raised)
    check("does not claim the old retry count", "after 6 attempt(s)" not in raised)

    client, completions = scripted_client([FakeRateLimit()] * 99)
    tpm_ok = False
    try:
        client.complete("sys", "user", json_mode=True)
    except Exception:
        tpm_ok = True
    check(
        f"per-minute limit still retries to exhaustion (calls={completions.calls})",
        completions.calls == client.max_retries + 1 and tpm_ok,
        f"calls={completions.calls}",
    )
    check(
        "per-minute limit is not reported as a daily quota",
        "daily token quota" not in str(completions),
    )

    print("\n=== json parsing ===")
    check("plain object", parse_json('{"a": 1}') == {"a": 1})
    check("fenced object", parse_json('```json\n{"a": 2}\n```') == {"a": 2})
    check("prose wrapped", parse_json('Sure! {"a": 3} hope that helps') == {"a": 3})
    check("array", parse_json("[1, 2]") == [1, 2])
    check("trailing comma repaired", parse_json('{"a": 4,}') == {"a": 4})
    check("trailing comma in array", parse_json("[1, 2,]") == [1, 2])
    check("fence with prose", parse_json('text\n```json\n{"a": 5}\n```\nmore') == {"a": 5})
    failed_parse = False
    try:
        parse_json("no json at all")
    except Exception:
        failed_parse = True
    check("rejects garbage", failed_parse)
    failed_parse2 = False
    try:
        parse_json('{"a": 1')
    except Exception:
        failed_parse2 = True
    check("rejects truncated", failed_parse2)

    print("\n=== attempt accounting ===")
    client, completions = scripted_client([FakeJsonValidation()])
    raised = ""
    try:
        client.complete("sys", "user", json_mode=True)
    except Exception as exc:
        raised = str(exc)
    check("json validation error not treated as retryable", not _is_retryable(FakeJsonValidation()))
    check("json validation error detected", _is_json_validation_error(FakeJsonValidation()))
    check("400 model error is not a json validation error", not _is_json_validation_error(FakeBadRequest()))
    check(
        f"reports ACTUAL attempts, not the maximum (calls={completions.calls})",
        "after 1 attempt(s)" in raised,
        raised[:90],
    )

    print("\n=== json validator fallback ===")

    class RejectThenSucceed:
        """Fails strict JSON mode, returns valid JSON without response_format."""

        def __init__(self):
            self.calls = 0
            self.modes = []

        def create(self, **kwargs):
            self.calls += 1
            strict = kwargs.get("response_format") is not None
            self.modes.append("strict" if strict else "fallback")
            if strict:
                raise FakeJsonValidation()
            return FakeResponse(
                'Here is the JSON you asked for:\n```json\n'
                '{"executive_summary":"recovered","sections":[{"title":"a","markdown":"b"}]}\n```'
            )

    client = LLMClient()
    scripted = RejectThenSucceed()
    client._client = type(
        "FakeGroq", (), {"chat": type("Chat", (), {"completions": scripted})()}
    )()
    data = client.complete_json("sys", "user")
    check("falls back when provider validator rejects", data["executive_summary"] == "recovered")
    check("fallback parsed fenced json inside prose", len(data["sections"]) == 1)
    check("strict attempted first, then fallback", scripted.modes == ["strict", "fallback"], str(scripted.modes))

    class AlwaysInvalid:
        def __init__(self):
            self.calls = 0

        def create(self, **kwargs):
            self.calls += 1
            return FakeResponse("I refuse to produce JSON, sorry about that.")

    client = LLMClient()
    always = AlwaysInvalid()
    client._client = type(
        "FakeGroq", (), {"chat": type("Chat", (), {"completions": always})()}
    )()
    gave_up = False
    gave_up_msg = ""
    try:
        client.complete_json("sys", "user")
    except Exception as exc:
        gave_up = True
        gave_up_msg = str(exc)
    check(
        "falls back when strict mode returns prose",
        always.calls == 2,
        f"calls={always.calls}",
    )
    check("gives up after fallback also fails", gave_up)
    check("error names both attempts", "Strict mode failed" in gave_up_msg and "Fallback failed" in gave_up_msg, gave_up_msg[:120])

    class ProseThenJson:
        def __init__(self):
            self.calls = 0

        def create(self, **kwargs):
            self.calls += 1
            if self.calls == 1:
                return FakeResponse("Sure, here is your report as prose, not JSON.")
            return FakeResponse('{"executive_summary":"recovered on fallback"}')

    client = LLMClient()
    prose = ProseThenJson()
    client._client = type(
        "FakeGroq", (), {"chat": type("Chat", (), {"completions": prose})()}
    )()
    recovered = client.complete_json("sys", "user")
    check(
        "recovers from prose-only strict response",
        recovered["executive_summary"] == "recovered on fallback" and prose.calls == 2,
        f"calls={prose.calls}",
    )

    class PlainBadRequest:
        def __init__(self):
            self.calls = 0

        def create(self, **kwargs):
            self.calls += 1
            raise FakeBadRequest()

    client = LLMClient()
    bad = PlainBadRequest()
    client._client = type(
        "FakeGroq", (), {"chat": type("Chat", (), {"completions": bad})()}
    )()
    raised_plain = False
    try:
        client.complete_json("sys", "user")
    except Exception:
        raised_plain = True
    check("non-json 400 does not trigger fallback", bad.calls == 1 and raised_plain, f"calls={bad.calls}")

    print(f"\n{passed} passed, {failed} failed")
    if failed:
        raise SystemExit(1)
    print("ALL RETRY TESTS PASSED")


if __name__ == "__main__":
    main()
