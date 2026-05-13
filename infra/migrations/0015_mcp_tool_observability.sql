PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS mcp_tool_observations (
  observation_id TEXT PRIMARY KEY,
  project_id TEXT,
  tool_name TEXT NOT NULL,
  status TEXT NOT NULL,
  latency_ms INTEGER NOT NULL,
  request_json TEXT NOT NULL DEFAULT '{}',
  response_json TEXT NOT NULL DEFAULT '{}',
  citations_json TEXT NOT NULL DEFAULT '[]',
  confirmation_required INTEGER NOT NULL DEFAULT 0,
  error_type_nullable TEXT,
  error_message_nullable TEXT,
  created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_mcp_tool_observations_project_tool
  ON mcp_tool_observations(project_id, tool_name, created_at);
