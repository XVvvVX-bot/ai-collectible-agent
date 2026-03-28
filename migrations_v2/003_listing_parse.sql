CREATE TABLE IF NOT EXISTS listing_parse_v2 (
  listing_id TEXT PRIMARY KEY,
  source_platform TEXT NOT NULL,
  source_listing_id TEXT NOT NULL,
  parser_version TEXT NOT NULL,
  parse_family TEXT NOT NULL,
  raw_title TEXT,
  title_normalized TEXT,
  identity_core TEXT,
  series_key TEXT,
  variant_key TEXT,
  condition_key TEXT,
  code_prefix_raw TEXT,
  code_prefix_norm TEXT,
  code_number TEXT,
  code_suffix TEXT,
  issue_code_norm TEXT,
  issue_name TEXT,
  year_value INTEGER,
  theme_name TEXT,
  asset_type TEXT,
  finish_type TEXT,
  weight_text TEXT,
  denomination_text TEXT,
  character_condition TEXT,
  variant_tokens_json TEXT NOT NULL,
  condition_tokens_json TEXT NOT NULL,
  quantity_tokens_json TEXT NOT NULL,
  parse_confidence REAL NOT NULL DEFAULT 0,
  parse_notes_json TEXT NOT NULL,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  FOREIGN KEY (listing_id) REFERENCES market_listings_norm_v2(id),
  UNIQUE (source_platform, source_listing_id)
);

CREATE INDEX IF NOT EXISTS idx_listing_parse_v2_family
  ON listing_parse_v2 (parse_family, source_platform);

CREATE INDEX IF NOT EXISTS idx_listing_parse_v2_identity
  ON listing_parse_v2 (identity_core, series_key);
