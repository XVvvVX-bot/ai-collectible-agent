CREATE TABLE IF NOT EXISTS listing_matches (
  id TEXT PRIMARY KEY,
  user_id TEXT NOT NULL,
  listing_id TEXT NOT NULL,
  user_item_id TEXT NOT NULL,
  item_type TEXT NOT NULL CHECK (item_type IN ('holding', 'watch')),
  match_score REAL NOT NULL,
  match_reasons_json TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'inactive')),
  matched_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  UNIQUE (user_id, listing_id, user_item_id),
  FOREIGN KEY (user_id) REFERENCES users(id),
  FOREIGN KEY (listing_id) REFERENCES market_listings_norm(id),
  FOREIGN KEY (user_item_id) REFERENCES user_items(id)
);

CREATE INDEX IF NOT EXISTS idx_listing_matches_user_status_score
  ON listing_matches (user_id, status, match_score, updated_at);

CREATE INDEX IF NOT EXISTS idx_listing_matches_listing_status
  ON listing_matches (listing_id, status, updated_at);
