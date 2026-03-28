PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS zhao_v2_sync_state (
  source_platform TEXT PRIMARY KEY,
  baseline_status_filter TEXT,
  last_baseline_started_at TEXT,
  last_baseline_finished_at TEXT,
  last_incremental_from_ms INTEGER,
  last_incremental_to_ms INTEGER,
  updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS zhao_v2_sync_runs (
  id TEXT PRIMARY KEY,
  source_platform TEXT NOT NULL,
  sync_type TEXT NOT NULL CHECK (sync_type IN ('baseline', 'incremental')),
  status_filter TEXT,
  window_from_ms INTEGER,
  window_to_ms INTEGER,
  started_at TEXT NOT NULL,
  finished_at TEXT,
  status TEXT NOT NULL CHECK (status IN ('running', 'success', 'failed')),
  error_message TEXT,
  pages_fetched INTEGER NOT NULL DEFAULT 0,
  items_seen INTEGER NOT NULL DEFAULT 0,
  items_inserted INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS zhao_v2_sync_run_pages (
  id TEXT PRIMARY KEY,
  sync_run_id TEXT NOT NULL,
  page_num INTEGER NOT NULL,
  page_size INTEGER NOT NULL,
  items_seen INTEGER NOT NULL DEFAULT 0,
  inserted_count INTEGER NOT NULL DEFAULT 0,
  page_meta_json TEXT,
  fetched_at TEXT NOT NULL,
  FOREIGN KEY (sync_run_id) REFERENCES zhao_v2_sync_runs(id)
);

CREATE TABLE IF NOT EXISTS zhao_v2_auction_raw (
  id TEXT PRIMARY KEY,
  sync_run_id TEXT NOT NULL,
  sync_type TEXT NOT NULL CHECK (sync_type IN ('baseline', 'incremental')),
  source_platform TEXT NOT NULL,
  auction_id TEXT NOT NULL,
  auction_no TEXT,
  status_raw TEXT,
  change_time_raw TEXT,
  payload_json TEXT NOT NULL,
  payload_hash TEXT NOT NULL,
  page_num INTEGER NOT NULL,
  page_size INTEGER NOT NULL,
  fetched_at TEXT NOT NULL,
  created_at TEXT NOT NULL,
  FOREIGN KEY (sync_run_id) REFERENCES zhao_v2_sync_runs(id),
  UNIQUE (sync_type, source_platform, auction_id, payload_hash)
);

CREATE TABLE IF NOT EXISTS zhao_v2_auction_change_raw (
  id TEXT PRIMARY KEY,
  sync_run_id TEXT NOT NULL,
  source_platform TEXT NOT NULL,
  auction_id TEXT NOT NULL,
  auction_no TEXT,
  old_status_raw TEXT,
  new_status_raw TEXT,
  change_time_raw TEXT,
  payload_json TEXT NOT NULL,
  payload_hash TEXT NOT NULL,
  fetched_at TEXT NOT NULL,
  created_at TEXT NOT NULL,
  FOREIGN KEY (sync_run_id) REFERENCES zhao_v2_sync_runs(id),
  UNIQUE (source_platform, auction_id, change_time_raw, payload_hash)
);

CREATE TABLE IF NOT EXISTS market_listings_norm_v2 (
  id TEXT PRIMARY KEY,
  source_platform TEXT NOT NULL,
  source_listing_id TEXT NOT NULL,
  auction_no TEXT,
  title TEXT,
  status_raw TEXT,
  status_norm TEXT,
  old_status_raw TEXT,
  new_status_raw TEXT,
  change_time TEXT,
  category_id_raw TEXT,
  category_name_raw TEXT,
  category_norm TEXT,
  character_id_raw TEXT,
  character_name_raw TEXT,
  character_norm TEXT,
  description TEXT,
  description_character TEXT,
  rating_agency TEXT,
  rating_score TEXT,
  grade_remarks TEXT,
  auction_type_raw TEXT,
  price_initial REAL,
  price_end REAL,
  buyer_fee_pct REAL,
  preview_at TEXT,
  start_at TEXT,
  end_at TEXT,
  upload_at TEXT,
  cancel_at TEXT,
  return_at TEXT,
  return_reason TEXT,
  return_remarks TEXT,
  settlement_status TEXT,
  settlement_at TEXT,
  auction_size TEXT,
  auction_metal TEXT,
  auction_num INTEGER,
  actual_num INTEGER,
  is_delay INTEGER,
  delay_time_sec INTEGER,
  exit_ban TEXT,
  primary_image_url TEXT,
  video_url TEXT,
  first_seen_at TEXT NOT NULL,
  last_seen_at TEXT NOT NULL,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  UNIQUE (source_platform, source_listing_id)
);

CREATE TABLE IF NOT EXISTS market_listing_events_v2 (
  id TEXT PRIMARY KEY,
  source_platform TEXT NOT NULL,
  source_listing_id TEXT NOT NULL,
  change_time TEXT,
  old_status_raw TEXT,
  new_status_raw TEXT,
  payload_json TEXT NOT NULL,
  created_at TEXT NOT NULL,
  UNIQUE (source_platform, source_listing_id, change_time, new_status_raw)
);

CREATE TABLE IF NOT EXISTS market_listing_media_v2 (
  id TEXT PRIMARY KEY,
  listing_id TEXT NOT NULL,
  source_platform TEXT NOT NULL,
  source_listing_id TEXT NOT NULL,
  media_type TEXT NOT NULL CHECK (media_type IN ('image', 'video')),
  media_url TEXT NOT NULL,
  sort_order INTEGER,
  label TEXT,
  created_at TEXT NOT NULL,
  UNIQUE (listing_id, media_type, media_url)
);
