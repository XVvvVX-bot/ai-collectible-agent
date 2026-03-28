# Zhaoonline Technician Questions (API/Data Clarification)

## 1. Enum Dictionary (Must-Have)

1. `status`: full value list and exact meaning for each value (including ended/cancelled/closed variants).
2. `auctionType`: full value list and exact meaning for each value.
3. `auctionCategoryId`: official mapping table (`id -> category name`).
4. `auctionCharacterId`: official mapping table (`id -> series/character name`).
5. `settlementStatus`: full value list and exact meaning for each value.
6. `isDelay`: value meaning and when/how it changes.

## 2. Time Field Semantics

1. Confirm whether `startAt`, `endAt`, `previewAt`, `delayTime` are always epoch milliseconds.
2. Confirm timezone used for these fields.
3. Clarify nullability rules: when each field can be null.
4. Clarify update timing: real-time vs delayed sync.

## 3. Price Field Semantics

1. Clarify `initialPrice` meaning.
2. Clarify `endPrice` meaning and when it is null/populated.
3. Confirm whether a separate "current bid/current price" field exists.
4. Confirm currency behavior: always CNY or multi-currency possible.

## 4. Identity and Lifecycle

1. Is `id` globally unique and immutable?
2. Is `auctionNo` unique per platform?
3. Which listing fields can change after publish?
4. How are cancelled/withdrawn/deleted listings represented in API?

## 5. Pagination and Ordering

1. What is the sorting key/order for `/api/search` results?
2. Is ordering stable across repeated calls?
3. Is there a max page limit or data access boundary?
4. Can historical pages be reordered due to upstream updates?

## 6. API Contract and Rate Limits

1. Official rate limit (hard limit, soft limit, burst behavior).
2. Recommended retry strategy for 4xx/5xx/timeouts.
3. Error code reference (status code + body code meanings).
4. Schema/versioning change process and notification channel.

## 7. Media and Description Fields

1. Should `picPath` be treated as primary image over `images[]`?
2. Difference between `descr` and `descrCharacter`.
3. Any guarantees on image count/quality/order in `images[]`.

## 8. Data Quality Guarantees

1. Which fields are guaranteed non-null?
2. Known edge cases to expect (missing title, missing times, invalid category IDs, etc.).
3. Whether historical records may be corrected/backfilled later.

## 9. Request for Deliverables

1. Sample API response for each major `status` and `auctionType`.
2. Official enum mapping file for categories/series (CSV or JSON preferred).
3. Contact/process for future enum additions or contract changes.

