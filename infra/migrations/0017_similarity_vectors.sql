PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS similarity_vectors (
  vector_id TEXT PRIMARY KEY,
  project_id TEXT NOT NULL,
  entity_type TEXT NOT NULL,
  entity_id TEXT NOT NULL,
  trace_id_nullable TEXT,
  representation_version TEXT NOT NULL,
  provider TEXT NOT NULL,
  model TEXT NOT NULL,
  dimensions INTEGER NOT NULL,
  vector_json TEXT NOT NULL,
  source_hash TEXT NOT NULL,
  source_summary_json TEXT NOT NULL,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  UNIQUE(project_id, entity_type, entity_id, representation_version)
);

CREATE INDEX IF NOT EXISTS idx_similarity_vectors_project_representation
  ON similarity_vectors(project_id, representation_version, entity_type);

CREATE INDEX IF NOT EXISTS idx_similarity_vectors_trace
  ON similarity_vectors(project_id, trace_id_nullable);
