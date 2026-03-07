# Contributing

## Branching

- Use short-lived branches from `main`.
- Naming:
  - `feature/<topic>`
  - `fix/<topic>`
  - `docs/<topic>`

## Pull Requests

Each PR should include:

1. what changed
2. why it changed
3. how it was tested
4. known limitations

## Commit Messages

Use concise, imperative commits.

Examples:
- `add zhaoonline client module`
- `create initial sqlite migration`
- `refine report signal schema`

## Code Standards

- Python 3.11+.
- Keep functions focused and testable.
- Prefer explicit typing in core logic.
- No secrets in code or docs.

## Data and Security

- `.env` is local-only.
- `.env.example` documents required variables.
- Keep API keys out of screenshots whenever possible.

## Docs Sync Rule

If schema or workflow changes, update:

1. `migrations/` SQL
2. `md/DATABASE_SCHEMA_V1.md`
3. `md/DATA_DICTIONARY_V1_DRAFT.md` (if field definitions changed)

