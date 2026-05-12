PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS trace_dimensions (
  trace_dimension_id TEXT PRIMARY KEY,
  trace_id TEXT NOT NULL,
  project_id TEXT NOT NULL,
  key TEXT NOT NULL,
  value TEXT NOT NULL,
  value_type TEXT NOT NULL,
  source TEXT NOT NULL,
  created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_trace_dimensions_lookup
  ON trace_dimensions(project_id, key, value);

CREATE TABLE IF NOT EXISTS deployment_contexts (
  deployment_context_id TEXT PRIMARY KEY,
  project_id TEXT NOT NULL,
  service_name TEXT NOT NULL,
  service_version TEXT NOT NULL,
  source_revision TEXT NOT NULL,
  branch_nullable TEXT,
  build_id_nullable TEXT,
  deploy_id_nullable TEXT,
  runtime_nullable TEXT,
  environment TEXT NOT NULL,
  created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS code_contexts (
  code_context_id TEXT PRIMARY KEY,
  project_id TEXT NOT NULL,
  trace_id TEXT NOT NULL,
  span_id_nullable TEXT,
  file_path_nullable TEXT,
  function_name_nullable TEXT,
  line_start_nullable INTEGER,
  line_end_nullable INTEGER,
  stack_frame_hash_nullable TEXT,
  source_url_nullable TEXT,
  source_revision_nullable TEXT,
  created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS saved_searches (
  saved_search_id TEXT PRIMARY KEY,
  project_id TEXT NOT NULL,
  name TEXT NOT NULL,
  query_json TEXT NOT NULL,
  owner_user_id TEXT,
  visibility TEXT NOT NULL,
  query_contract_version TEXT NOT NULL,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS review_tasks (
  review_task_id TEXT PRIMARY KEY,
  project_id TEXT NOT NULL,
  task_type TEXT NOT NULL,
  source_entity_type TEXT NOT NULL,
  source_entity_id TEXT NOT NULL,
  assigned_to_nullable TEXT,
  status TEXT NOT NULL,
  decision_nullable TEXT,
  notes_nullable TEXT,
  evidence_ids_json TEXT NOT NULL,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS notification_targets (
  target_id TEXT PRIMARY KEY,
  project_id TEXT NOT NULL,
  type TEXT NOT NULL,
  display_name TEXT NOT NULL,
  config_secret_refs_json TEXT NOT NULL,
  created_by TEXT,
  status TEXT NOT NULL,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS data_classification_policies (
  policy_id TEXT PRIMARY KEY,
  project_id TEXT NOT NULL,
  default_classification TEXT NOT NULL,
  rules_json TEXT NOT NULL,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS agent_configs (
  agent_config_id TEXT PRIMARY KEY,
  project_id TEXT NOT NULL,
  name TEXT NOT NULL,
  config_type TEXT NOT NULL,
  created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS agent_config_versions (
  agent_config_version_id TEXT PRIMARY KEY,
  agent_config_id TEXT NOT NULL,
  version INTEGER NOT NULL,
  commit_id TEXT NOT NULL,
  content_json TEXT NOT NULL,
  metadata_json TEXT NOT NULL,
  created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS issues (
  issue_id TEXT PRIMARY KEY,
  project_id TEXT NOT NULL,
  source_type TEXT NOT NULL,
  source_ref_nullable TEXT,
  reporter_nullable TEXT,
  title TEXT NOT NULL,
  description TEXT NOT NULL,
  screenshot_payload_id_nullable TEXT,
  seed_trace_id_nullable TEXT,
  seed_session_id_nullable TEXT,
  status TEXT NOT NULL,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS investigation_runs (
  investigation_run_id TEXT PRIMARY KEY,
  project_id TEXT NOT NULL,
  issue_id_nullable TEXT,
  seed_trace_id_nullable TEXT,
  seed_session_id_nullable TEXT,
  natural_language_problem_nullable TEXT,
  time_window_json TEXT NOT NULL,
  filters_json TEXT NOT NULL,
  allowed_tools_json TEXT NOT NULL,
  status TEXT NOT NULL,
  result_json TEXT NOT NULL,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS impact_reports (
  report_id TEXT PRIMARY KEY,
  project_id TEXT NOT NULL,
  issue_id TEXT,
  investigation_run_id TEXT,
  time_window_json TEXT NOT NULL,
  matching_trace_count INTEGER NOT NULL,
  affected_session_count INTEGER NOT NULL,
  affected_entity_count INTEGER NOT NULL,
  affected_entities_json TEXT NOT NULL,
  task_type_distribution_json TEXT NOT NULL,
  dimension_distribution_json TEXT NOT NULL,
  behavior_distribution_json TEXT NOT NULL,
  deployment_distribution_json TEXT NOT NULL,
  suspected_root_causes_json TEXT NOT NULL,
  representative_trace_ids_json TEXT NOT NULL,
  generated_summary TEXT NOT NULL,
  created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS affected_entities (
  affected_entity_id TEXT PRIMARY KEY,
  project_id TEXT NOT NULL,
  issue_id TEXT NOT NULL,
  entity_type TEXT NOT NULL,
  entity_id TEXT NOT NULL,
  display_name_nullable TEXT,
  trace_ids_json TEXT NOT NULL,
  status TEXT NOT NULL,
  owner_nullable TEXT,
  notes_nullable TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS agent_context_packs (
  context_pack_id TEXT PRIMARY KEY,
  project_id TEXT NOT NULL,
  issue_id_nullable TEXT,
  source_trace_ids_json TEXT NOT NULL,
  content_json TEXT NOT NULL,
  classification TEXT NOT NULL,
  created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS grounding_checks (
  grounding_check_id TEXT PRIMARY KEY,
  project_id TEXT NOT NULL,
  trace_id TEXT NOT NULL,
  span_id_nullable TEXT,
  status TEXT NOT NULL,
  claims_json TEXT NOT NULL,
  evidence_span_ids_json TEXT NOT NULL,
  created_at TEXT NOT NULL
);
