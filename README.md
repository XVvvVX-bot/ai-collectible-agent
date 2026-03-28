# AI Collectibles Intelligence Agent

Collectibles intelligence system focused on market monitoring, structured matching, and alert/report generation.

The repository currently contains:
- `ai_agent` for the V1 pipeline
- `ai_agent_v2` for the new Zhaoonline API migration and the next matching/signal stack

## Current Reality

V1 is still the stable reference implementation.

V2 is the active build track and already has:
- new Zhaoonline auth/client support for the V2 API
- V2 raw sync schema and forward incremental scheduler
- normalized listing/event/media tables in the local V2 database
- title parsing
- V2 interest-profile model
- V2 matching against `user_interests_v2` / `user_interest_targets_v2`
- Windows Task Scheduler integration for live incremental polling

V2 is not a finished replacement yet. The most important current gap is that live scheduled incremental sync currently lands raw change data only; it does not yet run a full downstream normalization + parsing + matching chain automatically.

## Repository Layout

```text
F:\AI Agent
|-- md/                         # Documentation
|   `-- v2/                     # V2-specific technical docs
|-- migrations/                 # V1 migrations
|-- migrations_v2/              # V2 migrations
|-- scripts/                    # V1 scripts
|-- scripts_v2/                 # V2 scripts
|   |-- matching/
|   |-- orchestration/
|   |-- reporting/
|   `-- windows/
|-- src/
|   |-- ai_agent/               # V1 package
|   `-- ai_agent_v2/            # V2 package
|-- tests/                      # Test suite
|-- data/                       # Local runtime data (git-ignored)
|-- reports/                    # V1 report outputs (git-ignored)
|-- reports_v2/                 # V2 report outputs (git-ignored)
|-- .env.example
`-- pyproject.toml
```

## Docs

- [Docs Index](./md/README.md)
- [V2 Docs Index](./md/v2/README.md)
- [V2 Developer Quickstart](./md/v2/V2_DEVELOPER_QUICKSTART.md)
- [V2 Current Status](./md/v2/V2_CURRENT_STATUS.md)
- [V2 Architecture](./md/v2/V2_ARCHITECTURE.md)
- [V2 Data Model](./md/v2/V2_DATA_MODEL.md)
- [V2 Runtime Workflow](./md/v2/V2_RUNTIME_WORKFLOW.md)
- [V2 Operations Runbook](./md/v2/V2_OPERATIONS_RUNBOOK.md)
- [V2 Matching Status](./md/v2/V2_MATCHING_STATUS.md)
- [V2 User Profile Model](./md/v2/V2_USER_PROFILE_MODEL.md)

## V2 Main Scripts

Seed the curated demo user:

```powershell
cd "F:\AI Agent"
.\.venv\Scripts\python.exe .\scripts_v2\orchestration\seed_v2_demo_user.py
```

Run one live V2 incremental window:

```powershell
.\.venv\Scripts\python.exe .\scripts_v2\orchestration\run_v2_incremental_cycle.py --db-path data/agent_v2.db
```

Run V2 matching for one user:

```powershell
.\.venv\Scripts\python.exe .\scripts_v2\matching\run_zhaoonline_v2_matching.py --db-path data/agent_v2.db --user-id demo_u_v2_curated
```

Build a V2 match audit report:

```powershell
.\.venv\Scripts\python.exe .\scripts_v2\reporting\run_zhaoonline_v2_match_audit.py --db-path data/agent_v2.db
```

Register the Windows scheduled live incremental task:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts_v2\windows\register_v2_incremental_task.ps1
```

6. Build provisional taxonomy mappings from currently unmapped values:

```powershell
python .\scripts\taxonomy\bootstrap_zhaoonline_taxonomy.py --db-path data/agent.db --top-n-per-field 100 --apply
```

7. View unmapped taxonomy values (for technician follow-up / governance loop):

```powershell
python .\scripts\taxonomy\report_unmapped_zhaoonline_taxonomy.py --db-path data/agent.db --top-n-per-field 20 --sample-size 3
```

8. Run normalized-data quality checks:

```powershell
python .\scripts\quality\run_norm_quality_checks.py --db-path data/agent.db --batch-size 2000
```

9. Import holdings/watchlist from CSV/Excel (preview by default):

```powershell
python .\scripts\importers\import_user_items.py --db-path data/agent.db --user-id u_001 --file-path data/user_items.csv
```

Add `--commit` to apply writes.

10. Run matching engine V1:

```powershell
python .\scripts\matching\run_v1_matching.py --db-path data/agent.db --user-id u_001 --min-score 30
```

11. Run rule-based signal generation:

```powershell
python .\scripts\signals\run_rule_signals.py --db-path data/agent.db --user-id u_001 --cooldown-hours 24 --freshness-hours 24 --price-move-threshold-pct 10
```

12. Run end-to-end orchestration pipeline (Step 10):

```powershell
python .\scripts\orchestration\run_pipeline.py --db-path data/agent.db --user-id u_001 --report-type daily
```

13. Scheduler-ready modes (Step 11):

```powershell
# daily full cycle
python .\scripts\orchestration\run_scheduled_cycle.py --mode daily --db-path data/agent.db --user-id u_001

# frequent alert cycle
python .\scripts\orchestration\run_scheduled_cycle.py --mode alerts --db-path data/agent.db --user-id u_001
```

14. Operations health report:

```powershell
python .\scripts\orchestration\report_pipeline_health.py --db-path data/agent.db --recent-runs 20 --alert-window-hours 24
```

## Development Workflow

- main DB: `data/agent_v2.db`
- live secret file: `data/secrets/zhaoonline_secret.txt`
- live scheduler log: `data/logs/zhao_v2_incremental_live.log`
- live scheduler lock: `data/locks/zhaoonline_v2_incremental_live.lock`
- live rate-limit state: `data/zhaoonline_v2_rate_limit_live.json`

## Tests

Run the focused V2 tests:

```powershell
.\.venv\Scripts\pytest.exe -q tests\test_v2_demo_user_seed.py tests\test_v2_interest_matching.py tests\test_v2_interest_profile_migration.py tests\test_v2_live_incremental.py tests\test_v2_matching_strictness.py
```

- project docs initialized
- source-agnostic V1 schema drafted
- initial SQL migration added
- Zhaoonline diagnostic tooling added
- raw ingestion + normalization + taxonomy bootstrap + quality checks implemented
- user domain services implemented for deterministic upsert and lifecycle control

- Do not commit real secrets.
- Keep the Zhaoonline secret outside source control.
- Use the local ignored path `data/secrets/zhaoonline_secret.txt` or environment variables.

1. Build CSV/Excel intake on top of `UserDomainService`.
2. Build matching engine and rule-based signal generation.

Read these in order:
1. [V2 Developer Quickstart](./md/v2/V2_DEVELOPER_QUICKSTART.md)
2. [V2 Current Status](./md/v2/V2_CURRENT_STATUS.md)
3. [V2 Architecture](./md/v2/V2_ARCHITECTURE.md)
4. [V2 Data Model](./md/v2/V2_DATA_MODEL.md)
5. [V2 Runtime Workflow](./md/v2/V2_RUNTIME_WORKFLOW.md)
6. [V2 Matching Status](./md/v2/V2_MATCHING_STATUS.md)
7. [V2 Operations Runbook](./md/v2/V2_OPERATIONS_RUNBOOK.md)
