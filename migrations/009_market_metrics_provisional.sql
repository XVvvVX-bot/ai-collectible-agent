UPDATE market_metrics
SET source_platform = 'unknown'
WHERE source_platform IS NULL OR trim(source_platform) = '';

DELETE FROM market_metrics
WHERE rowid NOT IN (
  SELECT MAX(rowid)
  FROM market_metrics
  GROUP BY item_key, source_platform, window_days
);

ALTER TABLE market_metrics
ADD COLUMN data_coverage_days INTEGER NOT NULL DEFAULT 0;

ALTER TABLE market_metrics
ADD COLUMN confidence_level TEXT NOT NULL DEFAULT 'low'
  CHECK (confidence_level IN ('high', 'medium', 'low'));

ALTER TABLE market_metrics
ADD COLUMN is_temporary INTEGER NOT NULL DEFAULT 1
  CHECK (is_temporary IN (0, 1));

CREATE UNIQUE INDEX IF NOT EXISTS idx_market_metrics_item_window_unique
  ON market_metrics (item_key, source_platform, window_days);
