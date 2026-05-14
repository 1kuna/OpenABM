PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS now_events (
  now_event_id TEXT PRIMARY KEY,
  project_id TEXT NOT NULL,
  event_type TEXT NOT NULL,
  cluster_key TEXT NOT NULL,
  title TEXT NOT NULL,
  summary TEXT NOT NULL,
  severity TEXT NOT NULL,
  trend TEXT NOT NULL,
  stage TEXT NOT NULL,
  recommendation_json TEXT NOT NULL,
  source_trace_ids_json TEXT NOT NULL,
  target_view TEXT NOT NULL,
  action_results_json TEXT NOT NULL DEFAULT '[]',
  verification_json TEXT NOT NULL DEFAULT '{}',
  applied_at TEXT,
  closed_at TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  UNIQUE(project_id, cluster_key, event_type)
);

CREATE INDEX IF NOT EXISTS idx_now_events_project_stage_updated
  ON now_events(project_id, stage, updated_at);
