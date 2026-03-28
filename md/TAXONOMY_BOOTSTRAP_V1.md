# TAXONOMY_BOOTSTRAP_V1

## Goal

Create and maintain provisional taxonomy mappings for `zhaoonline` so `*_norm` fields become stable and usable before official enum dictionaries arrive.

## Scope

Fields covered:
- `category` (`category_raw`)
- `series` (`series_raw`)
- `status` (`status_raw`)
- `auction_type` (`auction_type_raw`)
- `grade` (`grade_raw`)

## Bootstrap Strategy

1. Read currently unmapped raw values from `market_listings_norm`.
2. Rank by `observed_count` (descending).
3. Generate provisional mappings:
   - `status`: `1->preview`, `2->live`, `3->ended`, otherwise `status_<raw>`
   - `auction_type`: `1->auction`, otherwise `auction_type_<raw>`
   - `category`: `category_<raw>`
   - `series`: `series_<raw>`
   - `grade`: same as raw value
4. Apply with upsert into `market_taxonomy_map`.

## Commands

Create/apply provisional mappings:

```powershell
python .\scripts\taxonomy\bootstrap_zhaoonline_taxonomy.py --db-path data/agent.db --top-n-per-field 100 --apply
```

Inspect unmapped values:

```powershell
python .\scripts\taxonomy\report_unmapped_zhaoonline_taxonomy.py --db-path data/agent.db --top-n-per-field 20 --sample-size 3
```

## Governance Loop

1. Run unmapped report regularly.
2. Ask technician for official enum meaning.
3. Replace provisional `norm_value` with official value.
4. Re-run normalization if semantic mapping changed.

## Notes

- Provisional mapping is intentionally explicit and reversible.
- Taxonomy map overrides normalization fallback logic.

