"""Agent pipeline, search tool and store tests. No network or API keys required."""

import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

os.environ.setdefault("GROQ_API_KEY", "test-key")
os.environ.setdefault("TAVILY_API_KEY", "test-key")

from app.agent import ResearchAgent
from app.llm import LLMError
from app.store import (
    STATUS_COMPLETED,
    STATUS_QUEUED,
    STATUS_RUNNING,
    ReportStore,
)
from app.tools.web_search import Source, WebSearchError, WebSearchTool

PASSED = 0
FAILED = 0


def check(label, condition, detail=""):
    global PASSED, FAILED
    if condition:
        PASSED += 1
        print(f"PASS {label}")
    else:
        FAILED += 1
        print(f"FAIL {label}{(' -> ' + detail) if detail else ''}")


# --------------------------------------------------------------------------
# fakes
# --------------------------------------------------------------------------
class FakeLLM:
    model = "fake-model"

    def __init__(self, plan=None, analysis=None, writer=None):
        self.calls = 0
        self._plan = plan
        self._analysis = analysis
        self._writer = writer

    def complete_json(self, system_prompt, user_prompt):
        self.calls += 1
        if system_prompt.startswith("You are a research strategist"):
            return self._plan if self._plan is not None else {
                "objective": "Establish how agentic AI changes development practice.",
                "subtopics": [
                    {"title": "Productivity impact", "focus": "Measured throughput gains"},
                    {"title": "Adoption barriers", "focus": "Why teams hesitate"},
                ],
                "queries": ["agentic ai productivity", "agentic ai barriers"],
            }
        if system_prompt.startswith("You are a rigorous research analyst"):
            return self._analysis if self._analysis is not None else {
                "summary": "Sources indicate measurable but contested gains.",
                "findings": [
                    {
                        "claim": "Reported gains cluster in the 10-30% range.",
                        "evidence": "Two independent studies converge.",
                        "source_indexes": [1, 2, 99, "bogus"],
                    }
                ],
                "conflicts": ["Study A measures tasks, study B measures elapsed time."],
                "gaps": ["No long-horizon data."],
            }
        return self._writer if self._writer is not None else {
            "executive_summary": "Agentic tooling is reshaping developer workflows.",
            "sections": [
                {
                    "title": "Productivity impact",
                    "markdown": (
                        "## Productivity impact\n"
                        "Gains cluster at 10-30% [1]. A fabricated ref [99] must vanish, "
                        "and so must [100]. Valid [2] survives."
                    ),
                }
            ],
            "key_takeaways": ["Gains are real but modest."],
            "open_questions": ["How do gains hold over 12 months?"],
        }


class FakeSearch:
    def __init__(self, results=4, queries=None):
        self._results = results
        self._queries = queries
        self.queries = []

    def collect(self, queries):
        self.queries = queries
        if self._queries is not None:
            return [Source(i, f"S{i}", f"https://e{i}.com/a", f"e{i}.com", queries[0], "x") for i in self._queries]
        return [
            Source(i, f"Source {i}", f"https://example{i}.com/a", f"example{i}.com", queries[0], f"Snippet {i}")
            for i in range(1, self._results + 1)
        ]


def build(llm=None, search=None):
    return ResearchAgent(llm=llm or FakeLLM(), search=search or FakeSearch())


# --------------------------------------------------------------------------
def test_happy_path():
    print("\n=== pipeline happy path ===")
    llm, search = FakeLLM(), FakeSearch(4)
    events = []
    report = build(llm, search).run("Impact of Agentic AI", on_progress=events.append)
    md = report.markdown

    check("invalid citation [99] stripped", "[99]" not in md)
    check("invalid citation [100] stripped", "[100]" not in md)
    check("valid citation [1] kept", "[1]" in md)
    check("valid citation [2] kept", "[2]" in md)
    check("cited indexes sorted and unique", report.cited_indexes == [1, 2], str(report.cited_indexes))
    check("four llm calls (1 plan + 2 analyze + 1 write)", llm.calls == 4, f"calls={llm.calls}")
    check("search received plan queries", search.queries == report.plan.queries)
    check("exec summary rendered", "## Executive Summary" in md)
    check("objective rendered", "**Objective:**" in md)
    check("key takeaways rendered", "## Key Takeaways" in md)
    check("open questions rendered", "## Open Questions" in md)
    check("sources section rendered", "## Sources" in md)
    check("all 4 sources listed", all(f"example{i}.com" in md for i in range(1, 5)))
    check("uncited source flagged", "_(retrieved, not cited)_" in md)
    check("model named in footer", "fake-model" in md)
    check("no encoding corruption", "\ufffd" not in md)
    check("findings drop invalid index 99", all(99 not in f.source_indexes for f in report.analyses[0].findings))
    check("findings drop non-numeric index", all(f.source_indexes == [1, 2] for f in report.analyses[0].findings))
    check("conflicts captured", report.analyses[0].conflicts and "contested" not in report.analyses[0].conflicts[0].lower()[:4])
    check("gaps captured", len(report.analyses[0].gaps) == 1)
    check("one analysis per subtopic", len(report.analyses) == 2)
    check("four steps recorded", len(report.steps) == 4, str(report.steps))

    stages = [e.stage for e in events]
    check("stages in pipeline order", stages[:1] == ["plan"] and stages[-1] == "done")
    check("all stages present", set(stages) >= {"plan", "search", "analyze", "write", "done"})
    percents = [e.percent for e in events]
    check("percent never decreases", all(b >= a for a, b in zip(percents, percents[1:])), str(percents))
    check("ends at 100%", percents[-1] == 100)
    check("done event reports coverage", events[-1].detail.get("sources") == 4)


def test_plan_caps_and_coercion():
    print("\n=== planner coercion + caps ===")
    over = {
        "objective": "x",
        "subtopics": [{"title": f"T{i}", "focus": "f"} for i in range(12)],
        "queries": [f"q{i}" for i in range(12)],
    }
    report = build(FakeLLM(plan=over)).run("topic")
    check("subtopics capped at 4", len(report.plan.subtopics) == 4, str(len(report.plan.subtopics)))
    check("queries capped at 5", len(report.plan.queries) == 5, str(len(report.plan.queries)))

    strings = {"subtopics": ["A", "B"], "queries": ["q1"], "objective": "o"}
    plan = build(FakeLLM(plan=strings)).plan("topic")
    check("string subtopics coerced", [s.title for s in plan.subtopics] == ["A", "B"])
    check("string subtopic focus falls back to title", plan.subtopics[0].focus == "A")

    dicts = {"subtopics": [{"title": "A", "description": "desc"}], "queries": [{"query": "q1"}]}
    plan = build(FakeLLM(plan=dicts)).plan("topic")
    check("description used as focus", plan.subtopics[0].focus == "desc")
    check("dict queries coerced", plan.queries == ["q1"])


def test_plan_failure():
    print("\n=== planner failure ===")
    failed = False
    try:
        build(FakeLLM(plan={"subtopics": [], "queries": []})).plan("topic")
    except LLMError:
        failed = True
    check("empty plan raises LLMError", failed)

    fallback = build(FakeLLM(plan={"subtopics": ["A"], "queries": [], "objective": None})).plan("t")
    check("missing queries fall back to overview", fallback.queries == ["t overview"], str(fallback.queries))
    check("missing objective synthesised", "t" in fallback.objective.lower())


def test_no_sources():
    print("\n=== no sources retrieved ===")
    report = build(FakeLLM(), FakeSearch(0)).run("obscure topic")
    check("report still built", bool(report.markdown))
    check("no findings", all(not a.findings for a in report.analyses))
    check("no sources listed", "## Sources" in report.markdown)
    check("cited indexes empty", report.cited_indexes == [])


def test_search_tool():
    print("\n=== search tool dedup + normalisation ===")

    class FakeTavily:
        def __init__(self, results=None, error=None, payload=None):
            self.results = results
            self.error = error
            self.payload = payload
            self.calls = []

        def search(self, **kwargs):
            self.calls.append(kwargs)
            if self.error:
                raise self.error
            if self.payload is not None:
                return self.payload
            return {"results": self.results.get(kwargs["query"], [])}

    payload = {
        "q1": [
            {"url": "https://www.alpha.com/a", "title": "Alpha", "content": "x" * 3000},
            {"url": "https://beta.com/b", "title": "", "content": "y"},
            {"url": "", "title": "no url", "content": "z"},
        ],
        "q2": [
            {"url": "https://www.alpha.com/a", "title": "Alpha dup", "content": "dup"},
            {"url": "https://gamma.io/c", "title": "Gamma", "content": "z"},
        ],
    }
    tool = WebSearchTool()
    tool._client = FakeTavily(results=payload)
    events = []
    sources = tool.collect_with_progress(["q1", "q2"], events.append)

    check("duplicate urls collapsed", len(sources) == 3, str(len(sources)))
    check("empty url skipped", all(s.url for s in sources))
    check("indexes contiguous from 1", [s.index for s in sources] == [1, 2, 3])
    check("www stripped from domain", sources[0].domain == "alpha.com", sources[0].domain)
    check("missing title falls back to url", sources[1].title == "https://beta.com/b")
    check(
        "snippet truncated within limit",
        len(sources[0].snippet) <= 1200 and sources[0].snippet.endswith("..."),
        f"len={len(sources[0].snippet)}",
    )
    check("short snippet untouched", sources[1].snippet == "y")
    for limit in (10, 4, 1):
        from app.tools.web_search import _truncate

        check(
            f"truncate respects limit={limit}",
            len(_truncate("a" * 500, limit)) <= limit,
            f"got {len(_truncate('a' * 500, limit))}",
        )
    check("truncate collapses whitespace", _truncate("a   b\n\nc", 100) == "a b c")
    check("truncate keeps short text", _truncate("short", 100) == "short")
    check("query attribution kept", sources[2].query == "q2")
    check("progress emitted per query", len([e for e in events if e.stage == "search"]) == 2)
    check(
        "depth and result cap forwarded",
        all(c["search_depth"] == "advanced" and c["max_results"] == 4 for c in tool._client.calls),
    )

    tool._client = FakeTavily(error=RuntimeError("upstream 500"))
    wrapped = ""
    try:
        tool.collect(["q1"])
    except WebSearchError as exc:
        wrapped = str(exc)
    check("upstream failure wrapped in WebSearchError", bool(wrapped), wrapped)
    check("wrapped error names the query", "q1" in wrapped)

    tool._client = FakeTavily(payload={"results": None})
    check("null results -> empty list", tool.collect(["q1"]) == [])
    tool._client = FakeTavily(payload={})
    check("missing results key -> empty list", tool.collect(["q1"]) == [])

    tool._client = FakeTavily(payload=None)
    null_payload = ""
    try:
        tool.collect(["q1"])
    except WebSearchError as exc:
        null_payload = str(exc)
    check("null response wrapped, not leaked", bool(null_payload), null_payload)


def test_store_orphans():
    print("\n=== store orphan reconciliation ===")
    with tempfile.TemporaryDirectory() as tmp:
        store = ReportStore(Path(tmp) / "t.db")
        queued = store.create("queued topic")["id"]
        running = store.create("running topic")["id"]
        store.update(running, status=STATUS_RUNNING)
        done = store.create("done topic")["id"]
        store.update(done, status=STATUS_COMPLETED, markdown="# ok", cited_count=1, source_count=1)

        orphans = store.fail_orphaned()
        check("returns orphaned ids", sorted(orphans) == sorted([queued, running]), str(orphans))
        check("queued marked failed", store.get(queued)["status"] == "failed")
        check("running marked failed", store.get(running)["status"] == "failed")
        check("failure reason recorded", "restart" in store.get(running)["error"].lower())
        check("completed untouched", store.get(done)["status"] == STATUS_COMPLETED)
        check("completed markdown preserved", store.get(done)["markdown"] == "# ok")
        check("idempotent second call", store.fail_orphaned() == [])
        check("summarize_all matches summary", store.summarize_all() == [store.summary(r["id"]) for r in store.list_reports()])
        check("summaries omit markdown", "markdown" not in store.summarize_all()[0])


def test_quote_marks():
    print("\n=== plan edge: 100+ sources ===")
    big = [Source(i, f"S{i}", f"https://e{i}.com", f"e{i}.com", "q", "s") for i in range(1, 121)]
    agent = build(FakeLLM(), FakeSearch(0))
    md, cited = agent.assemble("t", agent.plan("t"), {"executive_summary": "", "sections": [{"title": "s", "markdown": "valid [120] bad [121] year [2024]"}], "key_takeaways": [], "open_questions": []}, big)
    check("valid 3-digit citation kept", "[120]" in md)
    check("out-of-range 3-digit citation stripped", "[121]" not in md)
    check("4-digit year not treated as citation", "[2024]" in md)


def main():
    test_happy_path()
    test_plan_caps_and_coercion()
    test_plan_failure()
    test_no_sources()
    test_search_tool()
    test_store_orphans()
    test_quote_marks()

    print(f"\n{PASSED} passed, {FAILED} failed")
    if FAILED:
        raise SystemExit(1)
    print("ALL AGENT TESTS PASSED")


if __name__ == "__main__":
    main()
