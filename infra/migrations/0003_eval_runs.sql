PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS eval_runs (
  eval_run_id TEXT PRIMARY KEY,
  project_id TEXT NOT NULL,
  dataset_version_id TEXT NOT NULL,
  baseline_eval_run_id TEXT,
  runner_json TEXT NOT NULL,
  judges_json TEXT NOT NULL,
  prompt_version_id TEXT,
  agent_config_version_id TEXT,
  runtime_context_json TEXT NOT NULL DEFAULT '{}',
  status TEXT NOT NULL,
  summary_json TEXT NOT NULL,
  created_at TEXT NOT NULL,
  completed_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_eval_runs_project
  ON eval_runs(project_id, created_at);

CREATE TABLE IF NOT EXISTS eval_results (
  eval_result_id TEXT PRIMARY KEY,
  project_id TEXT NOT NULL,
  eval_run_id TEXT NOT NULL,
  dataset_example_id TEXT NOT NULL,
  offline_trace_id TEXT,
  status TEXT NOT NULL,
  scores_json TEXT NOT NULL,
  cost_json TEXT,
  latency_ms INTEGER,
  created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_eval_results_run
  ON eval_results(project_id, eval_run_id);
