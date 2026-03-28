# V2 Matching Status

## Goal

The V2 matcher is meant to match real market listings against structured interest targets, not just free-text watch items.

It is not yet the signal layer. It is the structured relevance layer that future signals will consume.

Current implementation:

- matcher source: `src/ai_agent_v2/matching/v2_matcher.py`
- runner: `scripts_v2/matching/run_zhaoonline_v2_matching.py`
- audit report: `src/ai_agent_v2/reporting/match_audit.py`

## Current Match Subject Priority

The matcher currently loads subjects in this order:

1. `user_interest_targets_v2`
2. `user_items` only if the user has no active V2 targets

This is important:
- V2 profile model is now the primary matching input
- legacy `user_items` remain as fallback only

## Relationship Types

The matcher emits:

- `exact_identity`
- `variant_related`
- `series_related`

## Current Matching Model

### Stamp-Like

Main signals:
- normalized issue code
- normalized issue name
- series key
- issue part token
- variant tokens
- condition tokens

Important current protections:
- `J`/`纪` and `T`/`特` normalization
- part-specific targets only match the same part
- exact stamp targets require name agreement
- hard variant tokens like `型张`, `M`, `一版`, `带厂铭` refine strict targets

### Coin-Like

Main signals:
- year
- theme
- asset type
- series key
- finish
- weight
- denomination
- variant/quantity tokens

Important current protections:
- exact coin targets now reject packaging/lot variants when the target is strict
- broad series discovery can still accept family-level relatedness

## V2 Profile Controls That Now Affect Matching

The matcher now respects:

- `strictness_override`
- `precision_mode`
- `allow_variant_matches`
- `allow_series_matches`

Practical effect:
- exact watches no longer automatically inherit broad relatedness
- broad discovery interests can still stay broad

## Current Demo User Interpretation

The curated demo user intentionally mixes:
- exact buy watch
- broad discovery
- balanced family collecting
- strict condition-sensitive watch
- holding/sell monitor

That means a large match volume is not automatically bad.

The important question is whether the broad volume comes from the broad targets only.

## Current Known Behavior

### Healthy

- V2 targets are matched directly
- exact-watch noise is much lower than before
- broad discovery interests remain broad by design
- audit reports can now resolve labels from both legacy and V2 target ids

### Still Imperfect

- repeated market listings of very common items can create many exact matches
- broad series discovery can dominate total match count
- current matching is still listing-level, not grouped opportunity-level

Important interpretation:

- repeated exact matches are often caused by many real listings in the market
- they are not automatically parser bugs
- and they are not automatically scoring bugs

That means a common item like `2026年中国龙31.104克普制银币` can create many exact matches because many separate listings of that same product are active at once.

## Current Biggest Remaining Matching Gap

The main remaining noise is not parser confusion anymore.

It is result multiplicity:
- many listings for the same common item
- many listings for the same broad family

The next best improvement is likely not stricter matching rules.
It is:
- grouped results
- signal dedupe
- opportunity clustering

## Recommended Next Matching Milestones

1. group exact duplicate opportunities by normalized identity
2. group broad series opportunities into summary clusters
3. add signal-layer dedupe / cooldown on top of grouped matches
4. only then tune more parser strictness if needed

## Developer Review Path

Run:

```powershell
.\.venv\Scripts\python.exe .\scripts_v2\matching\run_zhaoonline_v2_matching.py --db-path data/agent_v2.db --user-id demo_u_v2_curated
```

Then inspect:

```powershell
.\.venv\Scripts\python.exe .\scripts_v2\reporting\run_zhaoonline_v2_match_audit.py --db-path data/agent_v2.db
```

Use the audit report to answer:
- are exact targets still too broad?
- is broad discovery behaving as intended?
- is a noisy result caused by parser error or by many real listings?
