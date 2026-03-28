# V2 Today Review (2026-03-27)

## Data Snapshot
- Normalized listings: 15274
- Normalized media rows: 35159
- Normalized lifecycle events: 4870
- Listing status `live`: 7183
- Listing status `preview`: 6460
- Listing status `ended`: 1394
- Listing status `unknown`: 237

## Demo Profile
- Curated demo user: `demo_u_v2_curated`
- Interests: 5
- Targets: 5
- Holdings: 1
- `中国龙普制银币抢拍`: watch_buy / exact_item / exact
- `中国龙银币系列捡漏`: discovery / series / broad
- `仕女图型张只收全品`: watch_buy / exact_item / exact
- `红楼梦型张持仓卖点`: watch_sell / exact_item / exact
- `西游记套票补全`: collecting / issue_family / balanced

## Matching Readiness
- Today's match run for `demo_u_v2_curated` returned 0 pairs.
- Legacy `user_items` rows for the demo user: 0
- Current blocker: the V2 matcher still reads legacy `user_items`, while the cleaned demo profile now lives in `user_interests_v2` and `user_interest_targets_v2`.
- Existing active matches still belong to legacy-profile users:
  - `demo_u_20260307`: 16
  - `u_001`: 7

## Data Quality Notes
- Transition `0->1`: 1611
- Transition `1->2`: 1544
- Transition `2->3`: 1394
- Transition `2->6`: 113
- Transition `2->11`: 75
- Unknown raw status `6`: 113
- Unknown raw status `11`: 77
- Unknown raw status `10`: 47

## Recommendation
- Before the week-long matching test, wire the matcher to `user_interests_v2`/`user_interest_targets_v2` or create a deliberate bridge from the new profile layer into legacy `user_items`.
