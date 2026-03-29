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
- documentation

The riskiest areas are the ones that are still transitional:

- automatic matching refresh after scheduled incremental sync
- signal generation refresh cadence
- end-user delivery
- signal/report threshold tuning

## First Read

Read these in order:

1. `V2_CURRENT_STATUS.md`
2. `V2_ARCHITECTURE.md`
3. `V2_DATA_MODEL.md`
4. `V2_RUNTIME_WORKFLOW.md`
5. `V2_OPERATIONS_RUNBOOK.md`

## Local Requirements

- Windows environment
- Python 3.11+
- local virtual environment in `.venv`
- local SQLite database at `data/agent_v2.db`

The current `pyproject.toml` has no external runtime dependencies listed, so most workflows run with the local source tree plus standard library and the current venv.

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

Think about V2 as four practical layers:

1. scheduler and raw landing
2. normalized market tables
3. parse, matching, and signals
4. review/report delivery

Today:
- layer 1 is fully wired into scheduled automation
- daily review/report delivery is scheduled
- matching refresh and signal generation still require explicit runs

## What To Check Before Making Changes

Before editing V2 code, confirm:

1. whether the change affects live scheduled polling
2. whether the change depends on normalized tables being refreshed automatically
3. whether the code reads V2 interests or legacy `user_items`
4. whether the change assumes the historical backfill state is still active

## Common Developer Mistakes To Avoid

- assuming scheduled incremental sync also refreshes normalized tables
- assuming daily signal-review tasks generate new signals
- assuming daily digest tasks generate new matches
- assuming `listing_matches_v2.user_item_id` always points to `user_items.id`
- assuming historical backfill state and live state are the same thing
- tightening broad discovery matching when the real problem is result grouping
- editing scheduler behavior without checking the local lock and state files
