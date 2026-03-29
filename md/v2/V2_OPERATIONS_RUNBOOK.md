# V2 Operations Runbook

## Purpose

This runbook is for developers operating the current V2 build on a local Windows machine.

Read `V2_CURRENT_STATUS.md` before using this runbook if you are new to the project.

## Required Local Files

### Database

- `data/agent_v2.db`

### Secret

Preferred local secret location:

- `data/secrets/zhaoonline_secret.txt`

Alternative:
- `ZHAO_SECRET`
- `ZHAO_V2_SECRET`

### Scheduler Runtime Files

- lock file:
  `data/locks/zhaoonline_v2_incremental_live.lock`
- rate-limit state:
  `data/zhaoonline_v2_rate_limit_live.json`
- scheduler log:
  `data/logs/zhao_v2_incremental_live.log`

## Windows Scheduled Task

Current installed task name:

- `AI Agent V2 Incremental Sync`
- `AI Agent V2 Daily Review`
- `AI Agent V2 Daily Signal Review`
- `AI Agent V2 Daily Interest Digest`

Registration script:

- `scripts_v2/windows/register_v2_incremental_task.ps1`
- `scripts_v2/windows/register_v2_daily_user_base_review_task.ps1`
- `scripts_v2/windows/register_v2_daily_signal_review_task.ps1`
- `scripts_v2/windows/register_v2_daily_interest_digest_task.ps1`

Runner script:

- `scripts_v2/windows/run_v2_incremental_cycle.ps1`
- `scripts_v2/windows/run_v2_daily_user_base_review.ps1`
- `scripts_v2/windows/run_v2_daily_signal_review.ps1`
- `scripts_v2/windows/run_v2_daily_interest_digest.ps1`

Python entrypoint:

- `scripts_v2/orchestration/run_v2_incremental_cycle.py`
- `scripts_v2/orchestration/run_v2_daily_user_base_review_cycle.py`
- `scripts_v2/orchestration/run_v2_daily_signal_review_cycle.py`
- `scripts_v2/orchestration/run_v2_daily_interest_digest_cycle.py`

## Current Scheduler Behavior

The scheduled task:
- runs every 30 minutes
- uses a lock file to avoid overlap
- polls completed 1-hour incremental windows
- can process multiple backlog windows in one run, up to a safe cap
- writes only meaningful raw changes
- refreshes normalized listings/events/media for affected listings
- refreshes parse rows for affected listings
- advances the live watermark under `source_platform='zhaoonline_live'`

It does not currently:
- run matching refresh
- generate fresh signals

The daily report tasks:
- run at logon
- use a once-per-local-day guard via `data/state/*.json`
- generate markdown reports under `reports_v2`
- do not mutate sync watermark state

## Commands

### Register / Re-register Scheduler

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts_v2\windows\register_v2_incremental_task.ps1
```

### Register Daily Review / Report Tasks

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts_v2\windows\register_v2_daily_user_base_review_task.ps1
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts_v2\windows\register_v2_daily_signal_review_task.ps1
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts_v2\windows\register_v2_daily_interest_digest_task.ps1
```

### Run One Live Window Manually

```powershell
.\.venv\Scripts\python.exe .\scripts_v2\orchestration\run_v2_incremental_cycle.py --db-path data/agent_v2.db
```

### Run A Faster Catch-Up Cycle Manually

```powershell
.\.venv\Scripts\python.exe .\scripts_v2\orchestration\run_v2_incremental_cycle.py --db-path data/agent_v2.db --max-windows-per-run 4
```

### Run Normalization Only

```powershell
.\.venv\Scripts\python.exe .\scripts_v2\normalization\run_zhaoonline_v2_normalization.py --db-path data/agent_v2.db
```

### Run Parse Refresh Only

```powershell
.\.venv\Scripts\python.exe .\scripts_v2\parsing\run_zhaoonline_v2_listing_parse.py --db-path data/agent_v2.db
```

### Seed Curated Demo User

```powershell
.\.venv\Scripts\python.exe .\scripts_v2\orchestration\seed_v2_demo_user.py
```

### Run Matching For Demo User

```powershell
.\.venv\Scripts\python.exe .\scripts_v2\matching\run_zhaoonline_v2_matching.py --db-path data/agent_v2.db --user-id demo_u_v2_curated
```

### Build Match Audit Report

```powershell
.\.venv\Scripts\python.exe .\scripts_v2\reporting\run_zhaoonline_v2_match_audit.py --db-path data/agent_v2.db
```

### Run Signals For Demo User

```powershell
.\.venv\Scripts\python.exe .\scripts_v2\signals\run_zhaoonline_v2_interest_signals.py --db-path data/agent_v2.db --user-id demo_u_v2_curated
```

### Build Review Reports Manually

```powershell
.\.venv\Scripts\python.exe .\scripts_v2\reporting\run_zhaoonline_v2_daily_user_base_review.py --db-path data/agent_v2.db
.\.venv\Scripts\python.exe .\scripts_v2\reporting\run_zhaoonline_v2_signal_review.py --db-path data/agent_v2.db --user-id demo_u_v2_curated
.\.venv\Scripts\python.exe .\scripts_v2\reporting\run_zhaoonline_v2_interest_digest.py --db-path data/agent_v2.db --user-id demo_u_v2_curated
```

## Health Checks

### Check Scheduled Task Exists

```powershell
Get-ScheduledTask | Where-Object { $_.TaskName -eq 'AI Agent V2 Incremental Sync' }
Get-ScheduledTask | Where-Object { $_.TaskName -eq 'AI Agent V2 Daily Review' }
Get-ScheduledTask | Where-Object { $_.TaskName -eq 'AI Agent V2 Daily Signal Review' }
Get-ScheduledTask | Where-Object { $_.TaskName -eq 'AI Agent V2 Daily Interest Digest' }
```

### Check Live Watermark

Query `zhao_v2_sync_state` for:
- `source_platform='zhaoonline_live'`

### Check Latest Live Sync Run

Query `zhao_v2_sync_runs` for:
- `source_platform='zhaoonline_live'`

### Check Latest Live Page Telemetry

Query:
- `zhao_v2_sync_run_pages`
joined to
- `zhao_v2_sync_runs`

## Failure Modes

### Missing Secret

Symptom:
- runner returns `{"skipped": true, "reason": "missing_secret"}`

Fix:
- create `data/secrets/zhaoonline_secret.txt`
- or set `ZHAO_SECRET` / `ZHAO_V2_SECRET`

### Lock Held

Symptom:
- runner returns `{"skipped": true, "reason": "lock_held"}`

Meaning:
- another run is active
- or a stale lock was left behind

Check:
- `data/locks/zhaoonline_v2_incremental_live.lock`

### Rate Limiting

Symptom:
- slower cycles
- repeated retries

Current protection:
- local pacer spacing
- retry after `429`
- capped windows per run instead of unlimited catch-up

### Backfill State Confusion

Important rule:
- scheduled live sync should use `zhaoonline_live`
- historical backfill state stays under `zhaoonline`

Do not point the scheduled runner at the old historical state key unless you intentionally want replay behavior.

### Daily Report Seems Missing

Check:
- the corresponding logon task exists and is enabled
- the state file under `data/state/` does not already show today
- the relevant log file exists:
  - `data/logs/v2_daily_user_base_review.log`
  - `data/logs/v2_daily_signal_review.log`
  - `data/logs/v2_daily_interest_digest.log`

Important:
- daily signal-review tasks only summarize existing `signals_v2`
- daily digest tasks only summarize existing matches and current normalized state
- if matching or signals were never refreshed, the report can still be structurally healthy but informationally stale

## Current Operational Limitation

The live scheduler now covers raw incremental sync plus normalization and parsing.

So if a developer expects:
- new raw rows
- new normalized rows
- new parse rows
- new matches

from a single scheduled run, that is not true yet.

Matching refresh and signal generation still need to be run separately.

That means the expected healthy outcome of a scheduled run is:

- new raw rows
- new sync telemetry
- refreshed normalized rows for affected listings
- refreshed parse rows for affected listings
- advanced live watermark

It does not mean:

- new matches

## Recommended Daily Developer Routine

1. check scheduler status
2. check latest `zhaoonline_live` run
3. inspect log file if needed
4. if reviewing matching quality:
   - reseed demo user if needed
   - rerun matching
   - rerun signals if needed
   - regenerate review/digest reports
