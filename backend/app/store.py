import json
import sqlite3
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path

DB_PATH = Path(__file__).resolve().parent.parent / "data" / "reports.db"

STATUS_QUEUED = "queued"
STATUS_RUNNING = "running"
STATUS_COMPLETED = "completed"
STATUS_FAILED = "failed"

_JSON_FIELDS = ("steps", "sources", "sections", "plan")
_COLUMNS = (
    "id",
    "topic",
    "status",
    "objective",
    "markdown",
    "steps",
    "sources",
    "sections",
    "plan",
    "coverage",
    "cited_count",
    "source_count",
    "model",
    "error",
    "created_at",
    "updated_at",
    "duration_seconds",
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class ReportStore:
    def __init__(self, path: Path | None = None) -> None:
        self._path = path or DB_PATH
        self._lock = threading.Lock()
        if str(self._path) != ":memory:":
            self._path.parent.mkdir(parents=True, exist_ok=True)
        self.initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self._path, check_same_thread=False)
        connection.row_factory = sqlite3.Row
        return connection

    def initialize(self) -> None:
        with self._lock, self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS reports (
                    id TEXT PRIMARY KEY,
                    topic TEXT NOT NULL,
                    status TEXT NOT NULL,
                    objective TEXT,
                    markdown TEXT,
                    steps TEXT,
                    sources TEXT,
                    sections TEXT,
                    plan TEXT,
                    coverage REAL,
                    cited_count INTEGER,
                    source_count INTEGER,
                    model TEXT,
                    error TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    duration_seconds REAL
                )
                """
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_reports_created ON reports(created_at DESC)"
            )

    def create(self, topic: str) -> dict:
        record = {
            "id": uuid.uuid4().hex[:12],
            "topic": topic,
            "status": STATUS_QUEUED,
            "created_at": _now(),
            "updated_at": _now(),
        }
        with self._lock, self._connect() as connection:
            connection.execute(
                "INSERT INTO reports (id, topic, status, created_at, updated_at) "
                "VALUES (:id, :topic, :status, :created_at, :updated_at)",
                record,
            )
        return self.get(record["id"]) or {}

    def get(self, report_id: str) -> dict | None:
        with self._lock, self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM reports WHERE id = ?", (report_id,)
            ).fetchone()
        return _hydrate(row) if row else None

    def list_reports(self, limit: int = 50) -> list[dict]:
        with self._lock, self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM reports ORDER BY created_at DESC LIMIT ?", (limit,)
            ).fetchall()
        return [_hydrate(row) for row in rows]

    def update(self, report_id: str, **fields) -> dict | None:
        if not fields:
            return self.get(report_id)

        assignments = []
        values: dict = {}
        for key, value in fields.items():
            if key in _JSON_FIELDS:
                value = json.dumps(value, default=str)
            assignments.append(f"{key} = :{key}")
            values[key] = value

        assignments.append("updated_at = :updated_at")
        values["updated_at"] = _now()
        values["id"] = report_id

        with self._lock, self._connect() as connection:
            connection.execute(
                f"UPDATE reports SET {', '.join(assignments)} WHERE id = :id", values
            )
        return self.get(report_id)

    def delete(self, report_id: str) -> bool:
        with self._lock, self._connect() as connection:
            cursor = connection.execute("DELETE FROM reports WHERE id = ?", (report_id,))
            return cursor.rowcount > 0

    def fail_orphaned(self, reason: str | None = None) -> list[str]:
        """Mark unfinished jobs as failed.

        Job state lives in memory, so a restart leaves rows stuck in
        queued/running forever. Without this the SSE stream never reaches a
        terminal event and the dashboard spins indefinitely.
        """
        message = reason or "Server restarted while this research was still in progress."
        with self._lock, self._connect() as connection:
            rows = connection.execute(
                "SELECT id FROM reports WHERE status IN (?, ?)",
                (STATUS_QUEUED, STATUS_RUNNING),
            ).fetchall()
            connection.execute(
                "UPDATE reports SET status = ?, error = ?, updated_at = ? "
                "WHERE status IN (?, ?)",
                (STATUS_FAILED, message, _now(), STATUS_QUEUED, STATUS_RUNNING),
            )
        return [row["id"] for row in rows]

    def summarize_all(self, limit: int = 50) -> list[dict]:
        """Return lightweight summaries without fetching full report bodies."""
        with self._lock, self._connect() as connection:
            rows = connection.execute(
                f"SELECT {_SUMMARY_COLUMNS} FROM reports "
                "ORDER BY created_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [_summary(row) for row in rows]

    def summary(self, report_id: str) -> dict:
        with self._lock, self._connect() as connection:
            row = connection.execute(
                f"SELECT {_SUMMARY_COLUMNS} FROM reports WHERE id = ?", (report_id,)
            ).fetchone()
        return _summary(row) if row else {}


_SUMMARY_FIELDS = (
    "id",
    "topic",
    "status",
    "coverage",
    "cited_count",
    "source_count",
    "model",
    "error",
    "created_at",
    "duration_seconds",
)
_SUMMARY_COLUMNS = ", ".join(_SUMMARY_FIELDS)


def _summary(row: sqlite3.Row) -> dict:
    return {key: row[key] for key in _SUMMARY_FIELDS if key in row.keys()}


def _hydrate(row: sqlite3.Row) -> dict:
    record = {key: row[key] for key in _COLUMNS if key in row.keys()}
    for field in _JSON_FIELDS:
        raw = record.get(field)
        if isinstance(raw, str):
            try:
                record[field] = json.loads(raw)
            except json.JSONDecodeError:
                record[field] = []
        elif raw is None:
            record[field] = []
    return record


_store: ReportStore | None = None


def get_store() -> ReportStore:
    global _store
    if _store is None:
        _store = ReportStore()
    return _store
