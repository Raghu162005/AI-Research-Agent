import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import app.jobs as jobs_module
import app.main as main_module
from app.agent import (
    Finding,
    ResearchPlan,
    ResearchReport,
    SectionAnalysis,
    Subtopic,
)
from app.config import get_settings
from app.tools.web_search import Source

TOPIC = "Impact of Agentic AI on Software Development"

SUBTOPICS = [{"title": "Productivity impact", "focus": "Measured throughput gains"}]
QUERIES = ["agentic AI developer productivity study"]


def fake_run(self, topic, on_progress=None):
    from app.agent import ProgressEvent, STAGE_ANALYZE, STAGE_DONE, STATUS_COMPLETED

    plan = ResearchPlan(
        topic=topic,
        objective="Establish how agentic AI changes software engineering.",
        subtopics=[Subtopic(**SUBTOPICS[0])],
        queries=QUERIES,
    )
    analysis = SectionAnalysis(
        title="Productivity impact",
        focus="Measured throughput gains",
        summary="Gains cluster in the 10-30% range.",
        findings=[Finding(claim="Gains are 10-30%.", evidence="Two studies.", source_indexes=[1])],
        conflicts=["Tasks vs elapsed time measure different things."],
        gaps=["No long-horizon data."],
    )
    source = Source(
        index=1,
        title="Study A",
        url="https://example.com/a",
        domain="example.com",
        query=QUERIES[0],
        snippet="snippet",
    )
    if on_progress:
        on_progress(ProgressEvent(STAGE_ANALYZE, STATUS_COMPLETED, "Analysed 1 section", 78))
    body = {
        "executive_summary": "Agentic tooling is reshaping developer workflows.",
        "sections": [
            {
                "title": "Productivity impact",
                "markdown": "## Productivity impact\nGains cluster in the 10-30% range [1].",
            }
        ],
        "key_takeaways": ["Gains are real but modest."],
        "open_questions": ["How do gains hold over 12 months?"],
    }
    markdown, cited = self.assemble(topic, plan, body, [source])
    if on_progress:
        on_progress(ProgressEvent(STAGE_DONE, STATUS_COMPLETED, "Report ready", 100))

    return ResearchReport(
        topic=topic,
        objective=plan.objective,
        markdown=markdown,
        plan=plan,
        analyses=[analysis],
        sources=[source],
        cited_indexes=cited,
        steps=["plan:1 subtopics, 1 queries", "search:1 unique sources"],
        model="fake-model",
        created_at="2026-01-01T00:00:00+00:00",
    )


def build_client(tmp_db):
    from fastapi.testclient import TestClient

    from app.store import ReportStore

    store = ReportStore(tmp_db)
    jobs_module.get_store = lambda: store
    main_module.get_store = lambda: store
    main_module.ResearchAgent = None

    from app.jobs import JobManager

    manager = JobManager(max_workers=2)
    jobs_module._manager = manager
    main_module.get_job_manager = lambda: manager

    client = TestClient(main_module.app)
    return client, store, manager


def check(label, condition, detail=""):
    print(("PASS " if condition else "FAIL ") + label + (f"  -> {detail}" if detail and not condition else ""))
    if not condition:
        raise SystemExit(1)


def wait_for(client, report_id, timeout=45):
    deadline = time.time() + timeout
    while time.time() < deadline:
        payload = client.get(f"/research/{report_id}").json()
        if payload["status"] in ("completed", "failed"):
            return payload
        time.sleep(0.2)
    raise SystemExit("timed out waiting for job")


def run_suite():
    import tempfile

    from app.agent import ResearchAgent

    ResearchAgent.run = fake_run
    ResearchAgent.settings = get_settings()

    tmp_db = Path(tempfile.mkdtemp()) / "test.db"
    client, store, manager = build_client(tmp_db)

    print("=== core ===")
    check("GET /", client.get("/").json()["message"] == "AI Research Agent is running")
    check("GET /health", client.get("/health").json()["status"] == "ok")

    resp = client.post("/research", json={"topic": "x"})
    check("rejects short topic", resp.status_code == 422, str(resp.status_code))
    resp = client.post("/research", json={})
    check("rejects missing topic", resp.status_code == 422, str(resp.status_code))

    print("\n=== async job lifecycle ===")
    resp = client.post("/research", json={"topic": TOPIC})
    check("POST /research returns 202", resp.status_code == 202, str(resp.status_code))
    created = resp.json()
    report_id = created["id"]
    check("returns id", bool(report_id), str(created))

    check(
        "unknown id 404s",
        client.get("/research/does-not-exist").status_code == 404,
    )
    check(
        "unknown download 404s",
        client.get("/research/does-not-exist/report.pdf").status_code == 404,
    )

    done = wait_for(client, report_id)
    check("job completed", done["status"] == "completed", str(done))
    check("markdown rendered", "## Executive Summary" in (done["markdown"] or ""))
    check("citations kept", "[1]" in (done["markdown"] or ""))
    check("objective rendered", "**Objective:**" in (done["markdown"] or ""))
    check("sources appendix", "## Sources" in (done["markdown"] or ""))
    check("plan persisted", done["plan"]["queries"] == QUERIES)
    check("sections persisted", len(done["sections"]) == 1)
    check("finding kept", done["sections"][0]["findings"][0]["claim"].startswith("Gains"))
    check("conflicts kept", len(done["sections"][0]["conflicts"]) == 1)
    check("gaps kept", len(done["sections"][0]["gaps"]) == 1)
    check("cited_count", done["cited_count"] == 1)
    check("coverage", done["coverage"] == 1.0)
    check("steps recorded", len(done["steps"]) == 2)
    check("events recorded", len(done["events"]) >= 1, str(len(done["events"])))
    check("cited flag on source", done["sources"][0]["cited"] is True)

    print("\n=== SSE stream ===")
    with client.stream("GET", f"/research/{report_id}/events") as stream:
        body = "".join(chunk for chunk in stream.iter_text())
    check("stream sent progress", "event: progress" in body, body[:200])
    check("stream sent done", "event: done" in body, body[-200:])
    check("stream payload is json", '"stage"' in body)

    print("\n=== downloads ===")
    md = client.get(f"/research/{report_id}/report.md")
    check("markdown download 200", md.status_code == 200)
    check("markdown content-type", "text/markdown" in md.headers["content-type"])
    check("markdown disposition", "attachment" in md.headers["content-disposition"])
    check("markdown slug filename", "impact-of-agentic-ai" in md.headers["content-disposition"])

    pdf = client.get(f"/research/{report_id}/report.pdf")
    check("pdf download 200", pdf.status_code == 200)
    check("pdf content-type", pdf.headers["content-type"] == "application/pdf")
    check("pdf magic bytes", pdf.content[:5] == b"%PDF-")
    check("pdf non-trivial size", len(pdf.content) > 2000, str(len(pdf.content)))

    print("\n=== history + delete ===")
    listing = client.get("/reports").json()["reports"]
    check("history lists report", any(r["id"] == report_id for r in listing))
    check("history has coverage", listing[0]["coverage"] == 1.0)
    check("limit respected", len(client.get("/reports?limit=1").json()["reports"]) == 1)

    check("delete works", client.delete(f"/research/{report_id}").status_code == 200)
    check("deleted gone", client.get(f"/research/{report_id}").status_code == 404)
    check("delete unknown 404", client.delete("/nope").status_code == 404)

    print("\n=== failure path ===")
    def boom(self, topic, on_progress=None):
        raise RuntimeError("simulated provider outage")

    ResearchAgent.run = boom
    failed_id = client.post("/research", json={"topic": "Failing topic test"}).json()["id"]
    failed = wait_for(client, failed_id)
    check("failed status", failed["status"] == "failed", str(failed))
    check("error surfaced", "simulated provider outage" in (failed["error"] or ""), str(failed.get("error")))
    check(
        "download blocked while failed",
        client.get(f"/research/{failed_id}/report.pdf").status_code == 409,
    )
    with client.stream("GET", f"/research/{failed_id}/events") as stream:
        fail_body = "".join(chunk for chunk in stream.iter_text())
    check("failure streamed", "event: done" in fail_body and "failed" in fail_body)

    print("\n=== restart recovery (orphaned job) ===")
    orphan = store.create("Interrupted topic")
    store.update(orphan["id"], status="running")
    check(
        "orphan reads as running before recovery",
        client.get(f"/research/{orphan['id']}").json()["status"] == "running",
    )
    recovered = store.fail_orphaned()
    check("orphan recovered on startup", orphan["id"] in recovered, str(recovered))
    after = client.get(f"/research/{orphan['id']}").json()
    check("orphan now failed", after["status"] == "failed", str(after["status"]))
    check("orphan error explains cause", "restart" in (after["error"] or "").lower(), str(after["error"]))
    with client.stream("GET", f"/research/{orphan['id']}/events") as stream:
        orphan_body = "".join(chunk for chunk in stream.iter_text())
    check(
        "SSE terminates for recovered orphan (no infinite hang)",
        "event: done" in orphan_body and "failed" in orphan_body,
        orphan_body[:200],
    )

    ResearchAgent.run = fake_run

    print("\nALL TESTS PASSED")


if __name__ == "__main__":
    run_suite()
