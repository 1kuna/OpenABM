PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS auth_invite_deliveries (
  invite_delivery_id TEXT PRIMARY KEY,
  invite_id TEXT NOT NULL,
  project_id TEXT NOT NULL,
  delivery_channel TEXT NOT NULL,
  delivery_status TEXT NOT NULL,
  recipient_email TEXT NOT NULL,
  payload_json TEXT NOT NULL,
  error_nullable TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  FOREIGN KEY(invite_id) REFERENCES auth_invites(invite_id),
  FOREIGN KEY(project_id) REFERENCES projects(project_id)
);

CREATE INDEX IF NOT EXISTS idx_auth_invite_deliveries_project
  ON auth_invite_deliveries(project_id, delivery_status, created_at);
