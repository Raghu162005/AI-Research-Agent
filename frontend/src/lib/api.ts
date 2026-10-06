import type { IeeePaper, Report, ReportSummary } from "./types";

export const API_BASE =
  process.env.NEXT_PUBLIC_API_URL?.replace(/\/$/, "") ?? "http://127.0.0.1:8000";

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, {
    ...init,
    headers: { "Content-Type": "application/json", ...(init?.headers ?? {}) },
    cache: "no-store",
  });

  if (!response.ok) {
    let detail = `Request failed with status ${response.status}`;
    try {
      const body = await response.json();
      if (body?.detail) detail = String(body.detail);
    } catch {
      // response body was not JSON
    }
    throw new Error(detail);
  }

  return (await response.json()) as T;
}

export function startResearch(topic: string) {
  return request<{ id: string; topic: string; status: string; created_at: string }>(
    "/research",
    { method: "POST", body: JSON.stringify({ topic }) }
  );
}

export function fetchReport(id: string) {
  return request<Report>(`/research/${id}`);
}

export function fetchReports(limit = 20) {
  return request<{ reports: ReportSummary[] }>(`/reports?limit=${limit}`).then(
    (data) => data.reports
  );
}

export function deleteReport(id: string) {
  return request<{ deleted: string }>(`/research/${id}`, { method: "DELETE" });
}

export function fetchPaper(id: string) {
  return request<IeeePaper>(`/research/${id}/paper`);
}

export const downloadUrls = {
  markdown: (id: string) => `${API_BASE}/research/${id}/report.md`,
  pdf: (id: string) => `${API_BASE}/research/${id}/report.pdf`,
  events: (id: string) => `${API_BASE}/research/${id}/events`,
  paperMarkdown: (id: string) => `${API_BASE}/research/${id}/paper.md`,
  paperPdf: (id: string) => `${API_BASE}/research/${id}/paper.pdf`,
};
