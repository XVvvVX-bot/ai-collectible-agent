CREATE TABLE IF NOT EXISTS quality_check_runs (
  id TEXT PRIMARY KEY,
  source_platform TEXT NOT NULL,
  started_at TEXT NOT NULL,
  finished_at TEXT NOT NULL,
  since_last_run INTEGER NOT NULL DEFAULT 1,
  rowid_start INTEGER NOT NULL DEFAULT 0,
  rowid_end INTEGER NOT NULL DEFAULT 0,
  rows_evaluated INTEGER NOT NULL DEFAULT 0,
  pass_count INTEGER NOT NULL DEFAULT 0,
  warning_count INTEGER NOT NULL DEFAULT 0,
  fail_count INTEGER NOT NULL DEFAULT 0,
  issue_counts_json TEXT NOT NULL,
  sample_listing_ids_json TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_quality_check_runs_platform_finished
  ON quality_check_runs (source_platform, finished_at);

CREATE TABLE IF NOT EXISTS quality_check_state (
  source_platform TEXT PRIMARY KEY,
  last_norm_rowid INTEGER NOT NULL DEFAULT 0,
  updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

