# V2 Test User Matching Report

## Live Data Status

- Live watermark window end: `2026-03-29T04:00:00+00:00` UTC
- Live watermark window start: `2026-03-29T03:00:00+00:00` UTC
- Successful live runs in last 24h: `25`
- Incremental API rows seen in last 24h: `22159`
- Meaningful incremental rows kept in last 24h: `5413`
- Last 24h coverage: `2026-03-28T03:00:00+00:00` -> `2026-03-29T04:00:00+00:00` UTC

## Table Snapshot

- Baseline raw snapshots: `13596`
- Incremental raw snapshots: `12753`
- Raw change events: `12753`
- market_listings_norm_v2: `15274`
- market_listing_events_v2: `4870`
- listing_parse_v2: `15274`
- listing_matches_v2_active: `675`

## Important Limitation

- Scheduled live sync is working and current at the raw layer.
- Normalization, parse refresh, and matching refresh are still manual, not automatic.
- So this report reflects current matching on the existing normalized catalog, not a fully auto-refreshed end-to-end V2 pipeline.

## Test User Base

- `demo_u_20260307` | `Demo Collector` | active V2 interests `0`
- `demo_u_v2_curated` | `V2 Curated Demo Collector` | active V2 interests `5`
- `u_001` | `Unnamed user` | active V2 interests `0`

## Active Matches By User

- `demo_u_v2_curated`: `654` active matches
- `demo_u_20260307`: `16` active matches
- `u_001`: `5` active matches

## Relationship Mix By User

- `demo_u_20260307` | `exact_identity` | `16`
- `demo_u_v2_curated` | `exact_identity` | `491`
- `demo_u_v2_curated` | `series_related` | `162`
- `demo_u_v2_curated` | `variant_related` | `1`
- `u_001` | `exact_identity` | `5`

## Main Match Drivers

### `demo_u_20260307`
- `纪94（8-8）新` | `9`
- `纪94（8-1）新` | `6`
- `T67（7-6）带色标数字直角边12连新` | `1`
### `demo_u_v2_curated`
- `中国龙银币系列` | `391`
- `2026年中国龙31.104克普制银币` | `205`
- `T43西游记` | `26`
- `T69M红楼梦型张新` | `22`
- `T89M仕女图型张新` | `10`
### `u_001`
- `纪6（5-3）原版新` | `4`
- `T130泰山新28套（一版）` | `1`

## Latest Live Runs

- `2026-03-29T04:00:03+00:00` | `2026-03-29T03:00:00+00:00` -> `2026-03-29T04:00:00+00:00` | status `success` | pages `3` | seen `1171` | kept `279`
- `2026-03-29T03:00:02+00:00` | `2026-03-29T02:00:00+00:00` -> `2026-03-29T03:00:00+00:00` | status `success` | pages `3` | seen `1206` | kept `363`
- `2026-03-29T02:00:02+00:00` | `2026-03-29T01:00:00+00:00` -> `2026-03-29T02:00:00+00:00` | status `success` | pages `2` | seen `568` | kept `4`
- `2026-03-29T01:00:02+00:00` | `2026-03-29T00:00:00+00:00` -> `2026-03-29T01:00:00+00:00` | status `success` | pages `1` | seen `393` | kept `4`
- `2026-03-29T00:00:02+00:00` | `2026-03-28T23:00:00+00:00` -> `2026-03-29T00:00:00+00:00` | status `success` | pages `1` | seen `438` | kept `0`

## Readout

- The live scheduler is healthy and has collected a full day of raw incremental activity.
- The strongest testing signal still comes from `demo_u_v2_curated`, because it is the only user with the new V2 multi-interest profile model.
- Current match volume is still dominated by broad discovery and repeated common-item listings, especially the dragon-coin family.
- Before using this as a product-facing output, the next step is still grouped opportunities plus signal dedupe on top of the current matcher.