PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS judges (
  judge_id TEXT PRIMARY KEY,
  project_id TEXT NOT NULL,
  name TEXT NOT NULL,
  description TEXT,
  judge_type TEXT NOT NULL,
  status TEXT NOT NULL,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  FOREIGN KEY(project_id) REFERENCES projects(project_id)
);

CREATE TABLE IF NOT EXISTS judge_versions (
  judge_version_id TEXT PRIMARY KEY,
  judge_id TEXT NOT NULL,
  project_id TEXT NOT NULL,
  version INTEGER NOT NULL,
  definition_json TEXT NOT NULL,
  created_by TEXT,
  created_at TEXT NOT NULL,
  UNIQUE(judge_id, version),
  FOREIGN KEY(judge_id) REFERENCES judges(judge_id),
  FOREIGN KEY(project_id) REFERENCES projects(project_id)
);

CREATE INDEX IF NOT EXISTS idx_judges_project_created
  ON judges(project_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_judge_versions_judge_version
  ON judge_versions(project_id, judge_id, version DESC);
