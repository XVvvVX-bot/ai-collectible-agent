# Zhaoonline API Interface Notes

This is a practical integration note based on the official document `API接口文档.md`.

## Base Endpoint

- Base URL: `http://8.218.2.12:8888`
- Search path: `/api/search`

Example:

```text
http://8.218.2.12:8888/api/search?status=2&page=1&pageSize=10
```

## Authentication

Every `/api/*` request must include:

1. `X-Auth-Timestamp` (milliseconds timestamp as string)
2. `X-Auth-Token` (`MD5(secret + X-Auth-Timestamp)`)

Rules:
- UTF-8 encoding for hash input string
- expected time drift around +/- 5 minutes

## Query Parameters

- `status` (required)
  - `1`: preview
  - `2`: live bidding
- `page` (optional, default `1`)
- `pageSize` (optional, default `50`, max `50`)

## Response

JSON page object:
- `total`
- `pageNum`
- `pageSize`
- `pages`
- `list` (auction items)

Common item fields used in V1:
- `id`
- `auctionNo`
- `name`
- `status`
- `startAt`
- `endAt`
- `previewAt`
- `initialPrice`
- `endPrice`
- `picPath`

## Error Handling

- `401`: auth/token/timestamp problem
- `429`: rate limit
- `500`: upstream/internal service error

## Operational Limits

As communicated by the Zhaoonline technician:
- keep calls under about `30` per hour

Recommended V1 policy:
- target <= `20` calls/hour baseline
- reserve retry budget for transient failures

