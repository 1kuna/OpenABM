PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS worker_heartbeats (
  worker_id TEXT PRIMARY KEY,
  project_id TEXT,
  worker_type TEXT NOT NULL,
  status TEXT NOT NULL,
  queue_depth INTEGER NOT NULL,
  details_json TEXT NOT NULL,
  last_seen_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_worker_heartbeats_project
  ON worker_heartbeats(project_id, worker_type, status);
