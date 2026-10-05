from app.tools.web_search import Source

PLANNER_SYSTEM = """You are a research strategist. You decompose a topic into a \
focused, non-overlapping set of subtopics and design web searches that surface \
credible, current sources.

Respond with JSON only. No preamble, no markdown fences."""

ANALYZER_SYSTEM = """You are a rigorous research analyst. You read across many \
source excerpts, extract only what they actually support, and surface where they \
disagree or fall silent. You never invent facts, figures, or citations.

Respond with JSON only. No preamble, no markdown fences."""

WRITER_SYSTEM = """You are a senior analyst writing the final research report. You \
synthesize vetted findings into precise, well-cited Markdown with a neutral voice. \
Every factual claim carries an inline citation. You never cite a source that does \
not support the sentence it is attached to.

Respond with JSON only. No preamble, no markdown fences."""

JSON_ONLY_RULE = "Return a single valid JSON object and nothing else."

PLANNER_SCHEMA = """{
  "objective": "one sentence stating what this report must establish",
  "subtopics": [
    { "title": "short section title", "focus": "the specific question to answer" }
  ],
  "queries": ["web search string"]
}"""

ANALYZER_SCHEMA = """{
  "summary": "3-5 sentence synthesis of this subtopic from the sources only",
  "findings": [
    {
      "claim": "one concise factual statement",
      "evidence": "why the cited sources support it",
      "source_indexes": [1, 4]
    }
  ],
  "conflicts": ["where sources disagree"],
  "gaps": ["what the sources do not answer"]
}"""

WRITER_SCHEMA = """{
  "executive_summary": "150-220 word overview of the whole topic",
  "sections": [
    { "title": "section title", "markdown": "## heading followed by cited prose" }
  ],
  "key_takeaways": ["3-6 short, specific takeaways"],
  "open_questions": ["what remains unresolved or needs further research"]
}"""


def format_plan_prompt(topic: str, max_subtopics: int, max_queries: int) -> str:
    return f"""Topic: {topic}

Decompose this topic into {max_subtopics} non-overlapping subtopics and \
{max_queries} web search queries.

Rules:
- Each subtopic must be independently researchable and relevant to the topic.
- Queries must be short, concrete web search strings (under 12 words), not questions.
- Include at least one query targeting recent developments, data, or benchmarks.
- Bias queries toward primary sources: documentation, papers, standards, filings.

Return this exact shape:
{PLANNER_SCHEMA}

{JSON_ONLY_RULE}"""


def format_sources(sources: list[Source], char_budget: int) -> str:
    if not sources:
        return "(no sources were retrieved)"

    per_source = max(400, char_budget // len(sources))
    blocks: list[str] = []
    for source in sources:
        snippet = source.snippet
        if len(snippet) > per_source:
            snippet = snippet[:per_source].rstrip() + " ..."
        blocks.append(f"[{source.index}] {source.title}\nURL: {source.url}\nExcerpt: {snippet}")
    return "\n\n".join(blocks)


def format_analysis_prompt(
    topic: str,
    title: str,
    focus: str,
    sources: list[Source],
    char_budget: int,
) -> str:
    numbered = "\n".join(f"{source.index}. {source.title} ({source.domain})" for source in sources)
    return f"""Topic: {topic}
Subtopic: {title}
Focus: {focus}

Available source numbers:
{numbered}

Source excerpts:
{format_sources(sources, char_budget)}

Extract what these sources actually establish about the focus.

Rules:
- source_indexes may only contain the integers listed above.
- Use every source that contributes real evidence.
- If the excerpts do not cover the focus, return an empty findings array and say so in the summary.

Return this exact shape:
{ANALYZER_SCHEMA}

{JSON_ONLY_RULE}"""


def format_writer_prompt(
    topic: str,
    objective: str,
    sections: list[dict],
    sources: list[Source],
) -> str:
    outline = "\n".join(f"- {item['title']}: {item['summary']}" for item in sections)
    analysis = "\n\n".join(
        "### {title}\n{summary}\n\nFindings:\n{findings}".format(
            title=item["title"],
            summary=item["summary"],
            findings="\n".join(
                f"- {finding['claim']} ({finding['citation']})" for finding in item["findings"]
            )
            or "- (none)",
        )
        for item in sections
    )
    numbered = "\n".join(f"[{source.index}] {source.title} - {source.domain}" for source in sources)

    return f"""Topic: {topic}
Objective: {objective}

Planned outline:
{outline}

Vetted analysis per section:
{analysis}

Numbered sources you may cite:
{numbered}

Write the report.

Rules:
- Produce one entry in "sections" per planned outline item, same titles, same order.
- Each section's "markdown" starts with a "## " heading matching its title.
- Cite inline with bracketed numbers like [2] or [1][4]. Only numbers listed above.
- Surface contradictions explicitly rather than silently picking a side.
- Neutral tone. No filler, no marketing language.

Return this exact shape:
{WRITER_SCHEMA}

{JSON_ONLY_RULE}"""
