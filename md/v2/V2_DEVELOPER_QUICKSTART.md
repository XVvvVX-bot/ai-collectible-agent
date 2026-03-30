# V2 Developer Quickstart

## Goal

This document helps a new developer get oriented quickly without needing project history from earlier chats.

## What This Repo Contains

The repository currently has two parallel tracks:

- `src/ai_agent`
  V1 implementation and the older stable reference path
- `src/ai_agent_v2`
  V2 implementation for the new Zhaoonline API, new profile model, and new matching stack

V2 is the active development track.

## What Is Safe To Work On First

The safest checked-in V2 areas for a new developer are:

- live incremental polling
- post-sync normalization and parse refresh
- profile model
- listing parser
- V2 matcher
- match audit reporting
- daily review/report automation
- Render-hosted dashboard/report browser
- thin API layer
- documentation

The riskiest areas are the ones that are still transitional:

- automatic matching refresh after scheduled incremental sync
- signal generation refresh cadence
- full standalone frontend
- storage abstraction for future Postgres support
- signal/report threshold tuning

## First Read

Read these in order:

1. `V2_CURRENT_STATUS.md`
2. `V2_ARCHITECTURE.md`
3. `V2_DASHBOARD_AND_API.md`
4. `V2_DATA_MODEL.md`
5. `V2_RUNTIME_WORKFLOW.md`
6. `V2_RENDER_DEPLOYMENT.md`
7. `V2_OPERATIONS_RUNBOOK.md`

## Current Runtime Choices

Today there are two practical ways to work on V2:

- local developer runtime on Windows
- Render-hosted web runtime with a persistent disk

New developers should understand both, because the checked-in code supports local development while the current product-facing runtime is on Render.

## Local Requirements

- Windows environment
- Python 3.11+
- local virtual environment in `.venv`
- local SQLite database at `data/agent_v2.db`

The current `pyproject.toml` has no external runtime dependencies listed, so most workflows run with the local source tree plus standard library and the current venv.

## Current Render Runtime

The current live runtime is:

- one Render web service
- one Render persistent disk
- one SQLite database file on that disk
- one combined process that serves the dashboard/API and runs the background loops

The main runtime entrypoint there is:

- `scripts_v2/orchestration/run_v2_report_service.py`

That service currently exposes:

- dashboard at `/`
- health check at `/healthz`
- report listing at `/api/reports`
- user profile API at `/api/users/{user_id}/profile`
- user report API at `/api/users/{user_id}/reports`
- latest digest API at `/api/users/{user_id}/digest/latest`
- matching action API at `/api/users/{user_id}/matching/run`
- signals action API at `/api/users/{user_id}/signals/run`

## Local Secrets

Preferred secret file:

- `data/secrets/zhaoonline_secret.txt`

Alternative environment variables:

- `ZHAO_SECRET`
- `ZHAO_V2_SECRET`

Do not commit secrets into source control.

## Most Important Runtime Rule

The scheduled live V2 runner uses a separate sync state key:

- `source_platform='zhaoonline_live'`

This must stay separate from the older historical backfill state:

- `source_platform='zhaoonline'`

That separation is what keeps the live scheduler from replaying old backfill windows.

## Main Commands

Run the combined dashboard + API + background runtime locally:

```powershell
.\.venv\Scripts\python.exe .\scripts_v2\orchestration\run_v2_report_service.py --runtime-root runtime --timezone Asia/Shanghai
```

Run one live incremental cycle:

```powershell
.\.venv\Scripts\python.exe .\scripts_v2\orchestration\run_v2_incremental_cycle.py --db-path data/agent_v2.db
```

Seed the curated demo user:

```powershell
.\.venv\Scripts\python.exe .\scripts_v2\orchestration\seed_v2_demo_user.py
```

Run matching for the curated demo user:

```powershell
.\.venv\Scripts\python.exe .\scripts_v2\matching\run_zhaoonline_v2_matching.py --db-path data/agent_v2.db --user-id demo_u_v2_curated
```

Build the current match audit report:

```powershell
.\.venv\Scripts\python.exe .\scripts_v2\reporting\run_zhaoonline_v2_match_audit.py --db-path data/agent_v2.db
```

Register the Windows scheduled task:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts_v2\windows\register_v2_incremental_task.ps1
```

Register the daily logon-triggered reporting tasks:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts_v2\windows\register_v2_daily_user_base_review_task.ps1
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts_v2\windows\register_v2_daily_signal_review_task.ps1
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts_v2\windows\register_v2_daily_interest_digest_task.ps1
```

Run focused V2 tests:

```powershell
.\.venv\Scripts\pytest.exe -q tests\test_v2_demo_user_seed.py tests\test_v2_interest_matching.py tests\test_v2_interest_profile_migration.py tests\test_v2_live_incremental.py tests\test_v2_matching_strictness.py
```

## Current Mental Model

Think about V2 as five practical layers:

1. scheduler and raw landing
2. normalized market tables
3. parse, matching, and signals
4. review/report delivery
5. dashboard and thin API surface

Today:
- layer 1 is fully wired into scheduled automation
- daily review/report delivery is scheduled
- dashboard and thin API are live on the Render runtime
- matching refresh and signal generation still require explicit runs

## What To Check Before Making Changes

Before editing V2 code, confirm:

1. whether the change affects live scheduled polling
2. whether the change depends on normalized tables being refreshed automatically
3. whether the code reads V2 interests or legacy `user_items`
4. whether the change assumes the historical backfill state is still active
5. whether the change affects the combined web/API/background Render runtime
6. whether the change assumes reports are only offline markdown artifacts rather than live product UI inputs

## Common Developer Mistakes To Avoid

- assuming scheduled incremental sync also refreshes normalized tables
- assuming daily signal-review tasks generate new signals
- assuming daily digest tasks generate new matches
- assuming `listing_matches_v2.user_item_id` always points to `user_items.id`
- assuming historical backfill state and live state are the same thing
- tightening broad discovery matching when the real problem is result grouping
- editing scheduler behavior without checking the local lock and state files
- assuming the current dashboard is a separate frontend app
- assuming the current Render runtime is already Postgres-ready
