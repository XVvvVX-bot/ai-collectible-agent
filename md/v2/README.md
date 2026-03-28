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

## What V2 Covers Today

- V2 raw sync schema
- forward-looking incremental polling
- normalized V2 database tables
- listing parse layer
- V2 profile model
- V2 matching on top of interest targets
- Windows scheduled polling setup

## Important Limitation

The live scheduled V2 incremental cycle currently writes raw incremental data and advances the live watermark, but it does not yet run a full automatic downstream chain for normalization, parsing, matching, or signals.

That limitation is deliberate to keep the scheduler stable while the rest of V2 is still evolving.

## Fast Orientation

If you are new to the repo:

1. read `V2_DEVELOPER_QUICKSTART.md`
2. read `V2_CURRENT_STATUS.md`
3. use `V2_OPERATIONS_RUNBOOK.md` before touching the live scheduler
