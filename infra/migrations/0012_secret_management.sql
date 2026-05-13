PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS secret_refs (
  secret_ref TEXT PRIMARY KEY,
  org_id TEXT NOT NULL,
  project_id TEXT NOT NULL,
  purpose TEXT NOT NULL,
  provider TEXT,
  status TEXT NOT NULL,
  current_version INTEGER NOT NULL,
  encryption_mode TEXT NOT NULL,
  ciphertext TEXT NOT NULL,
  ciphertext_sha256 TEXT NOT NULL,
  rotation_due_at TEXT,
  rotated_at TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  deleted_at TEXT,
  FOREIGN KEY(project_id) REFERENCES projects(project_id)
);

CREATE TABLE IF NOT EXISTS secret_versions (
  secret_version_id TEXT PRIMARY KEY,
  secret_ref TEXT NOT NULL,
  project_id TEXT NOT NULL,
  version INTEGER NOT NULL,
  encryption_mode TEXT NOT NULL,
  ciphertext TEXT NOT NULL,
  ciphertext_sha256 TEXT NOT NULL,
  created_at TEXT NOT NULL,
  UNIQUE(secret_ref, version),
  FOREIGN KEY(secret_ref) REFERENCES secret_refs(secret_ref)
);

CREATE TABLE IF NOT EXISTS secret_access_log (
  secret_access_id TEXT PRIMARY KEY,
  project_id TEXT NOT NULL,
  secret_ref TEXT NOT NULL,
  actor_id TEXT,
  action TEXT NOT NULL,
  purpose TEXT,
  created_at TEXT NOT NULL,
  FOREIGN KEY(secret_ref) REFERENCES secret_refs(secret_ref)
);

CREATE INDEX IF NOT EXISTS idx_secret_refs_project
  ON secret_refs(project_id, status, purpose);

CREATE INDEX IF NOT EXISTS idx_secret_access_project
  ON secret_access_log(project_id, secret_ref, created_at);
