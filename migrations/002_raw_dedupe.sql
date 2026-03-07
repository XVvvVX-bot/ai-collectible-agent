ALTER TABLE market_listings_raw ADD COLUMN payload_hash TEXT;

CREATE INDEX IF NOT EXISTS idx_market_listings_raw_payload_hash
  ON market_listings_raw (source_platform, fetch_status, source_listing_id, payload_hash);

CREATE UNIQUE INDEX IF NOT EXISTS uq_market_listings_raw_dedupe
  ON market_listings_raw (source_platform, fetch_status, source_listing_id, payload_hash)
  WHERE payload_hash IS NOT NULL;
