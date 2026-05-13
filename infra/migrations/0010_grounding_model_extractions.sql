PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS grounding_check_model_extractions (
  grounding_check_id TEXT PRIMARY KEY,
  project_id TEXT NOT NULL,
  model_extraction_json TEXT NOT NULL,
  created_at TEXT NOT NULL,
  FOREIGN KEY(grounding_check_id) REFERENCES grounding_checks(grounding_check_id)
);
