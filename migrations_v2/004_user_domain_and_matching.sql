CREATE TABLE IF NOT EXISTS users (
  id TEXT PRIMARY KEY,
  display_name TEXT,
  language TEXT NOT NULL DEFAULT 'zh-CN',
  timezone TEXT NOT NULL DEFAULT 'Asia/Shanghai',
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS user_items (
  id TEXT PRIMARY KEY,
  user_id TEXT NOT NULL,
  item_type TEXT NOT NULL CHECK (item_type IN ('holding', 'watch')),
  category TEXT,
  series TEXT,
  item_name TEXT NOT NULL,
  year INTEGER,
  grade_condition TEXT,
  quantity REAL,
  cost_basis_total REAL,
  priority TEXT CHECK (priority IN ('high', 'normal', 'low')),
  max_buy_price REAL,
  notes TEXT,
  is_active INTEGER NOT NULL DEFAULT 1,
  dedupe_key TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  FOREIGN KEY (user_id) REFERENCES users(id)
);

CREATE TABLE IF NOT EXISTS user_preferences (
  id TEXT PRIMARY KEY,
  user_id TEXT NOT NULL,
  buy_rule_text TEXT,
  sell_rule_text TEXT,
  high_interest_flag INTEGER NOT NULL DEFAULT 0,
  keywords_json TEXT,
  rules_json TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  FOREIGN KEY (user_id) REFERENCES users(id)
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_v2_user_items_user_type_dedupe
  ON user_items (user_id, item_type, dedupe_key);

CREATE UNIQUE INDEX IF NOT EXISTS idx_v2_user_preferences_user
  ON user_preferences (user_id);

CREATE TABLE IF NOT EXISTS listing_match_runs_v2 (
  id TEXT PRIMARY KEY,
  user_id TEXT,
  matcher_version TEXT NOT NULL,
  only_active_listings INTEGER NOT NULL DEFAULT 1,
  started_at TEXT NOT NULL,
  finished_at TEXT,
  status TEXT NOT NULL DEFAULT 'running' CHECK (status IN ('running', 'success', 'failed')),
  users_processed INTEGER NOT NULL DEFAULT 0,
  items_scanned INTEGER NOT NULL DEFAULT 0,
  listings_scanned INTEGER NOT NULL DEFAULT 0,
  evaluated_pairs INTEGER NOT NULL DEFAULT 0,
  matched_pairs INTEGER NOT NULL DEFAULT 0,
  inserted INTEGER NOT NULL DEFAULT 0,
  updated INTEGER NOT NULL DEFAULT 0,
  deactivated INTEGER NOT NULL DEFAULT 0,
  error_message TEXT,
  FOREIGN KEY (user_id) REFERENCES users(id)
);

CREATE TABLE IF NOT EXISTS listing_matches_v2 (
  id TEXT PRIMARY KEY,
  user_id TEXT NOT NULL,
  listing_id TEXT NOT NULL,
  user_item_id TEXT NOT NULL,
  item_type TEXT NOT NULL CHECK (item_type IN ('holding', 'watch')),
  relationship_type TEXT NOT NULL CHECK (relationship_type IN ('exact_identity', 'variant_related', 'series_related')),
  match_score REAL NOT NULL,
  identity_score REAL NOT NULL DEFAULT 0,
  series_score REAL NOT NULL DEFAULT 0,
  variant_score REAL NOT NULL DEFAULT 0,
  condition_score REAL NOT NULL DEFAULT 0,
  matcher_version TEXT NOT NULL,
  match_reasons_json TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'inactive')),
  matched_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  UNIQUE (user_id, listing_id, user_item_id),
  FOREIGN KEY (user_id) REFERENCES users(id),
  FOREIGN KEY (listing_id) REFERENCES market_listings_norm_v2(id),
  FOREIGN KEY (user_item_id) REFERENCES user_items(id)
);
