# V2 Render Deployment

## Purpose

This document captures the current simplest cloud deployment for V2:

- one Render web service
- one Render persistent disk
- one SQLite database file on that disk

This is the current "off the laptop" deployment path. It is not yet the future Postgres architecture.

## What This Deployment Does

The current Render service:

- runs `scripts_v2/orchestration/run_v2_report_service.py`
- keeps runtime files under `/opt/render/project/src/runtime`
- stores the current V2 SQLite database on the attached Render disk
- serves the collector dashboard and report pages over HTTP
- exposes the thin V2 API
- keeps the live incremental and daily review/report loops running in a background thread

## Current Render Files

- root blueprint: `render.yaml`
- background/local helper entrypoint: `scripts_v2/orchestration/run_v2_background_worker.py`
- current deployed web entrypoint: `scripts_v2/orchestration/run_v2_report_service.py`

## Current Runtime Paths On Render

- runtime root:
  `/opt/render/project/src/runtime`
- database:
  `/opt/render/project/src/runtime/data/agent_v2.db`
- reports:
  `/opt/render/project/src/runtime/reports_v2`
- exports:
  `/opt/render/project/src/runtime/exports`
- state files:
  `/opt/render/project/src/runtime/data/state`
- secret file fallback:
  `/opt/render/project/src/runtime/data/secrets/zhaoonline_secret.txt`

## Why This Uses SQLite On Disk

The checked-in V2 code still uses `sqlite3` directly in many modules.

That means the simplest cloud deployment today is:

- Render web service
- persistent disk
- SQLite database copied from local development or maintained directly on Render

This is already isolated from the developer laptop because both the service and the database file live on Render infrastructure.

## Current Deployment Flow

1. push the branch containing `render.yaml`
2. create or sync the Render Blueprint from GitHub
3. let Render create/update the web service and disk
4. set `ZHAO_V2_SECRET`
5. confirm the service starts successfully in logs
6. open the Render service URL

Important:

- when `render.yaml` changes, Render may require a Blueprint sync, not only a manual code deploy

## Importing Or Restoring The Working Database

If the cloud service starts with a mostly empty fresh database, the simplest way to bring over the current working state is to copy the local `data/agent_v2.db` file onto the Render disk.

The tested path is:

1. open Render Shell
2. move aside the existing cloud DB if needed
3. transfer the local DB with Magic Wormhole
4. keep the uploaded file as `agent_v2.db`
5. confirm `ZHAO_V2_DATABASE_PATH` points at that file
6. redeploy if needed

### Example Render Shell Commands

Move aside the current DB:

```bash
cd /opt/render/project/src/runtime/data
mv agent_v2.db agent_v2_before_import.db
```

Receive the uploaded file:

```bash
wormhole receive <code-from-local-machine>
```

Verify the restored DB:

```bash
python - <<'PY'
import sqlite3
db="/opt/render/project/src/runtime/data/agent_v2.db"
conn=sqlite3.connect(db)
cur=conn.cursor()
print("users", cur.execute("select count(*) from users").fetchone()[0])
print("active_v2_interests", cur.execute("select count(*) from user_interests_v2 where active_status='active'").fetchone()[0])
print("active_matches_v2", cur.execute("select count(*) from listing_matches_v2 where status='active'").fetchone()[0])
print("active_signals_v2", cur.execute("select count(*) from signals_v2 where status='active'").fetchone()[0])
PY
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
- `APP_DEFAULT_USER_ID`
- `ZHAO_V2_MAX_WINDOWS_PER_RUN`
- `ZHAO_V2_MIN_INTERVAL_SEC`

Current checked-in database path in `render.yaml`:

- `/opt/render/project/src/runtime/data/agent_v2.db`

## Logs To Expect

Healthy startup logs include:

- `worker_started`
- `report_service_started`
- `incremental_cycle`
- `daily_cycles`

Healthy behavior examples:

- `skip_reason="no_completed_window"` means there was no closed sync window available yet
- `skip_reason="already_ran_today"` means the once-per-day daily report guard is working
- `reason="missing_secret"` means the service is up but sync will skip until `ZHAO_V2_SECRET` is available

## Current Dashboard / Report / API Routes

The Render service now exposes:

### HTML

- `/`
- `/healthz`
- `/latest/<kind>`
- `/reports/<filename>`
- `/raw/<filename>`
- `/downloads/<bundle-name>`

### JSON API

- `/api/reports`
- `/api/users/{user_id}/profile`
- `/api/users/{user_id}/reports`
- `/api/users/{user_id}/digest/latest`
- `/api/users/{user_id}/matching/run`
- `/api/users/{user_id}/signals/run`

## Manual Report Refresh On Render

If daily reports already ran before a DB restore, remove the state files and rerun them manually.

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

Create a zip bundle:

```bash
cd /opt/render/project/src
python scripts_v2/reporting/package_v2_reports.py --reports-dir /opt/render/project/src/runtime/reports_v2 --output-dir /opt/render/project/src/runtime/exports --limit 20
```

That creates a zip like:

- `/opt/render/project/src/runtime/exports/v2_reports_bundle_<timestamp>.zip`

## Current Known Limitations

- still SQLite, not managed Postgres
- matching and signals are still not automatically refreshed after every live sync
- the dashboard is still built into the same service as the background loop
- the current frontend shell is transitional and demo-user-centered

## Recommended Next Cleanup

When ready, the next cleanup milestones are:

1. keep the Render runtime stable on `main`
2. keep the runtime DB at the normal name `agent_v2.db`
3. expand the thin API rather than adding more file-first UI logic
4. later split the product shell from background work when the frontend grows
5. only then plan Postgres migration
