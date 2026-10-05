"use client";

import { useCallback, useEffect, useState } from "react";

import { fetchReports, deleteReport } from "@/lib/api";
import type { ReportSummary } from "@/lib/types";

const STATUS_STYLES: Record<string, string> = {
  completed: "bg-success/15 text-success",
  running: "bg-accent/15 text-accent",
  queued: "bg-[#1b2439] text-muted",
  failed: "bg-danger/15 text-danger",
};

export function HistoryList({
  activeId,
  onSelect,
}: {
  activeId?: string;
  onSelect?: (id: string) => void;
}) {
  const [reports, setReports] = useState<ReportSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    try {
      const data = await fetchReports(12);
      setReports(data);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not load history");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    let cancelled = false;

    const poll = async () => {
      try {
        const data = await fetchReports(12);
        if (cancelled) return;
        setReports(data);
        setError(null);
      } catch (err) {
        if (cancelled) return;
        setError(err instanceof Error ? err.message : "Could not load history");
      } finally {
        if (!cancelled) setLoading(false);
      }
    };

    void poll();
    const timer = setInterval(() => void poll(), 5000);
    return () => {
      cancelled = true;
      clearInterval(timer);
    };
  }, []);

  async function remove(id: string, event: React.MouseEvent) {
    event.stopPropagation();
    try {
      await deleteReport(id);
      setReports((current) => current.filter((report) => report.id !== id));
    } catch {
      await refresh();
    }
  }

  return (
    <section className="rounded-2xl border border-border-subtle bg-surface/80 p-5 backdrop-blur">
      <header className="mb-4 flex items-center justify-between gap-3">
        <h2 className="text-sm font-semibold tracking-wide text-foreground uppercase">
          Recent reports
        </h2>
        <button
          type="button"
          onClick={() => void refresh()}
          className="rounded-lg border border-border-subtle px-2 py-1 text-[11px] text-muted transition hover:border-accent/50 hover:text-foreground"
        >
          Refresh
        </button>
      </header>

      {loading && <p className="text-sm text-muted">Loading history…</p>}
      {error && (
        <p className="rounded-lg border border-danger/30 bg-danger/10 p-3 text-xs text-danger">
          {error}
        </p>
      )}

      {!loading && !error && reports.length === 0 && (
        <p className="text-sm text-muted">No reports yet. Run your first research above.</p>
      )}

      <ul className="space-y-2">
        {reports.map((report) => (
          <li key={report.id}>
            <div
              role="button"
              tabIndex={0}
              onClick={() => onSelect?.(report.id)}
              onKeyDown={(event) => {
                if (event.key === "Enter" || event.key === " ") {
                  event.preventDefault();
                  onSelect?.(report.id);
                }
              }}
              className={`group flex cursor-pointer items-start justify-between gap-3 rounded-xl border p-3 transition ${
                report.id === activeId
                  ? "border-accent/60 bg-accent/10"
                  : "border-border-subtle bg-surface-raised/50 hover:border-accent/40"
              }`}
            >
              <div className="min-w-0 flex-1">
                <p className="truncate text-sm font-medium text-foreground">{report.topic}</p>
                <div className="mt-1.5 flex flex-wrap items-center gap-2 font-mono text-[10px] text-muted">
                  <span
                    className={`rounded px-1.5 py-0.5 ${
                      STATUS_STYLES[report.status] ?? STATUS_STYLES.queued
                    }`}
                  >
                    {report.status}
                  </span>
                  {report.status === "completed" && (
                    <span>
                      {report.cited_count}/{report.source_count} cited ·{" "}
                      {Math.round((report.coverage ?? 0) * 100)}%
                    </span>
                  )}
                  {report.created_at && <span>{report.created_at.slice(0, 16).replace("T", " ")}</span>}
                </div>
              </div>
              <button
                type="button"
                aria-label="Delete report"
                onClick={(event) => void remove(report.id, event)}
                className="rounded-md p-1 text-muted opacity-0 transition group-hover:opacity-100 hover:text-danger focus:opacity-100"
              >
                <svg viewBox="0 0 16 16" className="h-3.5 w-3.5 fill-current">
                  <path d="M6 2h4l.5 1.5H13V5H3V3.5h2.5L6 2zM4 6h8l-.6 8H4.6L4 6z" />
                </svg>
              </button>
            </div>
          </li>
        ))}
      </ul>
    </section>
  );
}
