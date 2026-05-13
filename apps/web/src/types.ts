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
  status: string;
  summary: Record<string, unknown>;
  created_at: string;
  completed_at: string | null;
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
