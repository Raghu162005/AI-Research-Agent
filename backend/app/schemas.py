from typing import Any

from pydantic import BaseModel, Field


class ResearchRequest(BaseModel):
    topic: str = Field(
        min_length=3,
        max_length=300,
        description="The research topic the agent should investigate.",
    )


class ProgressEventOut(BaseModel):
    stage: str
    status: str
    message: str
    percent: int = 0
    detail: dict[str, Any] = Field(default_factory=dict)


class ResearchCreated(BaseModel):
    id: str
    topic: str
    status: str
    created_at: str | None = None


class ReportSummary(BaseModel):
    id: str
    topic: str
    status: str
    coverage: float | None = None
    cited_count: int | None = None
    source_count: int | None = None
    model: str | None = None
    error: str | None = None
    created_at: str | None = None
    duration_seconds: float | None = None


class ReportList(BaseModel):
    reports: list[ReportSummary]


class ResearchResponse(BaseModel):
    id: str
    topic: str
    status: str
    objective: str | None = None
    markdown: str | None = None
    plan: dict[str, Any] | None = None
    sections: list[dict[str, Any]] = Field(default_factory=list)
    sources: list[dict[str, Any]] = Field(default_factory=list)
    steps: list[str] = Field(default_factory=list)
    events: list[ProgressEventOut] = Field(default_factory=list)
    cited_count: int = 0
    source_count: int = 0
    coverage: float = 0.0
    model: str | None = None
    error: str | None = None
    duration_seconds: float | None = None
    created_at: str | None = None


class HealthResponse(BaseModel):
    status: str
    llm_model: str
