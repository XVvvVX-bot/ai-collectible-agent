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

## V2 Local Runtime Files

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

## Security

- Do not commit real secrets.
- Keep the Zhaoonline secret outside source control.
- Use the local ignored path `data/secrets/zhaoonline_secret.txt` or environment variables.

## Recommendation For New Developers

Read these in order:
1. [V2 Developer Quickstart](./md/v2/V2_DEVELOPER_QUICKSTART.md)
2. [V2 Current Status](./md/v2/V2_CURRENT_STATUS.md)
3. [V2 Architecture](./md/v2/V2_ARCHITECTURE.md)
4. [V2 Data Model](./md/v2/V2_DATA_MODEL.md)
5. [V2 Runtime Workflow](./md/v2/V2_RUNTIME_WORKFLOW.md)
6. [V2 Matching Status](./md/v2/V2_MATCHING_STATUS.md)
7. [V2 Operations Runbook](./md/v2/V2_OPERATIONS_RUNBOOK.md)
