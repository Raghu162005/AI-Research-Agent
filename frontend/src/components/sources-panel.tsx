"use client";

import type { Source } from "@/lib/types";

export function SourcesPanel({ sources }: { sources: Source[] }) {
  const cited = sources.filter((source) => source.cited);

  return (
    <section className="rounded-2xl border border-border-subtle bg-surface/80 p-5 backdrop-blur">
      <header className="mb-4 flex items-baseline justify-between gap-3">
        <h2 className="text-sm font-semibold tracking-wide text-foreground uppercase">Sources</h2>
        <span className="font-mono text-xs text-muted">
          {cited.length}/{sources.length} cited
        </span>
      </header>

      {sources.length === 0 ? (
        <p className="text-sm text-muted">No sources were retrieved.</p>
      ) : (
        <ol className="space-y-2.5">
          {sources.map((source) => (
            <li
              key={source.index}
              id={`source-${source.index}`}
              className="rounded-xl border border-border-subtle bg-surface-raised/60 p-3 transition hover:border-accent/40"
            >
              <div className="flex items-start gap-2.5">
                <span
                  className={`mt-0.5 flex h-5 w-5 shrink-0 items-center justify-center rounded-md font-mono text-[10px] font-semibold ${
                    source.cited
                      ? "bg-accent/20 text-[#9cc0ff]"
                      : "bg-[#1b2439] text-muted"
                  }`}
                >
                  {source.index}
                </span>
                <div className="min-w-0 flex-1">
                  <a
                    href={source.url}
                    target="_blank"
                    rel="noreferrer noopener"
                    className="block text-sm leading-snug font-medium text-foreground transition hover:text-accent"
                  >
                    {source.title}
                  </a>
                  <div className="mt-1 flex flex-wrap items-center gap-x-2 gap-y-1 font-mono text-[10px] text-muted">
                    <span className="truncate">{source.domain}</span>
                    {source.cited ? (
                      <span className="rounded bg-success/15 px-1.5 py-0.5 text-success">
                        cited
                      </span>
                    ) : (
                      <span className="rounded bg-[#1b2439] px-1.5 py-0.5 text-muted">
                        retrieved, uncited
                      </span>
                    )}
                  </div>
                </div>
              </div>
            </li>
          ))}
        </ol>
      )}
    </section>
  );
}
