# V2 Runtime Workflow

## Overview

There are currently three practical workflows in V2:

1. live forward incremental polling
2. profile + parsing + matching review
3. daily review/report automation

These are related, but they are not yet one fully automated pipeline.

Read `V2_CURRENT_STATUS.md` first if you need the short version of what is and is not automated today.

## Workflow 1: Live Incremental Polling

Primary entrypoint:

- `scripts_v2/orchestration/run_v2_incremental_cycle.py`

Windows scheduled wrapper:

- `scripts_v2/windows/run_v2_incremental_cycle.ps1`

### What It Does

1. load the Zhaoonline secret from env or `data/secrets/zhaoonline_secret.txt`
2. acquire a local lock
3. read live watermark from `zhao_v2_sync_state` using `source_platform='zhaoonline_live'`
4. choose the next completed 1-hour window
5. process up to a safe capped number of completed windows in one run when backlog exists
6. call `/api/search/auctions/incremental`
7. keep only meaningful rows where `oldStatus != newStatus`
8. write raw rows to:
   - `zhao_v2_auction_raw`
   - `zhao_v2_auction_change_raw`
9. normalize affected listings into:
   - `market_listings_norm_v2`
   - `market_listing_events_v2`
   - `market_listing_media_v2`
10. refresh affected parse rows in:
   - `listing_parse_v2`
11. write telemetry to:
   - `zhao_v2_sync_runs`
   - `zhao_v2_sync_run_pages`
12. advance the live watermark after each successfully completed window

### What It Does Not Yet Do

It does not automatically:
- rerun matching
- regenerate signals

That limitation matters when interpreting live scheduled polling: matching and signals can still lag behind raw/normalized/parsed data.

## Workflow 2: Parsing + Matching Review

### Seed or Prepare User Profile

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

Important current note:

- the parser module is checked in
- a standalone parsing runner now exists in `scripts_v2/parsing/run_zhaoonline_v2_listing_parse.py`
- the live scheduler can refresh parse rows for affected listings

### Run Matching

```powershell
.\.venv\Scripts\python.exe .\scripts_v2\matching\run_zhaoonline_v2_matching.py --db-path data/agent_v2.db --user-id demo_u_v2_curated
```

### Build Audit Report

```powershell
.\.venv\Scripts\python.exe .\scripts_v2\reporting\run_zhaoonline_v2_match_audit.py --db-path data/agent_v2.db
```

### Build Signals And Review Outputs

```powershell
.\.venv\Scripts\python.exe .\scripts_v2\signals\run_zhaoonline_v2_interest_signals.py --db-path data/agent_v2.db --user-id demo_u_v2_curated
.\.venv\Scripts\python.exe .\scripts_v2\reporting\run_zhaoonline_v2_signal_review.py --db-path data/agent_v2.db --user-id demo_u_v2_curated
.\.venv\Scripts\python.exe .\scripts_v2\reporting\run_zhaoonline_v2_interest_digest.py --db-path data/agent_v2.db --user-id demo_u_v2_curated
```

## Workflow 3: Daily Review/Report Automation

There are now three logon-triggered, once-per-local-day reporting tasks:

- `AI Agent V2 Daily Review`
- `AI Agent V2 Daily Signal Review`
- `AI Agent V2 Daily Interest Digest`

These use local state files in `data/state/` so multiple logins on the same day do not produce duplicate daily outputs.

### What These Tasks Do

- `AI Agent V2 Daily Review`
  Builds one consolidated user-base review report.
- `AI Agent V2 Daily Signal Review`
  Builds one signal-review report per active V2 user plus an index file.
- `AI Agent V2 Daily Interest Digest`
  Builds one interest-digest report per active V2 user plus an index file.

### What These Tasks Do Not Do

They do not:
- refresh matching
- generate signals
- advance sync watermark state

They only summarize the current state already present in the database.

## Current Working Model

### Live Ops Path

scheduled incremental -> raw tables -> normalization -> parse refresh -> watermark

Current catch-up behavior:

- task trigger frequency is every 30 minutes
- each successful cycle can now process multiple completed 1-hour windows
- the safe cap is controlled by `ZHAO_V2_MAX_WINDOWS_PER_RUN` or `--max-windows-per-run`

### Developer Review Path

profile seed/migration -> parse -> matching -> signals -> audit/review reports

### Daily Reporting Path

logon -> once-per-day guard -> review/signal/digest reports

## Why These Are Separate Right Now

Because V2 is still in transition:
- live polling is stable enough to run on schedule
- downstream transformation and signal logic still need more shaping

Keeping these separated reduces the chance that a scheduler problem corrupts higher layers while the matching/signal model is still changing.

This separation is intentional, not accidental.

## Important Runtime Files

### Database

- `data/agent_v2.db`

### Secret

- `data/secrets/zhaoonline_secret.txt`

### Scheduler Files

- `data/locks/zhaoonline_v2_incremental_live.lock`
- `data/zhaoonline_v2_rate_limit_live.json`
- `data/logs/zhao_v2_incremental_live.log`

### Reports

- `reports_v2/*.md`

## Recommended Developer Sequence

When working on V2 locally:

1. confirm schema with `SqliteV2Store.ensure_schema()`
2. confirm live sync can run one window
3. inspect raw sync results in `zhao_v2_sync_runs` and `zhao_v2_sync_run_pages`
4. seed or migrate the profile model you want to test
5. run matching
6. review the audit report

## Current Known Gap

For full end-to-end product behavior, V2 still needs the remaining downstream chain:

live incremental -> normalization -> parsing refresh -> matching refresh -> signals

That is the next major operational milestone after the current documentation pass.
