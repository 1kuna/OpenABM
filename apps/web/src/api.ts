import type {
  AgentConfigCompareResult,
  AgentConfigDefinition,
  AgentConfigVersion,
  AgentContextPack,
  AuthApiKey,
  AuthContract,
  AuthInvite,
  AuthSession,
  AuthUser,
  AutomationDefinition,
  AutomationPreviewResult,
  AutomationRun,
  BehaviorBacktestResult,
  BehaviorDefinition,
  BehaviorMatch,
  ChatOpsInvestigationResult,
  ClassificationResult,
  DataClassificationPolicy,
  DatasetDefinition,
  DatasetExample,
  DocsSearchResult,
  EvalComparison,
  EvalResult,
  EvalRun,
  HealthStatus,
  ImpactReport,
  InvestigationRun,
  IssueDefinition,
  JudgeCalibrationReport,
  JudgeDefinition,
  JudgePromotionResult,
  JudgeVersion,
  LabelTraceBehaviorResult,
  NotificationTarget,
  Project,
  ProjectExportBundle,
  PromptDefinition,
  PromptDiffResult,
  PromptVersion,
  RetentionApplyResult,
  RetentionPolicy,
  ReviewTask,
  SavedSearch,
  ScoreResult,
  ScreenshotIssueResult,
  SecretAccessLogEntry,
  SecretBackendStatus,
  SecretRef,
  SimilarTraceSearchResult,
  TraceDetail,
  TraceEnvelope,
  TraceAssertionResult
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

  async getHealth(): Promise<HealthStatus> {
    return this.get<HealthStatus>("/health");
  }

  async getReady(): Promise<HealthStatus> {
    return this.get<HealthStatus>("/ready");
  }

  async getMetricsText(): Promise<string> {
    return this.getText("/metrics");
  }

  async getAuthContract(): Promise<AuthContract> {
    return this.get<AuthContract>("/v1/auth/contract");
  }

  async listAuthApiKeys(projectId: string): Promise<AuthApiKey[]> {
    const params = new URLSearchParams({ project_id: projectId });
    const body = await this.get<{ data: AuthApiKey[] }>(`/v1/auth/api-keys?${params.toString()}`);
    return body.data;
  }

  async createAuthApiKey(
    projectId: string,
    name: string,
    role: string,
    scopes: string[] = ["*"]
  ): Promise<AuthApiKey> {
    return this.post<AuthApiKey>("/v1/auth/api-keys", {
      project_id: projectId,
      name,
      role,
      scopes
    });
  }

  async revokeAuthApiKey(projectId: string, apiKeyId: string): Promise<AuthApiKey> {
    return this.post<AuthApiKey>(`/v1/auth/api-keys/${apiKeyId}/revoke`, {
      project_id: projectId
    });
  }

  async listAuthUsers(projectId: string): Promise<AuthUser[]> {
    const params = new URLSearchParams({ project_id: projectId });
    const body = await this.get<{ data: AuthUser[] }>(`/v1/auth/users?${params.toString()}`);
    return body.data;
  }

  async createAuthUser(projectId: string, email: string, role: string): Promise<AuthUser> {
    return this.post<AuthUser>("/v1/auth/users", {
      project_id: projectId,
      email,
      role
    });
  }

  async listAuthInvites(projectId: string): Promise<AuthInvite[]> {
    const params = new URLSearchParams({ project_id: projectId });
    const body = await this.get<{ data: AuthInvite[] }>(`/v1/auth/invites?${params.toString()}`);
    return body.data;
  }

  async createAuthInvite(projectId: string, email: string, role: string): Promise<AuthInvite> {
    return this.post<AuthInvite>("/v1/auth/invites", {
      project_id: projectId,
      email,
      role
    });
  }

  async listAuthSessions(projectId: string): Promise<AuthSession[]> {
    const params = new URLSearchParams({ project_id: projectId });
    const body = await this.get<{ data: AuthSession[] }>(`/v1/auth/sessions?${params.toString()}`);
    return body.data;
  }

  async createAuthSession(projectId: string, userId: string): Promise<AuthSession> {
    return this.post<AuthSession>("/v1/auth/sessions", {
      project_id: projectId,
      user_id: userId
    });
  }

  async revokeAuthSession(projectId: string, sessionId: string): Promise<AuthSession> {
    return this.post<AuthSession>(`/v1/auth/sessions/${sessionId}/revoke`, {
      project_id: projectId
    });
  }

  async getSecretBackend(): Promise<SecretBackendStatus> {
    return this.get<SecretBackendStatus>("/v1/secrets/backend");
  }

  async listSecretRefs(projectId: string): Promise<SecretRef[]> {
    const params = new URLSearchParams({ project_id: projectId });
    const body = await this.get<{ data: SecretRef[] }>(`/v1/secrets?${params.toString()}`);
    return body.data;
  }

  async createSecretRef(projectId: string, purpose: string, value: string): Promise<SecretRef> {
    return this.post<SecretRef>("/v1/secrets", {
      project_id: projectId,
      purpose,
      value
    });
  }

  async rotateSecretRef(projectId: string, secretRef: string, value: string): Promise<SecretRef> {
    return this.post<SecretRef>(`/v1/secrets/${encodeURIComponent(secretRef)}/rotate`, {
      project_id: projectId,
      value
    });
  }

  async listSecretAccessLog(projectId: string, secretRef: string): Promise<SecretAccessLogEntry[]> {
    const params = new URLSearchParams({ project_id: projectId });
    const body = await this.get<{ data: SecretAccessLogEntry[] }>(
      `/v1/secrets/${encodeURIComponent(secretRef)}/access-log?${params.toString()}`
    );
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

  async searchSimilar(projectId: string, sourceId: string): Promise<SimilarTraceSearchResult> {
    return this.post<SimilarTraceSearchResult>("/v1/search/similar", {
      project_id: projectId,
      source_id: sourceId,
      source_type: "trace"
    });
  }

  async checkTraceAssertions(
    projectId: string,
    traceId: string,
    assertions: Record<string, unknown>
  ): Promise<TraceAssertionResult> {
    return this.post<TraceAssertionResult>(`/v1/traces/${traceId}/assertions/check`, {
      project_id: projectId,
      assertions
    });
  }

  async listIssues(projectId: string): Promise<IssueDefinition[]> {
    const params = new URLSearchParams({ project_id: projectId });
    const body = await this.get<{ data: IssueDefinition[] }>(`/v1/issues?${params.toString()}`);
    return body.data;
  }

  async getIssue(projectId: string, issueId: string): Promise<IssueDefinition> {
    const params = new URLSearchParams({ project_id: projectId });
    return this.get<IssueDefinition>(`/v1/issues/${issueId}?${params.toString()}`);
  }

  async createIssue(
    projectId: string,
    request: {
      title: string;
      description?: string;
      sourceType?: string;
      seedTraceId?: string;
      seedSessionId?: string;
    }
  ): Promise<IssueDefinition> {
    return this.post<IssueDefinition>("/v1/issues", {
      project_id: projectId,
      title: request.title,
      description: request.description || "",
      source_type: request.sourceType || "manual",
      seed_trace_id_nullable: request.seedTraceId || null,
      seed_session_id_nullable: request.seedSessionId || null
    });
  }

  async createIssueFromScreenshot(
    projectId: string,
    request: {
      title: string;
      screenshotPayloadId: string;
      extractedText?: string;
      description?: string;
    }
  ): Promise<ScreenshotIssueResult> {
    return this.post<ScreenshotIssueResult>("/v1/issues/from-screenshot", {
      project_id: projectId,
      title: request.title,
      description: request.description || null,
      screenshot_payload_id_nullable: request.screenshotPayloadId,
      extracted_text: request.extractedText || null
    });
  }

  async chatopsInvestigate(
    projectId: string,
    message: string,
    seedTraceId?: string,
    seedSessionId?: string
  ): Promise<ChatOpsInvestigationResult> {
    return this.post<ChatOpsInvestigationResult>("/v1/chatops/investigate", {
      project_id: projectId,
      message,
      seed_trace_id_nullable: seedTraceId || null,
      seed_session_id_nullable: seedSessionId || null
    });
  }

  async listInvestigations(projectId: string, issueId?: string): Promise<InvestigationRun[]> {
    const params = new URLSearchParams({ project_id: projectId });
    if (issueId) params.set("issue_id", issueId);
    const body = await this.get<{ data: InvestigationRun[] }>(`/v1/investigations?${params.toString()}`);
    return body.data;
  }

  async getInvestigation(projectId: string, investigationRunId: string): Promise<InvestigationRun> {
    const params = new URLSearchParams({ project_id: projectId });
    return this.get<InvestigationRun>(`/v1/investigations/${investigationRunId}?${params.toString()}`);
  }

  async startInvestigation(
    projectId: string,
    request: {
      issueId?: string;
      seedTraceId?: string;
      seedSessionId?: string;
      problem?: string;
      filters?: Record<string, unknown>;
    }
  ): Promise<InvestigationRun> {
    return this.post<InvestigationRun>("/v1/investigations", {
      project_id: projectId,
      issue_id_nullable: request.issueId || null,
      seed_trace_id_nullable: request.seedTraceId || null,
      seed_session_id_nullable: request.seedSessionId || null,
      natural_language_problem_nullable: request.problem || null,
      filters: request.filters || {}
    });
  }

  async listContextPacks(projectId: string, issueId?: string): Promise<AgentContextPack[]> {
    const params = new URLSearchParams({ project_id: projectId });
    if (issueId) params.set("issue_id", issueId);
    const body = await this.get<{ data: AgentContextPack[] }>(`/v1/context-packs?${params.toString()}`);
    return body.data;
  }

  async createContextPack(
    projectId: string,
    request: {
      issueId?: string;
      sourceTraceIds: string[];
      allowedNextActions?: string[];
      classification?: string;
    }
  ): Promise<AgentContextPack> {
    return this.post<AgentContextPack>("/v1/context-packs", {
      project_id: projectId,
      issue_id_nullable: request.issueId || null,
      source_trace_ids: request.sourceTraceIds,
      allowed_next_actions: request.allowedNextActions || ["read", "draft_behavior", "draft_judge", "create_dataset"],
      classification: request.classification || "internal"
    });
  }

  async listImpactReports(projectId: string): Promise<ImpactReport[]> {
    const params = new URLSearchParams({ project_id: projectId });
    const body = await this.get<{ data: ImpactReport[] }>(`/v1/impact-reports?${params.toString()}`);
    return body.data;
  }

  async getImpactReport(projectId: string, reportId: string): Promise<ImpactReport> {
    const params = new URLSearchParams({ project_id: projectId });
    return this.get<ImpactReport>(`/v1/impact-reports/${reportId}?${params.toString()}`);
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

  async listBehaviorMatches(
    projectId: string,
    filters: string | { traceId?: string; behaviorId?: string } = {}
  ): Promise<BehaviorMatch[]> {
    const params = new URLSearchParams({ project_id: projectId });
    const normalized = typeof filters === "string" ? { traceId: filters } : filters;
    if (normalized.traceId) params.set("trace_id", normalized.traceId);
    if (normalized.behaviorId) params.set("behavior_id", normalized.behaviorId);
    const body = await this.get<{ data: BehaviorMatch[] }>(`/v1/behavior-matches?${params.toString()}`);
    return body.data;
  }

  async listScores(projectId: string, traceId?: string): Promise<ScoreResult[]> {
    const params = new URLSearchParams({ project_id: projectId });
    if (traceId) params.set("trace_id", traceId);
    const body = await this.get<{ data: ScoreResult[] }>(`/v1/scores?${params.toString()}`);
    return body.data;
  }

  async runRubricJudge(
    projectId: string,
    traceId: string,
    judge: Record<string, unknown>
  ): Promise<ScoreResult> {
    return this.post<ScoreResult>("/v1/judges/rubric/run", {
      project_id: projectId,
      trace_id: traceId,
      judge
    });
  }

  async labelTraceBehavior(
    projectId: string,
    traceId: string,
    behaviorId: string,
    spanId?: string
  ): Promise<LabelTraceBehaviorResult> {
    return this.post<LabelTraceBehaviorResult>(`/v1/traces/${traceId}/behavior-labels`, {
      project_id: projectId,
      behavior_id: behaviorId,
      span_id_nullable: spanId || null
    });
  }

  async listPrompts(projectId: string): Promise<PromptDefinition[]> {
    const params = new URLSearchParams({ project_id: projectId });
    const body = await this.get<{ data: PromptDefinition[] }>(`/v1/prompts?${params.toString()}`);
    return body.data;
  }

  async createPrompt(projectId: string, name: string, description?: string): Promise<PromptDefinition> {
    return this.post<PromptDefinition>("/v1/prompts", {
      project_id: projectId,
      name,
      description: description || null
    });
  }

  async getPrompt(projectId: string, promptId: string): Promise<PromptDefinition> {
    const params = new URLSearchParams({ project_id: projectId });
    return this.get<PromptDefinition>(`/v1/prompts/${promptId}?${params.toString()}`);
  }

  async commitPromptVersion(
    projectId: string,
    promptId: string,
    request: {
      templateText: string;
      variablesSchema: Record<string, unknown>;
      parentCommitId?: string;
      tag?: string;
    }
  ): Promise<PromptVersion> {
    return this.post<PromptVersion>(`/v1/prompts/${promptId}/versions`, {
      project_id: projectId,
      template_text: request.templateText,
      variables_schema: request.variablesSchema,
      parent_commit_id: request.parentCommitId || null,
      tag: request.tag || null
    });
  }

  async renderPrompt(
    projectId: string,
    promptId: string,
    commitId: string,
    variables: Record<string, unknown>
  ): Promise<{ prompt_id: string; commit_id: string; rendered: string }> {
    return this.post<{ prompt_id: string; commit_id: string; rendered: string }>(`/v1/prompts/${promptId}/render`, {
      project_id: projectId,
      commit_id: commitId,
      variables
    });
  }

  async diffPromptVersions(
    projectId: string,
    promptId: string,
    oldCommitId: string,
    newCommitId: string
  ): Promise<PromptDiffResult> {
    return this.post<PromptDiffResult>(`/v1/prompts/${promptId}/diff`, {
      project_id: projectId,
      old_commit_id: oldCommitId,
      new_commit_id: newCommitId
    });
  }

  async listAgentConfigs(projectId: string): Promise<AgentConfigDefinition[]> {
    const params = new URLSearchParams({ project_id: projectId });
    const body = await this.get<{ data: AgentConfigDefinition[] }>(`/v1/agent-configs?${params.toString()}`);
    return body.data;
  }

  async createAgentConfig(
    projectId: string,
    name: string,
    configType: string
  ): Promise<AgentConfigDefinition> {
    return this.post<AgentConfigDefinition>("/v1/agent-configs", {
      project_id: projectId,
      name,
      config_type: configType
    });
  }

  async getAgentConfig(projectId: string, agentConfigId: string): Promise<AgentConfigDefinition> {
    const params = new URLSearchParams({ project_id: projectId });
    return this.get<AgentConfigDefinition>(`/v1/agent-configs/${agentConfigId}?${params.toString()}`);
  }

  async commitAgentConfigVersion(
    projectId: string,
    agentConfigId: string,
    content: Record<string, unknown>,
    metadata: Record<string, unknown>
  ): Promise<AgentConfigVersion> {
    return this.post<AgentConfigVersion>(`/v1/agent-configs/${agentConfigId}/versions`, {
      project_id: projectId,
      content,
      metadata
    });
  }

  async compareAgentConfigVersions(
    projectId: string,
    agentConfigId: string,
    oldCommitId: string,
    newCommitId: string
  ): Promise<AgentConfigCompareResult> {
    return this.post<AgentConfigCompareResult>(`/v1/agent-configs/${agentConfigId}/compare`, {
      project_id: projectId,
      old_commit_id: oldCommitId,
      new_commit_id: newCommitId
    });
  }

  async listRetentionPolicies(projectId: string): Promise<RetentionPolicy[]> {
    const params = new URLSearchParams({ project_id: projectId });
    const body = await this.get<{ data: RetentionPolicy[] }>(`/v1/retention-policies?${params.toString()}`);
    return body.data;
  }

  async createRetentionPolicy(
    projectId: string,
    name: string,
    rules: Array<Record<string, unknown>>,
    status: RetentionPolicy["status"]
  ): Promise<RetentionPolicy> {
    return this.post<RetentionPolicy>("/v1/retention-policies", {
      project_id: projectId,
      name,
      rules,
      status
    });
  }

  async applyRetentionPolicy(
    projectId: string,
    retentionPolicyId: string,
    dryRun: boolean
  ): Promise<RetentionApplyResult> {
    return this.post<RetentionApplyResult>(`/v1/retention-policies/${retentionPolicyId}/apply`, {
      project_id: projectId,
      dry_run: dryRun
    });
  }

  async exportProject(projectId: string, includePayloads: boolean): Promise<ProjectExportBundle> {
    return this.post<ProjectExportBundle>("/v1/exports/project", {
      project_id: projectId,
      include_payloads: includePayloads
    });
  }

  async listDataClassificationPolicies(projectId: string): Promise<DataClassificationPolicy[]> {
    const params = new URLSearchParams({ project_id: projectId });
    const body = await this.get<{ data: DataClassificationPolicy[] }>(
      `/v1/data-classification-policies?${params.toString()}`
    );
    return body.data;
  }

  async createDataClassificationPolicy(
    projectId: string,
    defaultClassification: string,
    rules: Array<Record<string, unknown>>
  ): Promise<DataClassificationPolicy> {
    return this.post<DataClassificationPolicy>("/v1/data-classification-policies", {
      project_id: projectId,
      default_classification: defaultClassification,
      rules
    });
  }

  async classifyPayload(
    payload: Record<string, unknown>,
    policy: DataClassificationPolicy,
    maxClassification?: string
  ): Promise<ClassificationResult> {
    return this.post<ClassificationResult>("/v1/data-classification/classify", {
      payload,
      policy,
      max_classification: maxClassification || null
    });
  }

  async getJudge(projectId: string, judgeId: string): Promise<JudgeDefinition> {
    const params = new URLSearchParams({ project_id: projectId });
    return this.get<JudgeDefinition>(`/v1/judges/${judgeId}?${params.toString()}`);
  }

  async createJudgeDraft(
    projectId: string,
    request: {
      name: string;
      description?: string;
      judgeType: string;
      definition: Record<string, unknown>;
    }
  ): Promise<JudgeDefinition> {
    return this.post<JudgeDefinition>("/v1/judges/drafts", {
      project_id: projectId,
      name: request.name,
      description: request.description || null,
      judge_type: request.judgeType,
      definition: request.definition
    });
  }

  async commitJudgeVersion(
    projectId: string,
    judgeId: string,
    definition: Record<string, unknown>
  ): Promise<JudgeVersion> {
    return this.post<JudgeVersion>(`/v1/judges/${judgeId}/versions`, {
      project_id: projectId,
      definition
    });
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

  async listSavedSearches(projectId: string): Promise<SavedSearch[]> {
    const params = new URLSearchParams({ project_id: projectId });
    const body = await this.get<{ data: SavedSearch[] }>(`/v1/saved-searches?${params.toString()}`);
    return body.data;
  }

  async getSavedSearch(projectId: string, savedSearchId: string): Promise<SavedSearch> {
    const params = new URLSearchParams({ project_id: projectId });
    return this.get<SavedSearch>(`/v1/saved-searches/${savedSearchId}?${params.toString()}`);
  }

  async createSavedSearch(
    projectId: string,
    name: string,
    query: Record<string, unknown>,
    visibility: SavedSearch["visibility"] = "project"
  ): Promise<SavedSearch> {
    return this.post<SavedSearch>("/v1/saved-searches", {
      project_id: projectId,
      name,
      query,
      visibility
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

  async listNotificationTargets(projectId: string): Promise<NotificationTarget[]> {
    const params = new URLSearchParams({ project_id: projectId });
    const body = await this.get<{ data: NotificationTarget[] }>(`/v1/notification-targets?${params.toString()}`);
    return body.data;
  }

  async createNotificationTarget(
    projectId: string,
    request: {
      type: NotificationTarget["type"];
      displayName: string;
      configSecretRefs: string[];
      status?: NotificationTarget["status"];
    }
  ): Promise<NotificationTarget> {
    return this.post<NotificationTarget>("/v1/notification-targets", {
      project_id: projectId,
      type: request.type,
      display_name: request.displayName,
      config_secret_refs: request.configSecretRefs,
      status: request.status || "active"
    });
  }

  async listAutomations(projectId: string): Promise<AutomationDefinition[]> {
    const params = new URLSearchParams({ project_id: projectId });
    const body = await this.get<{ data: AutomationDefinition[] }>(`/v1/automations?${params.toString()}`);
    return body.data;
  }

  async getAutomation(projectId: string, automationId: string): Promise<AutomationDefinition> {
    const params = new URLSearchParams({ project_id: projectId });
    return this.get<AutomationDefinition>(`/v1/automations/${automationId}?${params.toString()}`);
  }

  async listAutomationRuns(projectId: string, automationId: string): Promise<AutomationRun[]> {
    const params = new URLSearchParams({ project_id: projectId, limit: "25" });
    const body = await this.get<{ data: AutomationRun[] }>(`/v1/automations/${automationId}/runs?${params.toString()}`);
    return body.data;
  }

  async previewAutomationMatches(
    projectId: string,
    automationId: string,
    request: { status?: string; query?: string; limit?: number }
  ): Promise<AutomationPreviewResult> {
    const filters: Record<string, unknown> = {};
    if (request.status) filters.status = request.status;
    return this.post<AutomationPreviewResult>(`/v1/automations/${automationId}/preview`, {
      project_id: projectId,
      filters,
      query: request.query || null,
      limit: request.limit ?? 100
    });
  }

  async createAutomation(projectId: string, request: {
    name: string;
    trigger: Record<string, unknown>;
    conditions: Record<string, unknown>;
    actions: Array<Record<string, unknown>>;
    cooldown?: Record<string, unknown> | null;
    status?: AutomationDefinition["status"];
  }): Promise<AutomationDefinition> {
    return this.post<AutomationDefinition>("/v1/automations", {
      project_id: projectId,
      name: request.name,
      trigger: request.trigger,
      conditions: request.conditions,
      actions: request.actions,
      cooldown: request.cooldown ?? null,
      status: request.status || "active"
    });
  }

  async runAutomation(
    projectId: string,
    automationId: string,
    request: { traceId?: string; idempotencyKey?: string }
  ): Promise<AutomationRun> {
    return this.post<AutomationRun>(`/v1/automations/${automationId}/run`, {
      project_id: projectId,
      trace_id: request.traceId || null,
      idempotency_key: request.idempotencyKey || null
    });
  }

  private async get<T>(path: string): Promise<T> {
    const response = await fetch(`${this.baseUrl}${path}`, {
      headers: this.headers()
    });
    return this.parse<T>(response);
  }

  private async getText(path: string): Promise<string> {
    const response = await fetch(`${this.baseUrl}${path}`, {
      headers: this.headers()
    });
    if (!response.ok) {
      throw new Error(`${response.status} ${response.statusText}`);
    }
    return response.text();
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
