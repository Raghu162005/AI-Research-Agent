import re
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone

from app.config import get_settings
from app.llm import LLMClient, LLMError
from app.prompts import research_prompt as prompts
from app.tools.web_search import Source, WebSearchTool

CITATION_PATTERN = re.compile(r"\[(\d{1,3})\]")

STAGE_PLAN = "plan"
STAGE_SEARCH = "search"
STAGE_ANALYZE = "analyze"
STAGE_WRITE = "write"
STAGE_DONE = "done"

STATUS_RUNNING = "running"
STATUS_COMPLETED = "completed"
STATUS_FAILED = "failed"


@dataclass(frozen=True)
class ProgressEvent:
    stage: str
    status: str
    message: str
    percent: int = 0
    detail: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "stage": self.stage,
            "status": self.status,
            "message": self.message,
            "percent": self.percent,
            "detail": self.detail,
        }


@dataclass
class Subtopic:
    title: str
    focus: str


@dataclass
class ResearchPlan:
    topic: str
    objective: str
    subtopics: list[Subtopic]
    queries: list[str]

    def to_dict(self) -> dict:
        return {
            "topic": self.topic,
            "objective": self.objective,
            "subtopics": [asdict(item) for item in self.subtopics],
            "queries": self.queries,
        }


@dataclass
class Finding:
    claim: str
    evidence: str
    source_indexes: list[int] = field(default_factory=list)

    @property
    def citation(self) -> str:
        return "".join(f"[{index}]" for index in self.source_indexes)


@dataclass
class SectionAnalysis:
    title: str
    focus: str
    summary: str
    findings: list[Finding] = field(default_factory=list)
    conflicts: list[str] = field(default_factory=list)
    gaps: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "title": self.title,
            "focus": self.focus,
            "summary": self.summary,
            "findings": [asdict(item) for item in self.findings],
            "conflicts": self.conflicts,
            "gaps": self.gaps,
        }


@dataclass
class ResearchReport:
    topic: str
    objective: str
    markdown: str
    plan: ResearchPlan
    analyses: list[SectionAnalysis]
    sources: list[Source]
    cited_indexes: list[int]
    steps: list[str]
    model: str
    created_at: str


class ResearchAgent:
    def __init__(self, llm: LLMClient | None = None, search: WebSearchTool | None = None) -> None:
        self.settings = get_settings()
        self.llm = llm or LLMClient()
        self.search = search or WebSearchTool()

    def run(self, topic: str, on_progress=None) -> ResearchReport:
        emit = on_progress or _noop
        steps: list[str] = []

        emit(ProgressEvent(STAGE_PLAN, STATUS_RUNNING, "Decomposing topic into subtopics", 5))
        plan = self.plan(topic)
        steps.append(f"plan:{len(plan.subtopics)} subtopics, {len(plan.queries)} queries")
        emit(
            ProgressEvent(
                STAGE_PLAN,
                STATUS_COMPLETED,
                f"Planned {len(plan.subtopics)} subtopics and {len(plan.queries)} searches",
                18,
                {"subtopics": [item.title for item in plan.subtopics], "queries": plan.queries},
            )
        )

        emit(ProgressEvent(STAGE_SEARCH, STATUS_RUNNING, "Searching the web for sources", 22))
        sources = self.gather(plan, emit)
        steps.append(f"search:{len(sources)} unique sources from {len(plan.queries)} queries")
        emit(
            ProgressEvent(
                STAGE_SEARCH,
                STATUS_COMPLETED,
                f"Retrieved {len(sources)} unique sources",
                35,
                {"source_count": len(sources)},
            )
        )

        analyses = self.analyze(plan, sources, emit)
        steps.append(f"analyze:{len(analyses)} sections, {sum(len(a.findings) for a in analyses)} findings")
        emit(
            ProgressEvent(
                STAGE_ANALYZE,
                STATUS_COMPLETED,
                f"Analysed {len(analyses)} sections",
                78,
                {"sections": len(analyses)},
            )
        )

        emit(ProgressEvent(STAGE_WRITE, STATUS_RUNNING, "Writing the cited report", 82))
        body = self.write(plan, sources, analyses)
        steps.append(f"write:{len(body['sections'])} sections, {len(body['key_takeaways'])} takeaways")
        emit(
            ProgressEvent(
                STAGE_WRITE,
                STATUS_COMPLETED,
                f"Wrote {len(body['sections'])} sections",
                94,
                {"sections": len(body["sections"])},
            )
        )

        markdown, cited = self.assemble(topic, plan, body, sources)

        report = ResearchReport(
            topic=topic,
            objective=plan.objective,
            markdown=markdown,
            plan=plan,
            analyses=analyses,
            sources=sources,
            cited_indexes=cited,
            steps=steps,
            model=self.llm.model,
            created_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        )

        emit(
            ProgressEvent(
                STAGE_DONE,
                STATUS_COMPLETED,
                f"Report ready with {len(cited)}/{len(sources)} sources cited",
                100,
                {"cited": len(cited), "sources": len(sources)},
            )
        )
        return report

    def plan(self, topic: str) -> ResearchPlan:
        user_prompt = prompts.format_plan_prompt(
            topic, self.settings.max_subtopics, self.settings.max_queries
        )
        data = self.llm.complete_json(prompts.PLANNER_SYSTEM, user_prompt)

        subtopics = _coerce_subtopics(data)
        if not subtopics:
            raise LLMError("Planner returned no usable subtopics")

        queries = _coerce_queries(data) or [f"{topic} overview"]
        objective = str(data.get("objective") or f"Produce an evidence-based overview of {topic}.")

        return ResearchPlan(
            topic=topic,
            objective=objective.strip(),
            subtopics=subtopics[: self.settings.max_subtopics],
            queries=queries[: self.settings.max_queries],
        )

    def gather(self, plan: ResearchPlan, emit=None) -> list[Source]:
        emit = emit or _noop
        if hasattr(self.search, "collect_with_progress"):
            return self.search.collect_with_progress(plan.queries, emit)

        total = len(plan.queries)
        for position, query in enumerate(plan.queries, start=1):
            emit(
                ProgressEvent(
                    STAGE_SEARCH,
                    STATUS_RUNNING,
                    f'Searching "{query}"',
                    22 + int(12 * (position - 1) / max(total, 1)),
                    {"query": query, "position": position, "total": total},
                )
            )
        return self.search.collect(plan.queries)

    def analyze(self, plan: ResearchPlan, sources: list[Source], emit=None) -> list[SectionAnalysis]:
        emit = emit or _noop
        if not sources:
            return [
                SectionAnalysis(
                    title=subtopic.title,
                    focus=subtopic.focus,
                    summary="No web sources were retrieved, so this section has no evidence.",
                )
                for subtopic in plan.subtopics
            ]

        analyses: list[SectionAnalysis] = []
        total = len(plan.subtopics)
        valid = {source.index for source in sources}
        emit(
            ProgressEvent(
                STAGE_ANALYZE,
                STATUS_RUNNING,
                f"Reading {len(sources)} sources across {total} subtopics",
                40,
            )
        )

        for position, subtopic in enumerate(plan.subtopics, start=1):
            emit(
                ProgressEvent(
                    STAGE_ANALYZE,
                    STATUS_RUNNING,
                    f'Analysing "{subtopic.title}"',
                    40 + int(38 * (position - 1) / max(total, 1)),
                    {
                        "section": subtopic.title,
                        "position": position,
                        "total": total,
                    },
                )
            )
            user_prompt = prompts.format_analysis_prompt(
                plan.topic,
                subtopic.title,
                subtopic.focus,
                sources,
                self.settings.max_prompt_chars,
            )
            data = self.llm.complete_json(prompts.ANALYZER_SYSTEM, user_prompt)
            analyses.append(
                SectionAnalysis(
                    title=subtopic.title,
                    focus=subtopic.focus,
                    summary=str(data.get("summary") or "").strip(),
                    findings=_coerce_findings(data, valid),
                    conflicts=_coerce_str_list(data.get("conflicts")),
                    gaps=_coerce_str_list(data.get("gaps")),
                )
            )
        return analyses

    def write(
        self, plan: ResearchPlan, sources: list[Source], analyses: list[SectionAnalysis]
    ) -> dict:
        user_prompt = prompts.format_writer_prompt(
            plan.topic,
            plan.objective,
            [
                {
                    "title": analysis.title,
                    "summary": analysis.summary,
                    "findings": [
                        {"claim": f.claim, "citation": f.citation} for f in analysis.findings
                    ],
                }
                for analysis in analyses
            ],
            sources,
        )
        data = self.llm.complete_json(prompts.WRITER_SYSTEM, user_prompt)
        return {
            "executive_summary": str(data.get("executive_summary") or "").strip(),
            "sections": [
                {
                    "title": str(item.get("title") or "Section").strip(),
                    "markdown": str(item.get("markdown") or "").strip(),
                }
                for item in _coerce_list(data.get("sections"))
                if isinstance(item, dict)
            ],
            "key_takeaways": _coerce_str_list(data.get("key_takeaways")),
            "open_questions": _coerce_str_list(data.get("open_questions")),
        }

    def assemble(
        self,
        topic: str,
        plan: ResearchPlan,
        body: dict,
        sources: list[Source],
    ) -> tuple[str, list[int]]:
        valid = {source.index for source in sources}
        parts: list[str] = [f"# {topic}", "", f"**Objective:** {plan.objective}", ""]

        if body["executive_summary"]:
            parts.extend(["## Executive Summary", "", body["executive_summary"], ""])

        cited: set[int] = set()
        for section in body["sections"]:
            cleaned = self._strip_bad_citations(section["markdown"], valid)
            cited.update(self._collect_citations(cleaned))
            parts.extend([cleaned, ""])

        if body["key_takeaways"]:
            parts.extend(["## Key Takeaways", ""])
            parts.extend(f"- {item}" for item in body["key_takeaways"])
            parts.append("")

        if body["open_questions"]:
            parts.extend(["## Open Questions", ""])
            parts.extend(f"- {item}" for item in body["open_questions"])
            parts.append("")

        cited_indexes = sorted(cited)
        parts.extend(["## Sources", ""])
        for source in sources:
            marker = "" if source.index in cited else " _(retrieved, not cited)_"
            parts.append(f"{source.index}. [{source.title}]({source.url}) - {source.domain}{marker}")
        parts.append("")

        parts.append(
            f"_Generated by the AI Research Agent using `{self.llm.model}` "
            f"on {datetime.now(timezone.utc).strftime('%Y-%m-%d')}. "
            "Verify claims against the linked sources before reuse._"
        )

        return "\n".join(parts).strip() + "\n", cited_indexes

    def _strip_bad_citations(self, markdown: str, valid: set[int]) -> str:
        def replace(match: re.Match[str]) -> str:
            return match.group(0) if int(match.group(1)) in valid else ""

        cleaned = CITATION_PATTERN.sub(replace, markdown)
        return re.sub(r"(?<=\S)[ \t]{2,}(?=\S)", " ", cleaned)

    def _collect_citations(self, markdown: str) -> set[int]:
        return {int(match.group(1)) for match in CITATION_PATTERN.finditer(markdown)}


def _noop(event: ProgressEvent) -> None:
    return None


def _coerce_list(value) -> list:
    if isinstance(value, list):
        return value
    if isinstance(value, dict):
        return list(value.values())
    return []


def _coerce_str_list(value) -> list[str]:
    items = []
    for item in _coerce_list(value):
        if isinstance(item, str) and item.strip():
            items.append(item.strip())
        elif item is not None and not isinstance(item, (str, dict, list)):
            items.append(str(item))
    return items


def _coerce_subtopics(data: dict) -> list[Subtopic]:
    subtopics: list[Subtopic] = []
    for item in _coerce_list(data.get("subtopics")):
        if isinstance(item, str) and item.strip():
            subtopics.append(Subtopic(title=item.strip(), focus=item.strip()))
        elif isinstance(item, dict):
            title = str(item.get("title") or "").strip()
            focus = str(item.get("focus") or item.get("description") or "").strip()
            if title:
                subtopics.append(Subtopic(title=title, focus=focus or title))
    return subtopics


def _coerce_queries(data: dict) -> list[str]:
    queries: list[str] = []
    for item in _coerce_list(data.get("queries")):
        if isinstance(item, str) and item.strip():
            queries.append(item.strip())
        elif isinstance(item, dict):
            query = str(item.get("query") or "").strip()
            if query:
                queries.append(query)
    return queries


def _coerce_findings(data: dict, valid: set[int]) -> list[Finding]:
    findings: list[Finding] = []
    for item in _coerce_list(data.get("findings")):
        if not isinstance(item, dict):
            continue
        claim = str(item.get("claim") or "").strip()
        if not claim:
            continue
        indexes = []
        for value in _coerce_list(item.get("source_indexes")):
            try:
                index = int(value)
            except (TypeError, ValueError):
                continue
            if index in valid and index not in indexes:
                indexes.append(index)
        findings.append(
            Finding(
                claim=claim,
                evidence=str(item.get("evidence") or "").strip(),
                source_indexes=sorted(indexes),
            )
        )
    return findings
