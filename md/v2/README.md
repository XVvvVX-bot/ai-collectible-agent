# V2 Documentation Index

This folder documents the current V2 implementation around the new Zhaoonline API.

Recommended reading order:

1. [V2_DEVELOPER_QUICKSTART.md](./V2_DEVELOPER_QUICKSTART.md)
2. [V2_CURRENT_STATUS.md](./V2_CURRENT_STATUS.md)
3. [V2_ARCHITECTURE.md](./V2_ARCHITECTURE.md)
4. [V2_DATA_MODEL.md](./V2_DATA_MODEL.md)
5. [V2_RUNTIME_WORKFLOW.md](./V2_RUNTIME_WORKFLOW.md)
6. [V2_MATCHING_STATUS.md](./V2_MATCHING_STATUS.md)
7. [V2_OPERATIONS_RUNBOOK.md](./V2_OPERATIONS_RUNBOOK.md)
8. [V2_USER_PROFILE_MODEL.md](./V2_USER_PROFILE_MODEL.md)
9. [V2_DAILY_EVALUATION_CHECKLIST.md](./V2_DAILY_EVALUATION_CHECKLIST.md)

## What V2 Covers Today

- V2 raw sync schema
- forward-looking incremental polling
- scheduled normalization refresh
- scheduled parse refresh
- normalized V2 database tables
- listing parse layer
- V2 profile model
- V2 matching on top of interest targets
- signal review and digest reporting
- Windows scheduled polling and daily review/report setup

## Important Limitation

The live scheduled V2 incremental cycle now runs:

- raw incremental sync
- normalization refresh for affected listings
- parse refresh for affected listings

It does not yet run automatic matching refresh or signal generation.

The daily report tasks now exist, but they report on current database state only. They do not create new matches or new signals on their own.

That remaining limitation is deliberate while matching and signals are still evolving.

## Fast Orientation

If you are new to the repo:

1. read `V2_DEVELOPER_QUICKSTART.md`
2. read `V2_CURRENT_STATUS.md`
3. use `V2_OPERATIONS_RUNBOOK.md` before touching the live scheduler
