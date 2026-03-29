# V2 Current Status

## Why This Document Exists

V2 has grown through several implementation slices, and not every earlier runtime path is now represented as a clean checked-in entrypoint. This document tells a new developer what is real today, what is still transitional, and what should not be assumed.

## Stable Enough Today

These parts are present in the source tree and are usable:

- Zhaoonline V2 auth and API client
- live incremental polling runner
- Windows scheduled task wrapper for live incremental polling
- post-sync normalization module and runner
- post-sync parse refresh module and runner
- post-sync normalization refresh
- post-sync parse refresh
- V2 schema migrations currently checked in under `migrations_v2`
- V2 interest profile model
- curated demo user seeding
- listing parser module
- V2 matcher
- V2 signal engine
- V2 match audit reporting
- V2 signal review reporting
- V2 interest digest reporting
- Windows scheduled daily review/report tasks

## Transitional Or Incomplete

These parts are not yet a clean fully checked-in end-to-end operational path:

- automatic matching refresh after each scheduled incremental run
- automatic signal generation refresh after live sync
- user-facing delivery beyond developer-review reports
- one-command end-to-end V2 orchestration

## Important Reality About Data Layers

The local V2 database may already contain:

- normalized listings
- normalized media
- normalized events
- parsed listing rows
- active matches

But a developer must not assume those layers are being refreshed automatically by the live scheduler.

Current scheduled behavior is narrower:

- fetch one completed incremental window
- keep meaningful raw changes
- normalize affected listings
- refresh parse rows for affected listings
- write sync telemetry
- advance the live watermark

Matching refresh and signal generation are still outside the scheduled live-sync path.

Separately, V2 now also has logon-triggered once-per-day reporting tasks that generate:

- a daily user-base review
- a daily per-user signal-review batch
- a daily per-user interest-digest batch

Those reporting tasks summarize current database state only.

## What Exists In Source Vs What Exists In Local Data

Checked-in source currently includes:

- `src/ai_agent_v2/clients/zhaoonline.py`
- `src/ai_agent_v2/ingestion/live_incremental.py`
- `src/ai_agent_v2/parsing/listing_parser.py`
- `src/ai_agent_v2/profile/*.py`
- `src/ai_agent_v2/matching/v2_matcher.py`
- `src/ai_agent_v2/reporting/match_audit.py`
- `scripts_v2/orchestration/run_v2_incremental_cycle.py`
- `scripts_v2/orchestration/seed_v2_demo_user.py`
- `scripts_v2/orchestration/migrate_v2_interest_profile.py`
- `scripts_v2/matching/run_zhaoonline_v2_matching.py`
- `scripts_v2/reporting/run_zhaoonline_v2_match_audit.py`

The repo now exposes checked-in standalone normalization and parsing runners in `scripts_v2`.

So if a developer sees normalized or parsed data in `data/agent_v2.db`, they should treat that as existing local state, not as proof that the full refresh path is already automated.

## Current Profile And Matching State

The primary V2 user model is now:

- `user_profile_defaults_v2`
- `user_interests_v2`
- `user_interest_targets_v2`
- `user_holdings_v2`
- `user_interest_signal_policies_v2`

The matcher now prefers V2 targets first and uses legacy `user_items` only as fallback for users who do not have V2 interests.

## Current Operational State

The live scheduler is intended to be the only background automation that keeps running.

Current task:

- `AI Agent V2 Incremental Sync`

Current reporting tasks:

- `AI Agent V2 Daily Review`
- `AI Agent V2 Daily Signal Review`
- `AI Agent V2 Daily Interest Digest`

Current live state key:

- `source_platform='zhaoonline_live'`

This is intentionally separate from older backfill state.

## Current Biggest Product Gap

The biggest missing V2 capability is not raw ingestion anymore.

It is the absence of a stable automatic downstream chain:

live incremental -> normalization -> parse refresh -> matching refresh -> signals

Until that exists, developers should think of V2 as:

- raw live intake plus manually refreshed developer-review layers

not:

- a fully automated product pipeline

## Recommended Next Development Themes

If a new developer wants to help, the highest-value areas are:

1. automatic matching refresh after live incremental sync
2. automatic signal refresh on top of `user_interests_v2`
3. tighter grouping/ranking for review reports
4. cleanup of remaining transitional runtime paths
