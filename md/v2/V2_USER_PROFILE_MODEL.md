# V2 User Profile Model

## Goal

Move from one flat `user_items` list to a multi-interest profile model where one user can have many unrelated and differently-scoped interests.

## Core Idea

- `users` stays as lightweight identity and locale
- `user_profile_defaults_v2` stores weak user-level defaults
- `user_interests_v2` is the operational unit for signals
- `user_interest_targets_v2` stores the specific collectible targets under each interest
- `user_holdings_v2` stores owned positions separately from wants
- `user_interest_signal_policies_v2` stores per-interest signal behavior

## Why

One user can simultaneously have:

- strict exact-item completion goals
- broad discovery interests
- price-watch interests
- sell-monitor interests

Those should not be forced into one global preference model.

## New Tables

### `user_profile_defaults_v2`

Weak defaults only:

- currency
- default precision mode
- delivery mode
- cooldown
- default match threshold

### `user_interests_v2`

One row per interest track:

- `interest_kind`: `collecting`, `watch_buy`, `watch_sell`, `discovery`, `portfolio_monitor`
- `scope_kind`: `exact_item`, `issue_part`, `issue_family`, `series`, `theme`, `category`, `keyword`
- `precision_mode`: `exact`, `balanced`, `broad`

### `user_interest_targets_v2`

Stores parsed target structure:

- `issue_code_norm`
- `issue_part_token`
- `series_key`
- `theme_name`
- `variant_tokens_json`
- `quantity_tokens_json`
- `condition_tokens_json`
- `budget_max`

### `user_holdings_v2`

Separate owned positions:

- structured collectible identity
- quantity
- cost basis total / unit

### `user_interest_signal_policies_v2`

Per-interest signaling rules:

- lifecycle triggers
- exact / variant / series match behavior
- cooldown
- delivery mode

## Migration From Current Tables

### Current watch row -> V2

Each active `user_items.item_type = 'watch'` row becomes:

1. one `user_interests_v2` row
2. one `user_interest_targets_v2` row
3. one `user_interest_signal_policies_v2` row

### Current holding row -> V2

Each active `user_items.item_type = 'holding'` row becomes:

1. one `user_holdings_v2` row

### Current preferences -> V2

`user_preferences` is migrated into:

- `user_profile_defaults_v2`
- and used to seed cooldown / series tolerance for migrated interest policies

## Current Migration Heuristics

### Scope

- explicit `(x-y)` stamp token -> `issue_part`
- issue code plus quantity/version detail -> `exact_item`
- issue code only -> `issue_family`
- otherwise parsed series/theme -> `series` or `theme`
- fallback -> `keyword`

### Precision

- explicit part token or variant/quantity tokens -> `exact`
- issue/theme/series only -> `balanced`
- otherwise -> `broad`

### Signal Defaults

- high-priority watch -> `immediate`
- otherwise -> `daily_digest`
- exact interests allow variant matches but not series matches by default
- broad interests allow series expansion

## What This Unlocks

This structure lets signals answer:

- which specific interest is this listing relevant to?
- should we signal exact only, or allow variants?
- should this be immediate or digest?
- is this a buy opportunity, discovery item, or holding monitor?
