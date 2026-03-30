# V2 Current Status

## Why This Document Exists

V2 now spans:

- live Zhaoonline incremental sync
- normalization and parse refresh
- interest-driven matching and signals
- daily review/report generation
- a Render-hosted dashboard/report/API runtime

This document tells a new developer what is real today, what is still transitional, and what should not be assumed.

## Stable Enough Today

These parts are present in source control and are usable:

- Zhaoonline V2 auth and API client
- live incremental polling runner
- post-sync normalization module and runner
- post-sync parse refresh module and runner
- V2 schema migrations under `migrations_v2`
- V2 interest profile model
- curated demo user seeding
- listing parser module
- V2 matcher
- V2 signal engine
- V2 daily review, signal-review, and interest-digest reporting
- Render-hosted web runtime
- built-in collector dashboard
- built-in report browser
- thin V2 HTTP API for profile, report, digest, matching, and signals
- legacy local Windows scheduled task wrappers for live sync and daily review/reporting

## Transitional Or Incomplete

These parts are still transitional:

- automatic matching refresh after each live incremental run
- automatic signal generation refresh after each live incremental run
- standalone frontend app separate from the current built-in dashboard shell
- storage abstraction for Postgres readiness
- one-command end-to-end V2 orchestration
- clean separation between web/API work and background-worker work

## Important Reality About Data Layers

The current V2 database may already contain:

- normalized listings
- normalized media
- normalized events
- parsed listing rows
- active matches
- active signals

But a developer must not assume those layers are fully refreshed automatically by the live sync loop.

Current live behavior is narrower:

- fetch one completed incremental window
- keep meaningful raw changes
- normalize affected listings
- refresh parse rows for affected listings
- write sync telemetry
- advance the live watermark

Matching refresh and signal generation are still outside the automatic live-sync path.

## Current Deployment Reality

The current simplest production-ish deployment is:

- one Render web service
- one Render persistent disk
- one SQLite database file on that disk

The current service runs:

- the dashboard and report browser
- the thin API
- the background incremental-check loop
- the background daily review/report loop

That combined runtime is implemented through:

- `scripts_v2/orchestration/run_v2_report_service.py`
- `src/ai_agent_v2/runtime_host.py`

This is intentionally simple for the current stage. It is not yet the final scalable architecture.

## What Exists In Source Vs What Exists In Local Or Cloud Data

Checked-in source currently includes:

- `src/ai_agent_v2/clients/zhaoonline.py`
- `src/ai_agent_v2/ingestion/live_incremental.py`
- `src/ai_agent_v2/parsing/listing_parser.py`
- `src/ai_agent_v2/profile/*.py`
- `src/ai_agent_v2/matching/v2_matcher.py`
- `src/ai_agent_v2/signals/interest_signals.py`
- `src/ai_agent_v2/reporting/*.py`
- `src/ai_agent_v2/runtime_host.py`
- `scripts_v2/orchestration/run_v2_incremental_cycle.py`
- `scripts_v2/orchestration/run_v2_report_service.py`
- `scripts_v2/orchestration/seed_v2_demo_user.py`
- `scripts_v2/orchestration/migrate_v2_interest_profile.py`
- `scripts_v2/matching/run_zhaoonline_v2_matching.py`

So if a developer sees rich data in `agent_v2.db`, they should treat that as:

- real working state

but not automatically assume:

- full end-to-end automatic refresh already exists

## Current Product Surface

The current product-facing V2 surface is no longer only developer reports.

It now includes:

- dashboard at `/`
- report browser routes
- digest/report pages
- profile/report/digest JSON endpoints
- matching/signal action endpoints

The current dashboard is still transitional:

- it is built into the same service as the reports
- it is currently centered on the demo collector
- it is a product shell, not yet a separate frontend app

## Current Profile And Matching State

The primary V2 user model is:

- `user_profile_defaults_v2`
- `user_interests_v2`
- `user_interest_targets_v2`
- `user_holdings_v2`
- `user_interest_signal_policies_v2`

The matcher prefers V2 targets first and uses legacy `user_items` only as fallback.

## Current Biggest Product Gap

The biggest missing V2 capability is not raw ingestion anymore.

It is the absence of a stable automatic downstream chain:

live incremental -> normalization -> parse refresh -> matching refresh -> signals

Until that exists, developers should think of V2 as:

- stable live intake plus a transitional product shell

not:

- a fully automated product pipeline

## Recommended Next Development Themes

If a new developer wants to help, the highest-value areas are:

1. automatic matching refresh after live incremental sync
2. automatic signal refresh on top of `user_interests_v2`
3. signals and matches dashboard views on top of the thin API
4. cleaner storage boundaries for future Postgres support
5. separation of web/API and background-worker concerns when the product surface grows
