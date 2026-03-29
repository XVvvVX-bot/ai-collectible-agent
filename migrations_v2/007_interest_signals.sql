CREATE TABLE IF NOT EXISTS signal_runs_v2 (
  id TEXT PRIMARY KEY,
  user_id TEXT,
  lookback_hours INTEGER NOT NULL DEFAULT 24,
  started_at TEXT NOT NULL,
  finished_at TEXT,
  status TEXT NOT NULL DEFAULT 'running' CHECK (status IN ('running', 'success', 'failed')),
  interests_processed INTEGER NOT NULL DEFAULT 0,
  candidates INTEGER NOT NULL DEFAULT 0,
  inserted INTEGER NOT NULL DEFAULT 0,
  skipped_cooldown INTEGER NOT NULL DEFAULT 0,
  error_message TEXT,
  FOREIGN KEY (user_id) REFERENCES users(id)
);

CREATE TABLE IF NOT EXISTS signals_v2 (
  id TEXT PRIMARY KEY,
  run_id TEXT NOT NULL,
  user_id TEXT NOT NULL,
  interest_id TEXT NOT NULL,
  target_id TEXT,
  listing_id TEXT,
  signal_type TEXT NOT NULL,
  urgency TEXT NOT NULL CHECK (urgency IN ('low', 'medium', 'high')),
  reason_code TEXT NOT NULL,
  signal_title TEXT NOT NULL,
  signal_summary TEXT NOT NULL,
  group_key TEXT,
  payload_json TEXT NOT NULL,
  created_at TEXT NOT NULL,
  last_seen_at TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'inactive')),
  FOREIGN KEY (run_id) REFERENCES signal_runs_v2(id),
  FOREIGN KEY (user_id) REFERENCES users(id),
  FOREIGN KEY (interest_id) REFERENCES user_interests_v2(id),
  FOREIGN KEY (target_id) REFERENCES user_interest_targets_v2(id),
  FOREIGN KEY (listing_id) REFERENCES market_listings_norm_v2(id)
);

CREATE INDEX IF NOT EXISTS idx_signal_runs_v2_user_started
  ON signal_runs_v2 (user_id, started_at DESC);

CREATE INDEX IF NOT EXISTS idx_signals_v2_user_interest_created
  ON signals_v2 (user_id, interest_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_signals_v2_lookup
  ON signals_v2 (user_id, interest_id, signal_type, reason_code, group_key, created_at DESC);
