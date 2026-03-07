ALTER TABLE user_items ADD COLUMN dedupe_key TEXT;

UPDATE user_items
SET dedupe_key =
  lower(trim(coalesce(category, ''))) || '|' ||
  lower(trim(coalesce(series, ''))) || '|' ||
  lower(trim(item_name)) || '|' ||
  coalesce(CAST(year AS TEXT), '') || '|' ||
  lower(trim(coalesce(grade_condition, '')))
WHERE dedupe_key IS NULL;

CREATE UNIQUE INDEX IF NOT EXISTS idx_user_items_user_type_dedupe
  ON user_items (user_id, item_type, dedupe_key);

CREATE INDEX IF NOT EXISTS idx_user_items_user_active
  ON user_items (user_id, is_active, updated_at);

CREATE UNIQUE INDEX IF NOT EXISTS idx_user_preferences_user
  ON user_preferences (user_id);
