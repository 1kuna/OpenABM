PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS novel_behavior_detection_runs (
  novelty_run_id TEXT PRIMARY KEY,
  project_id TEXT NOT NULL,
  input_json TEXT NOT NULL,
  result_json TEXT NOT NULL,
  status TEXT NOT NULL,
  created_at TEXT NOT NULL
);
