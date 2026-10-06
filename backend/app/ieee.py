import io
import math
import re
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_JUSTIFY
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (
    BaseDocTemplate,
    Frame,
    ListFlowable,
    ListItem,
    NextPageTemplate,
    PageTemplate,
    Paragraph,
)

from app.pdf import BOLD_PATTERN, CITATION_PATTERN, sanitize

AUTHORS = "AI Research Agent"

_STOPWORDS = {
    "a", "an", "and", "are", "as", "at", "be", "by", "can", "do", "does", "for",
    "from", "how", "in", "into", "is", "it", "its", "of", "on", "or", "the",
    "their", "this", "that", "to", "under", "via", "what", "when", "which", "with",
    "why", "across", "over",
}


def _paragraph(text: str) -> dict:
    return {"kind": "paragraph", "text": text.strip()}


def _subheading(text: str) -> dict:
    return {"kind": "subheading", "text": text.strip()}


def _bullet_list(items: list[str]) -> dict:
    return {"kind": "list", "items": [item.strip() for item in items if item and item.strip()]}


def _clean(text: str, limit: int | None = None) -> str:
    text = str(text)
    text = re.sub(r"(?:^|\s)#{1,6}\s+", " ", text)
    text = text.replace("|", " ")
    text = re.sub(r"\*+", "", text)
    text = re.sub(r"\s+", " ", text).strip()
    if limit and len(text) > limit:
        cut = text[:limit].rsplit(" ", 1)[0]
        text = cut.rstrip(" ,.;:") + "..."
    return text


def _strip_invalid(text: str, valid: set[int]) -> str:
    def replace(match: re.Match[str]) -> str:
        return match.group(0) if int(match.group(1)) in valid else ""

    cleaned = CITATION_PATTERN.sub(replace, text)
    return re.sub(r"(?<=\S)[ \t]{2,}(?=\S)", " ", cleaned).strip()


def _extract(markdown: str, heading: str) -> tuple[str, list[str]]:
    lines = markdown.splitlines()
    start = None
    for index, line in enumerate(lines):
        if line.strip() == f"## {heading}":
            start = index + 1
            break
    if start is None:
        return "", []

    body: list[str] = []
    for line in lines[start:]:
        if line.startswith("#"):
            break
        body.append(line)

    paragraphs = " ".join(
        line.strip() for line in body if line.strip() and not line.strip().startswith("- ")
    ).strip()
    bullets = [line.strip()[2:].strip() for line in body if line.strip().startswith("- ")]
    return paragraphs, [bullet for bullet in bullets if bullet]


def _keywords(topic: str, subtopics: list[dict]) -> list[str]:
    phrases: list[str] = []
    for chunk in re.split(
        r"\s+(?:of|on|in|for|and|with|to|by|via|from|the|a|an)\s+", topic, flags=re.IGNORECASE
    ):
        chunk = chunk.strip(" .,:;!?-()")
        if chunk and chunk.lower() not in _STOPWORDS and len(chunk) > 1:
            phrases.append(chunk)

    seen = {phrase.lower() for phrase in phrases}
    for subtopic in subtopics:
        title = str(subtopic.get("title") or "").strip()
        if title and title.lower() not in seen:
            phrases.append(title)
            seen.add(title.lower())

    return phrases[:6] or [topic]


def _citation(source_indexes: list, valid: set[int]) -> str:
    return "".join(f"[{index}]" for index in source_indexes if index in valid)


def _introduction(
    topic: str,
    objective: str,
    subtopic_count: int,
    query_count: int,
    source_count: int,
    cited_count: int,
    coverage_pct: int,
    finding_count: int,
    conflict_count: int,
    gap_count: int,
) -> list[dict]:
    blocks = [
        _paragraph(
            f"This paper presents an automated review of {topic}. The review was produced by "
            "an autonomous research agent that decomposes the topic into subtopics, retrieves "
            "sources from the live web, analyses each source against the plan, and validates "
            "every citation against the sources actually retrieved."
        )
    ]
    if objective:
        blocks.append(
            _paragraph(f"The review was guided by the following objective: {objective}")
        )
    blocks.append(_paragraph("The main contributions of this review are:"))
    blocks.append(
        _bullet_list(
            [
                f"a decomposition of the topic into {subtopic_count} subtopics and "
                f"{query_count} search queries;",
                f"the retrieval of {source_count} sources, {cited_count} of which are cited "
                f"in this paper ({coverage_pct}% citation coverage);",
                f"structured analysis recording {finding_count} findings, {conflict_count} "
                f"points of conflicting evidence and {gap_count} evidence gaps.",
            ]
        )
    )
    return blocks


def _related_work(
    cited_sources: list[dict], source_count: int, query_count: int
) -> list[dict]:
    if not cited_sources:
        return [_paragraph("No external sources were cited in this review.")]

    blocks = [
        _paragraph(
            f"The retrieval phase returned {source_count} sources across {query_count} search "
            "queries. The sources cited in this paper are summarised below."
        )
    ]
    for source in cited_sources:
        head = (
            f"\"{_clean(source.get('title') or 'Untitled')}\" "
            f"[{source.get('index')}] ({source.get('domain') or 'web'})"
        )
        snippet = _clean(source.get("snippet") or "", limit=420)
        blocks.append(_paragraph(f"{head}: {snippet}" if snippet else f"{head}."))
    return blocks


def _methodology(
    subtopics: list[dict],
    queries: list[str],
    model: str,
    source_count: int,
    cited_count: int,
    coverage_pct: int,
    finding_count: int,
    conflict_count: int,
    gap_count: int,
) -> list[dict]:
    blocks = [
        _paragraph(
            "The review was produced in five stages: planning, retrieval, analysis, writing, "
            "and citation validation."
        ),
        _paragraph("Planning. The topic was decomposed into the following subtopics:"),
    ]
    if subtopics:
        blocks.append(
            _bullet_list(
                [
                    f"{subtopic.get('title')}: {subtopic.get('focus')}"
                    if subtopic.get("focus")
                    else str(subtopic.get("title") or "")
                    for subtopic in subtopics
                ]
            )
        )
    else:
        blocks.append(_paragraph("No subtopics were recorded for this plan."))

    blocks.append(
        _paragraph(
            "Retrieval. Each subtopic was expanded into search queries executed against the "
            "live web and de-duplicated by URL:"
        )
    )
    if queries:
        blocks.append(_bullet_list([str(query) for query in queries]))
    else:
        blocks.append(_paragraph("No search queries were recorded for this plan."))

    blocks.extend(
        [
            _paragraph(
                f"Analysis. Every source was read against one subtopic and reduced to "
                f"claim/evidence pairs carrying explicit source references; disagreements "
                f"between sources and gaps in the evidence were recorded separately. Across "
                f"all subtopics the analysis produced {finding_count} findings, "
                f"{conflict_count} conflicting claims and {gap_count} evidence gaps."
            ),
            _paragraph(
                f"Writing. The report was drafted from the validated analyses by the {model} "
                "language model, producing an executive summary, structured sections, key "
                "takeaways and open questions."
            ),
            _paragraph(
                f"Validation. Each citation in the final text was checked against the set of "
                f"retrieved sources and any unmatched reference was removed, leaving "
                f"{cited_count} of {source_count} sources cited ({coverage_pct}% coverage)."
            ),
        ]
    )
    return blocks


def _results(analyses: list[dict], valid: set[int], finding_count: int) -> list[dict]:
    if not analyses:
        return [_paragraph("The analysis stage produced no recorded findings for this topic.")]

    blocks = [
        _paragraph(
            f"The analysis produced {finding_count} findings across {len(analyses)} analysed "
            f"subtopic{'s' if len(analyses) != 1 else ''}."
        )
    ]
    for position, analysis in enumerate(analyses):
        title = str(analysis.get("title") or f"Subtopic {position + 1}")
        blocks.append(_subheading(f"{chr(ord('A') + position)}. {title}"))

        summary = str(analysis.get("summary") or "").strip()
        if summary:
            blocks.append(_paragraph(summary))

        findings = analysis.get("findings") or []
        if not findings:
            blocks.append(_paragraph("No findings were recorded for this subtopic."))
            continue

        for finding in findings:
            claim = str(finding.get("claim") or "").strip()
            evidence = str(finding.get("evidence") or "").strip()
            text = " ".join(part for part in (claim, evidence) if part)
            if not text:
                continue
            cite = _citation(finding.get("source_indexes") or [], valid)
            blocks.append(_paragraph(f"{text} {cite}".strip()))
    return blocks


def _discussion(
    takeaways: list[str],
    conflicts: list[str],
    gaps: list[str],
    open_questions: list[str],
) -> list[dict]:
    blocks: list[dict] = []
    if takeaways:
        blocks.append(_paragraph("The review yielded the following key takeaways:"))
        blocks.append(_bullet_list(takeaways))
    if conflicts:
        blocks.append(
            _paragraph(
                f"The sources did not agree on every point; {len(conflicts)} point"
                f"{'s were' if len(conflicts) != 1 else ' was'} of conflicting evidence "
                "recorded:"
            )
        )
        blocks.append(_bullet_list(conflicts))
    if gaps:
        blocks.append(_paragraph("The following evidence gaps were recorded:"))
        blocks.append(_bullet_list(gaps))
    if open_questions:
        blocks.append(_paragraph("The review left the following questions open:"))
        blocks.append(_bullet_list(open_questions))
    if not blocks:
        blocks.append(
            _paragraph("No conflicts, evidence gaps or open questions were recorded.")
        )
    return blocks


def _conclusion(
    topic: str,
    source_count: int,
    cited_count: int,
    coverage_pct: int,
    analysis_count: int,
    conflicts: list[str],
    gaps: list[str],
    open_questions: list[str],
) -> list[dict]:
    blocks = [
        _paragraph(
            f"This review examined {topic}. The agent retrieved {source_count} sources and "
            f"cited {cited_count} of them ({coverage_pct}% coverage) across {analysis_count} "
            f"analysed subtopic{'s' if analysis_count != 1 else ''}."
        )
    ]
    if gaps or conflicts:
        blocks.append(
            _paragraph(
                f"The evidence base is bounded: {len(gaps)} evidence gaps and "
                f"{len(conflicts)} conflicting claims were recorded, and the underlying "
                "sources are live web pages that may change over time."
            )
        )
    blocks.append(
        _paragraph(
            "Every claim in this paper is linked to a retrieved source; findings should be "
            "verified against those sources before reuse."
        )
    )
    followups = open_questions or gaps
    if followups:
        blocks.append(
            _paragraph("Future work should address the open questions identified above:")
        )
        blocks.append(_bullet_list(followups[:5]))
    return blocks


def _references(sections: list[dict], abstract: str, sources: list[dict]) -> list[dict]:
    sources_by_index = {
        int(source["index"]): source
        for source in sources
        if source.get("index") is not None
    }

    texts = [abstract]
    for section in sections:
        for block in section["blocks"]:
            if block["kind"] == "list":
                texts.extend(block["items"])
            elif block.get("text"):
                texts.append(block["text"])

    used: set[int] = set()
    for text in texts:
        used.update(int(match.group(1)) for match in CITATION_PATTERN.finditer(text))

    references = []
    for index in sorted(used & set(sources_by_index)):
        source = sources_by_index[index]
        title = _clean(source.get("title") or "Untitled").replace('"', "'")
        domain = _clean(source.get("domain") or "web")
        url = str(source.get("url") or "").strip()
        if url:
            text = f"\"{title},\" {domain}. [Online]. Available: {url}"
        else:
            text = f"\"{title},\" {domain}."
        references.append({"number": index, "text": text, "url": url or None})
    return references


def build_paper(record: dict) -> dict:
    topic = str(record.get("topic") or "Research Report").strip()
    markdown = str(record.get("markdown") or "")
    plan = record.get("plan") or {}
    objective = str(record.get("objective") or plan.get("objective") or "").strip()
    sources = record.get("sources") or []
    analyses = record.get("sections") or []
    model = str(record.get("model") or "an unspecified")
    subtopics = plan.get("subtopics") or []
    queries = plan.get("queries") or []

    abstract, _ = _extract(markdown, "Executive Summary")
    _, takeaways = _extract(markdown, "Key Takeaways")
    _, open_questions = _extract(markdown, "Open Questions")
    if not abstract:
        abstract = objective or f"This paper reviews {topic}."

    valid = {int(source["index"]) for source in sources if source.get("index") is not None}
    cited_sources = [
        source for source in sources if source.get("index") in valid and source.get("cited")
    ]

    source_count = len(sources)
    cited_count = len(cited_sources)
    coverage = record.get("coverage") or (cited_count / source_count if source_count else 0.0)
    coverage_pct = round(float(coverage) * 100)

    conflicts = [str(item) for analysis in analyses for item in (analysis.get("conflicts") or [])]
    gaps = [str(item) for analysis in analyses for item in (analysis.get("gaps") or [])]
    finding_count = sum(len(analysis.get("findings") or []) for analysis in analyses)

    sections = [
        {
            "heading": "I. INTRODUCTION",
            "blocks": _introduction(
                topic,
                objective,
                len(subtopics),
                len(queries),
                source_count,
                cited_count,
                coverage_pct,
                finding_count,
                len(conflicts),
                len(gaps),
            ),
        },
        {
            "heading": "II. RELATED WORK",
            "blocks": _related_work(cited_sources, source_count, len(queries)),
        },
        {
            "heading": "III. METHODOLOGY",
            "blocks": _methodology(
                subtopics,
                queries,
                model,
                source_count,
                cited_count,
                coverage_pct,
                finding_count,
                len(conflicts),
                len(gaps),
            ),
        },
        {
            "heading": "IV. RESULTS AND ANALYSIS",
            "blocks": _results(analyses, valid, finding_count),
        },
        {
            "heading": "V. DISCUSSION",
            "blocks": _discussion(takeaways, conflicts, gaps, open_questions),
        },
        {
            "heading": "VI. CONCLUSION",
            "blocks": _conclusion(
                topic,
                source_count,
                cited_count,
                coverage_pct,
                len(analyses),
                conflicts,
                gaps,
                open_questions,
            ),
        },
    ]

    abstract = _strip_invalid(abstract, valid)
    for section in sections:
        cleaned_blocks = []
        for block in section["blocks"]:
            if block["kind"] == "list":
                items = [_strip_invalid(item, valid) for item in block["items"]]
                cleaned_blocks.append(
                    {"kind": "list", "items": [item for item in items if item]}
                )
            else:
                text = _strip_invalid(block["text"], valid)
                if text:
                    cleaned_blocks.append({"kind": block["kind"], "text": text})
        section["blocks"] = cleaned_blocks

    references = _references(sections, abstract, sources)

    paper = {
        "title": topic,
        "authors": AUTHORS,
        "abstract": abstract,
        "keywords": _keywords(topic, subtopics),
        "sections": sections,
        "references": references,
        "source_count": source_count,
        "cited_count": len(references),
    }
    paper["markdown"] = _to_markdown(paper)
    return paper


def _to_markdown(paper: dict) -> str:
    parts = [
        f"# {paper['title']}",
        "",
        f"**Authors:** {paper['authors']}",
        "",
        f"**Abstract** — {paper['abstract']}",
        "",
        f"**Index Terms** — {', '.join(paper['keywords'])}",
        "",
    ]
    for section in paper["sections"]:
        parts.extend([f"## {section['heading']}", ""])
        for block in section["blocks"]:
            if block["kind"] == "paragraph":
                parts.extend([block["text"], ""])
            elif block["kind"] == "subheading":
                parts.extend([f"**{block['text']}**", ""])
            else:
                parts.extend(f"- {item}" for item in block["items"])
                parts.append("")

    parts.extend(["## REFERENCES", ""])
    if paper["references"]:
        parts.extend(
            f"[{reference['number']}] {reference['text']}"
            for reference in paper["references"]
        )
        parts.append("")
    else:
        parts.extend(["No external sources were cited.", ""])

    parts.append(
        "_Generated by the AI Research Agent from a completed research report. "
        "This is an IEEE-style paper, not a submission to any venue. "
        "Verify claims against the linked sources._"
    )
    return "\n".join(parts).strip() + "\n"


_PAGE_W, _PAGE_H = A4
_LEFT = 15 * mm
_RIGHT = 15 * mm
_TOP = 14 * mm
_BOTTOM = 16 * mm
_GAP = 5 * mm
_COL_W = (_PAGE_W - _LEFT - _RIGHT - _GAP) / 2
_LINK_COLOR = colors.HexColor("#1a4fa0")


def _page_furniture(canvas, doc) -> None:
    canvas.saveState()
    canvas.setFont("Times-Roman", 8.5)
    canvas.setFillColor(colors.HexColor("#333333"))
    canvas.drawCentredString(_PAGE_W / 2, 9 * mm, str(canvas.getPageNumber()))
    canvas.restoreState()


def _styles() -> dict[str, ParagraphStyle]:
    base = getSampleStyleSheet()
    return {
        "title": ParagraphStyle(
            "PaperTitle",
            parent=base["Title"],
            fontName="Times-Bold",
            fontSize=13.5,
            leading=16,
            alignment=TA_CENTER,
            textColor=colors.black,
            spaceAfter=2,
        ),
        "authors": ParagraphStyle(
            "PaperAuthors",
            parent=base["Normal"],
            fontName="Times-Roman",
            fontSize=9.5,
            leading=12,
            alignment=TA_CENTER,
            textColor=colors.HexColor("#333333"),
        ),
        "abstract": ParagraphStyle(
            "PaperAbstract",
            parent=base["BodyText"],
            fontName="Times-Italic",
            fontSize=9,
            leading=11.5,
            alignment=TA_JUSTIFY,
            textColor=colors.black,
            spaceAfter=3,
        ),
        "index": ParagraphStyle(
            "PaperIndexTerms",
            parent=base["BodyText"],
            fontName="Times-Italic",
            fontSize=9,
            leading=11.5,
            alignment=TA_JUSTIFY,
            textColor=colors.black,
            spaceAfter=4,
        ),
        "heading": ParagraphStyle(
            "PaperHeading",
            parent=base["Heading1"],
            fontName="Times-Bold",
            fontSize=10,
            leading=12.5,
            alignment=TA_CENTER,
            textColor=colors.black,
            spaceBefore=7,
            spaceAfter=3.5,
        ),
        "subheading": ParagraphStyle(
            "PaperSubheading",
            parent=base["Heading2"],
            fontName="Times-BoldItalic",
            fontSize=9.5,
            leading=12,
            textColor=colors.black,
            spaceBefore=4.5,
            spaceAfter=2,
        ),
        "body": ParagraphStyle(
            "PaperBody",
            parent=base["BodyText"],
            fontName="Times-Roman",
            fontSize=9,
            leading=11.4,
            alignment=TA_JUSTIFY,
            textColor=colors.black,
            spaceAfter=4,
        ),
        "bullet": ParagraphStyle(
            "PaperBullet",
            parent=base["BodyText"],
            fontName="Times-Roman",
            fontSize=9,
            leading=11.4,
            leftIndent=10,
            textColor=colors.black,
        ),
        "reference": ParagraphStyle(
            "PaperReference",
            parent=base["BodyText"],
            fontName="Times-Roman",
            fontSize=8.5,
            leading=10.5,
            alignment=TA_JUSTIFY,
            leftIndent=13,
            firstLineIndent=-13,
            textColor=colors.black,
            spaceAfter=3,
        ),
        "refheading": ParagraphStyle(
            "PaperReferenceHeading",
            parent=base["Heading1"],
            fontName="Times-Bold",
            fontSize=10,
            leading=12.5,
            alignment=TA_CENTER,
            textColor=colors.black,
            spaceBefore=8,
            spaceAfter=4,
        ),
    }


def _markup(text: str, sources: dict[int, str]) -> str:
    rendered = escape(sanitize(text))

    def citation(match: re.Match[str]) -> str:
        index = int(match.group(1))
        url = sources.get(index)
        if not url:
            return match.group(0)
        return f'<super><link href="{escape(url)}" color="#1a4fa0">[{index}]</link></super>'

    def bold(match: re.Match[str]) -> str:
        return f"<b>{escape(match.group(1))}</b>"

    rendered = CITATION_PATTERN.sub(citation, rendered)
    return BOLD_PATTERN.sub(bold, rendered)


def _reference_markup(reference: dict) -> str:
    raw = sanitize(f"[{reference['number']}] {reference['text']}")
    rendered = escape(raw)
    url = reference.get("url")
    if url:
        shown = escape(sanitize(url))
        if shown in rendered:
            rendered = rendered.replace(
                shown, f'<link href="{escape(url)}" color="#1a4fa0">{shown}</link>'
            )
    return rendered


def _flowables(paper: dict, styles: dict[str, ParagraphStyle], sources: dict[int, str]):
    flow: list = [
        NextPageTemplate("columns"),
        Paragraph(escape(sanitize(paper["title"])), styles["title"]),
        Paragraph(escape(sanitize(paper["authors"])), styles["authors"]),
        Paragraph(
            f"<b>Abstract</b>\u2014{_markup(paper['abstract'], sources)}",
            styles["abstract"],
        ),
        Paragraph(
            f"<b>Index Terms</b>\u2014{_markup(', '.join(paper['keywords']), sources)}",
            styles["index"],
        ),
    ]

    for section in paper["sections"]:
        flow.append(Paragraph(escape(section["heading"]), styles["heading"]))
        for block in section["blocks"]:
            if block["kind"] == "paragraph":
                flow.append(Paragraph(_markup(block["text"], sources), styles["body"]))
            elif block["kind"] == "subheading":
                flow.append(Paragraph(escape(block["text"]), styles["subheading"]))
            else:
                items = [
                    ListItem(
                        Paragraph(_markup(item, sources), styles["bullet"]), leftIndent=12
                    )
                    for item in block["items"]
                ]
                if items:
                    flow.append(
                        ListFlowable(
                            items,
                            bulletType="bullet",
                            start="•",
                            leftIndent=12,
                            spaceAfter=4,
                        )
                    )

    flow.append(Paragraph("REFERENCES", styles["refheading"]))
    if paper["references"]:
        for reference in paper["references"]:
            flow.append(Paragraph(_reference_markup(reference), styles["reference"]))
    else:
        flow.append(Paragraph("No external sources were cited.", styles["body"]))
    return flow


def render_ieee_pdf(paper: dict, sources: dict[int, str] | None = None) -> bytes:
    source_map = sources or {}
    styles = _styles()

    title = sanitize(paper.get("title") or "Research Paper")
    authors = sanitize(paper.get("authors") or AUTHORS)
    title_lines = max(1, math.ceil(len(title) / 70))
    title_height = (title_lines * 6.0 + 8.0) * mm
    first_column_top = _PAGE_H - _TOP - title_height - 2 * mm
    first_column_height = max(60 * mm, first_column_top - _BOTTOM)
    full_column_height = _PAGE_H - _TOP - _BOTTOM

    buffer = io.BytesIO()
    document = BaseDocTemplate(
        buffer,
        pagesize=A4,
        leftMargin=_LEFT,
        rightMargin=_RIGHT,
        topMargin=_TOP,
        bottomMargin=_BOTTOM,
        title=title,
        author=authors,
    )

    title_frame = Frame(
        _LEFT,
        _PAGE_H - _TOP - title_height,
        _PAGE_W - _LEFT - _RIGHT,
        title_height,
        id="title",
        leftPadding=0,
        rightPadding=0,
        topPadding=0,
        bottomPadding=0,
    )

    def columns(frame_id: str, height: float) -> list[Frame]:
        return [
            Frame(
                _LEFT,
                _BOTTOM,
                _COL_W,
                height,
                id=f"{frame_id}-left",
                leftPadding=0,
                rightPadding=0,
                topPadding=0,
                bottomPadding=0,
            ),
            Frame(
                _LEFT + _COL_W + _GAP,
                _BOTTOM,
                _COL_W,
                height,
                id=f"{frame_id}-right",
                leftPadding=0,
                rightPadding=0,
                topPadding=0,
                bottomPadding=0,
            ),
        ]

    document.addPageTemplates(
        [
            PageTemplate(
                id="first",
                frames=[title_frame, *columns("first", first_column_height)],
                onPage=_page_furniture,
            ),
            PageTemplate(
                id="columns",
                frames=columns("full", full_column_height),
                onPage=_page_furniture,
            ),
        ]
    )
    document.build(_flowables(paper, styles, source_map))
    return buffer.getvalue()
