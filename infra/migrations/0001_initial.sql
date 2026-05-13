PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS projects (
  project_id TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS api_keys (
  api_key_id TEXT PRIMARY KEY,
  project_id TEXT NOT NULL,
  key_hash TEXT NOT NULL UNIQUE,
  scopes_json TEXT NOT NULL,
  revoked_at TEXT,
  created_at TEXT NOT NULL,
  FOREIGN KEY (project_id) REFERENCES projects(project_id)
);

CREATE TABLE IF NOT EXISTS trace_metadata (
  trace_id TEXT PRIMARY KEY,
  project_id TEXT NOT NULL,
  session_id TEXT,
  user_external_id TEXT,
  root_span_id TEXT,
  environment TEXT NOT NULL,
  status TEXT NOT NULL,
  started_at TEXT NOT NULL,
  ended_at TEXT,
  tags_json TEXT NOT NULL,
  attributes_json TEXT NOT NULL,
  prompt_version_id TEXT,
  agent_config_version_id TEXT,
  deployment_context_id TEXT,
  tool_version_ids_json TEXT NOT NULL DEFAULT '[]',
  summary TEXT,
  server_received_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_trace_metadata_project_time
  ON trace_metadata(project_id, started_at DESC);

CREATE INDEX IF NOT EXISTS idx_trace_metadata_status
  ON trace_metadata(project_id, status);

CREATE TABLE IF NOT EXISTS trace_spans (
  span_id TEXT PRIMARY KEY,
  trace_id TEXT NOT NULL,
  project_id TEXT NOT NULL,
  parent_span_id TEXT,
  name TEXT NOT NULL,
  span_type TEXT NOT NULL,
  status TEXT NOT NULL,
  started_at TEXT NOT NULL,
  ended_at TEXT,
  input_json TEXT,
  output_json TEXT,
  attributes_json TEXT NOT NULL,
  resource_json TEXT NOT NULL DEFAULT '{}',
  events_json TEXT NOT NULL,
  links_json TEXT NOT NULL,
  server_received_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_trace_spans_trace
  ON trace_spans(project_id, trace_id, started_at);

CREATE INDEX IF NOT EXISTS idx_trace_spans_parent
  ON trace_spans(project_id, parent_span_id);

CREATE INDEX IF NOT EXISTS idx_trace_spans_type
  ON trace_spans(project_id, span_type);

CREATE TABLE IF NOT EXISTS payload_objects (
  payload_id TEXT PRIMARY KEY,
  project_id TEXT NOT NULL,
  trace_id TEXT,
  span_id TEXT,
  content_type TEXT NOT NULL,
  byte_size_nullable INTEGER,
  sha256_nullable TEXT,
  redaction_state TEXT NOT NULL,
  storage_uri TEXT,
  created_at TEXT NOT NULL,
  deleted_at TEXT
);

CREATE TABLE IF NOT EXISTS scores (
  score_id TEXT PRIMARY KEY,
  project_id TEXT NOT NULL,
  trace_id TEXT NOT NULL,
  span_id TEXT,
  judge_id TEXT NOT NULL,
  judge_version_id TEXT,
  status TEXT NOT NULL,
  failure_reason TEXT,
  value_json TEXT NOT NULL,
  confidence REAL,
  reasoning TEXT,
  evidence_span_ids_json TEXT NOT NULL,
  failure_mode TEXT,
  cost_json TEXT,
  latency_ms INTEGER,
  created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_scores_trace
  ON scores(project_id, trace_id);

CREATE TABLE IF NOT EXISTS behaviors (
  behavior_id TEXT PRIMARY KEY,
  project_id TEXT NOT NULL,
  name TEXT NOT NULL,
  description TEXT,
  severity TEXT NOT NULL,
  detector_json TEXT NOT NULL,
  status TEXT NOT NULL,
  created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS behavior_matches (
  behavior_match_id TEXT PRIMARY KEY,
  project_id TEXT NOT NULL,
  behavior_id TEXT NOT NULL,
  trace_id TEXT NOT NULL,
  span_id TEXT,
  score_id TEXT,
  status TEXT NOT NULL,
  evidence_span_ids_json TEXT NOT NULL,
  created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS datasets (
  dataset_id TEXT PRIMARY KEY,
  project_id TEXT NOT NULL,
  name TEXT NOT NULL,
  description TEXT,
  status TEXT NOT NULL,
  created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS dataset_versions (
  dataset_version_id TEXT PRIMARY KEY,
  dataset_id TEXT NOT NULL,
  version INTEGER NOT NULL,
  immutable INTEGER NOT NULL DEFAULT 1,
  created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS dataset_examples (
  dataset_example_id TEXT PRIMARY KEY,
  project_id TEXT NOT NULL,
  dataset_id TEXT NOT NULL,
  dataset_version_id TEXT NOT NULL,
  source_trace_id TEXT,
  source_span_id TEXT,
  input_json TEXT,
  expected_output_json TEXT,
  expected_scores_json TEXT NOT NULL,
  labels_json TEXT NOT NULL,
  metadata_json TEXT NOT NULL,
  split TEXT NOT NULL,
  created_from TEXT NOT NULL,
  created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS audit_log (
  audit_id TEXT PRIMARY KEY,
  project_id TEXT,
  actor_id TEXT,
  action TEXT NOT NULL,
  target_type TEXT NOT NULL,
  target_id TEXT,
  metadata_json TEXT NOT NULL,
  created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS ingest_diagnostics (
  diagnostic_id TEXT PRIMARY KEY,
  project_id TEXT NOT NULL,
  trace_id TEXT,
  span_id TEXT,
  diagnostic_type TEXT NOT NULL,
  message TEXT NOT NULL,
  payload_json TEXT NOT NULL,
  created_at TEXT NOT NULL
);

CREATE VIRTUAL TABLE IF NOT EXISTS trace_search_fts USING fts5(
  trace_id UNINDEXED,
  project_id UNINDEXED,
  body
);
