export type JobStatus = "queued" | "running" | "completed" | "failed";

export type Stage =
  | "plan"
  | "search"
  | "analyze"
  | "write"
  | "done"
  | "string";

export interface ProgressEvent {
  stage: Stage;
  status: string;
  message: string;
  percent: number;
  detail: Record<string, unknown>;
}

export interface Source {
  index: number;
  title: string;
  url: string;
  domain: string;
  query: string;
  cited: boolean;
}

export interface Finding {
  claim: string;
  evidence: string;
  source_indexes: number[];
}

export interface SectionAnalysis {
  title: string;
  focus: string;
  summary: string;
  findings: Finding[];
  conflicts: string[];
  gaps: string[];
}

export interface ResearchPlan {
  topic: string;
  objective: string;
  subtopics: { title: string; focus: string }[];
  queries: string[];
}

export interface Report {
  id: string;
  topic: string;
  status: JobStatus;
  objective: string | null;
  markdown: string | null;
  plan: ResearchPlan | null;
  sections: SectionAnalysis[];
  sources: Source[];
  steps: string[];
  events: ProgressEvent[];
  cited_count: number;
  source_count: number;
  coverage: number;
  model: string | null;
  error: string | null;
  duration_seconds: number | null;
  created_at: string | null;
}

export interface ReportSummary {
  id: string;
  topic: string;
  status: JobStatus;
  coverage: number | null;
  cited_count: number | null;
  source_count: number | null;
  model: string | null;
  error: string | null;
  created_at: string | null;
  duration_seconds: number | null;
}

export const STAGE_LABELS: Record<string, string> = {
  plan: "Planning",
  search: "Searching",
  analyze: "Analysing",
  write: "Writing",
  done: "Complete",
};
