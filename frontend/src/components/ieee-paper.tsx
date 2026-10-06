"use client";

import type { IeeeBlock, IeeePaper, Source } from "@/lib/types";

const CITATION_PATTERN = /\[(\d{1,3})\]/g;

function CitedText({ text, sources }: { text: string; sources: Source[] }) {
  const known = new Set(sources.map((source) => source.index));
  const parts = text.split(CITATION_PATTERN);

  return (
    <>
      {parts.map((part, position) => {
        if (position % 2 === 0) return <span key={position}>{part}</span>;
        const index = Number(part);
        if (!Number.isInteger(index) || !known.has(index)) {
          return <span key={position}>[{part}]</span>;
        }
        return (
          <a
            key={position}
            href={`#source-${index}`}
            className="citation"
            title={`Jump to source ${index}`}
            onClick={(event) => {
              event.preventDefault();
              document
                .getElementById(`source-${index}`)
                ?.scrollIntoView({ behavior: "smooth", block: "center" });
            }}
          >
            {part}
          </a>
        );
      })}
    </>
  );
}

function PaperBlock({ block, sources }: { block: IeeeBlock; sources: Source[] }) {
  if (block.kind === "list") {
    return (
      <ul className="mb-3 list-disc space-y-1 pl-5 text-[13px] leading-relaxed text-[#c3d0e4]">
        {(block.items ?? []).map((item, index) => (
          <li key={index}>
            <CitedText text={item} sources={sources} />
          </li>
        ))}
      </ul>
    );
  }

  if (block.kind === "subheading") {
    return (
      <p className="mt-3 mb-1.5 text-[13px] font-semibold italic text-foreground">
        {block.text}
      </p>
    );
  }

  return (
    <p className="mb-3 text-justify text-[13px] leading-relaxed text-[#c3d0e4]">
      <CitedText text={block.text ?? ""} sources={sources} />
    </p>
  );
}

export function IeeePaperView({
  paper,
  sources,
}: {
  paper: IeeePaper;
  sources: Source[];
}) {
  return (
    <article className="ieee-paper">
      <h1 className="text-center font-serif text-lg font-bold tracking-wide text-foreground uppercase">
        {paper.title}
      </h1>
      <p className="mt-1.5 text-center font-serif text-xs text-muted">{paper.authors}</p>

      <div className="mt-4 rounded-xl border border-border-subtle bg-[#0a1020] p-4">
        <p className="text-justify font-serif text-[13px] leading-relaxed text-[#c3d0e4] italic">
          <span className="font-semibold not-italic text-foreground">Abstract—</span>
          <CitedText text={paper.abstract} sources={sources} />
        </p>
        <p className="mt-2 text-justify font-serif text-[13px] leading-relaxed text-[#c3d0e4] italic">
          <span className="font-semibold not-italic text-foreground">Index Terms—</span>
          {paper.keywords.join(", ")}
        </p>
      </div>

      {paper.sections.map((section) => (
        <section key={section.heading} className="mt-6">
          <h2 className="mb-2.5 text-center font-serif text-sm font-bold tracking-wide text-foreground uppercase">
            {section.heading}
          </h2>
          {section.blocks.map((block, index) => (
            <PaperBlock key={index} block={block} sources={sources} />
          ))}
        </section>
      ))}

      <section className="mt-6">
        <h2 className="mb-2.5 text-center font-serif text-sm font-bold tracking-wide text-foreground uppercase">
          References
        </h2>
        {paper.references.length === 0 ? (
          <p className="text-[13px] text-muted">No external sources were cited.</p>
        ) : (
          <ol className="space-y-2">
            {paper.references.map((reference) => (
              <li
                key={reference.number}
                className="flex gap-2 font-serif text-[13px] leading-relaxed"
              >
                <span className="shrink-0 font-mono text-[11px] text-muted">
                  [{reference.number}]
                </span>
                {reference.url ? (
                  <a
                    href={reference.url}
                    target="_blank"
                    rel="noreferrer noopener"
                    className="break-words text-[#c3d0e4] underline decoration-border-subtle underline-offset-2 transition hover:text-foreground"
                  >
                    {reference.text}
                  </a>
                ) : (
                  <span className="break-words text-[#c3d0e4]">{reference.text}</span>
                )}
              </li>
            ))}
          </ol>
        )}
      </section>

      <p className="mt-6 border-t border-border-subtle pt-3 font-mono text-[10px] leading-relaxed text-muted">
        IEEE-style paper generated from a completed research report. References are drawn
        only from sources retrieved by the agent. Not a submission to any venue.
      </p>
    </article>
  );
}
