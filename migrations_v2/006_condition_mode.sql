ALTER TABLE user_profile_defaults_v2
ADD COLUMN default_condition_mode TEXT NOT NULL DEFAULT 'ignore'
  CHECK (default_condition_mode IN ('ignore', 'prefer', 'require'));

ALTER TABLE user_interest_targets_v2
ADD COLUMN condition_mode TEXT NOT NULL DEFAULT 'ignore'
  CHECK (condition_mode IN ('ignore', 'prefer', 'require'));

UPDATE user_interest_targets_v2
SET condition_mode = CASE
  WHEN json_array_length(condition_tokens_json) <= 0 THEN 'ignore'
  WHEN COALESCE(
    strictness_override,
    (SELECT precision_mode FROM user_interests_v2 i WHERE i.id = user_interest_targets_v2.interest_id)
  ) = 'exact' THEN 'require'
  ELSE 'prefer'
END;
