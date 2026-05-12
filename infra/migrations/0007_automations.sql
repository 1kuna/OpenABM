PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS automations (
  automation_id TEXT PRIMARY KEY,
  project_id TEXT NOT NULL,
  name TEXT NOT NULL,
  trigger_json TEXT NOT NULL,
  conditions_json TEXT NOT NULL,
  actions_json TEXT NOT NULL,
  cooldown_json TEXT,
  status TEXT NOT NULL,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS automation_runs (
  automation_run_id TEXT PRIMARY KEY,
  automation_id TEXT NOT NULL,
  project_id TEXT NOT NULL,
  trigger_entity_type TEXT,
  trigger_entity_id TEXT,
  idempotency_key TEXT,
  status TEXT NOT NULL,
  condition_result_json TEXT NOT NULL,
  action_results_json TEXT NOT NULL,
  started_at TEXT NOT NULL,
  completed_at TEXT
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_automation_runs_idempotency
  ON automation_runs(project_id, automation_id, idempotency_key)
  WHERE idempotency_key IS NOT NULL;
