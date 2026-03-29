# Chat Memory Summary (AI Collectibles Intelligence Agent)

## Project Scope (Current)

- Project path: `F:\AI Agent`
- Product direction: decision-intelligence for collectibles, not transaction execution
- V1 remains the stable reference implementation
- V2 is now the active development track and should be treated as the forward path

## V1 Status (Keep In Mind, But Not Main Focus)

- V1 is Zhaoonline-only and CLI-first
- V1 user domain is the older flat model:
  - `users`
  - `user_items`
  - `user_preferences`
- V1 still matters as a reference for business intent and older orchestration ideas
- V2 should not be implemented as an in-place rewrite of V1 logic

## Zhaoonline V2 Integration Facts

- Base URL in practice: `http://zhaoonline.hk:8888`
- Legacy direct IP also worked during testing: `http://8.218.2.12:8888`
- Auth per request:
  - `X-Auth-Timestamp` = current ms timestamp
  - `X-Auth-Token` = `MD5(secret + timestamp)`
- Important V2 endpoints:
  - baseline: `GET /api/search/auctions`
  - incremental: `GET /api/search/auctions/incremental`
- Current live operations use the incremental endpoint, not historical backfill

## Important Zhaoonline V2 Behavior

- Baseline endpoint is for current active inventory, not full history
- Incremental endpoint is window-based and should be processed as:
  - `(fromTime, toTime]`
- Incremental rows can include same-status updates, not only lifecycle transitions
- Current live ingestion deliberately keeps only meaningful status changes:
  - `oldStatus != newStatus`
- Known status meaning from observed behavior:
  - `1` preview
  - `2` live
  - `3` ended/sold
- Raw statuses `6`, `10`, and `11` were observed in live data and remain unresolved
  - this needs technician clarification before final status mapping or signals

## Critical V2 Architecture Reality

- V2 is not yet a full automated product pipeline
- What is stable enough today:
  - V2 API/auth client
  - live incremental polling
  - V2 schema migrations
  - profile model
  - parser
  - matcher
  - audit-style reporting
- What is still missing as a clean automated chain:
  - normalization refresh after live sync
  - parsing refresh after live sync
  - matching refresh after live sync
  - signals
  - end-user delivery on top of V2

## V2 Source Vs Local DB State

- The local `data/agent_v2.db` may already contain:
  - normalized listings
  - normalized media
  - normalized events
  - parsed listing rows
  - active matches
- Do not assume those layers are refreshed automatically by the live scheduler
- Current scheduled behavior is narrower:
  - fetch completed incremental windows
  - keep meaningful raw changes
  - write sync telemetry
  - advance the live watermark

## V2 Profile Model (Important)

- One user can have many unrelated interests with different precision and signal needs
- V2 should not assume one consistent user-wide preference model
- Operational profile tables are now:
  - `user_profile_defaults_v2`
  - `user_interests_v2`
  - `user_interest_targets_v2`
  - `user_holdings_v2`
  - `user_interest_signal_policies_v2`
- Holdings must stay separate from wants/interests

## V2 Matching Model (Important)

- Matcher now prefers V2 interest targets first
- Legacy `user_items` are fallback only
- Current relationship types:
  - `exact_identity`
  - `variant_related`
  - `series_related`
- Domain matching rules learned in discussion:
  - treat title as `name + modifiers`
  - modifiers are mostly condition/presentation evidence
  - `character_name_raw` also carries condition evidence
  - relatedness should not be based on text similarity alone
  - relatedness should come from collectible meaning, issue/series structure, or collect-together logic
- Stamp-specific normalization rule:
  - `J` and the Chinese `ji` prefix should be treated as equivalent codes
  - `T` and the Chinese `te` prefix should be treated as equivalent codes
- Current broad-noise problem is mostly multiplicity of real market listings, not parser confusion
- Next matching/signal improvement should focus on grouped opportunities and dedupe, not endless strictness tweaks

## Demo User / Review Setup

- Curated demo user id:
  - `demo_u_v2_curated`
- It was seeded from real ended (`status=3`) listing examples chosen from commonly seen items
- The demo profile intentionally mixes:
  - exact buy watch
  - broad discovery
  - balanced family collecting
  - strict condition-sensitive watch
  - holding/sell monitor
- This is the main evaluation profile for current V2 matching work

## Scheduler / Operations Facts

- Current Windows task name:
  - `AI Agent V2 Incremental Sync`
- Task is installed on the local Windows machine
- It now runs with hidden window style to avoid popping a visible terminal
- Trigger frequency:
  - every 30 minutes
- Data window size:
  - 1 completed hour per incremental window
- Catch-up behavior:
  - one run can now process multiple backlog windows
  - current safe cap defaults to `4` windows per run
  - each completed window commits its watermark immediately
- This means offline gaps are caught up faster than before

## Live State Keys And Scheduling Rule

- Historical/backfill state key:
  - `source_platform='zhaoonline'`
- Live scheduled forward-sync state key:
  - `source_platform='zhaoonline_live'`
- These must stay separate
- From now on, ignore historical backfill as an active development priority
- The live scheduler should keep using `zhaoonline_live` only

## Local Runtime Paths That Matter

- V2 DB:
  - `data/agent_v2.db`
- Preferred local secret file:
  - `data/secrets/zhaoonline_secret.txt`
- Live scheduler log:
  - `data/logs/zhao_v2_incremental_live.log`
- Live lock file:
  - `data/locks/zhaoonline_v2_incremental_live.lock`
- Live rate-limit state:
  - `data/zhaoonline_v2_rate_limit_live.json`

## Rate Limiting / API Safety

- Early live testing showed the upstream API can return `429` quickly
- Safe request spacing that worked in practice:
  - about `60` seconds between requests
- The live runner includes pacing and retry behavior
- Catch-up should remain capped rather than unlimited

## Documentation State

- Technical docs were refreshed to make the repo understandable for new developers
- Main docs to read first:
  - `README.md`
  - `md/README.md`
  - `md/v2/README.md`
  - `md/v2/V2_DEVELOPER_QUICKSTART.md`
  - `md/v2/V2_CURRENT_STATUS.md`
  - `md/v2/V2_ARCHITECTURE.md`
  - `md/v2/V2_DATA_MODEL.md`
  - `md/v2/V2_RUNTIME_WORKFLOW.md`
  - `md/v2/V2_OPERATIONS_RUNBOOK.md`
  - `md/v2/V2_MATCHING_STATUS.md`
  - `md/v2/V2_USER_PROFILE_MODEL.md`

## Validation / Current Local State

- Focused V2 tests were added around:
  - live incremental sync
  - profile migration
  - demo user seeding
  - V2 interest matching
  - matching strictness
- The live scheduler was observed to run successfully with:
  - `LastTaskResult = 0`
- Current branch at last update:
  - `codex/v2-docs-handoff`
- That branch was pushed to GitHub as a safe branch because local `main` had diverged from `origin/main`

## Most Important Next Development Themes

1. integrate downstream refresh after live incremental sync
2. build signals on top of `user_interests_v2`
3. group duplicate opportunities to reduce match multiplicity
4. resolve unknown raw statuses `6`, `10`, `11` with Zhaoonline technician
5. keep live ops stable and avoid reintroducing backfill complexity into the scheduler
