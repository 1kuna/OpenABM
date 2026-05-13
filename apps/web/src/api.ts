import type {
  DocsSearchResult,
  EvalRun,
  JudgeDefinition,
  Project,
  ReviewTask,
  TraceDetail,
  TraceEnvelope
} from "./types";

export interface OpenAbmClientConfig {
  baseUrl: string;
  apiKey: string;
}

export class OpenAbmClient {
  private readonly baseUrl: string;
  private readonly apiKey: string;

  constructor(config: OpenAbmClientConfig) {
    this.baseUrl = config.baseUrl.replace(/\/$/, "");
    this.apiKey = config.apiKey;
  }

  async listProjects(): Promise<Project[]> {
    const body = await this.get<{ data: Project[] }>("/v1/projects");
    return body.data;
  }

  async listTraces(projectId: string, status?: string, environment?: string): Promise<TraceEnvelope[]> {
    const params = new URLSearchParams({ project_id: projectId, limit: "100" });
    if (status) params.set("status", status);
    if (environment) params.set("environment", environment);
    const body = await this.get<{ data: TraceEnvelope[] }>(`/v1/traces?${params.toString()}`);
    return body.data;
  }

  async searchTraces(projectId: string, query: string): Promise<TraceEnvelope[]> {
    const body = await this.post<{ data: TraceEnvelope[] }>("/v1/search/traces", {
      project_id: projectId,
      full_text_query: query || null,
      limit: 100
    });
    return body.data;
  }

  async getTrace(projectId: string, traceId: string): Promise<TraceDetail> {
    const params = new URLSearchParams({ project_id: projectId });
    return this.get<TraceDetail>(`/v1/traces/${traceId}?${params.toString()}`);
  }

  async searchSimilar(projectId: string, sourceId: string): Promise<{ disabled: boolean; reason?: string }> {
    return this.post("/v1/search/similar", {
      project_id: projectId,
      source_id: sourceId,
      source_type: "trace"
    });
  }

  async listJudges(projectId: string): Promise<JudgeDefinition[]> {
    const params = new URLSearchParams({ project_id: projectId });
    const body = await this.get<{ data: JudgeDefinition[] }>(`/v1/judges?${params.toString()}`);
    return body.data;
  }

  async listEvalRuns(projectId: string): Promise<EvalRun[]> {
    const params = new URLSearchParams({ project_id: projectId });
    const body = await this.get<{ data: EvalRun[] }>(`/v1/evals?${params.toString()}`);
    return body.data;
  }

  async searchDocs(query: string): Promise<DocsSearchResult[]> {
    const body = await this.post<{ results: DocsSearchResult[] }>("/v1/docs/search", {
      query,
      limit: 5
    });
    return body.results;
  }

  async listReviewTasks(
    projectId: string,
    filters: { status?: string; taskType?: string } = {}
  ): Promise<ReviewTask[]> {
    const params = new URLSearchParams({ project_id: projectId });
    if (filters.status) params.set("status", filters.status);
    if (filters.taskType) params.set("task_type", filters.taskType);
    const body = await this.get<{ data: ReviewTask[] }>(`/v1/review-tasks?${params.toString()}`);
    return body.data;
  }

  async updateReviewTask(
    projectId: string,
    reviewTaskId: string,
    patch: { status: ReviewTask["status"]; decision: string; notes?: string }
  ): Promise<ReviewTask> {
    return this.patch<ReviewTask>(`/v1/review-tasks/${reviewTaskId}`, {
      project_id: projectId,
      status: patch.status,
      decision: patch.decision,
      notes: patch.notes ?? null
    });
  }

  private async get<T>(path: string): Promise<T> {
    const response = await fetch(`${this.baseUrl}${path}`, {
      headers: this.headers()
    });
    return this.parse<T>(response);
  }

  private async post<T>(path: string, body: unknown): Promise<T> {
    const response = await fetch(`${this.baseUrl}${path}`, {
      method: "POST",
      headers: { ...this.headers(), "Content-Type": "application/json" },
      body: JSON.stringify(body)
    });
    return this.parse<T>(response);
  }

  private async patch<T>(path: string, body: unknown): Promise<T> {
    const response = await fetch(`${this.baseUrl}${path}`, {
      method: "PATCH",
      headers: { ...this.headers(), "Content-Type": "application/json" },
      body: JSON.stringify(body)
    });
    return this.parse<T>(response);
  }

  private headers(): Record<string, string> {
    return { Authorization: `Bearer ${this.apiKey}` };
  }

  private async parse<T>(response: Response): Promise<T> {
    if (!response.ok) {
      throw new Error(`${response.status} ${response.statusText}`);
    }
    return response.json() as Promise<T>;
  }
}
