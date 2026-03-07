# NORM_QUALITY_STAGE_V1

## Goal

Run data quality checks on `market_listings_norm` before downstream matching/signals/reports.

## Rules (V1)

Fail-level:
- `missing_source_listing_id`
- `missing_title`
- `missing_status_norm`
- `invalid_start_at`
- `invalid_end_at`
- `invalid_preview_at`
- `start_after_end`
- `price_initial_negative`
- `price_current_negative`
- `price_end_negative`
- `is_active_mismatch_status`

Warning-level:
- `invalid_status_norm`
- `price_current_not_equal_end`
- `price_current_not_equal_initial`
- `unmapped_category`
- `unmapped_series`

## Incremental Strategy

- Uses `quality_check_state.last_norm_rowid` as cursor.
- Default run checks rows with `rowid > last_norm_rowid`.
- `--full-scan` ignores cursor and scans from rowid 0.

## Persisted Output

`quality_check_runs` stores:
- run metadata and evaluated rowid range
- pass/warning/fail row counts
- issue counts JSON
- sample listing IDs JSON per issue code

## Command

Incremental (default):

```powershell
python .\scripts\quality\run_norm_quality_checks.py --db-path data/agent.db --batch-size 2000
```

Full scan:

```powershell
python .\scripts\quality\run_norm_quality_checks.py --db-path data/agent.db --batch-size 2000 --full-scan
```

