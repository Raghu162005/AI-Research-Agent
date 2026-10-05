import io
import re
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (
    HRFlowable,
    ListFlowable,
    ListItem,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
)

CITATION_PATTERN = re.compile(r"\[(\d{1,3})\]")
LINK_PATTERN = re.compile(r"\[([^\]]+)\]\((https?://[^\s)]+)\)")
BOLD_PATTERN = re.compile(r"\*\*([^*]+)\*\*")
ITALIC_PATTERN = re.compile(r"(?<!\*)\*([^*]+)\*(?!\*)")

CHAR_TRANSLATION = {
    "‑": "-",
    "‒": "-",
    "―": "-",
    "−": "-",
    "•": "-",
    "→": "->",
    "≥": ">=",
    "≤": "<=",
    "≈": "~",
    "×": "x",
    "′": "'",
    "“": '"',
    "”": '"',
    "‘": "'",
    "’": "'",
    "\xa0": " ",
    "…": "...",
}


def sanitize(text: str) -> str:
    text = text.translate(str.maketrans(CHAR_TRANSLATION))
    return "".join(
        char
        for char in text
        if char in "\n\t" or 32 <= ord(char) < 127 or 160 <= ord(char) < 256
    )


def _inline(text: str, sources: dict[int, str]) -> str:
    def citation(match: re.Match[str]) -> str:
        index = int(match.group(1))
        url = sources.get(index)
        if not url:
            return match.group(0)
        return f'<super><link href="{escape(url)}" color="#2563eb">[{index}]</link></super>'

    def link(match: re.Match[str]) -> str:
        label = escape(match.group(1))
        return f'<link href="{escape(match.group(2))}" color="#2563eb">{label}</link>'

    def bold(match: re.Match[str]) -> str:
        return f"<b>{escape(match.group(1))}</b>"

    def italic(match: re.Match[str]) -> str:
        return f"<i>{escape(match.group(1))}</i>"

    rendered = escape(sanitize(text))
    rendered = LINK_PATTERN.sub(link, rendered)
    rendered = CITATION_PATTERN.sub(citation, rendered)
    rendered = BOLD_PATTERN.sub(bold, rendered)
    rendered = ITALIC_PATTERN.sub(italic, rendered)
    return rendered


def _build_styles() -> dict[str, ParagraphStyle]:
    base = getSampleStyleSheet()
    return {
        "title": ParagraphStyle(
            "ReportTitle",
            parent=base["Title"],
            fontName="Helvetica-Bold",
            fontSize=19,
            leading=23,
            alignment=TA_LEFT,
            textColor=colors.HexColor("#0f172a"),
            spaceAfter=4,
        ),
        "h2": ParagraphStyle(
            "SectionHeading",
            parent=base["Heading2"],
            fontName="Helvetica-Bold",
            fontSize=13,
            leading=17,
            textColor=colors.HexColor("#0f172a"),
            spaceBefore=12,
            spaceAfter=5,
        ),
        "h3": ParagraphStyle(
            "SubHeading",
            parent=base["Heading3"],
            fontName="Helvetica-Bold",
            fontSize=11,
            leading=15,
            textColor=colors.HexColor("#334155"),
            spaceBefore=8,
            spaceAfter=3,
        ),
        "body": ParagraphStyle(
            "Body",
            parent=base["BodyText"],
            fontName="Helvetica",
            fontSize=9.5,
            leading=14.5,
            textColor=colors.HexColor("#1e293b"),
            alignment=TA_LEFT,
            spaceAfter=6,
        ),
        "bullet": ParagraphStyle(
            "Bullet",
            parent=base["BodyText"],
            fontName="Helvetica",
            fontSize=9.5,
            leading=14,
            leftIndent=10,
            textColor=colors.HexColor("#1e293b"),
        ),
        "meta": ParagraphStyle(
            "Meta",
            parent=base["BodyText"],
            fontName="Helvetica-Oblique",
            fontSize=8.5,
            leading=12,
            textColor=colors.HexColor("#64748b"),
            spaceAfter=10,
        ),
    }


def _flowables(markdown: str, styles: dict[str, ParagraphStyle], sources: dict[int, str]):
    flowables: list = []
    paragraph_buffer: list[str] = []
    list_buffer: list[str] = []
    in_front_matter = False

    def flush_paragraph() -> None:
        if not paragraph_buffer:
            return
        text = " ".join(paragraph_buffer).strip()
        paragraph_buffer.clear()
        if not text:
            return
        if text.startswith("**") and text.endswith("**") and "Objective" in text:
            flowables.append(Paragraph(_inline(text, sources), styles["meta"]))
            return
        flowables.append(Paragraph(_inline(text, sources), styles["body"]))

    def flush_list() -> None:
        if not list_buffer:
            return
        items = [
            ListItem(
                Paragraph(_inline(item, sources), styles["bullet"]),
                leftIndent=12,
            )
            for item in list_buffer
        ]
        list_buffer.clear()
        flowables.append(
            ListFlowable(items, bulletType="bullet", start="•", leftIndent=14, spaceAfter=6)
        )

    def flush_all() -> None:
        flush_paragraph()
        flush_list()

    for raw_line in sanitize(markdown).splitlines():
        line = raw_line.rstrip()

        if not line.strip():
            flush_all()
            in_front_matter = False
            continue

        if line.startswith("# "):
            flush_all()
            flowables.append(Paragraph(_inline(line[2:].strip(), sources), styles["title"]))
            in_front_matter = True
            continue

        if line.startswith("## "):
            flush_all()
            in_front_matter = False
            flowables.append(
                Paragraph(_inline(line[3:].strip(), sources), styles["h2"])
            )
            flowables.append(
                HRFlowable(
                    width="100%",
                    thickness=0.5,
                    color=colors.HexColor("#e2e8f0"),
                    spaceBefore=1,
                    spaceAfter=6,
                )
            )
            continue

        if line.startswith("### "):
            flush_all()
            flowables.append(Paragraph(_inline(line[4:].strip(), sources), styles["h3"]))
            continue

        if re.match(r"^\s*[-*]\s+", line) or re.match(r"^\s*\d+\.\s+", line):
            flush_paragraph()
            in_front_matter = False
            list_buffer.append(re.sub(r"^\s*(?:[-*]|\d+\.)\s+", "", line))
            continue

        if in_front_matter:
            paragraph_buffer.append(line.strip())
            continue

        flush_list()
        paragraph_buffer.append(line.strip())

    flush_all()
    return flowables


def render_pdf(markdown: str, sources: dict[int, str] | None = None) -> bytes:
    styles = _build_styles()
    source_map = sources or {}

    buffer = io.BytesIO()
    document = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        leftMargin=20 * mm,
        rightMargin=20 * mm,
        topMargin=18 * mm,
        bottomMargin=18 * mm,
        title="AI Research Report",
        author="AI Research Agent",
    )
    document.build(_flowables(markdown, styles, source_map))
    return buffer.getvalue()
