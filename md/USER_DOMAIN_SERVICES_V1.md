# USER_DOMAIN_SERVICES_V1

Step 4 implements deterministic domain services for:

- `users`
- `user_items`
- `user_preferences`

Location:

- `src/ai_agent/user_domain.py`

## Scope

The service provides CRUD/upsert behavior designed for repeated chat edits and upcoming CSV/Excel imports.

## Deterministic Upsert Rules

## `users`

- Key: `users.id`
- Method: `upsert_user(user_id, ...)`
- Behavior:
  - insert if `id` does not exist
  - update mutable fields if it exists
  - keep original `created_at`, bump `updated_at`

## `user_items`

- Canonical natural key:
  - `(user_id, item_type, dedupe_key)`
- `dedupe_key` is canonicalized from:
  - `category|series|item_name|year|grade_condition`
  - string fields are trimmed + lowercased
- Method: `upsert_user_item(...)`
- Behavior:
  - insert new row for unseen natural key
  - update existing row for same natural key
  - no duplicate active rows for the same logical item

`dedupe_key` uniqueness is enforced by:

- migration `migrations/006_user_domain_constraints.sql`
- unique index `idx_user_items_user_type_dedupe`

## `user_preferences`

- One preference row per user
- Key: `user_id` (unique index `idx_user_preferences_user`)
- Method: `upsert_user_preferences(...)`
- Behavior:
  - insert first row
  - update same row on subsequent edits/imports

`rules_json` is serialized with stable key order (`sort_keys=True`) for deterministic output.

## Active/Inactive Lifecycle

No hard deletes are required for normal update/import flows.

- `upsert_user_item(..., is_active=...)` updates active state per item.
- `deactivate_missing_user_items(user_id, item_type, keep_dedupe_keys=...)` performs soft deactivation for rows not present in current import set.

This keeps history while making active portfolio/watchlist state deterministic.
