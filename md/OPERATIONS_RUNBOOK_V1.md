# OPERATIONS_RUNBOOK_V1

## Purpose

Operational guide for running the Step 10/11 orchestration pipeline safely in production-like environments.

## Preflight

1. Validate runtime and schema:

```powershell
python .\scripts\orchestration\bootstrap_env.py --db-path data/agent.db
```

2. Confirm ingestion credential is not placeholder:

- `ZHAO_SECRET` must be a real assigned secret.
- For strict enforcement use:

```powershell
python .\scripts\orchestration\bootstrap_env.py --db-path data/agent.db --strict-env
```

## Scheduler Modes

Daily full cycle:

```powershell
python .\scripts\orchestration\run_scheduled_cycle.py --mode daily --db-path data/agent.db --user-id u_001
```

Alert tick cycle (higher frequency, lower API budget):

```powershell
python .\scripts\orchestration\run_scheduled_cycle.py --mode alerts --db-path data/agent.db --user-id u_001
```

Suggested cadence:

- `daily` at a fixed local time once per day.
- `alerts` every 1-2 hours (respecting source API limits).

## Failure Recovery

1. Check latest runs:

```powershell
python .\scripts\orchestration\report_pipeline_health.py --db-path data/agent.db --recent-runs 20
```

2. If a stage fails repeatedly:
- inspect `orchestration_stage_runs.error_message` and `metrics_json`
- rerun targeted cycle with fewer retries for quick feedback
- if ingestion is failing due to rate limit, wait and rerun in `alerts` mode with lower budget

3. Resume behavior:
- matching/signals/metrics/report stages are idempotent by design
- alert dispatch is deduped by `(signal_id, channel)`

## Observability Queries

Recent run outcomes:

```sql
SELECT started_at, finished_at, status, user_id, report_date
FROM orchestration_runs
ORDER BY started_at DESC
LIMIT 20;
```

Recent failed stage attempts:

```sql
SELECT orchestration_run_id, stage_name, attempt_no, started_at, error_message
FROM orchestration_stage_runs
WHERE status = 'failed'
ORDER BY started_at DESC
LIMIT 20;
```

Immediate alert dispatch status:

```sql
SELECT status, COUNT(*) AS cnt
FROM alert_dispatch_log
GROUP BY status;
```

## Concurrency Rule

Do not run multiple schema-initializing scripts in parallel against the same SQLite DB.

## Deployment Smoke Check

Use CI/local smoke run to verify minimum end-to-end behavior:

```powershell
python .\scripts\orchestration\run_smoke_pipeline.py
```

Expected:

- orchestration run succeeds
- at least one signal generated
- at least one report generated
- at least one immediate alert dispatch logged
