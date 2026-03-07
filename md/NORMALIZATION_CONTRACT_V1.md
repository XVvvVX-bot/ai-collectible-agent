# NORMALIZATION_CONTRACT_V1

## Purpose

This contract defines deterministic V1 transformation from `market_listings_raw` to `market_listings_norm` for source `zhaoonline`.

## Record Scope

- Input unit: one raw row from `market_listings_raw`.
- Output unit: one upsert into `market_listings_norm` keyed by:
  - `(source_platform, source_listing_id)`.

## Field Mapping Contract

| Norm Field | Rule | Fallback/Notes |
|---|---|---|
| `source_platform` | constant | `zhaoonline` |
| `source_listing_id` | from raw row | already extracted during raw ingestion |
| `source_url` | `payload.url` as trimmed string | null if missing/empty |
| `auction_no` | `payload.auctionNo` as trimmed string | null if missing/empty |
| `title` | `payload.name` | fallback `payload.title`; if still empty, skip row |
| `category_raw` | `payload.auctionCategoryId` stringified | null if missing |
| `category_norm` | taxonomy map (`field_name=category`) by `category_raw` | null if unmapped |
| `series_raw` | `payload.auctionCharacterId` stringified | null if missing |
| `series_norm` | taxonomy map (`field_name=series`) by `series_raw` | null if unmapped |
| `status_raw` | `payload.status` | fallback raw-row `fetch_status` |
| `status_norm` | taxonomy map (`field_name=status`) by `status_raw` | else `1->preview`, `2->live`, `3->ended`, default `unknown` |
| `auction_type_raw` | `payload.auctionType` stringified | null if missing |
| `auction_type_norm` | taxonomy map (`field_name=auction_type`) by `auction_type_raw` | else `auction` only when raw is `1` |
| `grade_raw` | join `ratingAgency` and `ratingScore` with one space | agency-only or score-only allowed |
| `grade_norm` | taxonomy map (`field_name=grade`) by `grade_raw` | fallback `grade_raw` |
| `description` | `payload.descr` | fallback `payload.descrCharacter` |
| `image_url` | `payload.picPath` | fallback first non-empty `payload.images[].url` |
| `start_at` | `payload.startAt` epoch milliseconds -> UTC ISO | null on missing/invalid |
| `end_at` | `payload.endAt` epoch milliseconds -> UTC ISO | null on missing/invalid |
| `preview_at` | `payload.previewAt` epoch milliseconds -> UTC ISO | null on missing/invalid |
| `price_initial` | float(`payload.initialPrice`) | null on missing/invalid |
| `price_end` | float(`payload.endPrice`) | null on missing/invalid |
| `price_current` | `price_end` when present | else `price_initial` |
| `currency` | constant | `CNY` |
| `is_active` | derived from `status_norm` | `1` for `preview/live`, else `0` |
| `first_seen_at` | incoming raw `fetched_at` on insert | update uses `min(existing, incoming)` |
| `last_seen_at` | incoming raw `fetched_at` on insert | update uses `max(existing, incoming)` |
| `created_at` | current UTC ISO at insert | not changed by upsert update |
| `updated_at` | current UTC ISO | updated on each upsert |

## Precedence Rules

1. Taxonomy override has highest precedence for `*_norm` fields where applicable.
2. If taxonomy has no entry, default fallback applies per field.
3. Trimmed empty strings are treated as null before mapping.

## Row Skip Rules

Skip the row (counted as `skipped`) when:
- raw JSON is invalid, or
- decoded payload is not a JSON object, or
- `title` cannot be resolved from `name/title`.

Skipped rows do not fail the batch.

## Upsert Rules

- Conflict key: `(source_platform, source_listing_id)`.
- On update:
  - mutable normalized fields are replaced by new values,
  - `first_seen_at` keeps earliest timestamp,
  - `last_seen_at` keeps latest timestamp.

## Golden Test Policy

- Contract must be guarded by fixture-driven tests covering:
  - standard live listing,
  - fallback behavior,
  - taxonomy override behavior,
  - invalid-row skip behavior.

