# AI Collectibles Intelligence Agent

An intelligence system for collectibles research and decision support.

V1 focus:
- user holdings/interests intake (chat + CSV/Excel)
- Zhaoonline market monitoring (`status=1` preview, `status=2` live)
- daily report + rare high-priority immediate alerts

## Project Structure

```text
F:\AI Agent
|-- md/                     # Product and technical documentation
|-- migrations/             # SQL migrations
|-- scripts/
|   `-- diagnostics/        # API/network diagnostic scripts
|-- src/
|   `-- ai_agent/           # Core package
|-- tests/                  # Unit tests
|-- data/                   # Local artifacts (git-ignored)
|-- reports/                # Local outputs (git-ignored)
|-- logs/                   # Local logs (git-ignored)
|-- pyproject.toml
|-- .env.example
`-- test_zhaoonline_api.py  # Compatibility launcher
```

## Core Docs

- [Docs Index](./md/README.md)
- [Project Context](./md/PROJECT_CONTEXT.md)
- [API Interface (Zhaoonline)](./md/API_INTERFACE_ZHAOONLINE.md)
- [Data Dictionary (Draft)](./md/DATA_DICTIONARY_V1_DRAFT.md)
- [Database Schema (Design)](./md/DATABASE_SCHEMA_V1.md)
- [Database Migration (SQL)](./migrations/001_init.sql)

## Quick Start

1. Install Python 3.11+.
2. Copy `.env.example` to `.env`.
3. Run diagnostics:

```powershell
cd "F:\AI Agent"
python .\test_zhaoonline_api.py --secret zhao123 --status 2 --page 1 --page-size 10
```

4. Run one raw-ingestion cycle (status `1` + `2`):

```powershell
python .\scripts\ingestion\run_raw_ingestion.py --secret zhao123 --call-budget-per-run 30 --fresh-pages-per-status 2
```

By default, this command also runs raw-to-norm normalization immediately after ingestion.
Use `--skip-normalization` to disable it for a run.

The command prints run coverage details including:
- `calls_used`
- `inserted_by_status`
- `pages_fetched_by_status`
- `completed_by_status` (true means the status reached an end-of-data condition)
- `next_page_by_status` (cursor for next run deep crawl continuation)

Raw ingestion is duplicate-safe:
- identical rows (same `source_platform`, `fetch_status`, `source_listing_id`, and payload hash) are ignored on reruns

5. Normalize newly ingested raw rows into `market_listings_norm` (manual fallback):

```powershell
python .\scripts\normalization\run_zhaoonline_normalization.py --batch-size 500
```

6. Build provisional taxonomy mappings from currently unmapped values:

```powershell
python .\scripts\taxonomy\bootstrap_zhaoonline_taxonomy.py --db-path data/agent.db --top-n-per-field 100 --apply
```

7. View unmapped taxonomy values (for technician follow-up / governance loop):

```powershell
python .\scripts\taxonomy\report_unmapped_zhaoonline_taxonomy.py --db-path data/agent.db --top-n-per-field 20 --sample-size 3
```

8. Run normalized-data quality checks:

```powershell
python .\scripts\quality\run_norm_quality_checks.py --db-path data/agent.db --batch-size 2000
```

9. Import holdings/watchlist from CSV/Excel (preview by default):

```powershell
python .\scripts\importers\import_user_items.py --db-path data/agent.db --user-id u_001 --file-path data/user_items.csv
```

Add `--commit` to apply writes.

10. Run matching engine V1:

```powershell
python .\scripts\matching\run_v1_matching.py --db-path data/agent.db --user-id u_001 --min-score 30
```

11. Run rule-based signal generation:

```powershell
python .\scripts\signals\run_rule_signals.py --db-path data/agent.db --user-id u_001 --cooldown-hours 24 --freshness-hours 24 --price-move-threshold-pct 10
```

## Development Workflow

1. Keep `main` stable and protected.
2. Create branches per task:
   - `feature/<topic>`
   - `fix/<topic>`
   - `docs/<topic>`
3. Open a Pull Request for every merge.
4. Keep PRs small and testable.

## Security Rules

- Do not commit secrets or production keys.
- Keep API secret in environment variables only.
- Run auth logic in backend or controlled scripts, never frontend.

## Current Status

- project docs initialized
- source-agnostic V1 schema drafted
- initial SQL migration added
- Zhaoonline diagnostic tooling added
- raw ingestion + normalization + taxonomy bootstrap + quality checks implemented
- user domain services implemented for deterministic upsert and lifecycle control

## Next Steps

1. Build CSV/Excel intake on top of `UserDomainService`.
2. Build matching engine and rule-based signal generation.

CI test
