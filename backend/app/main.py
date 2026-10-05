import asyncio
import json
import logging
import re
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response, StreamingResponse

from app.config import ConfigError, get_settings
from app.jobs import get_job_manager
from app.pdf import render_pdf
from app.schemas import (
    HealthResponse,
    ReportList,
    ReportSummary,
    ResearchCreated,
    ResearchRequest,
    ResearchResponse,
)
from app.store import STATUS_COMPLETED, get_store

logger = logging.getLogger("research_agent")

@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    store = get_store()
    orphaned = store.fail_orphaned()
    if orphaned:
        logger.warning(
            "Marked %s interrupted job(s) as failed: %s", len(orphaned), ", ".join(orphaned)
        )
    logger.info("AI Research Agent ready")
    yield


app = FastAPI(
    title="AI Research Agent",
    version="1.0.0",
    description=(
        "Autonomous agent that plans, searches, analyses and reports on any topic. "
        "Runs asynchronously with live progress streaming over SSE."
    ),
    lifespan=lifespan,
)


def _cors_origins() -> list[str]:
    try:
        return list(get_settings().cors_origins)
    except ConfigError:
        return ["http://localhost:3000", "http://127.0.0.1:3000"]


app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins(),
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/")
def home():
    return {
        "message": "AI Research Agent is running",
        "docs": "/docs",
        "endpoints": [
            "POST /research",
            "GET /research/{id}",
            "GET /research/{id}/events",
            "GET /research/{id}/report.md",
            "GET /research/{id}/report.pdf",
            "GET /reports",
        ],
    }


@app.get("/health", response_model=HealthResponse)
def health():
    try:
        settings = get_settings()
    except ConfigError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return HealthResponse(status="ok", llm_model=settings.groq_model)


@app.post("/research", response_model=ResearchCreated, status_code=202)
def create_research(request: ResearchRequest) -> ResearchCreated:
    topic = request.topic.strip()
    if len(topic) < 3:
        raise HTTPException(status_code=422, detail="Topic must be at least 3 characters.")

    try:
        job = get_job_manager().submit(topic)
    except ConfigError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("Failed to submit research job")
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    record = get_store().summary(job.id)
    return ResearchCreated(
        id=job.id,
        topic=topic,
        status=job.status,
        created_at=record.get("created_at"),
    )


@app.get("/research/{report_id}", response_model=ResearchResponse)
def get_research(report_id: str) -> ResearchResponse:
    store = get_store()
    record = store.get(report_id)
    if record is None:
        raise HTTPException(status_code=404, detail=f"No report with id '{report_id}'.")

    job = get_job_manager().get(report_id)
    events, _ = job.snapshot() if job else ([], False)

    return ResearchResponse(
        id=record["id"],
        topic=record["topic"],
        status=record["status"],
        objective=record.get("objective"),
        markdown=record.get("markdown"),
        plan=record.get("plan") or None,
        sections=record.get("sections") or [],
        sources=record.get("sources") or [],
        steps=record.get("steps") or [],
        events=events,
        cited_count=record.get("cited_count") or 0,
        source_count=record.get("source_count") or 0,
        coverage=record.get("coverage") or 0.0,
        model=record.get("model"),
        error=record.get("error"),
        duration_seconds=record.get("duration_seconds"),
        created_at=record.get("created_at"),
    )


@app.get("/research/{report_id}/events")
async def stream_events(report_id: str, request: Request) -> StreamingResponse:
    store = get_store()
    record = store.get(report_id)
    if record is None:
        raise HTTPException(status_code=404, detail=f"No report with id '{report_id}'.")

    async def event_stream():
        cursor = 0
        idle_ticks = 0
        while True:
            if await request.is_disconnected():
                break

            job = get_job_manager().get(report_id)
            events: list[dict] = []

            if job is not None:
                new_events, terminal = job.snapshot(cursor)
                cursor += len(new_events)
                events = new_events
            else:
                terminal = record["status"] in ("completed", "failed")

            for event in events:
                yield f"event: progress\ndata: {json.dumps(event)}\n\n"

            if terminal and not events:
                status = job.status if job else record["status"]
                yield f"event: done\ndata: {json.dumps({'id': report_id, 'status': status, 'error': record.get('error')})}\n\n"
                break

            if events:
                idle_ticks = 0
            else:
                idle_ticks += 1
                if idle_ticks % 20 == 0:
                    yield ": keep-alive\n\n"

            await asyncio.sleep(0.25)

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@app.get("/research/{report_id}/report.md")
def download_markdown(report_id: str) -> Response:
    record = _completed_report(report_id)
    filename = f"{_slug(record['topic'])}.md"
    return Response(
        content=record["markdown"],
        media_type="text/markdown; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@app.get("/research/{report_id}/report.pdf")
def download_pdf(report_id: str) -> Response:
    record = _completed_report(report_id)
    sources = {
        int(source["index"]): source["url"]
        for source in record.get("sources") or []
        if source.get("index") and source.get("url")
    }
    pdf_bytes = render_pdf(record["markdown"], sources)
    filename = f"{_slug(record['topic'])}.pdf"
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@app.get("/reports", response_model=ReportList)
def list_reports(limit: int = 50) -> ReportList:
    summaries = get_store().summarize_all(limit=limit)
    return ReportList(reports=[ReportSummary(**summary) for summary in summaries])


@app.delete("/research/{report_id}")
def delete_research(report_id: str) -> dict:
    if not get_store().delete(report_id):
        raise HTTPException(status_code=404, detail=f"No report with id '{report_id}'.")
    return {"deleted": report_id}


def _completed_report(report_id: str) -> dict:
    record = get_store().get(report_id)
    if record is None:
        raise HTTPException(status_code=404, detail=f"No report with id '{report_id}'.")
    if record["status"] != STATUS_COMPLETED or not record.get("markdown"):
        raise HTTPException(
            status_code=409,
            detail=f"Report is '{record['status']}', not ready for download.",
        )
    return record


def _slug(topic: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", topic).strip("-").lower()
    return (slug or "research-report")[:60]
