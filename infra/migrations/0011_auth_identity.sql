PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS orgs (
  org_id TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS auth_users (
  user_id TEXT PRIMARY KEY,
  email TEXT NOT NULL UNIQUE,
  display_name TEXT,
  auth_provider TEXT NOT NULL,
  external_subject TEXT,
  status TEXT NOT NULL,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS service_accounts (
  service_account_id TEXT PRIMARY KEY,
  org_id TEXT NOT NULL,
  project_id TEXT NOT NULL,
  name TEXT NOT NULL,
  role TEXT NOT NULL,
  status TEXT NOT NULL,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  FOREIGN KEY(project_id) REFERENCES projects(project_id)
);

CREATE TABLE IF NOT EXISTS project_memberships (
  membership_id TEXT PRIMARY KEY,
  org_id TEXT NOT NULL,
  project_id TEXT NOT NULL,
  user_id TEXT NOT NULL,
  role TEXT NOT NULL,
  status TEXT NOT NULL,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  UNIQUE(project_id, user_id),
  FOREIGN KEY(project_id) REFERENCES projects(project_id),
  FOREIGN KEY(user_id) REFERENCES auth_users(user_id)
);

CREATE TABLE IF NOT EXISTS auth_sessions (
  auth_session_id TEXT PRIMARY KEY,
  user_id TEXT NOT NULL,
  org_id TEXT NOT NULL,
  project_id TEXT NOT NULL,
  session_token_hash TEXT NOT NULL UNIQUE,
  csrf_token_hash TEXT NOT NULL,
  cookie_policy_json TEXT NOT NULL,
  ip_hint TEXT,
  user_agent_hint TEXT,
  status TEXT NOT NULL,
  expires_at TEXT NOT NULL,
  revoked_at TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  FOREIGN KEY(user_id) REFERENCES auth_users(user_id),
  FOREIGN KEY(project_id) REFERENCES projects(project_id)
);

CREATE TABLE IF NOT EXISTS auth_invites (
  invite_id TEXT PRIMARY KEY,
  org_id TEXT NOT NULL,
  project_id TEXT NOT NULL,
  email TEXT NOT NULL,
  role TEXT NOT NULL,
  status TEXT NOT NULL,
  invited_by TEXT,
  expires_at TEXT,
  accepted_at TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  FOREIGN KEY(project_id) REFERENCES projects(project_id)
);

CREATE TABLE IF NOT EXISTS auth_decision_records (
  record_id TEXT PRIMARY KEY,
  topic TEXT NOT NULL,
  decision TEXT NOT NULL,
  rationale TEXT NOT NULL,
  status TEXT NOT NULL,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_project_memberships_project
  ON project_memberships(project_id, role, status);

CREATE INDEX IF NOT EXISTS idx_auth_sessions_project
  ON auth_sessions(project_id, user_id, status);

CREATE INDEX IF NOT EXISTS idx_auth_invites_project
  ON auth_invites(project_id, status);
