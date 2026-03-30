# V2 Dashboard And API

## Purpose

This document describes the current product-facing V2 surface:

- the Render-hosted collector dashboard
- the built-in report browser
- the thin HTTP API currently exposed by the same runtime

This is the bridge between the repo's earlier developer/report tooling and the next-stage frontend product.

## Current Runtime Shape

Today the live V2 service is one combined process:

- HTTP server from `scripts_v2/orchestration/run_v2_report_service.py`
- background loop from `src/ai_agent_v2/runtime_host.py`
- SQLite database on the Render disk at `runtime/data/agent_v2.db`

That means one Render service currently does all of the following:

- serves the dashboard and report pages
- exposes the thin API
- runs incremental sync checks
- runs daily review/report cycles

This is intentionally simple for the current stage. It is not yet the final multi-service architecture.

## Current Product Objects

The current UI and API revolve around four V2 product objects:

- interests from `user_interests_v2`
- matches from `listing_matches_v2`
- signals from `signals_v2`
- digest/review outputs from `reports_v2/*.md`

Those objects are the basis for the next-stage frontend.

## Current Dashboard

Current root route:

- `/`

Current homepage role:

- collector dashboard for the default demo user

Current dashboard sections:

- collector identity / top hero
- summary cards
- latest digest preview
- latest digest / signal review / daily review shortcuts
- priority interests
- user-scoped report list
- shared daily report list
- bundle downloads
- live API links

Current default dashboard user:

- `demo_u_v2_curated`

The dashboard is still backed by report and SQLite data directly. It is a transitional product shell rather than a separate frontend app.

## Current HTML Routes

The built-in web service currently serves:

- `/`
- `/healthz`
- `/latest/<kind>`
- `/reports/<filename>`
- `/raw/<filename>`
- `/downloads/<bundle-name>`

`/latest/<kind>` is a convenience redirect for the newest report of a given type.

## Current API Routes

### General

- `GET /api/reports`

Returns:

- all report metadata visible to the service
- bundle metadata

### User Profile

- `GET /api/users/{user_id}/profile`

Returns:

- user record
- V2 default profile settings
- summary counts
- active interests
- nested targets
- nested holdings
- signal policy per interest

This is the best current backend endpoint for a frontend "Interests" or "Profile" page.

### User Reports

- `GET /api/users/{user_id}/reports`

Returns:

- user-scoped reports
- shared daily reports
- latest report metadata by type

This is the best current backend endpoint for a "Reports" page or dashboard shortcuts.

### Latest Digest

- `GET /api/users/{user_id}/digest/latest`

Returns:

- latest digest metadata
- links to rendered/raw views
- markdown content

If no digest exists yet, the service can build one on demand using the current SQLite data.

### Matching Action

- `POST /api/users/{user_id}/matching/run`

Optional query param:

- `only_active=true|false`

Wraps:

- `run_v2_matching(...)`

Returns the structured matching run result.

### Signals Action

- `POST /api/users/{user_id}/signals/run`

Optional query param:

- `lookback_hours=<int>`

Wraps:

- `run_interest_signal_generation(...)`

Returns the structured signal-generation result.

## Why The API Is Thin

The current codebase still depends directly on:

- `sqlite3`
- file-based runtime state
- file-backed reports

So the safest next backend step was not a full framework rewrite. It was a thin API layer that wraps the existing stable V2 functions.

This keeps the current runtime working while giving a frontend real JSON surfaces to build against.

## Current Limitations

The current dashboard/API layer is useful, but still transitional:

- still SQLite-backed
- still file-backed for reports and some runtime state
- still one combined HTTP + background-loop process
- dashboard is currently centered on the demo user
- live sync still does not automatically rerun matching or signal generation after every incremental update
- report markdown is still a major presentation layer, not just a backend artifact

## Near-Term Frontend Plan

The recommended first real frontend product shape is:

1. dashboard
2. signals inbox
3. interest profile
4. matches / opportunities
5. reports as supporting detail

The current built-in dashboard should be treated as:

- a live transitional frontend shell
- a design/prototyping surface
- not yet the final standalone frontend application

## Near-Term Backend Plan

Recommended next backend sequence:

1. keep the current Render + SQLite runtime stable
2. keep expanding the thin API around existing V2 functions
3. build frontend pages against those API routes
4. isolate storage access behind cleaner interfaces
5. only then plan Postgres support

That order keeps product progress moving without forcing an early storage rewrite.
