# RULE_SIGNALS_V1

Step 7 implements deterministic rule-based signal generation.

Implementation:

- `src/ai_agent/signals/rule_engine.py`
- `scripts/signals/run_rule_signals.py`
- `migrations/008_signal_dedupe_indexes.sql`

## Generated Signal Types

- `new_relevant_listing`
- `buy_opportunity`
- `sell_opportunity`
- `price_movement`

## Rule Summary

- `new_relevant_listing`:
  - active listing match and listing recency within `freshness_hours`
- `buy_opportunity`:
  - watch item with `price_current <= max_buy_price`
  - fallback: `price_current <= 95% of price_initial`
- `sell_opportunity`:
  - holding item with `price_current >= 120% of unit cost basis`
- `price_movement`:
  - absolute change from `price_initial` to current/end price >= threshold pct

## Urgency Routing

- Default urgency: `daily`
- Immediate escalation:
  - user `high_interest_flag=1` for buy/sell opportunities
  - or high-interest keyword hit in listing title for relevant-listing alerts

## Dedupe / Cooldown

- Per-run dedupe key:
  - `(user_id, listing_id, signal_type, reason_code)`
- Cross-run cooldown check:
  - skip if same key exists with `created_at >= now - cooldown_hours`

## Example

```powershell
python .\scripts\signals\run_rule_signals.py --db-path data/agent.db --user-id u_001 --cooldown-hours 24 --freshness-hours 24 --price-move-threshold-pct 10
```
