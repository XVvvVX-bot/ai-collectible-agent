# RAW_TO_NORM_DESIGN (V1)

## Goal

Turn `market_listings_raw` snapshots into a stable, query-friendly `market_listings_norm` record per listing.

## Pipeline

1. Read incremental raw rows for `zhaoonline` ordered by `rowid`.
2. Normalize each payload to V1 norm fields.
3. Upsert by unique key `(source_platform, source_listing_id)`.
4. Persist normalization cursor (`normalization_state.last_raw_rowid`) for next run.

## Incremental Strategy

- Cursor is `rowid`-based for fast append-only processing.
- Each run processes `LIMIT batch_size`.
- Reruns are idempotent:
  - already-processed rows are skipped by cursor
  - listing-level updates are upserted deterministically

## Core Mapping (Zhaoonline)

- `source_listing_id`: from raw ingestion ID extraction
- `auction_no`: `auctionNo`
- `title`: `name` (fallback `title`)
- `status_raw`: payload `status` (fallback `fetch_status`)
- `status_norm`: taxonomy map override, else
  - `1 -> preview`
  - `2 -> live`
  - `3 -> ended`
  - else `unknown`
- `auction_type_raw`: `auctionType`
- `auction_type_norm`: taxonomy map override, else `1 -> auction`
- `category_raw`: `auctionCategoryId` (string)
- `category_norm`: taxonomy map override
- `series_raw`: `auctionCharacterId` (string)
- `series_norm`: taxonomy map override
- `grade_raw`: `ratingAgency + ratingScore` (when present)
- `grade_norm`: taxonomy map override, else same as `grade_raw`
- `description`: `descr` (fallback `descrCharacter`)
- `image_url`: `picPath` (fallback first `images[].url`)
- `start_at/end_at/preview_at`: epoch ms -> UTC ISO
- `price_initial`: `initialPrice`
- `price_end`: `endPrice`
- `price_current`: `endPrice` if present else `initialPrice`
- `is_active`: `1` when `status_norm` in (`preview`, `live`), else `0`
- `currency`: fixed `CNY` for V1

## Seen-Timestamp Semantics

- Insert:
  - `first_seen_at = fetched_at`
  - `last_seen_at = fetched_at`
- Update:
  - `first_seen_at = min(existing, incoming)`
  - `last_seen_at = max(existing, incoming)`

## Error Handling

- Skip rows when payload JSON is invalid or `title` is missing.
- Do not fail whole batch on bad row.

## Operational Command

```powershell
python .\scripts\normalization\run_zhaoonline_normalization.py --batch-size 500
```

