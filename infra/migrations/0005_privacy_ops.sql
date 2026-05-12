PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS retention_policies (
  retention_policy_id TEXT PRIMARY KEY,
  project_id TEXT NOT NULL,
  name TEXT NOT NULL,
  rules_json TEXT NOT NULL,
  status TEXT NOT NULL,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
