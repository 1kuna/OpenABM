export type TraceStatus = "ok" | "error" | "cancelled" | "timeout" | "incomplete" | "unknown";

export interface TraceEnvelope {
  trace_id: string;
  project_id: string;
  session_id: string | null;
  user_external_id: string | null;
  root_span_id: string | null;
  environment: string;
  status: TraceStatus;
  started_at: string;
  ended_at: string | null;
  tags: string[];
  attributes: Record<string, unknown>;
  prompt_version_id: string | null;
  agent_config_version_id: string | null;
  deployment_context_id: string | null;
  tool_version_ids: string[];
  summary: string | null;
}

export interface SpanEnvelope {
  trace_id: string;
  span_id: string;
  parent_span_id: string | null;
  project_id: string;
  name: string;
  span_type: string;
  status: TraceStatus;
  started_at: string;
  ended_at: string | null;
  input: PayloadState | null;
  output: PayloadState | null;
  attributes: Record<string, unknown>;
  events: Array<{ name: string; time: string; attributes: Record<string, unknown> }>;
  links: Record<string, unknown>[];
}

export interface PayloadState {
  mode: string;
  value?: unknown;
  payload_id?: string;
  redaction_state?: string;
}

export interface TraceDetail {
  trace: TraceEnvelope;
  spans: SpanEnvelope[];
  reconstruction: {
    span_tree: SpanNode[];
    timeline_rows: TimelineRow[];
    missing_parent_group: SpanNode[];
    incomplete_span_ids: string[];
    warnings: Array<Record<string, unknown>>;
    payload_availability: Record<string, { input: string; output: string }>;
  };
}

export interface SimilarTraceMatch {
  trace_id: string;
  similarity_score: number;
  rationale: string;
  evidence_span_ids: string[];
}

export interface SimilarTraceSearchResult {
  data: SimilarTraceMatch[];
  disabled: boolean;
  reason?: string | null;
  representation_version: string | null;
  model_metadata?: Record<string, unknown>;
  request: Record<string, unknown>;
  page: { limit: number; next_cursor: string | null; has_more: boolean };
}

export interface TraceAssertionResult {
  status: "passed" | "failed";
  failures: Array<Record<string, unknown>>;
  observed: Record<string, unknown>;
}

export interface SpanNode {
  span: SpanEnvelope;
  children: SpanNode[];
  payload_state: { input: string; output: string };
}

export interface TimelineRow {
  span_id: string;
  parent_span_id: string | null;
  name: string;
  span_type: string;
  status: TraceStatus;
  started_at: string;
  ended_at: string | null;
}

export interface Project {
  project_id: string;
  name: string;
  created_at: string;
}

export interface DatasetDefinition {
  dataset_id: string;
  project_id: string;
  name: string;
  description: string | null;
  status: string;
  created_at: string;
  latest_version_id: string;
}

export interface DatasetExample {
  dataset_example_id: string;
  dataset_id: string;
  dataset_version_id: string;
  source_trace_id: string;
  source_span_id: string | null;
  input: unknown;
  expected_output: unknown;
  expected_scores: unknown[];
  labels: string[];
  metadata: Record<string, unknown>;
  split: string;
  created_from: string;
  created_at: string;
}

export interface SavedSearch {
  saved_search_id: string;
  project_id: string;
  name: string;
  query: Record<string, unknown>;
  owner_user_id: string | null;
  visibility: "private" | "project";
  query_contract_version: string;
  created_at: string;
  updated_at: string;
}

export interface BehaviorDefinition {
  behavior_id: string;
  project_id: string;
  name: string;
  description: string | null;
  severity: string;
  detector: Record<string, unknown>;
  status: string;
  created_at: string;
}

export interface BehaviorBacktestResult {
  status: string;
  behavior_id: string;
  detector_type: string;
  trace_count: number;
  positive_count: number;
  negative_count: number;
  detection_rate: number;
  positive_examples: Array<{ trace_id: string; evidence_span_ids: string[]; reason: string }>;
  negative_examples: Array<{ trace_id: string; evidence_span_ids: string[]; reason: string }>;
  review_required: boolean;
  unsupported_reason: string | null;
  cost: Record<string, unknown>;
  persisted_behavior_matches?: Array<Record<string, unknown>>;
  review_task?: ReviewTask;
}

export interface BehaviorMatch {
  behavior_match_id: string;
  project_id: string;
  behavior_id: string;
  trace_id: string;
  span_id: string | null;
  score_id: string | null;
  status: string;
  evidence_span_ids: string[];
  created_at: string;
}

export interface LabelTraceBehaviorResult {
  trace: TraceEnvelope;
  behavior_match: BehaviorMatch;
}

export interface ScoreResult {
  score_id: string;
  trace_id: string;
  span_id: string | null;
  judge_id: string;
  judge_version_id: string | null;
  status: string;
  value: unknown;
  confidence: number | null;
  reasoning: string | null;
  evidence_span_ids: string[];
  failure_mode: string | null;
  cost: Record<string, unknown> | null;
  latency_ms: number | null;
  created_at: string;
}

export interface PromptDefinition {
  prompt_id: string;
  project_id: string;
  name: string;
  description: string | null;
  tags: Record<string, string>;
  created_at: string;
  updated_at: string;
  versions?: PromptVersion[];
}

export interface PromptVersion {
  prompt_version_id: string;
  prompt_id: string;
  commit_id: string;
  parent_commit_id: string | null;
  template_text: string;
  variables_schema: Record<string, unknown>;
  metadata: Record<string, unknown>;
  created_at: string;
}

export interface PromptDiffResult {
  prompt_id: string;
  old_commit_id: string;
  new_commit_id: string;
  text_diff: string;
  variables_schema_changed: boolean;
}

export interface AgentConfigDefinition {
  agent_config_id: string;
  project_id: string;
  name: string;
  config_type: string;
  created_at: string;
  versions?: AgentConfigVersion[];
}

export interface AgentConfigVersion {
  agent_config_version_id: string;
  agent_config_id: string;
  version: number;
  commit_id: string;
  content: Record<string, unknown>;
  metadata: Record<string, unknown>;
  created_at: string;
}

export interface AgentConfigCompareResult {
  agent_config_id: string;
  old_commit_id: string;
  new_commit_id: string;
  content_diff: string;
  metadata_changed: boolean;
}

export interface HealthStatus {
  status: string;
  service: string;
  details: Record<string, unknown>;
}

export interface RetentionPolicy {
  retention_policy_id: string;
  project_id: string;
  name: string;
  rules: Array<Record<string, unknown>>;
  status: "draft" | "active" | "paused" | "archived";
  created_at: string;
  updated_at: string;
}

export interface RetentionApplyResult {
  retention_policy_id: string;
  project_id: string;
  dry_run: boolean;
  status: "planned" | "applied";
  evaluated_rules: Array<Record<string, unknown>>;
  candidate_trace_ids: string[];
  deleted_trace_ids: string[];
  effects: Array<Record<string, unknown>>;
  created_at: string;
}

export interface ProjectExportManifest {
  export_id: string;
  project_id: string;
  created_at: string;
  include_payloads: boolean;
  included_classifications: string[];
  sections: Record<string, { count: number; sha256: string }>;
}

export interface ProjectExportBundle {
  metadata: Record<string, unknown>;
  manifest: ProjectExportManifest;
  [section: string]: unknown;
}

export interface DataClassificationPolicy {
  policy_id: string;
  project_id: string;
  default_classification: string;
  rules: Array<Record<string, unknown>>;
  created_at: string;
  updated_at: string;
}

export interface ClassificationResult {
  classification: string;
  matched_rules: Array<Record<string, unknown>>;
  payload?: unknown;
}

export interface IssueDefinition {
  issue_id: string;
  project_id: string;
  source_type: "manual" | "chat" | "screenshot" | "support_ticket" | "trace_link" | "webhook" | "alert";
  source_ref_nullable: string | null;
  reporter_nullable: string | null;
  title: string;
  description: string;
  screenshot_payload_id_nullable: string | null;
  seed_trace_id_nullable: string | null;
  seed_session_id_nullable: string | null;
  status: "open" | "investigating" | "behavior_created" | "fixed" | "archived";
  created_at: string;
  updated_at: string;
}

export interface IssueLink {
  issue_link_id: string;
  project_id: string;
  issue_id: string;
  target_type: string;
  target_id: string;
  relation: string;
  source: string;
  evidence_trace_ids: string[];
  evidence_span_ids: string[];
  metadata: Record<string, unknown>;
  created_at: string;
}

export interface ScreenshotIssueResult extends IssueDefinition {
  candidate_seed_traces: Array<Record<string, unknown>>;
  intake_evidence: Record<string, unknown>;
}

export interface ImpactReport {
  report_id: string;
  project_id: string;
  issue_id: string | null;
  investigation_run_id: string | null;
  time_window: Record<string, unknown>;
  matching_trace_count: number;
  affected_session_count: number;
  affected_entity_count: number;
  affected_entities: Array<Record<string, unknown>>;
  task_type_distribution: Record<string, unknown>;
  dimension_distribution: Record<string, unknown>;
  behavior_distribution: Record<string, unknown>;
  deployment_distribution: Record<string, unknown>;
  suspected_root_causes: Array<Record<string, unknown>>;
  representative_trace_ids: string[];
  generated_summary: string;
  created_at: string;
}

export interface InvestigationRun {
  investigation_run_id: string;
  project_id: string;
  issue_id_nullable: string | null;
  seed_trace_id_nullable: string | null;
  seed_session_id_nullable: string | null;
  natural_language_problem_nullable: string | null;
  time_window: Record<string, unknown>;
  filters: Record<string, unknown>;
  allowed_tools: string[];
  status: "queued" | "running" | "completed" | "failed";
  result: Record<string, unknown> & { impact_report?: ImpactReport };
  created_at: string;
  updated_at: string;
}

export interface AgentContextPack {
  context_pack_id: string;
  project_id: string;
  issue_id_nullable: string | null;
  source_trace_ids: string[];
  content: Record<string, unknown>;
  classification: string;
  created_at: string;
}

export interface ChatOpsInvestigationResult {
  status: string;
  response: string;
  issue: IssueDefinition;
  investigation_run: InvestigationRun;
  links: Record<string, string>;
}

export interface NotificationTarget {
  target_id: string;
  project_id: string;
  type: "chat" | "email" | "webhook" | "issue_tracker" | "custom";
  display_name: string;
  config_secret_refs: string[];
  created_by: string | null;
  status: "active" | "paused" | "archived";
  created_at: string;
  updated_at: string;
}

export interface AutomationDefinition {
  automation_id: string;
  project_id: string;
  name: string;
  trigger: Record<string, unknown>;
  conditions: Record<string, unknown>;
  actions: Array<Record<string, unknown>>;
  cooldown: Record<string, unknown> | null;
  status: "draft" | "active" | "paused" | "archived";
  created_at: string;
  updated_at: string;
}

export interface AutomationRun {
  automation_run_id: string;
  automation_id: string;
  project_id: string;
  trigger_entity_type: string | null;
  trigger_entity_id: string | null;
  idempotency_key: string | null;
  trace_id?: string | null;
  cooldown_key?: string | null;
  status: "succeeded" | "failed" | "partial_failure" | "skipped" | "skipped_conditions" | "skipped_cooldown" | "dead_lettered";
  condition_result: Record<string, unknown>;
  condition_results?: Array<Record<string, unknown>>;
  cooldown_result: Record<string, unknown>;
  action_results: Array<Record<string, unknown>>;
  started_at: string;
  completed_at: string | null;
  ended_at?: string | null;
  duplicate?: boolean;
}

export interface AutomationPreviewMatch {
  trace_id: string;
  session_id: string | null;
  status: string | null;
  started_at: string | null;
  condition_result: Record<string, unknown>;
}

export interface AutomationPreviewResult {
  automation_id: string;
  project_id: string;
  trace_count: number;
  match_count: number;
  matches: AutomationPreviewMatch[];
}

export interface AuthContract {
  active_auth_mode: string;
  supported_auth_modes: string[];
  session_cookie_policy: Record<string, unknown>;
  csrf_policy: Record<string, unknown>;
  password_or_passwordless_decision: string;
  external_identity_provider_integration_point: Record<string, unknown>;
  role_matrix: Record<string, string[]>;
  decision_records: Array<Record<string, unknown>>;
}

export interface AuthApiKey {
  api_key_id: string;
  project_id: string;
  name: string;
  actor_id: string | null;
  actor_type: string;
  role: string;
  scopes: string[];
  status: string;
  last_used_at: string | null;
  expires_at: string | null;
  revoked_at: string | null;
  created_at: string;
  updated_at: string;
  api_key?: string;
}

export interface AuthUser {
  user_id: string;
  email: string;
  display_name: string | null;
  auth_provider: string;
  external_subject: string | null;
  status: string;
  created_at: string;
  updated_at: string;
  membership?: Record<string, unknown>;
}

export interface AuthInvite {
  invite_id: string;
  org_id: string;
  project_id: string;
  email: string;
  role: string;
  status: string;
  invited_by: string | null;
  expires_at: string | null;
  accepted_at: string | null;
  created_at: string;
  updated_at: string;
}

export interface AuthSession {
  auth_session_id: string;
  user_id: string;
  email: string;
  display_name: string | null;
  org_id: string;
  project_id: string;
  cookie_policy: Record<string, unknown>;
  ip_hint: string | null;
  user_agent_hint: string | null;
  status: string;
  expires_at: string;
  revoked_at: string | null;
  created_at: string;
  updated_at: string;
  session_token?: string;
  csrf_token?: string;
}

export interface SecretBackendStatus {
  active_mode: string;
  local_development_secret_mode: Record<string, unknown>;
  production_external_secret_manager_integration_point: Record<string, unknown>;
  secret_refs_only_in_configs: boolean;
  plaintext_storage: boolean;
  sandbox_mount_default: string;
}

export interface SecretRef {
  secret_ref: string;
  org_id: string;
  project_id: string;
  purpose: string;
  provider: string | null;
  status: string;
  current_version: number;
  encryption_mode: string;
  ciphertext_sha256: string;
  has_value: boolean;
  redacted_value: string;
  rotation_due_at: string | null;
  rotated_at: string | null;
  created_at: string;
  updated_at: string;
  deleted_at: string | null;
}

export interface SecretAccessLogEntry {
  secret_access_id: string;
  project_id: string;
  secret_ref: string;
  actor_id: string | null;
  action: string;
  purpose: string | null;
  created_at: string;
}

export interface MetricObservation {
  count: number;
  sum: number;
  max: number;
  avg: number;
}

export interface MetricsSnapshot {
  counters: Record<string, number>;
  gauges: Record<string, number>;
  observations: Record<string, MetricObservation>;
}

export interface WorkerHeartbeat {
  worker_id: string;
  project_id: string | null;
  worker_type: string;
  status: string;
  queue_depth: number;
  details: Record<string, unknown>;
  last_seen_at: string;
}

export interface OpsStatus {
  project_id: string;
  generated_at: string;
  storage_growth: Record<string, number>;
  payload_store_growth: {
    object_count: number;
    total_bytes: number;
  };
  queue_depth: Record<string, number>;
  retention_job_status: Record<string, unknown> | null;
  automation_action_failures: number;
  dead_letter_count: number;
  worker_heartbeats: WorkerHeartbeat[];
  worker_health: Array<{
    worker_id: string;
    worker_type: string;
    status: string;
    reported_status: string;
    queue_depth: number;
    last_seen_at: string;
    last_seen_age_seconds: number | null;
    stale_after_seconds: number;
  }>;
  stale_worker_count: number;
  mcp_tool_observability: {
    total_calls: number;
    error_count: number;
    tools: Array<{
      tool_name: string;
      call_count: number;
      error_count: number;
      avg_latency_ms: number;
      max_latency_ms: number;
    }>;
  };
  metrics?: MetricsSnapshot;
}

export interface JudgeDefinition {
  judge_id: string;
  project_id: string;
  name: string;
  description: string | null;
  judge_type: string;
  status: string;
  versions?: JudgeVersion[];
}

export interface JudgeVersion {
  judge_version_id: string;
  judge_id: string;
  version: number;
  definition: Record<string, unknown>;
  created_at: string;
}

export interface JudgeCalibrationReport {
  judge_id: string;
  project_id: string;
  score_count: number;
  eval_run_ids: string[];
  verdict_counts: Record<string, number>;
  status_counts: Record<string, number>;
  invalid_output_rate: number | null;
  avg_score: number | null;
  latency_ms: { avg: number | null; total: number };
  token_usage: number | null;
  human_review_labels: Record<string, number>;
  false_positive_reports: number;
  false_negative_reports: number;
  drift_report: Array<Record<string, unknown>>;
}

export interface JudgePromotionResult {
  status: "promoted" | "blocked";
  judge_id?: string;
  project_id?: string;
  judge?: JudgeDefinition;
  promotion_policy: Record<string, unknown>;
  blocking_reasons: string[];
  calibration_report: JudgeCalibrationReport;
}

export interface EvalRun {
  eval_run_id: string;
  project_id: string;
  dataset_version_id: string;
  baseline_eval_run_id: string | null;
  runner: Record<string, unknown>;
  judges: Array<Record<string, unknown>>;
  prompt_version_id: string | null;
  agent_config_version_id: string | null;
  runtime_context: Record<string, unknown>;
  status: string;
  summary: Record<string, unknown>;
  created_at: string;
  completed_at: string | null;
}

export interface EvalResult {
  eval_result_id: string;
  project_id: string;
  eval_run_id: string;
  dataset_example_id: string;
  offline_trace_id: string;
  status: string;
  scores: Array<Record<string, unknown>>;
  cost: Record<string, unknown> | null;
  latency_ms: number;
  created_at: string;
}

export interface EvalComparison {
  baseline_eval_run_id: string;
  candidate_eval_run_id: string;
  baseline_summary: Record<string, unknown>;
  candidate_summary: Record<string, unknown>;
  pass_rate_delta: number;
  avg_score_delta: number | null;
  new_failures: string[];
  fixed_failures: string[];
  unchanged_failures: string[];
  invalid_judge_output_delta: number;
  cost_delta: number | null;
  latency_delta: number;
  token_delta: number | null;
  behavior_distribution_shift: Record<string, unknown>;
  provenance_comparison: Record<string, unknown>;
}

export interface DocsSearchResult {
  path: string;
  line: number;
  snippet: string;
  score: number;
  reason: string;
}

export interface ReviewTask {
  review_task_id: string;
  project_id: string;
  task_type: string;
  source_entity_type: string;
  source_entity_id: string;
  assigned_to_nullable: string | null;
  status: "open" | "accepted" | "rejected" | "needs_more_evidence" | "resolved";
  decision_nullable: string | null;
  notes_nullable: string | null;
  evidence_ids: string[];
  created_at: string;
  updated_at: string;
}
