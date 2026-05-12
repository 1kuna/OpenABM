PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS prompts (
  prompt_id TEXT PRIMARY KEY,
  project_id TEXT NOT NULL,
  name TEXT NOT NULL,
  description TEXT,
  tags_json TEXT NOT NULL,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS prompt_versions (
  prompt_version_id TEXT PRIMARY KEY,
  prompt_id TEXT NOT NULL,
  project_id TEXT NOT NULL,
  commit_id TEXT NOT NULL UNIQUE,
  parent_commit_id TEXT,
  template_text TEXT NOT NULL,
  variables_schema_json TEXT NOT NULL,
  metadata_json TEXT NOT NULL,
  created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS prompt_tag_events (
  prompt_tag_event_id TEXT PRIMARY KEY,
  prompt_id TEXT NOT NULL,
  project_id TEXT NOT NULL,
  tag TEXT NOT NULL,
  previous_commit_id TEXT,
  new_commit_id TEXT NOT NULL,
  created_at TEXT NOT NULL
);
