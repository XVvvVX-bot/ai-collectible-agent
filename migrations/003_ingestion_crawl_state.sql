CREATE TABLE IF NOT EXISTS ingestion_crawl_state (
  source_platform TEXT NOT NULL,
  fetch_status TEXT NOT NULL,
  next_page INTEGER NOT NULL DEFAULT 1,
  updated_at TEXT NOT NULL DEFAULT (datetime('now')),
  PRIMARY KEY (source_platform, fetch_status)
);
