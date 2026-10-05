import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import os

os.environ.setdefault("GROQ_API_KEY", "test-key")
os.environ.setdefault("TAVILY_API_KEY", "test-key")

from app.llm import LLMClient, _is_retryable, _retry_delay, parse_json


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


class FakeServerError(Exception):
    status_code = 503

    def __str__(self) -> str:
        return "service unavailable"


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

    def check(label: str, condition: bool) -> None:
        nonlocal passed, failed
        if condition:
            passed += 1
            print(f"PASS {label}")
        else:
            failed += 1
            print(f"FAIL {label}")

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

    print("\n=== json parsing ===")
    check("plain object", parse_json('{"a": 1}') == {"a": 1})
    check("fenced object", parse_json('```json\n{"a": 2}\n```') == {"a": 2})
    check("prose wrapped", parse_json('Sure! {"a": 3} hope that helps') == {"a": 3})
    check("array", parse_json("[1, 2]") == [1, 2])
    failed_parse = False
    try:
        parse_json("no json at all")
    except Exception:
        failed_parse = True
    check("rejects garbage", failed_parse)

    print(f"\n{passed} passed, {failed} failed")
    if failed:
        raise SystemExit(1)
    print("ALL RETRY TESTS PASSED")


if __name__ == "__main__":
    main()
