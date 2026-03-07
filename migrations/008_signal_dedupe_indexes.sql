CREATE INDEX IF NOT EXISTS idx_signals_dedupe_lookup
  ON signals (user_id, listing_id, signal_type, reason_code, created_at);

CREATE INDEX IF NOT EXISTS idx_signals_status_created
  ON signals (status, created_at);
