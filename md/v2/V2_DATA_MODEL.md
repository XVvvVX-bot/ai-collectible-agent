# V2 Data Model

## Database

Current local V2 database:

- `data/agent_v2.db`

The V2 schema is additive and lives in:

- `migrations_v2/001_init.sql`
- `migrations_v2/003_listing_parse.sql`
- `migrations_v2/004_user_domain_and_matching.sql`
- `migrations_v2/005_interest_profile.sql`

## Core Table Groups

## 1. Sync Control Tables

### `zhao_v2_sync_state`

Purpose:
- store last-known sync positions
- separate historical/backfill state from live forward-sync state

Important current keys:
- `zhaoonline`
  historical/backfill-oriented state
- `zhaoonline_live`
  scheduled live incremental state

### `zhao_v2_sync_runs`

Purpose:
- one row per baseline or incremental sync run
- stores status, page counts, item counts, error text

### `zhao_v2_sync_run_pages`

Purpose:
- per-page telemetry inside a sync run
- useful for debugging throttling, paging, and insert volume

## 2. Raw Landing Tables

### `zhao_v2_auction_raw`

Purpose:
- store raw baseline or incremental auction payload snapshots

Notes:
- duplicate-safe through payload-hash uniqueness
- currently used by live incremental meaningful-change ingestion

### `zhao_v2_auction_change_raw`

Purpose:
- store raw incremental change rows

Notes:
- dedupes on source, auction, change time, and payload hash
- only meaningful changes are kept by the current live incremental path

## 3. Normalized Market Tables

### `market_listings_norm_v2`

Purpose:
- one canonical listing row per normalized source listing

Examples of fields:
- source identity
- title
- raw + normalized status
- category / character
- pricing
- schedule times
- media pointers
- descriptive fields

### `market_listing_events_v2`

Purpose:
- normalized lifecycle event history

Typical use:
- status transition analysis
- future signals

### `market_listing_media_v2`

Purpose:
- child media rows for listings

Typical use:
- images and videos for listing review or later UI

Important current note:
- these normalized tables may already contain useful local state
- but the live scheduled incremental runner does not refresh them automatically today

## 4. Parse Layer

### `listing_parse_v2`

Purpose:
- parsed debug and matching layer between normalized listings and the matcher

Key outputs:
- `parse_family`
- `identity_core`
- `series_key`
- `variant_key`
- `condition_key`
- stamp fields like `issue_code_norm`, `issue_name`
- coin fields like `year_value`, `theme_name`, `asset_type`

Why it exists:
- easier debugging
- stable SQL-visible parse output
- matcher does not need to re-parse listing titles on every run

## 5. Matching Tables

### `listing_match_runs_v2`

Purpose:
- telemetry for matcher runs

### `listing_matches_v2`

Purpose:
- active/inactive listing matches for a user target

Important current columns:
- `user_id`
- `listing_id`
- `user_item_id`
  This is now polymorphic in practice:
  - either a legacy `user_items.id`
  - or a V2 `user_interest_targets_v2.id`
- `item_type`
- `relationship_type`
- score columns
- `match_reasons_json`
- `status`

Important note:
- the schema name `user_item_id` is legacy-shaped, but the matcher now also writes V2 target ids into it
- downstream code must not assume the id always belongs to `user_items`

## 6. V2 Profile Tables

### `user_profile_defaults_v2`

Purpose:
- default settings for a user across interests

### `user_interests_v2`

Purpose:
- one row per interest track

Examples:
- exact buy watch
- broad series discovery
- collecting family completion
- sell monitor

### `user_interest_targets_v2`

Purpose:
- concrete matching targets under an interest

Examples:
- exact coin target
- exact stamp issue
- broad series key

### `user_holdings_v2`

Purpose:
- owned positions, separate from wants/interests

### `user_interest_signal_policies_v2`

Purpose:
- signal behavior per interest track

Examples:
- exact-only vs broad
- cooldown
- delivery mode
- notify on preview/live/ended

## Current Important Model Behavior

### Scheduled Polling State

Live scheduled polling only advances:
- `zhao_v2_sync_state.source_platform = 'zhaoonline_live'`

It does not touch the historical backfill watermark.

### Matcher Source Priority

Current matcher source order:
1. `user_interest_targets_v2` for users who have V2 interests
2. `user_items` only as legacy fallback

### Match Semantics

The matcher emits:
- `exact_identity`
- `variant_related`
- `series_related`

The V2 profile can now suppress some relationship classes through:
- `allow_variant_matches`
- `allow_series_matches`
- `strictness_override` / interest precision

## Developer Guidance

Use these tables by purpose:

- sync debugging:
  `zhao_v2_sync_state`, `zhao_v2_sync_runs`, `zhao_v2_sync_run_pages`
- raw source debugging:
  `zhao_v2_auction_raw`, `zhao_v2_auction_change_raw`
- market logic:
  `market_listings_norm_v2`, `market_listing_events_v2`, `market_listing_media_v2`
- parse debugging:
  `listing_parse_v2`
- matching review:
  `listing_matches_v2`, `listing_match_runs_v2`
- user intent:
  `user_interests_v2`, `user_interest_targets_v2`, `user_holdings_v2`, `user_interest_signal_policies_v2`
