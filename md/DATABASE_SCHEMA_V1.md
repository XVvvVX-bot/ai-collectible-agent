# DATABASE_SCHEMA_V1

## Goal

Design a V1 database schema that:

- supports current single-user prototype
- supports current data source (Zhaoonline)
- can expand to multi-user and multi-source later without major redesign

---

## Design Principles

1. Source-agnostic core model  
Use generic `market_*` tables instead of source-specific table names.

2. Raw + normalized storage  
Store full raw payload for traceability, plus normalized fields for matching/reporting.

3. Chat-persisted preferences  
User preferences from chat must be persisted and editable.

4. V1 simplicity with clear extension path  
Keep current schema lean but reserve columns/keys needed for future ML and additional sources.

---

## Entity Overview

1. `users`  
Single user in V1, expandable to multi-user.

2. `user_items`  
Unified table for holdings and watchlist.

3. `user_preferences`  
Persistent chat-defined preference/rule storage.

4. `market_sources`  
Registered external platforms (Zhaoonline first).

5. `market_listings_raw`  
Full API payload snapshots by source and fetch time.

6. `market_listings_norm`  
Normalized listing record for matching and analytics.

7. `market_taxonomy_map`  
Map source-specific categories/status/grades to internal standard values.

8. `market_metrics`  
Computed metrics (30-day in V1) used by reports/rules.

9. `signals`  
Detected opportunities/relevant events.

10. `reports`  
Daily/immediate generated report artifacts and delivery status.

11. `report_signal_links`  
Many-to-many linking between reports and signals.

---

## Table Specs (V1 Draft)

### 1) users

- `id` TEXT PRIMARY KEY
- `display_name` TEXT NULL
- `language` TEXT NOT NULL DEFAULT `zh-CN`
- `timezone` TEXT NOT NULL DEFAULT `Asia/Shanghai`
- `created_at` DATETIME NOT NULL
- `updated_at` DATETIME NOT NULL

Notes:
- V1 can use one row, but keep PK-based design for future multi-user.

### 2) user_items

- `id` TEXT PRIMARY KEY
- `user_id` TEXT NOT NULL FK -> `users(id)`
- `item_type` TEXT NOT NULL CHECK in (`holding`,`watch`)
- `category` TEXT NULL
- `series` TEXT NULL
- `item_name` TEXT NOT NULL
- `year` INTEGER NULL
- `grade_condition` TEXT NULL
- `quantity` REAL NULL
- `cost_basis_total` REAL NULL
- `priority` TEXT NULL CHECK in (`high`,`normal`,`low`)
- `max_buy_price` REAL NULL
- `notes` TEXT NULL
- `is_active` INTEGER NOT NULL DEFAULT 1
- `created_at` DATETIME NOT NULL
- `updated_at` DATETIME NOT NULL

Notes:
- `quantity` is typically for holdings.
- `priority` is typically for watch items.

### 3) user_preferences

- `id` TEXT PRIMARY KEY
- `user_id` TEXT NOT NULL FK -> `users(id)`
- `buy_rule_text` TEXT NULL
- `sell_rule_text` TEXT NULL
- `high_interest_flag` INTEGER NOT NULL DEFAULT 0
- `keywords_json` TEXT NULL
- `rules_json` TEXT NULL
- `created_at` DATETIME NOT NULL
- `updated_at` DATETIME NOT NULL

Notes:
- `rules_json` can hold structured thresholds later without schema break.

### 4) market_sources

- `id` TEXT PRIMARY KEY
- `source_platform` TEXT NOT NULL UNIQUE
- `base_url` TEXT NULL
- `status` TEXT NOT NULL DEFAULT `active`
- `created_at` DATETIME NOT NULL
- `updated_at` DATETIME NOT NULL

Seed for V1:
- `source_platform = zhaoonline`

### 5) market_listings_raw

- `id` TEXT PRIMARY KEY
- `source_platform` TEXT NOT NULL
- `source_listing_id` TEXT NOT NULL
- `fetch_status` TEXT NULL
- `fetched_at` DATETIME NOT NULL
- `payload_json` TEXT NOT NULL
- `request_meta_json` TEXT NULL
- `created_at` DATETIME NOT NULL

Recommended indexes:
- INDEX(`source_platform`, `source_listing_id`)
- INDEX(`source_platform`, `fetched_at`)

Notes:
- Keep exact upstream record for debugging and reprocessing.

### 6) market_listings_norm

- `id` TEXT PRIMARY KEY
- `source_platform` TEXT NOT NULL
- `source_listing_id` TEXT NOT NULL
- `source_url` TEXT NULL
- `auction_no` TEXT NULL
- `title` TEXT NOT NULL
- `category_raw` TEXT NULL
- `category_norm` TEXT NULL
- `series_raw` TEXT NULL
- `series_norm` TEXT NULL
- `status_raw` TEXT NULL
- `status_norm` TEXT NULL
- `auction_type_raw` TEXT NULL
- `auction_type_norm` TEXT NULL
- `grade_raw` TEXT NULL
- `grade_norm` TEXT NULL
- `description` TEXT NULL
- `image_url` TEXT NULL
- `start_at` DATETIME NULL
- `end_at` DATETIME NULL
- `preview_at` DATETIME NULL
- `price_initial` REAL NULL
- `price_current` REAL NULL
- `price_end` REAL NULL
- `currency` TEXT NOT NULL DEFAULT `CNY`
- `is_active` INTEGER NOT NULL DEFAULT 1
- `first_seen_at` DATETIME NOT NULL
- `last_seen_at` DATETIME NOT NULL
- `created_at` DATETIME NOT NULL
- `updated_at` DATETIME NOT NULL

Constraints:
- UNIQUE(`source_platform`, `source_listing_id`)

Recommended indexes:
- INDEX(`status_norm`, `last_seen_at`)
- INDEX(`category_norm`, `series_norm`)
- INDEX(`end_at`)

### 7) market_taxonomy_map

- `id` TEXT PRIMARY KEY
- `source_platform` TEXT NOT NULL
- `field_name` TEXT NOT NULL
- `raw_value` TEXT NOT NULL
- `norm_value` TEXT NOT NULL
- `created_at` DATETIME NOT NULL
- `updated_at` DATETIME NOT NULL

Constraints:
- UNIQUE(`source_platform`, `field_name`, `raw_value`)

Use cases:
- map source status (`1`,`2`,`3`) to internal (`preview`,`live`,`closed`)
- map source category IDs to internal category names
- map source grade labels to normalized grade buckets

### 8) market_metrics

- `id` TEXT PRIMARY KEY
- `item_key` TEXT NOT NULL
- `source_platform` TEXT NULL
- `window_days` INTEGER NOT NULL DEFAULT 30
- `sample_count` INTEGER NOT NULL DEFAULT 0
- `price_avg` REAL NULL
- `price_median` REAL NULL
- `price_min` REAL NULL
- `price_max` REAL NULL
- `trend_direction` TEXT NULL CHECK in (`up`,`down`,`flat`)
- `computed_at` DATETIME NOT NULL

Recommended indexes:
- INDEX(`item_key`, `window_days`, `computed_at`)

### 9) signals

- `id` TEXT PRIMARY KEY
- `user_id` TEXT NOT NULL FK -> `users(id)`
- `listing_id` TEXT NOT NULL FK -> `market_listings_norm(id)`
- `signal_type` TEXT NOT NULL
- `urgency` TEXT NOT NULL CHECK in (`daily`,`immediate`)
- `reason_code` TEXT NOT NULL
- `confidence_level` TEXT NULL CHECK in (`high`,`medium`,`low`)
- `recommendation_text` TEXT NULL
- `status` TEXT NOT NULL DEFAULT `active`
- `created_at` DATETIME NOT NULL
- `updated_at` DATETIME NOT NULL

Recommended indexes:
- INDEX(`user_id`, `urgency`, `created_at`)
- INDEX(`signal_type`, `status`)

### 10) reports

- `id` TEXT PRIMARY KEY
- `user_id` TEXT NOT NULL FK -> `users(id)`
- `report_date` DATE NOT NULL
- `report_type` TEXT NOT NULL CHECK in (`daily`,`immediate`)
- `content_summary` TEXT NULL
- `content_payload_json` TEXT NOT NULL
- `delivery_channel` TEXT NOT NULL DEFAULT `app_console`
- `delivery_status` TEXT NOT NULL DEFAULT `pending`
- `sent_at` DATETIME NULL
- `created_at` DATETIME NOT NULL

Recommended indexes:
- INDEX(`user_id`, `report_date`, `report_type`)

### 11) report_signal_links

- `report_id` TEXT NOT NULL FK -> `reports(id)`
- `signal_id` TEXT NOT NULL FK -> `signals(id)`
- `created_at` DATETIME NOT NULL
- PRIMARY KEY (`report_id`, `signal_id`)

---

## Minimal V1 Required Fields (Practical Cut)

If implementation bandwidth is limited, keep these first:

1. `users`
2. `user_items`
3. `user_preferences`
4. `market_listings_raw`
5. `market_listings_norm`
6. `signals`
7. `reports`

Add `market_sources`, `market_taxonomy_map`, `market_metrics`, `report_signal_links` next.

---

## V1 Data Flow (Zhaoonline)

1. Fetch `status=1` and `status=2` pages from `/api/search`
2. Save full records into `market_listings_raw`
3. Normalize into/upsert `market_listings_norm`
4. Match against `user_items` + `user_preferences`
5. Generate `signals`
6. Build daily/immediate `reports`

---

## Expansion Path

When adding a new source later:

1. register source in `market_sources`
2. write source connector for raw ingestion
3. add normalization mapping in `market_taxonomy_map`
4. keep using same `market_listings_norm`, `signals`, `reports`

No core schema rewrite required.
