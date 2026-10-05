"use client";

import { useMemo, useState } from "react";
import ReactMarkdown, { type Components } from "react-markdown";
import remarkGfm from "remark-gfm";

import type { Source } from "@/lib/types";

const CITATION_PATTERN = /\[(\d{1,3})\]/g;

function escapeLabel(text: string): string {
  return text.replace(/[[\]]/g, "");
}

export function linkifyCitations(markdown: string, sources: Source[]): string {
  const known = new Map(sources.map((source) => [source.index, source.url]));
  return markdown.replace(CITATION_PATTERN, (match, raw) => {
    const index = Number(raw);
    if (!known.has(index)) return match;
    return `[${escapeLabel(raw)}](#source-${index})`;
  });
}

export function ReportMarkdown({
  markdown,
  sources,
}: {
  markdown: string;
  sources: Source[];
}) {
  const prepared = useMemo(() => linkifyCitations(markdown, sources), [markdown, sources]);

  const components: Components = useMemo(
    () => ({
      a({ href, children, ...rest }) {
        const target = href ?? "";
        if (target.startsWith("#source-")) {
          const index = target.replace("#source-", "");
          return (
            <a
              href={target}
              className="citation"
              title={`Jump to source ${index}`}
              onClick={(event) => {
                event.preventDefault();
                const element = document.getElementById(target.slice(1));
                element?.scrollIntoView({ behavior: "smooth", block: "center" });
                element?.animate(
                  [
                    { backgroundColor: "rgba(79,140,255,0.28)" },
                    { backgroundColor: "rgba(13,20,36,1)" },
                  ],
                  { duration: 1100, easing: "ease-out" }
                );
              }}
            >
              {index}
            </a>
          );
        }
        return (
          <a href={target} target="_blank" rel="noreferrer noopener" {...rest}>
            {children}
          </a>
        );
      },
      h1({ children }) {
        return <h1>{children}</h1>;
      },
      h2({ children }) {
        return <h2>{children}</h2>;
      },
      h3({ children }) {
        return <h3>{children}</h3>;
      },
      p({ children }) {
        return <p>{children}</p>;
      },
      ul({ children }) {
        return <ul>{children}</ul>;
      },
      ol({ children }) {
        return <ol>{children}</ol>;
      },
      li({ children }) {
        return <li>{children}</li>;
      },
    }),
    []
  );

  return (
    <div className="prose-report">
      <ReactMarkdown remarkPlugins={[remarkGfm]} components={components}>
        {prepared}
      </ReactMarkdown>
    </div>
  );
}

export function RawMarkdown({ markdown }: { markdown: string }) {
  const [copied, setCopied] = useState(false);
  return (
    <div>
      <button
        type="button"
        onClick={async () => {
          try {
            await navigator.clipboard.writeText(markdown);
            setCopied(true);
            setTimeout(() => setCopied(false), 1600);
          } catch {
            setCopied(false);
          }
        }}
        className="rounded-lg border border-border-subtle bg-surface px-3 py-1.5 text-xs font-medium text-muted transition hover:border-accent/50 hover:text-foreground"
      >
        {copied ? "Copied" : "Copy Markdown"}
      </button>
      <pre className="mt-3 max-h-[32rem] overflow-auto rounded-xl border border-border-subtle bg-[#0a1020] p-4 text-xs leading-relaxed text-[#b9c8de]">
        {markdown}
      </pre>
    </div>
  );
}
