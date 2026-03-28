CREATE TABLE IF NOT EXISTS user_profile_defaults_v2 (
  user_id TEXT PRIMARY KEY,
  default_currency TEXT NOT NULL DEFAULT 'CNY',
  default_precision_mode TEXT NOT NULL DEFAULT 'balanced'
    CHECK (default_precision_mode IN ('exact', 'balanced', 'broad')),
  default_delivery_mode TEXT NOT NULL DEFAULT 'daily_digest'
    CHECK (default_delivery_mode IN ('immediate', 'daily_digest', 'silent_log')),
  default_min_match_score REAL NOT NULL DEFAULT 70,
  default_cooldown_hours INTEGER NOT NULL DEFAULT 24,
  default_allow_related_matches INTEGER NOT NULL DEFAULT 0,
  default_allow_series_matches INTEGER NOT NULL DEFAULT 0,
  default_allow_variant_matches INTEGER NOT NULL DEFAULT 1,
  notes TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  FOREIGN KEY (user_id) REFERENCES users(id)
);

CREATE TABLE IF NOT EXISTS user_interests_v2 (
  id TEXT PRIMARY KEY,
  user_id TEXT NOT NULL,
  legacy_user_item_id TEXT,
  interest_name TEXT NOT NULL,
  interest_kind TEXT NOT NULL
    CHECK (interest_kind IN ('collecting', 'watch_buy', 'watch_sell', 'discovery', 'portfolio_monitor')),
  scope_kind TEXT NOT NULL
    CHECK (scope_kind IN ('exact_item', 'issue_part', 'issue_family', 'series', 'theme', 'category', 'keyword')),
  precision_mode TEXT NOT NULL
    CHECK (precision_mode IN ('exact', 'balanced', 'broad')),
  interest_priority TEXT NOT NULL DEFAULT 'normal'
    CHECK (interest_priority IN ('high', 'normal', 'low')),
  intent_confidence REAL NOT NULL DEFAULT 0.7,
  allow_related_matches INTEGER NOT NULL DEFAULT 0,
  allow_series_matches INTEGER NOT NULL DEFAULT 0,
  allow_variant_matches INTEGER NOT NULL DEFAULT 1,
  active_status TEXT NOT NULL DEFAULT 'active'
    CHECK (active_status IN ('active', 'inactive', 'archived')),
  notes TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  UNIQUE (user_id, legacy_user_item_id),
  FOREIGN KEY (user_id) REFERENCES users(id),
  FOREIGN KEY (legacy_user_item_id) REFERENCES user_items(id)
);

CREATE INDEX IF NOT EXISTS idx_user_interests_v2_user_status
  ON user_interests_v2 (user_id, active_status, interest_priority, updated_at);

CREATE TABLE IF NOT EXISTS user_interest_targets_v2 (
  id TEXT PRIMARY KEY,
  interest_id TEXT NOT NULL,
  target_label TEXT NOT NULL,
  target_kind TEXT NOT NULL
    CHECK (target_kind IN ('listing_identity', 'issue_part', 'issue_family', 'series_key', 'theme', 'category', 'keyword')),
  parse_family TEXT,
  raw_input TEXT NOT NULL,
  normalized_name TEXT,
  issue_code_norm TEXT,
  issue_part_token TEXT,
  series_key TEXT,
  theme_name TEXT,
  asset_type TEXT,
  variant_tokens_json TEXT NOT NULL DEFAULT '[]',
  quantity_tokens_json TEXT NOT NULL DEFAULT '[]',
  condition_tokens_json TEXT NOT NULL DEFAULT '[]',
  year_value INTEGER,
  budget_min REAL,
  budget_max REAL,
  strictness_override TEXT
    CHECK (strictness_override IN ('exact', 'balanced', 'broad')),
  priority_override TEXT
    CHECK (priority_override IN ('high', 'normal', 'low')),
  is_active INTEGER NOT NULL DEFAULT 1,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  FOREIGN KEY (interest_id) REFERENCES user_interests_v2(id)
);

CREATE INDEX IF NOT EXISTS idx_user_interest_targets_v2_interest
  ON user_interest_targets_v2 (interest_id, is_active, updated_at);

CREATE INDEX IF NOT EXISTS idx_user_interest_targets_v2_identity
  ON user_interest_targets_v2 (issue_code_norm, issue_part_token, series_key, theme_name);

CREATE TABLE IF NOT EXISTS user_holdings_v2 (
  id TEXT PRIMARY KEY,
  user_id TEXT NOT NULL,
  legacy_user_item_id TEXT,
  linked_interest_id TEXT,
  raw_input TEXT NOT NULL,
  parse_family TEXT,
  normalized_name TEXT,
  issue_code_norm TEXT,
  issue_part_token TEXT,
  series_key TEXT,
  theme_name TEXT,
  asset_type TEXT,
  variant_tokens_json TEXT NOT NULL DEFAULT '[]',
  quantity_tokens_json TEXT NOT NULL DEFAULT '[]',
  condition_tokens_json TEXT NOT NULL DEFAULT '[]',
  year_value INTEGER,
  holding_quantity REAL,
  cost_basis_total REAL,
  cost_basis_unit REAL,
  acquired_at TEXT,
  notes TEXT,
  is_active INTEGER NOT NULL DEFAULT 1,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  UNIQUE (legacy_user_item_id),
  FOREIGN KEY (user_id) REFERENCES users(id),
  FOREIGN KEY (legacy_user_item_id) REFERENCES user_items(id),
  FOREIGN KEY (linked_interest_id) REFERENCES user_interests_v2(id)
);

CREATE INDEX IF NOT EXISTS idx_user_holdings_v2_user_active
  ON user_holdings_v2 (user_id, is_active, updated_at);

CREATE TABLE IF NOT EXISTS user_interest_signal_policies_v2 (
  id TEXT PRIMARY KEY,
  interest_id TEXT NOT NULL,
  notify_on_preview INTEGER NOT NULL DEFAULT 1,
  notify_on_live INTEGER NOT NULL DEFAULT 1,
  notify_on_ended INTEGER NOT NULL DEFAULT 0,
  notify_on_exact_match INTEGER NOT NULL DEFAULT 1,
  notify_on_variant_match INTEGER NOT NULL DEFAULT 1,
  notify_on_series_match INTEGER NOT NULL DEFAULT 0,
  notify_on_price_opportunity INTEGER NOT NULL DEFAULT 1,
  notify_on_sell_opportunity INTEGER NOT NULL DEFAULT 0,
  min_match_score REAL NOT NULL DEFAULT 70,
  cooldown_hours INTEGER NOT NULL DEFAULT 24,
  delivery_mode TEXT NOT NULL DEFAULT 'daily_digest'
    CHECK (delivery_mode IN ('immediate', 'daily_digest', 'silent_log')),
  max_signals_per_day INTEGER NOT NULL DEFAULT 20,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  UNIQUE (interest_id),
  FOREIGN KEY (interest_id) REFERENCES user_interests_v2(id)
);
