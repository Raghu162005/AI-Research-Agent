from dataclasses import asdict, dataclass
from urllib.parse import urlparse

from tavily import TavilyClient

from app.config import get_settings


class WebSearchError(RuntimeError):
    pass


@dataclass(frozen=True)
class Source:
    index: int
    title: str
    url: str
    domain: str
    query: str
    snippet: str

    def as_citable_text(self) -> str:
        return (
            f"[{self.index}] {self.title}\n"
            f"URL: {self.url}\n"
            f"Excerpt: {self.snippet}"
        )

    def to_dict(self) -> dict:
        return asdict(self)


def _domain(url: str) -> str:
    return urlparse(url).netloc.replace("www.", "") or "unknown"


ELLIPSIS = " ..."


def _truncate(text: str, limit: int) -> str:
    text = " ".join(text.split())
    if len(text) <= limit:
        return text
    if limit <= len(ELLIPSIS):
        return text[:limit]
    return text[: limit - len(ELLIPSIS)].rstrip() + ELLIPSIS


class WebSearchTool:
    def __init__(self) -> None:
        settings = get_settings()
        self._client = TavilyClient(api_key=settings.tavily_api_key)
        self._results_per_query = settings.results_per_query
        self._max_snippet_chars = settings.max_snippet_chars
        self._search_depth = settings.search_depth

    def search(self, query: str) -> list[dict]:
        try:
            response = self._client.search(
                query=query,
                search_depth=self._search_depth,
                max_results=self._results_per_query,
                include_answer=False,
                include_images=False,
            )
        except Exception as exc:
            raise WebSearchError(f"Search failed for query '{query}': {exc}") from exc
        return response.get("results") or []

    def collect(self, queries: list[str]) -> list[Source]:
        return self.collect_with_progress(queries)

    def collect_with_progress(self, queries: list[str], emit=None) -> list[Source]:
        from app.agent import ProgressEvent, STAGE_SEARCH, STATUS_RUNNING

        emit = emit or (lambda event: None)
        sources: list[Source] = []
        seen_urls: set[str] = set()
        total = len(queries)

        for position, query in enumerate(queries, start=1):
            emit(
                ProgressEvent(
                    STAGE_SEARCH,
                    STATUS_RUNNING,
                    f'Searching "{query}"',
                    22 + int(12 * (position - 1) / max(total, 1)),
                    {"query": query, "position": position, "total": total},
                )
            )
            for result in self.search(query):
                url = (result.get("url") or "").strip()
                if not url or url in seen_urls:
                    continue
                seen_urls.add(url)
                sources.append(
                    Source(
                        index=len(sources) + 1,
                        title=(result.get("title") or url).strip(),
                        url=url,
                        domain=_domain(url),
                        query=query,
                        snippet=_truncate(
                            (result.get("content") or "").strip(),
                            self._max_snippet_chars,
                        ),
                    )
                )

        return sources
