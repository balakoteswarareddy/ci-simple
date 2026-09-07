function headers(): Record<string, string> {
  const h: Record<string, string> = { "Content-Type": "application/json" };
  const key = localStorage.getItem("ci-agent-api-key");
  if (key) h["X-API-Key"] = key;
  const actor = localStorage.getItem("ci-agent-actor");
  if (actor) h["X-Actor"] = actor;
  return h;
}

async function req<T>(path: string, init?: RequestInit): Promise<T> {
  const resp = await fetch(path, { ...init, headers: { ...headers(), ...(init?.headers || {}) } });
  const text = await resp.text();
  let body: unknown = null;
  try {
    body = text ? JSON.parse(text) : null;
  } catch {
    body = text;
  }
  if (!resp.ok) {
    const detail = (body as { detail?: string })?.detail || text || resp.statusText;
    throw new Error(`${resp.status}: ${detail}`);
  }
  return body as T;
}

export interface CreateRunOptions {
  platform: string;
  revision?: string;
  publish?: boolean;
  target_branch?: string;
  base_branch?: string;
  pr_title?: string;
  require_approval?: boolean;
  capabilities?: string[];
  deployment_target?: string;
  workflow_filename?: string;
}

export const api = {
  health: () => req<{ status: string }>("/healthz"),
  ready: () => req<{ ready: boolean; checks: Record<string, unknown> }>("/readyz"),
  listRuns: (status?: string, limit = 50) =>
    req<{ runs: import("./types").RunSummary[] }>(
      `/api/v1/runs?limit=${limit}${status ? `&status=${encodeURIComponent(status)}` : ""}`
    ),
  createRun: (repo_url: string, request: string, options: CreateRunOptions) =>
    req<{ run_id: string; status: string }>("/api/v1/runs", {
      method: "POST",
      body: JSON.stringify({ repo_url, request, options }),
    }),
  getRun: (id: string) => req<import("./types").RunDetail>(`/api/v1/runs/${id}`),
  getEvents: (id: string, after_seq = 0) =>
    req<{ events: import("./types").RunEvent[] }>(`/api/v1/runs/${id}/events?after_seq=${after_seq}`),
  getYaml: (id: string) => req<{ filename: string; content: string }>(`/api/v1/runs/${id}/yaml`),
  getEvidence: (id: string) => req<Record<string, unknown>>(`/api/v1/runs/${id}/evidence`),
  decide: (id: string, decision: string, reason: string, approver = "") =>
    req<{ status: string }>(`/api/v1/runs/${id}/approve`, {
      method: "POST",
      body: JSON.stringify({ decision, reason, approver }),
    }),
  refreshChecks: (id: string) =>
    req<{ checks: unknown[]; merge: unknown }>(`/api/v1/runs/${id}/checks/refresh`, { method: "POST" }),
  pendingApprovals: () => req<{ pending: import("./types").RunSummary[] }>("/api/v1/approvals/pending"),
  knowledgeTools: () => req<{ tools: string[] }>("/api/v1/knowledge/tools"),
  knowledgeStats: () => req<Record<string, unknown>>("/api/v1/knowledge/stats"),
  knowledgeTool: (name: string) => req<Record<string, unknown>>(`/api/v1/knowledge/tools/${name}`),
  ingest: (url: string, hint_tool = "", hint_capabilities: string[] = []) =>
    req<Record<string, unknown>>("/api/v1/knowledge/ingest", {
      method: "POST",
      body: JSON.stringify({ url, hint_tool, hint_capabilities }),
    }),
  refreshKnowledge: (tools?: string[]) =>
    req<Record<string, unknown>>("/api/v1/knowledge/refresh", {
      method: "POST",
      body: JSON.stringify({ tools: tools ?? null }),
    }),
  policyCatalog: () => req<Record<string, unknown>>("/api/v1/policies/catalog"),
  evaluatePolicy: (payload: Record<string, unknown>) =>
    req<Record<string, unknown>>("/api/v1/policies/evaluate", {
      method: "POST",
      body: JSON.stringify(payload),
    }),
};
