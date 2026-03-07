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

## Next Steps

1. Implement ingestion job for `status=1` and `status=2`.
2. Normalize raw payload into `market_listings_norm`.
3. Build matching engine (`user_items` + `user_preferences`).
4. Generate daily report sections and immediate alerts.
