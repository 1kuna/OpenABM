PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS issue_links (
  issue_link_id TEXT PRIMARY KEY,
  project_id TEXT NOT NULL,
  issue_id TEXT NOT NULL,
  target_type TEXT NOT NULL,
  target_id TEXT NOT NULL,
  relation TEXT NOT NULL,
  source TEXT NOT NULL,
  evidence_trace_ids_json TEXT NOT NULL,
  evidence_span_ids_json TEXT NOT NULL,
  metadata_json TEXT NOT NULL,
  created_at TEXT NOT NULL
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_issue_links_unique
  ON issue_links(project_id, issue_id, target_type, target_id, relation);

CREATE INDEX IF NOT EXISTS idx_issue_links_issue
  ON issue_links(project_id, issue_id, created_at);
