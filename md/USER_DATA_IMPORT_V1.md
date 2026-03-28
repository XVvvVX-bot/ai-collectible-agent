# USER_DATA_IMPORT_V1

Step 5 adds CSV/Excel intake for `user_items` on top of `UserDomainService`.

Implementation:

- `src/ai_agent/importers/user_data_import.py`
- `scripts/importers/import_user_items.py`

## Modes

- `preview` (default): parse and validate input; no DB writes.
- `commit` (`--commit`): apply inserts/updates through deterministic upsert.

## Structured Result

Each run returns:

- `inserted`
- `updated`
- `skipped`
- `errors` (row-level parse/validation issues)

## Alias Mapping

Supported header aliases include:

- `item_type`: `item_type`, `type`, `holding_or_watch`, `list_type`
- `item_name`: `item_name`, `name`, `title`
- `quantity`: `quantity`, `qty`
- `cost_basis_total`: `cost_basis_total`, `cost`, `total_cost`
- `max_buy_price`: `max_buy_price`, `budget`
- plus direct canonical fields (`category`, `series`, `year`, `grade_condition`, `priority`, `notes`, `is_active`)

## Strict Parsing Rules

- `item_type` must resolve to `holding` or `watch`.
- `item_name` is required.
- `year` must be integer when provided.
- `quantity`, `cost_basis_total`, `max_buy_price` must be numeric when provided.
- `is_active` must be a valid boolean token (`1/0/true/false/yes/no`).
- `priority` must be `high|normal|low` when provided.
- `watch` rows cannot include `quantity`.
- `holding` rows cannot include `priority`.
- Duplicate natural keys inside one file are reported as `duplicate_in_file`.

## Example

Preview:

```powershell
python .\scripts\importers\import_user_items.py --db-path data/agent.db --user-id u_001 --file-path data/user_items.csv
```

Commit:

```powershell
python .\scripts\importers\import_user_items.py --db-path data/agent.db --user-id u_001 --file-path data/user_items.csv --commit
```
