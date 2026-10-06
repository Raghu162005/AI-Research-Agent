"use client";

import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useCallback, useEffect, useRef, useState } from "react";

import { HistoryList } from "@/components/history-list";
import { IeeePaperView } from "@/components/ieee-paper";
import { ProgressTimeline } from "@/components/progress-timeline";
import { RawMarkdown, ReportMarkdown } from "@/components/report-markdown";
import { SourcesPanel } from "@/components/sources-panel";
import { API_BASE, downloadUrls, fetchPaper, fetchReport } from "@/lib/api";
import type { IeeePaper, ProgressEvent, Report } from "@/lib/types";

type Tab = "report" | "markdown" | "analysis" | "paper";

export default function ResearchPage() {
  const params = useParams<{ id: string }>();
  const router = useRouter();
  const reportId = params.id;

  const [report, setReport] = useState<Report | null>(null);
  const [events, setEvents] = useState<ProgressEvent[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [tab, setTab] = useState<Tab>("report");
  const [paper, setPaper] = useState<IeeePaper | null>(null);
  const [paperLoading, setPaperLoading] = useState(false);
  const [paperError, setPaperError] = useState<string | null>(null);
  const sourceRef = useRef<EventSource | null>(null);

  const generatePaper = useCallback(async () => {
    setPaperLoading(true);
    setPaperError(null);
    try {
      setPaper(await fetchPaper(reportId));
    } catch (err) {
      setPaperError(
        err instanceof Error ? err.message : "Could not generate the IEEE paper."
      );
    } finally {
      setPaperLoading(false);
    }
  }, [reportId]);

  const loadReport = useCallback(async () => {
    try {
      const data = await fetchReport(reportId);
      setReport(data);
      if (data.events.length) setEvents(data.events);
      return data;
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not load this report.");
      return null;
    }
  }, [reportId]);

  useEffect(() => {
    let cancelled = false;

    (async () => {
      const initial = await loadReport();
      if (cancelled || !initial) return;
      if (initial.status === "completed" || initial.status === "failed") return;

      const stream = new EventSource(downloadUrls.events(reportId));
      sourceRef.current = stream;

      stream.addEventListener("progress", (event) => {
        const parsed = JSON.parse((event as MessageEvent).data) as ProgressEvent;
        setEvents((current) => [...current, parsed]);
      });

      stream.addEventListener("done", () => {
        stream.close();
        sourceRef.current = null;
        void loadReport();
      });

      stream.onerror = () => {
        stream.close();
        sourceRef.current = null;
        void loadReport();
      };
    })();

    return () => {
      cancelled = true;
      sourceRef.current?.close();
      sourceRef.current = null;
    };
  }, [reportId, loadReport]);

  if (error) {
    return (
      <main className="mx-auto w-full max-w-3xl flex-1 px-5 py-16">
        <div className="rounded-2xl border border-danger/35 bg-danger/10 p-6">
          <h1 className="mb-2 text-lg font-semibold text-danger">Something went wrong</h1>
          <p className="text-sm text-danger/90">{error}</p>
          <Link
            href="/"
            className="mt-5 inline-block rounded-xl bg-accent px-4 py-2 text-sm font-semibold text-[#05070f]"
          >
            Start a new research
          </Link>
        </div>
      </main>
    );
  }

  if (!report) {
    return (
      <main className="mx-auto w-full max-w-5xl flex-1 px-5 py-16">
        <div className="animate-pulse-soft space-y-4">
          <div className="h-8 w-2/3 rounded-lg bg-surface-raised" />
          <div className="h-40 w-full rounded-2xl bg-surface-raised/60" />
        </div>
      </main>
    );
  }

  const done = report.status === "completed";
  const failed = report.status === "failed";
  const busy = !done && !failed;

  const tabs: { key: Tab; label: string }[] = [
    { key: "report", label: "Report" },
    { key: "analysis", label: "Evidence" },
    ...(report.markdown ? ([{ key: "markdown", label: "Markdown" }] as const) : []),
    { key: "paper", label: "IEEE Paper" },
  ];

  return (
    <main className="mx-auto w-full max-w-6xl flex-1 px-5 py-10">
      <div className="mb-8">
        <button
          type="button"
          onClick={() => router.push("/")}
          className="mb-4 inline-flex items-center gap-1.5 font-mono text-xs text-muted transition hover:text-foreground"
        >
          <span aria-hidden>&larr;</span> New research
        </button>
        <h1 className="text-2xl leading-snug font-bold tracking-tight text-foreground sm:text-3xl">
          {report.topic}
        </h1>
        <div className="mt-3 flex flex-wrap items-center gap-2 font-mono text-[11px] text-muted">
          <span
            className={`rounded px-2 py-0.5 ${
              done
                ? "bg-success/15 text-success"
                : failed
                  ? "bg-danger/15 text-danger"
                  : "bg-accent/15 text-accent"
            }`}
          >
            {report.status}
          </span>
          {done && (
            <>
              <span className="rounded bg-[#1b2439] px-2 py-0.5">
                {report.cited_count}/{report.source_count} sources cited
              </span>
              <span className="rounded bg-[#1b2439] px-2 py-0.5">
                {Math.round(report.coverage * 100)}% coverage
              </span>
            </>
          )}
          {report.model && <span>{report.model}</span>}
          {report.duration_seconds != null && (
            <span>{Math.round(report.duration_seconds)}s elapsed</span>
          )}
          {report.id && <span>id {report.id}</span>}
        </div>
      </div>

      <div className="grid gap-6 lg:grid-cols-[1fr_360px]">
        <div className="space-y-6">
          {busy && (
            <div className="animate-rise">
              <ProgressTimeline events={events} />
            </div>
          )}

          {failed && (
            <div className="animate-rise rounded-2xl border border-danger/35 bg-danger/10 p-5">
              <h2 className="mb-1 text-sm font-semibold text-danger">Research failed</h2>
              <p className="font-mono text-xs break-words text-danger/90">{report.error}</p>
              <Link
                href="/"
                className="mt-4 inline-block rounded-xl bg-accent px-4 py-2 text-sm font-semibold text-[#05070f]"
              >
                Try again
              </Link>
            </div>
          )}

          {done && report.markdown && (
            <section className="animate-rise rounded-2xl border border-border-subtle bg-surface/80 p-6 backdrop-blur">
              <nav className="mb-5 flex gap-1 border-b border-border-subtle">
                {tabs.map((item) => (
                  <button
                    key={item.key}
                    type="button"
                    onClick={() => setTab(item.key)}
                    className={`-mb-px border-b-2 px-3.5 py-2 text-sm font-medium transition ${
                      tab === item.key
                        ? "border-accent text-foreground"
                        : "border-transparent text-muted hover:text-foreground"
                    }`}
                  >
                    {item.label}
                  </button>
                ))}
                <div className="ml-auto flex items-center gap-2 pb-1.5">
                  <a
                    href={downloadUrls.markdown(reportId)}
                    className="rounded-lg border border-border-subtle px-3 py-1.5 text-xs font-medium text-muted transition hover:border-accent/50 hover:text-foreground"
                  >
                    .md
                  </a>
                  <a
                    href={downloadUrls.pdf(reportId)}
                    className="rounded-lg bg-accent px-3 py-1.5 text-xs font-semibold text-[#05070f] transition hover:bg-[#6ba0ff]"
                  >
                    .pdf
                  </a>
                </div>
              </nav>

              {tab === "report" && (
                <ReportMarkdown markdown={report.markdown} sources={report.sources} />
              )}
              {tab === "markdown" && <RawMarkdown markdown={report.markdown} />}
              {tab === "analysis" && <EvidenceView report={report} />}
              {tab === "paper" && (
                <div>
                  {paperLoading ? (
                    <div className="animate-pulse-soft space-y-3">
                      <div className="mx-auto h-6 w-2/3 rounded bg-surface-raised" />
                      <div className="h-24 w-full rounded-xl bg-surface-raised/60" />
                      <div className="h-40 w-full rounded-xl bg-surface-raised/40" />
                      <p className="text-center font-mono text-[11px] text-muted">
                        Generating IEEE-style paper...
                      </p>
                    </div>
                  ) : paper ? (
                    <div>
                      <div className="mb-4 flex flex-wrap items-center justify-end gap-2">
                        <span className="mr-auto font-mono text-[10px] tracking-wide text-muted uppercase">
                          {paper.cited_count} references from {paper.source_count} retrieved
                          sources
                        </span>
                        <button
                          type="button"
                          onClick={generatePaper}
                          className="rounded-lg border border-border-subtle px-3 py-1.5 text-xs font-medium text-muted transition hover:border-accent/50 hover:text-foreground"
                        >
                          Regenerate
                        </button>
                        <a
                          href={downloadUrls.paperMarkdown(reportId)}
                          className="rounded-lg border border-border-subtle px-3 py-1.5 text-xs font-medium text-muted transition hover:border-accent/50 hover:text-foreground"
                        >
                          .md
                        </a>
                        <a
                          href={downloadUrls.paperPdf(reportId)}
                          className="rounded-lg bg-accent px-3 py-1.5 text-xs font-semibold text-[#05070f] transition hover:bg-[#6ba0ff]"
                        >
                          .pdf
                        </a>
                      </div>
                      {paperError && (
                        <p className="mb-3 rounded-lg border border-danger/35 bg-danger/10 px-3 py-2 text-xs text-danger">
                          {paperError}
                        </p>
                      )}
                      <IeeePaperView paper={paper} sources={report.sources} />
                    </div>
                  ) : (
                    <div className="rounded-xl border border-border-subtle bg-[#0a1020] p-6 text-center">
                      <p className="text-sm leading-relaxed text-muted">
                        Restructure this completed report into an IEEE-style paper: abstract,
                        index terms, six numbered sections, and references drawn only from
                        sources the agent actually retrieved.
                      </p>
                      <button
                        type="button"
                        onClick={generatePaper}
                        className="mt-4 rounded-xl bg-accent px-5 py-2.5 text-sm font-semibold text-[#05070f] transition hover:bg-[#6ba0ff]"
                      >
                        Generate IEEE Research Paper
                      </button>
                      {paperError && (
                        <p className="mt-3 text-xs text-danger">{paperError}</p>
                      )}
                    </div>
                  )}
                </div>
              )}
            </section>
          )}
        </div>

        <aside className="space-y-6">
          {done && <SourcesPanel sources={report.sources} />}
          {done && report.plan && <PlanView plan={report.plan} />}
          <HistoryList activeId={reportId} onSelect={(id) => router.push(`/research/${id}`)} />
          <p className="px-1 font-mono text-[10px] text-muted">
            backend {API_BASE}
          </p>
        </aside>
      </div>
    </main>
  );
}

function PlanView({ plan }: { plan: NonNullable<Report["plan"]> }) {
  return (
    <section className="rounded-2xl border border-border-subtle bg-surface/80 p-5 backdrop-blur">
      <h2 className="mb-3 text-sm font-semibold tracking-wide text-foreground uppercase">
        Research plan
      </h2>
      <p className="mb-4 text-xs leading-relaxed text-muted">{plan.objective}</p>

      <p className="mb-1.5 font-mono text-[10px] tracking-wide text-muted uppercase">
        Subtopics
      </p>
      <ul className="mb-4 space-y-1.5">
        {plan.subtopics.map((subtopic, index) => (
          <li key={subtopic.title} className="flex gap-2 text-xs">
            <span className="font-mono text-muted">{index + 1}.</span>
            <span className="text-[#c3d0e4]">
              <span className="font-medium text-foreground">{subtopic.title}</span>
              <span className="block text-muted">{subtopic.focus}</span>
            </span>
          </li>
        ))}
      </ul>

      <p className="mb-1.5 font-mono text-[10px] tracking-wide text-muted uppercase">
        Search queries
      </p>
      <ul className="space-y-1">
        {plan.queries.map((query) => (
          <li
            key={query}
            className="rounded-md bg-[#0a1020] px-2 py-1 font-mono text-[10px] break-all text-[#9fb3ce]"
          >
            {query}
          </li>
        ))}
      </ul>
    </section>
  );
}

function EvidenceView({ report }: { report: Report }) {
  if (report.sections.length === 0) {
    return <p className="text-sm text-muted">No analysis recorded.</p>;
  }

  return (
    <div className="space-y-6">
      {report.sections.map((section) => (
        <article key={section.title} className="border-b border-border-subtle pb-5 last:border-0">
          <h3 className="mb-1 text-sm font-semibold text-foreground">{section.title}</h3>
          <p className="mb-2 font-mono text-[11px] text-muted">Focus: {section.focus}</p>
          <p className="mb-3 text-[13px] leading-relaxed text-[#c3d0e4]">{section.summary}</p>

          {section.findings.length > 0 && (
            <div className="mb-3">
              <p className="mb-1.5 font-mono text-[10px] tracking-wide text-muted uppercase">
                Findings
              </p>
              <ul className="space-y-2">
                {section.findings.map((finding, index) => (
                  <li key={index} className="rounded-lg bg-surface-raised/60 p-3">
                    <p className="text-[13px] leading-snug text-foreground">{finding.claim}</p>
                    {finding.evidence && (
                      <p className="mt-1 text-xs leading-relaxed text-muted">{finding.evidence}</p>
                    )}
                    {finding.source_indexes.length > 0 && (
                      <div className="mt-1.5 flex flex-wrap gap-1">
                        {finding.source_indexes.map((index) => (
                          <a
                            key={index}
                            href={`#source-${index}`}
                            onClick={(event) => {
                              event.preventDefault();
                              document
                                .getElementById(`source-${index}`)
                                ?.scrollIntoView({ behavior: "smooth", block: "center" });
                            }}
                            className="citation"
                          >
                            {index}
                          </a>
                        ))}
                      </div>
                    )}
                  </li>
                ))}
              </ul>
            </div>
          )}

          {section.conflicts.length > 0 && (
            <div className="mb-3">
              <p className="mb-1.5 font-mono text-[10px] tracking-wide text-warning uppercase">
                Source conflicts
              </p>
              <ul className="space-y-1">
                {section.conflicts.map((item, index) => (
                  <li key={index} className="text-xs leading-relaxed text-[#c3d0e4]">
                    &bull; {item}
                  </li>
                ))}
              </ul>
            </div>
          )}

          {section.gaps.length > 0 && (
            <div>
              <p className="mb-1.5 font-mono text-[10px] tracking-wide text-muted uppercase">
                Evidence gaps
              </p>
              <ul className="space-y-1">
                {section.gaps.map((item, index) => (
                  <li key={index} className="text-xs leading-relaxed text-muted">
                    &bull; {item}
                  </li>
                ))}
              </ul>
            </div>
          )}
        </article>
      ))}
    </div>
  );
}
