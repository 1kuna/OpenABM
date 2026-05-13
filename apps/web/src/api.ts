import type {
  BehaviorBacktestResult,
  BehaviorDefinition,
  DatasetDefinition,
  DatasetExample,
  DocsSearchResult,
  EvalComparison,
  EvalResult,
  EvalRun,
  JudgeCalibrationReport,
  JudgeDefinition,
  JudgePromotionResult,
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

  async listBehaviors(projectId: string): Promise<BehaviorDefinition[]> {
    const params = new URLSearchParams({ project_id: projectId });
    const body = await this.get<{ data: BehaviorDefinition[] }>(`/v1/behaviors?${params.toString()}`);
    return body.data;
  }

  async createBehavior(
    projectId: string,
    request: {
      name: string;
      description?: string;
      severity: string;
      detector: Record<string, unknown>;
    }
  ): Promise<BehaviorDefinition> {
    return this.post<BehaviorDefinition>("/v1/behaviors", {
      project_id: projectId,
      name: request.name,
      description: request.description || null,
      severity: request.severity,
      detector: request.detector
    });
  }

  async backtestBehavior(
    projectId: string,
    behaviorId: string,
    request: { status?: string; query?: string; limit?: number; sampleLimit?: number }
  ): Promise<BehaviorBacktestResult> {
    const filters: Record<string, unknown> = {};
    if (request.status) filters.status = request.status;
    return this.post<BehaviorBacktestResult>(`/v1/behaviors/${behaviorId}/backtest`, {
      project_id: projectId,
      filters,
      query: request.query || null,
      limit: request.limit ?? 100,
      sample_limit: request.sampleLimit ?? 10
    });
  }

  async getJudge(projectId: string, judgeId: string): Promise<JudgeDefinition> {
    const params = new URLSearchParams({ project_id: projectId });
    return this.get<JudgeDefinition>(`/v1/judges/${judgeId}?${params.toString()}`);
  }

  async getJudgeCalibrationReport(projectId: string, judgeId: string): Promise<JudgeCalibrationReport> {
    const params = new URLSearchParams({ project_id: projectId });
    return this.get<JudgeCalibrationReport>(`/v1/judges/${judgeId}/calibration-report?${params.toString()}`);
  }

  async promoteJudge(
    projectId: string,
    judgeId: string,
    promotionPolicy: Record<string, unknown>
  ): Promise<JudgePromotionResult> {
    return this.post<JudgePromotionResult>(`/v1/judges/${judgeId}/promote`, {
      project_id: projectId,
      promotion_policy: promotionPolicy
    });
  }

  async listEvalRuns(projectId: string): Promise<EvalRun[]> {
    const params = new URLSearchParams({ project_id: projectId });
    const body = await this.get<{ data: EvalRun[] }>(`/v1/evals?${params.toString()}`);
    return body.data;
  }

  async getEvalRun(projectId: string, evalRunId: string): Promise<EvalRun> {
    const params = new URLSearchParams({ project_id: projectId });
    return this.get<EvalRun>(`/v1/evals/${evalRunId}?${params.toString()}`);
  }

  async listEvalResults(projectId: string, evalRunId: string): Promise<EvalResult[]> {
    const params = new URLSearchParams({ project_id: projectId });
    const body = await this.get<{ data: EvalResult[] }>(`/v1/evals/${evalRunId}/results?${params.toString()}`);
    return body.data;
  }

  async runEval(
    projectId: string,
    datasetVersionId: string,
    judgeIds: string[],
    baselineEvalRunId?: string
  ): Promise<EvalRun> {
    return this.post<EvalRun>("/v1/evals/run", {
      project_id: projectId,
      dataset_version_id: datasetVersionId,
      judge_ids: judgeIds,
      baseline_eval_run_id: baselineEvalRunId || null
    });
  }

  async compareEvalRuns(
    projectId: string,
    baselineEvalRunId: string,
    candidateEvalRunId: string
  ): Promise<EvalComparison> {
    return this.post<EvalComparison>("/v1/evals/compare", {
      project_id: projectId,
      baseline_eval_run_id: baselineEvalRunId,
      candidate_eval_run_id: candidateEvalRunId
    });
  }

  async listDatasets(projectId: string): Promise<DatasetDefinition[]> {
    const params = new URLSearchParams({ project_id: projectId });
    const body = await this.get<{ data: DatasetDefinition[] }>(`/v1/datasets?${params.toString()}`);
    return body.data;
  }

  async getDataset(projectId: string, datasetId: string): Promise<DatasetDefinition> {
    const params = new URLSearchParams({ project_id: projectId });
    return this.get<DatasetDefinition>(`/v1/datasets/${datasetId}?${params.toString()}`);
  }

  async createDataset(projectId: string, name: string, description?: string): Promise<DatasetDefinition> {
    return this.post<DatasetDefinition>("/v1/datasets", {
      project_id: projectId,
      name,
      description: description || null
    });
  }

  async listDatasetExamples(projectId: string, datasetId: string): Promise<DatasetExample[]> {
    const params = new URLSearchParams({ project_id: projectId });
    const body = await this.get<{ data: DatasetExample[] }>(`/v1/datasets/${datasetId}/examples?${params.toString()}`);
    return body.data;
  }

  async addTraceToDataset(
    projectId: string,
    datasetId: string,
    traceId: string,
    labels: string[]
  ): Promise<DatasetExample> {
    return this.post<DatasetExample>(`/v1/datasets/${datasetId}/examples/from-trace`, {
      project_id: projectId,
      trace_id: traceId,
      labels
    });
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
