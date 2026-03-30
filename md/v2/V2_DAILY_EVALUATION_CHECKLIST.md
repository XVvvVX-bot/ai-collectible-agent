# V2 Daily Evaluation Checklist

## Purpose

This checklist is for the next 3 to 7 days of V2 observation.

Use it to review the daily V2 outputs consistently:

- daily user-base review
- daily signal review
- daily interest digest

The goal is not to judge every single match.
The goal is to decide whether V2 is useful enough on the majority of important cases and to identify the highest-value tuning work.

## Daily Files To Review

Each day, check:

- latest `v2_daily_user_base_review_*.md`
- latest `v2_daily_signal_review_index_*.md`
- latest per-user `v2_signal_review_*.md`
- latest `v2_daily_interest_digest_index_*.md`
- latest per-user `v2_interest_digest_*.md`

If something looks off, also inspect:

- `data/logs/zhao_v2_incremental_live.log`
- `data/logs/v2_daily_user_base_review.log`
- `data/logs/v2_daily_signal_review.log`
- `data/logs/v2_daily_interest_digest.log`

## Daily Review Flow

### 1. Automation Health

Confirm:

- the live incremental task ran
- the daily review task ran
- the daily signal review task ran
- the daily interest digest task ran

Questions:

- did each expected report file appear today?
- did the logs show successful completion?
- did any task silently skip for a bad reason?

Expected healthy result:

- reports exist
- no obvious scheduler failure
- once-per-day guard behaves correctly

### 2. Data Freshness

Check in the daily review:

- active match count
- active signal count
- recently refreshed matched listings

Questions:

- do counts look broadly stable or plausibly changed?
- is the system stale for several days in a row?
- did live sync advance but reports still look frozen?

Expected healthy result:

- counts may fluctuate, but not in obviously impossible ways
- no unexplained long flatline if the market is active

### 3. Signal Quality

Review the per-user signal review.

Questions:

- are the high-priority signals actually important?
- are standing signals understandable?
- are event-driven signals rare but meaningful?
- is the wording honest for auction behavior?

Reject these patterns if you see them often:

- fake “cheap now” language based only on start price
- repeated signals that say the same thing with no new value
- broad discovery signals crowding out exact-watch signals

Expected healthy result:

- high-priority signals feel worth reading
- low-priority signals are still understandable
- sell-side signals are backed by ended comps

### 4. Digest Usefulness

Review the per-user interest digest.

Questions:

- does each interest summary explain why it matters?
- does the comp-trend line help decision-making?
- are the top active groups representative?
- are ended comparables useful and believable?

Expected healthy result:

- the digest reads like a short market brief
- not just a dump of rows

### 5. Matching Noise

Use the signal review and digest together.

Questions:

- is the main problem bad matching, or just repeated common listings?
- are exact interests mostly clean?
- are broad interests noisy in an intentional way or an unhelpful way?
- are stamp condition-sensitive interests respecting condition well enough?

Important principle:

- do not tighten matching further just because common items appear many times
- first ask whether the reporting layer is grouping them well enough

Expected healthy result:

- exact interests look mostly right
- broad discovery is broader, but still interpretable
- remaining noise is mostly multiplicity, not obvious false relationships

### 6. Buy-Side Logic

Questions:

- are buy-side signals describing availability and affordability, not fake bargain claims?
- does comp-based budget logic feel believable?
- when budget is exceeded, does the report explain that clearly?

Expected healthy result:

- buy-side language stays conservative
- no overclaiming without current bid data

### 7. Sell-Side Logic

Questions:

- do sell interests show useful ended comps?
- is cost-basis comparison informative?
- does market-depth context help?

Expected healthy result:

- sell-side signals feel more valuation-oriented than alert-spam oriented

### 8. Most Important Daily Notes

At the end of each day, record just 3 things:

1. best useful signal or digest section today
2. worst noise/problem today
3. one concrete tuning idea

Keep this short.
The goal is pattern recognition over multiple days.

## Scoring Rubric

Use this simple daily scorecard:

- `Automation health`: pass / fail
- `Freshness`: good / borderline / stale
- `Exact-interest quality`: good / mixed / poor
- `Broad-interest usefulness`: good / mixed / poor
- `Buy-side honesty`: good / mixed / poor
- `Sell-side usefulness`: good / mixed / poor
- `Overall today`: good / mixed / poor

## What To Ignore For Now

Do not overreact yet to:

- categories outside the trusted majority
- rare art / other parsing edge cases
- unknown raw statuses until technician feedback arrives
- isolated weird listings

This V2 phase is about whether the main pipeline is strong on the important majority.

## Decision After 3 To 7 Days

At the end of the observation period, decide:

1. Is matching quality already good enough for the main structured cohorts?
2. Is the main problem ranking/grouping rather than raw matching?
3. Are daily outputs useful enough to continue tuning signals instead of reworking architecture?
4. Which one area needs the next sprint most?

Recommended priority order if the system is mostly healthy:

1. report ranking and grouping
2. signal threshold tuning
3. matching cleanup only where clearly necessary
4. broader category expansion later
