PRAGMA foreign_keys = ON;

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

CREATE TABLE IF NOT EXISTS market_sources (
  id TEXT PRIMARY KEY,
  source_platform TEXT NOT NULL UNIQUE,
  base_url TEXT,
  status TEXT NOT NULL DEFAULT 'active',
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS market_listings_raw (
  id TEXT PRIMARY KEY,
  source_platform TEXT NOT NULL,
  source_listing_id TEXT NOT NULL,
  fetch_status TEXT,
  fetched_at TEXT NOT NULL,
  payload_json TEXT NOT NULL,
  request_meta_json TEXT,
  created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS market_listings_norm (
  id TEXT PRIMARY KEY,
  source_platform TEXT NOT NULL,
  source_listing_id TEXT NOT NULL,
  source_url TEXT,
  auction_no TEXT,
  title TEXT NOT NULL,
  category_raw TEXT,
  category_norm TEXT,
  series_raw TEXT,
  series_norm TEXT,
  status_raw TEXT,
  status_norm TEXT,
  auction_type_raw TEXT,
  auction_type_norm TEXT,
  grade_raw TEXT,
  grade_norm TEXT,
  description TEXT,
  image_url TEXT,
  start_at TEXT,
  end_at TEXT,
  preview_at TEXT,
  price_initial REAL,
  price_current REAL,
  price_end REAL,
  currency TEXT NOT NULL DEFAULT 'CNY',
  is_active INTEGER NOT NULL DEFAULT 1,
  first_seen_at TEXT NOT NULL,
  last_seen_at TEXT NOT NULL,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  UNIQUE (source_platform, source_listing_id)
);

CREATE TABLE IF NOT EXISTS market_taxonomy_map (
  id TEXT PRIMARY KEY,
  source_platform TEXT NOT NULL,
  field_name TEXT NOT NULL,
  raw_value TEXT NOT NULL,
  norm_value TEXT NOT NULL,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  UNIQUE (source_platform, field_name, raw_value)
);

CREATE TABLE IF NOT EXISTS market_metrics (
  id TEXT PRIMARY KEY,
  item_key TEXT NOT NULL,
  source_platform TEXT,
  window_days INTEGER NOT NULL DEFAULT 30,
  sample_count INTEGER NOT NULL DEFAULT 0,
  price_avg REAL,
  price_median REAL,
  price_min REAL,
  price_max REAL,
  trend_direction TEXT CHECK (trend_direction IN ('up', 'down', 'flat')),
  computed_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS signals (
  id TEXT PRIMARY KEY,
  user_id TEXT NOT NULL,
  listing_id TEXT NOT NULL,
  signal_type TEXT NOT NULL,
  urgency TEXT NOT NULL CHECK (urgency IN ('daily', 'immediate')),
  reason_code TEXT NOT NULL,
  confidence_level TEXT CHECK (confidence_level IN ('high', 'medium', 'low')),
  recommendation_text TEXT,
  status TEXT NOT NULL DEFAULT 'active',
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  FOREIGN KEY (user_id) REFERENCES users(id),
  FOREIGN KEY (listing_id) REFERENCES market_listings_norm(id)
);

CREATE TABLE IF NOT EXISTS reports (
  id TEXT PRIMARY KEY,
  user_id TEXT NOT NULL,
  report_date TEXT NOT NULL,
  report_type TEXT NOT NULL CHECK (report_type IN ('daily', 'immediate')),
  content_summary TEXT,
  content_payload_json TEXT NOT NULL,
  delivery_channel TEXT NOT NULL DEFAULT 'app_console',
  delivery_status TEXT NOT NULL DEFAULT 'pending',
  sent_at TEXT,
  created_at TEXT NOT NULL,
  FOREIGN KEY (user_id) REFERENCES users(id)
);

CREATE TABLE IF NOT EXISTS report_signal_links (
  report_id TEXT NOT NULL,
  signal_id TEXT NOT NULL,
  created_at TEXT NOT NULL,
  PRIMARY KEY (report_id, signal_id),
  FOREIGN KEY (report_id) REFERENCES reports(id),
  FOREIGN KEY (signal_id) REFERENCES signals(id)
);

CREATE INDEX IF NOT EXISTS idx_market_listings_raw_platform_listing
  ON market_listings_raw (source_platform, source_listing_id);

CREATE INDEX IF NOT EXISTS idx_market_listings_raw_platform_fetched
  ON market_listings_raw (source_platform, fetched_at);

CREATE INDEX IF NOT EXISTS idx_market_listings_norm_status_last_seen
  ON market_listings_norm (status_norm, last_seen_at);

CREATE INDEX IF NOT EXISTS idx_market_listings_norm_category_series
  ON market_listings_norm (category_norm, series_norm);

CREATE INDEX IF NOT EXISTS idx_market_listings_norm_end_at
  ON market_listings_norm (end_at);

CREATE INDEX IF NOT EXISTS idx_market_metrics_item_window_computed
  ON market_metrics (item_key, window_days, computed_at);

CREATE INDEX IF NOT EXISTS idx_signals_user_urgency_created
  ON signals (user_id, urgency, created_at);

CREATE INDEX IF NOT EXISTS idx_signals_type_status
  ON signals (signal_type, status);

CREATE INDEX IF NOT EXISTS idx_reports_user_date_type
  ON reports (user_id, report_date, report_type);

INSERT OR IGNORE INTO market_sources (
  id, source_platform, base_url, status, created_at, updated_at
) VALUES (
  'src_zhaoonline', 'zhaoonline', 'http://8.218.2.12:8888', 'active', datetime('now'), datetime('now')
);

