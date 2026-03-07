CREATE TABLE IF NOT EXISTS normalization_state (
  source_platform TEXT PRIMARY KEY,
  last_raw_rowid INTEGER NOT NULL DEFAULT 0,
  updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

