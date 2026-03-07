# V1 Draft Data Dictionary

This document defines the first-pass fields for the AI Collectibles Intelligence Agent V1.

## 1) User Profile

| Field | Meaning | Type | Required | Example | Source |
|---|---|---|---|---|---|
| user_id | Unique user identifier | text | Yes | `u_001` | System |
| display_name | User nickname | text | No | `Alex` | Chat |
| language | Report language | text (enum) | Yes | `zh-CN` | System/Chat |
| timezone | User timezone | text | Yes | `Asia/Shanghai` | System/Chat |
| created_at | Profile created time | datetime | Yes | `2026-03-07 09:00` | System |
| updated_at | Last updated time | datetime | Yes | `2026-03-07 12:30` | System |

## 2) User Preferences (Persistent, Chat-Editable)

| Field | Meaning | Type | Required | Example | Source |
|---|---|---|---|---|---|
| preference_id | Unique preference record | text | Yes | `pref_001` | System |
| user_id | Owner user | text | Yes | `u_001` | System |
| interest_category | Interested category | text | No | `stamp` | Chat/CSV |
| interest_series | Interested series/set | text | No | `PRC J-series` | Chat/CSV |
| interest_keywords | Search keywords | text array | No | `["梅兰芳","纪念邮票"]` | Chat/CSV |
| buy_rule_text | Buy preference in plain language | text | No | `低于近30天均价就提醒` | Chat |
| sell_rule_text | Sell preference in plain language | text | No | `价格明显高位时提醒` | Chat |
| high_interest_flag | Whether this is high-interest | boolean | Yes | `true` | Chat |
| updated_at | Last updated time | datetime | Yes | `2026-03-07 12:30` | System |

## 3) Holdings (User Currently Owns)

| Field | Meaning | Type | Required | Example | Source |
|---|---|---|---|---|---|
| holding_id | Unique holding row | text | Yes | `h_001` | System |
| user_id | Owner user | text | Yes | `u_001` | System |
| category | Item category | text | Yes | `stamp` | Chat/CSV |
| series | Series/set | text | No | `T46` | Chat/CSV |
| item_name | Item name | text | Yes | `庚申年猴票` | Chat/CSV |
| year | Issue year | integer | No | `1980` | Chat/CSV |
| grade_condition | Condition/grade | text | No | `VF` | Chat/CSV |
| quantity | Quantity held | number | Yes | `2` | Chat/CSV |
| cost_basis_total | Total cost (optional) | number | No | `3200` | Chat/CSV |
| notes | Extra notes | text | No | `带证书` | Chat/CSV |
| updated_at | Last updated time | datetime | Yes | `2026-03-07 12:30` | System |

## 4) Watchlist (User Interested But May Not Own)

| Field | Meaning | Type | Required | Example | Source |
|---|---|---|---|---|---|
| watch_id | Unique watch row | text | Yes | `w_001` | System |
| user_id | Owner user | text | Yes | `u_001` | System |
| category | Category | text | Yes | `coin` | Chat/CSV |
| series | Series/set | text | No | `Panda` | Chat/CSV |
| item_name | Target item name | text | Yes | `1983 Panda 1oz` | Chat/CSV |
| year | Target year | integer | No | `1983` | Chat/CSV |
| grade_target | Preferred grade | text | No | `MS65+` | Chat/CSV |
| priority | Interest level | text (enum) | Yes | `high/normal/low` | Chat |
| max_buy_price | Optional budget ceiling | number | No | `12000` | Chat/CSV |
| updated_at | Last updated time | datetime | Yes | `2026-03-07 12:30` | System |

## 5) Zhaoonline Listings/Auctions

| Field | Meaning | Type | Required | Example | Source |
|---|---|---|---|---|---|
| listing_id | Platform listing ID | text | Yes | `zl_88991` | API |
| source_platform | Data source | text | Yes | `zhaoonline` | System |
| title | Listing title | text | Yes | `T46 庚申年猴票` | API |
| category | Category | text | No | `stamp` | API/mapped |
| series | Series | text | No | `T46` | API/mapped |
| item_name_norm | Normalized item name | text | No | `庚申年猴票` | System |
| current_price | Current/latest price | number | No | `1800` | API |
| currency | Currency | text | Yes | `CNY` | API |
| auction_status | Status | text (enum) | Yes | `upcoming/live/ended` | API |
| start_time | Auction/listing start | datetime | No | `2026-03-06 10:00` | API |
| end_time | Auction/listing end | datetime | No | `2026-03-08 21:00` | API |
| listing_url | Direct link | text | Yes | `https://...` | API |
| snapshot_time | Ingestion timestamp | datetime | Yes | `2026-03-07 08:00` | System |

## 6) Market Metrics (30-Day Based for V1)

| Field | Meaning | Type | Required | Example | Source |
|---|---|---|---|---|---|
| metric_id | Unique metric row | text | Yes | `m_001` | System |
| item_key | Standard item key | text | Yes | `stamp:T46:庚申年猴票` | System |
| window_days | Analysis window | integer | Yes | `30` | System |
| sample_count | Number of observations | integer | Yes | `12` | System |
| price_avg | 30-day average price | number | No | `1750` | System |
| price_median | 30-day median price | number | No | `1700` | System |
| price_min | 30-day minimum | number | No | `1400` | System |
| price_max | 30-day maximum | number | No | `2100` | System |
| trend_direction | Simple trend | text (enum) | No | `up/down/flat` | System |
| computed_at | Computed time | datetime | Yes | `2026-03-07 08:05` | System |

## 7) Opportunities/Signals

| Field | Meaning | Type | Required | Example | Source |
|---|---|---|---|---|---|
| signal_id | Unique signal | text | Yes | `s_001` | System |
| user_id | Target user | text | Yes | `u_001` | System |
| listing_id | Related listing | text | Yes | `zl_88991` | System |
| signal_type | Signal type | text (enum) | Yes | `buy_opportunity/sell_opportunity/new_relevant_listing` | System |
| urgency | Alert urgency | text (enum) | Yes | `immediate/daily` | System |
| reason_code | Why flagged | text | Yes | `price_below_reference` | System |
| confidence_level | Confidence bucket | text (enum) | Yes | `high/medium/low` | System |
| recommendation_text | Human-readable recommendation | text | No | `可关注买入机会` | System |
| created_at | Signal time | datetime | Yes | `2026-03-07 08:10` | System |

## 8) Reports & Alert Log

| Field | Meaning | Type | Required | Example | Source |
|---|---|---|---|---|---|
| report_id | Unique report | text | Yes | `r_20260307` | System |
| user_id | Owner user | text | Yes | `u_001` | System |
| report_date | Report date | date | Yes | `2026-03-07` | System |
| report_type | Type | text (enum) | Yes | `daily/immediate` | System |
| content_summary | Short summary text | text | No | `今日发现3条买入机会` | System |
| content_payload | Full structured report JSON/text | text/json | Yes | `{...}` | System |
| delivery_channel | Where sent | text | Yes | `app_console` | System |
| delivery_status | Delivery status | text (enum) | Yes | `sent/failed/pending` | System |
| sent_at | Sent time | datetime | No | `2026-03-07 08:30` | System |
