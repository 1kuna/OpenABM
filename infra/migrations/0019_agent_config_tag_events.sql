PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS agent_config_tag_events (
  agent_config_tag_event_id TEXT PRIMARY KEY,
  agent_config_id TEXT NOT NULL,
  project_id TEXT NOT NULL,
  tag TEXT NOT NULL,
  previous_commit_id TEXT,
  new_commit_id TEXT NOT NULL,
  created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_agent_config_tag_events_lookup
  ON agent_config_tag_events(project_id, agent_config_id, tag, created_at);
