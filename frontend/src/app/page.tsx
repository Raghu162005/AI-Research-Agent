"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";

import { HistoryList } from "@/components/history-list";
import { startResearch } from "@/lib/api";

const EXAMPLES = [
  "Impact of agentic AI on software engineering productivity",
  "Retrieval-augmented generation for enterprise search",
  "Why SQLite is winning against distributed databases",
  "Current state of solid-state battery commercialization",
];

export default function HomePage() {
  const router = useRouter();
  const [topic, setTopic] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    const trimmed = topic.trim();
    if (trimmed.length < 3) {
      setError("Enter a research topic of at least 3 characters.");
      return;
    }

    setSubmitting(true);
    setError(null);
    try {
      const job = await startResearch(trimmed);
      router.push(`/research/${job.id}`);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not start research.");
      setSubmitting(false);
    }
  }

  return (
    <main className="mx-auto w-full max-w-5xl flex-1 px-5 py-12 sm:py-16">
      <section className="mb-12">
        <div className="mb-4 inline-flex items-center gap-2 rounded-full border border-border-subtle bg-surface/70 px-3 py-1 font-mono text-[11px] text-muted">
          <span className="h-1.5 w-1.5 rounded-full bg-success" />
          planner · web search · analyser · report writer
        </div>
        <h1 className="mb-3 text-4xl leading-tight font-bold tracking-tight text-foreground sm:text-5xl">
          AI Research Agent
        </h1>
        <p className="max-w-2xl text-[15px] leading-relaxed text-muted">
          Give it a topic. It plans the research, searches the live web, reads every source
          critically, and writes a structured report where every factual claim carries a citation
          you can verify.
        </p>
      </section>

      <div className="grid gap-6 lg:grid-cols-[1.35fr_1fr]">
        <section className="rounded-2xl border border-border-subtle bg-surface/80 p-6 backdrop-blur">
          <form onSubmit={submit}>
            <label
              htmlFor="topic"
              className="mb-2 block text-xs font-medium tracking-wide text-muted uppercase"
            >
              Research topic
            </label>
            <textarea
              id="topic"
              value={topic}
              onChange={(event) => setTopic(event.target.value)}
              rows={3}
              maxLength={300}
              placeholder="e.g. Impact of agentic AI on software development productivity"
              className="w-full resize-none rounded-xl border border-border-subtle bg-[#0a1020] px-4 py-3 text-[15px] text-foreground outline-none transition placeholder:text-[#4d5f7d] focus:border-accent"
            />

            <div className="mt-2 flex items-center justify-between font-mono text-[11px] text-muted">
              <span>{error ? <span className="text-danger">{error}</span> : "Takes 2-4 minutes"}</span>
              <span>{topic.length}/300</span>
            </div>

            <button
              type="submit"
              disabled={submitting}
              className="mt-4 w-full rounded-xl bg-accent px-5 py-3 text-sm font-semibold text-[#05070f] transition hover:bg-[#6ba0ff] disabled:cursor-not-allowed disabled:opacity-50"
            >
              {submitting ? "Starting research…" : "Start research"}
            </button>
          </form>

          <div className="mt-6 border-t border-border-subtle pt-5">
            <p className="mb-2.5 text-xs font-medium tracking-wide text-muted uppercase">
              Try one
            </p>
            <div className="flex flex-wrap gap-2">
              {EXAMPLES.map((example) => (
                <button
                  key={example}
                  type="button"
                  onClick={() => setTopic(example)}
                  className="rounded-lg border border-border-subtle bg-surface-raised/60 px-3 py-1.5 text-xs text-muted transition hover:border-accent/50 hover:text-foreground"
                >
                  {example.length > 44 ? `${example.slice(0, 44)}…` : example}
                </button>
              ))}
            </div>
          </div>
        </section>

        <HistoryList onSelect={(id) => router.push(`/research/${id}`)} />
      </div>
    </main>
  );
}
