# V2 Render Deployment

## Purpose

This document captures the current simplest cloud deployment for V2:

- one Render web service
- one Render persistent disk
- one SQLite database file on that disk

This is the current "off the laptop" deployment path. It is not yet the future Postgres architecture.

## What This Deployment Does

- runs the long-lived report web service in `scripts_v2/orchestration/run_v2_report_service.py`
- keeps runtime files under `/opt/render/project/src/runtime`
- stores the current V2 SQLite database on the attached Render disk
- serves a report index and report pages over HTTP
- keeps the live incremental and daily review/report loops running in a background thread

## Current Render Files

- root blueprint: `render.yaml`
- worker entrypoint: `scripts_v2/orchestration/run_v2_background_worker.py`
- web/report entrypoint: `scripts_v2/orchestration/run_v2_report_service.py`

## Current Runtime Paths On Render

- runtime root:
  `/opt/render/project/src/runtime`
- database:
  `/opt/render/project/src/runtime/data/agent_v2.db`
- reports:
  `/opt/render/project/src/runtime/reports_v2`
- state files:
  `/opt/render/project/src/runtime/data/state`
- secret file fallback:
  `/opt/render/project/src/runtime/data/secrets/zhaoonline_secret.txt`

## Why This Uses SQLite On Disk

The checked-in V2 code still uses `sqlite3` directly in many modules.

That means the simplest cloud deployment today is:

- Render worker
- persistent disk
- SQLite database copied from local development

This is already isolated from the developer laptop because both the worker and the database file live on Render infrastructure.

## First Deployment Flow

1. push the branch containing `render.yaml`
2. create a Render Blueprint from the GitHub repo
3. let Render create the web service and disk
4. set `ZHAO_V2_SECRET`
5. confirm the service starts successfully in logs
6. open the Render service URL to browse reports

## Importing The Current Local Database

If the cloud worker starts with a mostly empty fresh database, the simplest way to bring over the current working state is to copy the local `data/agent_v2.db` file onto the Render disk.

The current tested path is:

1. open Render Shell
2. move aside the existing cloud DB if needed
3. transfer the local DB with Magic Wormhole
4. keep the uploaded file as `agent_v2.db`
5. point `ZHAO_V2_DATABASE_PATH` at that uploaded DB
6. redeploy the worker

### Example Render Shell Paths

Move aside the current DB:

```bash
cd /opt/render/project/src/runtime/data
mv agent_v2.db agent_v2_before_import.db
```

Receive the uploaded file:

```bash
wormhole receive <code-from-local-machine>
```

## Required Environment Variables

Current important Render env vars:

- `ZHAO_V2_SECRET`
- `ZHAO_V2_DATABASE_PATH`
- `ZHAO_V2_BASE_URL`
- `APP_INCREMENTAL_CHECK_MINUTES`
- `APP_DAILY_CHECK_MINUTES`
- `APP_DAILY_LOOKBACK_HOURS`
- `APP_LOOP_SLEEP_SECONDS`
- `ZHAO_V2_MAX_WINDOWS_PER_RUN`
- `ZHAO_V2_MIN_INTERVAL_SEC`

Current checked-in database path in `render.yaml`:

- `/opt/render/project/src/runtime/data/agent_v2.db`

If the DB filename changes later, update both:

- the Render environment variable
- `render.yaml`

## Logs To Expect

Healthy startup logs include:

- `worker_started`
- `report_service_started`
- `incremental_cycle`
- `daily_cycles`

## Report Browser Routes

The Render service now serves reports directly from the runtime disk.

Main routes:

- `/`
- `/healthz`
- `/api/reports`
- `/reports/<filename>`
- `/raw/<filename>`
- `/downloads/<bundle-name>`

Healthy behavior examples:

- `skip_reason="no_completed_window"` means there was simply no closed sync window available yet
- `skip_reason="already_ran_today"` means the once-per-day daily report guard is working

## Manual Report Refresh On Render

If daily reports already ran before a DB import, remove the state files and rerun them manually.

Clear once-per-day guards:

```bash
rm -f /opt/render/project/src/runtime/data/state/v2_daily_user_base_review_state.json
rm -f /opt/render/project/src/runtime/data/state/v2_daily_signal_review_state.json
rm -f /opt/render/project/src/runtime/data/state/v2_daily_interest_digest_state.json
```

Run the three report cycles:

```bash
cd /opt/render/project/src
python scripts_v2/orchestration/run_v2_daily_user_base_review_cycle.py --db-path /opt/render/project/src/runtime/data/agent_v2.db --output-dir /opt/render/project/src/runtime/reports_v2 --state-dir /opt/render/project/src/runtime/data/state
python scripts_v2/orchestration/run_v2_daily_signal_review_cycle.py --db-path /opt/render/project/src/runtime/data/agent_v2.db --output-dir /opt/render/project/src/runtime/reports_v2 --state-dir /opt/render/project/src/runtime/data/state
python scripts_v2/orchestration/run_v2_daily_interest_digest_cycle.py --db-path /opt/render/project/src/runtime/data/agent_v2.db --output-dir /opt/render/project/src/runtime/reports_v2 --state-dir /opt/render/project/src/runtime/data/state
```

## Packaging Reports For Download

The simplest current way to retrieve reports from Render is:

1. package the latest report markdown files into one zip
2. transfer that zip off the Render shell

Create a zip bundle:

```bash
cd /opt/render/project/src
python scripts_v2/reporting/package_v2_reports.py --reports-dir /opt/render/project/src/runtime/reports_v2 --output-dir /opt/render/project/src/runtime/exports --limit 20
```

That creates a zip like:

- `/opt/render/project/src/runtime/exports/v2_reports_bundle_<timestamp>.zip`

You can then transfer that single zip file with the same Magic Wormhole workflow used for the database.

## Current Known Limitations

- this is still SQLite, not managed Postgres
- matching and signals are still not automatically refreshed after every live sync
- reports live on the Render disk and are not yet exposed through a user-facing web UI

## Recommended Next Cleanup

When ready, the next cleanup milestone is:

1. merge this deployment setup into `main`
2. keep the runtime DB at the normal name `agent_v2.db`
3. use the report packaging helper when you want to retrieve report files
4. later migrate to Postgres when the codebase is ready
