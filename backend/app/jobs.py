import threading
import time
from concurrent.futures import ThreadPoolExecutor

from app.agent import ProgressEvent, ResearchAgent
from app.config import get_settings
from app.store import (
    STATUS_COMPLETED,
    STATUS_FAILED,
    STATUS_QUEUED,
    STATUS_RUNNING,
    get_store,
)


class Job:
    def __init__(self, job_id: str, topic: str) -> None:
        self.id = job_id
        self.topic = topic
        self.status = STATUS_QUEUED
        self.events: list[ProgressEvent] = []
        self.error: str | None = None
        self.started_at: float | None = None
        self.finished_at: float | None = None
        self._lock = threading.Lock()

    def append(self, event: ProgressEvent) -> None:
        with self._lock:
            self.events.append(event)

    def snapshot(self, since: int = 0) -> tuple[list[dict], bool]:
        with self._lock:
            events = [event.to_dict() for event in self.events[since:]]
            terminal = self.status in (STATUS_COMPLETED, STATUS_FAILED)
        return events, terminal

    @property
    def duration_seconds(self) -> float | None:
        if self.started_at is None:
            return None
        end = self.finished_at if self.finished_at is not None else time.monotonic()
        return round(end - self.started_at, 2)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "topic": self.topic,
            "status": self.status,
            "error": self.error,
            "duration_seconds": self.duration_seconds,
            "event_count": len(self.events),
        }


class JobManager:
    def __init__(self, max_workers: int | None = None) -> None:
        settings = get_settings()
        self._store = get_store()
        self._executor = ThreadPoolExecutor(
            max_workers=max_workers or settings.max_concurrent_jobs,
            thread_name_prefix="research-job",
        )
        self._jobs: dict[str, Job] = {}
        self._lock = threading.Lock()

    def submit(self, topic: str) -> Job:
        record = self._store.create(topic)
        job = Job(record["id"], topic)
        with self._lock:
            self._jobs[job.id] = job
        self._executor.submit(self._run, job)
        return job

    def get(self, job_id: str) -> Job | None:
        with self._lock:
            return self._jobs.get(job_id)

    def _run(self, job: Job) -> None:
        job.status = STATUS_RUNNING
        job.started_at = time.monotonic()
        self._store.update(job.id, status=STATUS_RUNNING)

        try:
            agent = ResearchAgent()
            report = agent.run(job.topic, on_progress=job.append)
        except Exception as exc:
            job.status = STATUS_FAILED
            job.error = f"{type(exc).__name__}: {exc}"
            job.finished_at = time.monotonic()
            job.append(
                ProgressEvent("done", STATUS_FAILED, job.error, 100, {"error": job.error})
            )
            self._store.update(
                job.id,
                status=STATUS_FAILED,
                error=job.error,
                duration_seconds=job.duration_seconds,
            )
            return

        job.status = STATUS_COMPLETED
        job.finished_at = time.monotonic()

        cited = len(report.cited_indexes)
        total = len(report.sources)
        self._store.update(
            job.id,
            status=STATUS_COMPLETED,
            objective=report.objective,
            markdown=report.markdown,
            steps=report.steps,
            sources=[
                {**source.to_dict(), "cited": source.index in set(report.cited_indexes)}
                for source in report.sources
            ],
            sections=[analysis.to_dict() for analysis in report.analyses],
            plan=report.plan.to_dict(),
            coverage=round(cited / total, 3) if total else 0.0,
            cited_count=cited,
            source_count=total,
            model=report.model,
            duration_seconds=job.duration_seconds,
        )


_manager: JobManager | None = None


def get_job_manager() -> JobManager:
    global _manager
    if _manager is None:
        _manager = JobManager()
    return _manager
