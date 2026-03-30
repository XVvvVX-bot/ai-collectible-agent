# V2 Runtime Workflow

## Overview

There are currently four practical V2 workflows:

1. live incremental polling
2. profile + parsing + matching + signals review
3. daily review/report automation
4. dashboard/API serving

These are related, but they are still not one fully automated end-to-end pipeline.

Read `V2_CURRENT_STATUS.md` first if you need the short version of what is and is not automated today.

## Workflow 1: Live Incremental Polling

Primary code:

- `src/ai_agent_v2/ingestion/live_incremental.py`
- `src/ai_agent_v2/runtime_host.py`
- `scripts_v2/orchestration/run_v2_incremental_cycle.py`

### What It Does

1. load the Zhaoonline secret from env or secret-file fallback
2. acquire a local lock
3. read live watermark from `zhao_v2_sync_state` using `source_platform='zhaoonline_live'`
4. choose the next completed 1-hour window
5. process up to a safe capped number of completed windows when backlog exists
6. call `/api/search/auctions/incremental`
7. keep only meaningful rows where `oldStatus != newStatus`
8. write raw rows to V2 raw tables
9. normalize affected listings into normalized V2 tables
10. refresh affected parse rows in `listing_parse_v2`
11. write telemetry
12. advance the live watermark after each successfully completed window

### What It Does Not Yet Do

It does not automatically:

- rerun matching
- regenerate signals

That limitation matters when interpreting the live system: matching and signals can still lag behind raw/normalized/parsed data.

## Workflow 2: Profile + Matching + Signals Review

### Seed or Prepare The User Profile

Curated demo user:

```powershell
.\.venv\Scripts\python.exe .\scripts_v2\orchestration\seed_v2_demo_user.py
```

Legacy-to-V2 migration:

```powershell
.\.venv\Scripts\python.exe .\scripts_v2\orchestration\migrate_v2_interest_profile.py
```

### Parse Listings

Current parser module:

- `src/ai_agent_v2/parsing/listing_parser.py`

Standalone parsing runner:

- `scripts_v2/parsing/run_zhaoonline_v2_listing_parse.py`

### Run Matching

```powershell
.\.venv\Scripts\python.exe .\scripts_v2\matching\run_zhaoonline_v2_matching.py --db-path data/agent_v2.db --user-id demo_u_v2_curated
```

### Run Signals

```powershell
.\.venv\Scripts\python.exe .\scripts_v2\signals\run_zhaoonline_v2_interest_signals.py --db-path data/agent_v2.db --user-id demo_u_v2_curated
```

### Build Review Outputs

```powershell
.\.venv\Scripts\python.exe .\scripts_v2\reporting\run_zhaoonline_v2_match_audit.py --db-path data/agent_v2.db
.\.venv\Scripts\python.exe .\scripts_v2\reporting\run_zhaoonline_v2_signal_review.py --db-path data/agent_v2.db --user-id demo_u_v2_curated
.\.venv\Scripts\python.exe .\scripts_v2\reporting\run_zhaoonline_v2_interest_digest.py --db-path data/agent_v2.db --user-id demo_u_v2_curated
```

## Workflow 3: Daily Review / Report Automation

The current long-lived runtime can run three periodic review/report cycles:

- daily user-base review
- daily signal review
- daily interest digest

Legacy local Windows tasks also still exist for local-machine operation.

### What These Cycles Do

- build one consolidated user-base review report
- build one signal-review report per active V2 user plus an index file
- build one interest-digest report per active V2 user plus an index file

### What These Cycles Do Not Do

They do not:

- refresh matching
- generate signals
- advance sync watermark state

They summarize the current state already present in the database.

## Workflow 4: Dashboard And API Serving

Primary entrypoint:

- `scripts_v2/orchestration/run_v2_report_service.py`

Supporting runtime module:

- `src/ai_agent_v2/runtime_host.py`

### What It Does

1. build runtime config and paths
2. start the background loop in a daemon thread
3. serve HTTP routes from the same process
4. expose HTML dashboard/report pages
5. expose the thin V2 JSON API

### Current HTML Routes

- `/`
- `/healthz`
- `/latest/<kind>`
- `/reports/<filename>`
- `/raw/<filename>`
- `/downloads/<bundle-name>`

### Current API Routes

- `GET /api/reports`
- `GET /api/users/{user_id}/profile`
- `GET /api/users/{user_id}/reports`
- `GET /api/users/{user_id}/digest/latest`
- `POST /api/users/{user_id}/matching/run`
- `POST /api/users/{user_id}/signals/run`

### Why This Is Still Transitional

The current runtime is one combined process for simplicity.

That means:

- the product shell is already live
- but the web/API and background concerns are not yet split

## Current Working Model

### Live Ops Path

incremental sync -> raw tables -> normalization -> parse refresh -> watermark

### Product Review Path

profile seed/migration -> parse -> matching -> signals -> digest/review outputs -> dashboard/API

### Dashboard Path

profile + reports + digest + current database state -> HTML dashboard + JSON routes

## Important Runtime Files

### Database

- `runtime/data/agent_v2.db` on Render
- `data/agent_v2.db` for local development

### Secret

- `runtime/data/secrets/zhaoonline_secret.txt` fallback on Render
- `data/secrets/zhaoonline_secret.txt` fallback locally
- `ZHAO_V2_SECRET` environment variable is preferred in deployed environments

### Runtime State

- `runtime/data/state/*`
- `runtime/data/locks/*`
- `runtime/data/zhaoonline_v2_rate_limit_live.json`

### Reports

- `runtime/reports_v2/*.md`

## Recommended Developer Sequence

When working on V2 today:

1. confirm schema with `SqliteV2Store.ensure_schema()`
2. confirm live sync can run one window
3. inspect sync telemetry
4. seed or migrate the profile model you want to test
5. run matching
6. run signals
7. review digest / signal / dashboard output

## Current Known Gap

For full end-to-end product behavior, V2 still needs the remaining automatic downstream chain:

live incremental -> normalization -> parsing refresh -> matching refresh -> signals

That is the next major operational milestone after the current dashboard/API stage.
