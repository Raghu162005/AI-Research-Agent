"use client";

import { STAGE_LABELS, type ProgressEvent } from "@/lib/types";

const STAGE_ORDER = ["plan", "search", "analyze", "write", "done"];

function stageState(
  stage: string,
  currentStage: string,
  status: string
): "done" | "active" | "pending" {
  const stageIndex = STAGE_ORDER.indexOf(stage);
  const currentIndex = STAGE_ORDER.indexOf(currentStage);
  if (stageIndex < 0) return "pending";
  if (status === "failed" && stage === currentStage) return "active";
  if (stageIndex < currentIndex) return "done";
  if (stageIndex === currentIndex) return "active";
  return "pending";
}

export function ProgressTimeline({ events }: { events: ProgressEvent[] }) {
  const latest = events.length ? events[events.length - 1] : null;
  const percent = latest?.percent ?? 0;
  const failed = latest?.status === "failed";
  const currentStage = latest?.stage ?? "plan";

  const seenQueries = new Set<string>();
  for (const event of events) {
    const query = event.detail?.query;
    if (typeof query === "string") seenQueries.add(query);
  }

  return (
    <div className="rounded-2xl border border-border-subtle bg-surface/80 p-5 backdrop-blur">
      <div className="mb-5 flex items-baseline justify-between gap-4">
        <h2 className="text-sm font-semibold tracking-wide text-foreground uppercase">
          {failed ? "Research failed" : "Research in progress"}
        </h2>
        <span className="font-mono text-xs text-muted tabular-nums">{percent}%</span>
      </div>

      <div className="mb-6 h-1.5 w-full overflow-hidden rounded-full bg-[#16203a]">
        <div
          className={`h-full rounded-full transition-all duration-500 ${
            failed ? "bg-danger" : "bg-gradient-to-r from-accent to-success"
          }`}
          style={{ width: `${Math.max(percent, 3)}%` }}
        />
      </div>

      <ol className="space-y-3">
        {STAGE_ORDER.filter((stage) => stage !== "done").map((stage) => {
          const state = stageState(stage, currentStage, latest?.status ?? "running");
          const stageEvents = events.filter((event) => event.stage === stage);
          const lastMessage = stageEvents[stageEvents.length - 1]?.message;
          const subtopics = stageEvents.flatMap((event) => {
            const section = event.detail?.section;
            return typeof section === "string" ? [section] : [];
          });

          return (
            <li key={stage} className="flex gap-3">
              <div className="flex flex-col items-center pt-1">
                <span
                  className={`flex h-4 w-4 shrink-0 items-center justify-center rounded-full border-2 ${
                    state === "done"
                      ? "border-success bg-success"
                      : state === "active"
                        ? "animate-pulse-soft border-accent bg-accent/30"
                        : "border-border-subtle bg-transparent"
                  }`}
                >
                  {state === "done" && (
                    <svg viewBox="0 0 12 12" className="h-2.5 w-2.5 fill-none stroke-[#070b14] stroke-[2]">
                      <path d="M2.5 6.3l2.4 2.4L9.5 4" strokeLinecap="round" strokeLinejoin="round" />
                    </svg>
                  )}
                </span>
                <span className="mt-1 w-px flex-1 bg-border-subtle" />
              </div>

              <div className="min-w-0 flex-1 pb-1">
                <div className="flex items-center gap-2">
                  <span
                    className={`text-sm font-medium ${
                      state === "pending" ? "text-muted" : "text-foreground"
                    }`}
                  >
                    {STAGE_LABELS[stage]}
                  </span>
                  {stage === "search" && seenQueries.size > 0 && (
                    <span className="font-mono text-[10px] text-muted">
                      {seenQueries.size} queries
                    </span>
                  )}
                  {stage === "analyze" && subtopics.length > 0 && (
                    <span className="font-mono text-[10px] text-muted">
                      {subtopics.length} subtopics
                    </span>
                  )}
                </div>

                {state === "active" && lastMessage && (
                  <p className="mt-0.5 truncate text-xs text-accent">{lastMessage}</p>
                )}
                {state === "done" && lastMessage && (
                  <p className="mt-0.5 text-xs text-muted">{lastMessage}</p>
                )}
              </div>
            </li>
          );
        })}
      </ol>

      {failed && latest?.message && (
        <div className="mt-5 rounded-xl border border-danger/35 bg-danger/10 p-3 text-xs text-danger">
          {latest.message}
        </div>
      )}

      {events.length > 0 && (
        <details className="mt-5">
          <summary className="cursor-pointer text-xs text-muted transition hover:text-foreground">
            Raw event log ({events.length})
          </summary>
          <pre className="mt-2 max-h-56 overflow-auto rounded-lg bg-[#0a1020] p-3 text-[10px] leading-relaxed text-[#93a6c2]">
            {events.map((event) => JSON.stringify(event)).join("\n")}
          </pre>
        </details>
      )}
    </div>
  );
}
