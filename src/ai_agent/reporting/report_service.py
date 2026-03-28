from __future__ import annotations

import json
import os
import sqlite3
import uuid
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib import error, request

from ai_agent.clients.zhaoonline import now_utc_iso
from ai_agent.storage.sqlite_raw_store import SqliteRawStore

HUMAN_REPORT_PROMPT_TEMPLATE = """你是资深收藏品市场分析师。请将下面“结构化报告草稿”改写为“中文、人类可读、可执行”的日报。

【硬性要求】
1) 必须使用中文输出。
2) 保留事实与数字，不得篡改数量、价格、时间、覆盖率等。
3) 拍品引用必须“名称优先”，不得用 listing ID 作为主语。
4) ID 只能放在末尾“参考”或“附注”中。
5) 必须包含并显式展示关键字段（如果缺失则写“暂无”）：
   - 品相/评级
   - 图片链接
   - 拍卖/预展链接
   - 时间信息（preview/start/end）
   - 价格信息（初始/当前/结束）
6) 对异常数据（如极端低价）必须给出“人工复核”提示。
7) 输出结构固定为以下一级标题（保持顺序）：
   - 今日总览
   - 优先处理事项（Top Action）
   - 买入机会
   - 卖出机会
   - 新增相关标的
   - 风险与说明
   - 关注清单覆盖
8) 每个“买入/卖出机会”条目使用紧凑卡片式要点：
   - 名称
   - 价格（初始/当前/结束）
   - 属性（品类/系列/品相评级/拍次/拍卖类型）
   - 时间（preview/start/end）
   - 信号（触发原因/紧急度/置信度）
   - 链接（拍卖链接/图片链接）
9) 不要输出代码块，不要输出 JSON。
10) 结尾必须给出“明日建议动作”（1-3 条）。

【风格要求】
- 专业、简洁、可执行，避免空话。
- 先结论后细节。
- 对同名拍品可合并叙述，但不能丢失关键价格差异。

下面是结构化报告草稿：
"""


@dataclass(frozen=True)
class ReportGenerationResult:
    users_processed: int
    generated_reports: int
    linked_signals: int
    report_type: str
    report_date: str
    exported_markdown_files: int = 0
    exported_humanized_files: int = 0


def run_report_generation(
    db_path: str,
    *,
    user_id: str | None = None,
    report_date: str | None = None,
    report_type: str = "daily",
    export_markdown: bool = False,
    reports_dir: str = "reports",
    max_items_per_section: int = 50,
    llm_humanize: bool = False,
    llm_model: str = "gpt-4.1-mini",
    openai_api_key: str | None = None,
) -> ReportGenerationResult:
    report_type_norm = report_type.strip().lower()
    if report_type_norm not in {"daily", "immediate"}:
        raise ValueError("report_type must be 'daily' or 'immediate'.")

    report_date_value = _resolve_report_date(report_date)
    window_start, window_end = _build_window(report_date_value, report_type_norm)

    store = SqliteRawStore(db_path)
    store.ensure_schema()
    db_file = Path(db_path)

    with sqlite3.connect(db_file) as conn:
        conn.row_factory = sqlite3.Row
        users = _load_users(conn, user_id=user_id)
        generated_reports = 0
        linked_signals = 0
        exported_markdown_files = 0
        exported_humanized_files = 0
        now_iso = now_utc_iso()
        output_dir = Path(reports_dir)
        if export_markdown:
            output_dir.mkdir(parents=True, exist_ok=True)

        for user in users:
            uid = str(user["id"])
            sections = _build_report_sections(
                conn,
                user_id=uid,
                window_start=window_start,
                window_end=window_end,
                now_iso=now_iso,
            )
            payload = {
                "meta": {
                    "user_id": uid,
                    "report_type": report_type_norm,
                    "report_date": report_date_value.isoformat(),
                    "window_start": window_start.isoformat(),
                    "window_end": window_end.isoformat(),
                    "generated_at": now_iso,
                },
                "sections": sections["sections"],
            }
            summary = _build_summary(sections["counts"])
            report_id = _upsert_report(
                conn,
                user_id=uid,
                report_date=report_date_value.isoformat(),
                report_type=report_type_norm,
                content_summary=summary,
                content_payload_json=json.dumps(payload, ensure_ascii=False),
                now_iso=now_iso,
            )
            linked_signals += _replace_report_signal_links(
                conn,
                report_id=report_id,
                signal_ids=sections["signal_ids"],
                now_iso=now_iso,
            )
            if export_markdown:
                md_text = _render_markdown_report(
                    report_id=report_id,
                    payload=payload,
                    content_summary=summary,
                    max_items_per_section=max_items_per_section,
                )
                file_path = output_dir / _report_filename(
                    user_id=uid,
                    report_date=report_date_value.isoformat(),
                    report_type=report_type_norm,
                )
                file_path.write_text(md_text, encoding="utf-8")
                exported_markdown_files += 1
                if llm_humanize:
                    human_text = _render_human_friendly_markdown(
                        draft_markdown=md_text,
                        model=llm_model,
                        api_key=openai_api_key or os.getenv("OPENAI_API_KEY"),
                    )
                    human_path = output_dir / _human_report_filename(
                        user_id=uid,
                        report_date=report_date_value.isoformat(),
                        report_type=report_type_norm,
                    )
                    human_path.write_text(human_text, encoding="utf-8")
                    exported_humanized_files += 1
            generated_reports += 1

        conn.commit()

    return ReportGenerationResult(
        users_processed=len(users),
        generated_reports=generated_reports,
        linked_signals=linked_signals,
        report_type=report_type_norm,
        report_date=report_date_value.isoformat(),
        exported_markdown_files=exported_markdown_files,
        exported_humanized_files=exported_humanized_files,
    )


def _report_filename(*, user_id: str, report_date: str, report_type: str) -> str:
    safe_user = "".join(ch if ch.isalnum() or ch in {"_", "-"} else "_" for ch in user_id)
    return f"report_{safe_user}_{report_date}_{report_type}.md"


def _human_report_filename(*, user_id: str, report_date: str, report_type: str) -> str:
    safe_user = "".join(ch if ch.isalnum() or ch in {"_", "-"} else "_" for ch in user_id)
    return f"report_{safe_user}_{report_date}_{report_type}_human.md"


def _render_markdown_report(
    *,
    report_id: str,
    payload: dict[str, Any],
    content_summary: str,
    max_items_per_section: int,
) -> str:
    meta = payload["meta"]
    sections = payload["sections"]
    lines: list[str] = []
    lines.append(f"# Report - {meta['user_id']} - {meta['report_date']} ({meta['report_type']})")
    lines.append("")
    lines.append(f"- report_id: `{report_id}`")
    lines.append(f"- generated_at: `{meta['generated_at']}`")
    lines.append(f"- window_start: `{meta['window_start']}`")
    lines.append(f"- window_end: `{meta['window_end']}`")
    lines.append(f"- summary: `{content_summary}`")
    lines.append("")

    lines.extend(
        _render_signal_section(
            "1) New Relevant Auctions/Listings",
            sections["new_relevant_auctions_listings"],
            max_items=max_items_per_section,
        )
    )
    lines.extend(
        _render_signal_section(
            "2) Buy Opportunities",
            sections["buy_opportunities"],
            max_items=max_items_per_section,
        )
    )
    lines.extend(
        _render_signal_section(
            "3) Sell Opportunities",
            sections["sell_opportunities"],
            max_items=max_items_per_section,
        )
    )

    pm = sections["price_movement_summary"]
    lines.append("## 4) Price Movement Summary")
    lines.append(
        f"- total: {pm['stats']['total']} | up_moves: {pm['stats']['up_moves']} | down_moves: {pm['stats']['down_moves']}"
    )
    lines.append("")
    lines.extend(_render_signal_items(pm["items"], max_items=max_items_per_section))

    missed = sections["missed_expired_opportunities"]
    lines.append("## 5) Missed/Expired Opportunities")
    lines.append(f"- total: {len(missed)}")
    for item in missed[:max_items_per_section]:
        lines.append(
            f"- {item['source_listing_id']} | {item['title']} | status={item['status_norm']} | "
            f"end_at={item['end_at']} | price={item['price_current'] or item['price_end']}"
        )
    if len(missed) > max_items_per_section:
        lines.append(f"- ... truncated {len(missed) - max_items_per_section} more")
    lines.append("")

    coverage = sections["watchlist_coverage"]
    lines.append("## 6) Watchlist Coverage")
    lines.append(
        f"- matched: {coverage['watch_items_matched']}/{coverage['watch_items_total']} ({coverage['coverage_pct']}%)"
    )
    if coverage["uncovered_items"]:
        lines.append("- uncovered_items:")
        for item in coverage["uncovered_items"][:max_items_per_section]:
            lines.append(f"  - {item['item_name']} ({item['user_item_id']})")

    lines.append("")
    return "\n".join(lines).strip() + "\n"


def _render_signal_section(title: str, rows: list[dict[str, Any]], *, max_items: int) -> list[str]:
    lines = [f"## {title}", f"- total: {len(rows)}", ""]
    lines.extend(_render_signal_items(rows, max_items=max_items))
    return lines


def _render_signal_items(rows: list[dict[str, Any]], *, max_items: int) -> list[str]:
    lines: list[str] = []
    for row in rows[:max_items]:
        listing = row["listing"]
        price = listing["price_current"] if listing["price_current"] is not None else listing["price_end"]
        item_name = listing["title"] or "未命名拍品"
        lines.append(f"- [{row['signal_type']}] {item_name}")
        lines.append(
            f"  - 价格: 当前={price} | 初始={listing['price_initial']} | 结束={listing['price_end']}"
        )
        lines.append(
            f"  - 属性: 品类={listing['category_norm'] or '-'} | 系列={listing['series_norm'] or '-'} | "
            f"品相/评级={listing['grade'] or '-'} | 拍卖类型={listing['auction_type'] or '-'} | "
            f"拍次={listing['auction_no'] or '-'}"
        )
        lines.append(
            f"  - 时间: preview={listing['preview_at'] or '-'} | start={listing['start_at'] or '-'} | end={listing['end_at'] or '-'}"
        )
        lines.append(
            f"  - 信号: 紧急度={row['urgency']} | 置信度={row['confidence_level']} | 原因={row['reason_code']} | 触发时间={row['created_at']}"
        )
        lines.append(
            f"  - 链接: 列表={listing['source_url'] or '-'} | 图片={listing['image_url'] or '-'} | 参考ID={listing['source_listing_id']}"
        )
    if len(rows) > max_items:
        lines.append(f"- ... truncated {len(rows) - max_items} more")
    lines.append("")
    return lines


def _build_report_sections(
    conn: sqlite3.Connection,
    *,
    user_id: str,
    window_start: datetime,
    window_end: datetime,
    now_iso: str,
) -> dict[str, Any]:
    new_relevant = _load_signal_rows(conn, user_id, "new_relevant_listing", window_start, window_end)
    buy_opportunities = _load_signal_rows(conn, user_id, "buy_opportunity", window_start, window_end)
    sell_opportunities = _load_signal_rows(conn, user_id, "sell_opportunity", window_start, window_end)
    price_movement_rows = _load_signal_rows(conn, user_id, "price_movement", window_start, window_end)
    missed_expired = _load_missed_expired(conn, user_id, window_end=window_end, now_iso=now_iso)
    watchlist_coverage = _load_watchlist_coverage(conn, user_id)

    price_movement_summary = {
        "items": price_movement_rows,
        "stats": {
            "total": len(price_movement_rows),
            "up_moves": sum(1 for x in price_movement_rows if str(x.get("reason_code")) == "price_move_up_large"),
            "down_moves": sum(
                1 for x in price_movement_rows if str(x.get("reason_code")) == "price_move_down_large"
            ),
        },
    }

    signal_ids = (
        [x["signal_id"] for x in new_relevant]
        + [x["signal_id"] for x in buy_opportunities]
        + [x["signal_id"] for x in sell_opportunities]
        + [x["signal_id"] for x in price_movement_rows]
    )
    unique_signal_ids = list(dict.fromkeys(signal_ids))

    sections = {
        "new_relevant_auctions_listings": new_relevant,
        "buy_opportunities": buy_opportunities,
        "sell_opportunities": sell_opportunities,
        "price_movement_summary": price_movement_summary,
        "missed_expired_opportunities": missed_expired,
        "watchlist_coverage": watchlist_coverage,
    }
    counts = {
        "new_relevant": len(new_relevant),
        "buy": len(buy_opportunities),
        "sell": len(sell_opportunities),
        "price_movement": len(price_movement_rows),
        "missed_expired": len(missed_expired),
        "watchlist_total": int(watchlist_coverage["watch_items_total"]),
        "watchlist_matched": int(watchlist_coverage["watch_items_matched"]),
    }
    return {"sections": sections, "counts": counts, "signal_ids": unique_signal_ids}


def _load_signal_rows(
    conn: sqlite3.Connection,
    user_id: str,
    signal_type: str,
    window_start: datetime,
    window_end: datetime,
) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT
          s.id AS signal_id,
          s.signal_type,
          s.urgency,
          s.reason_code,
          s.confidence_level,
          s.recommendation_text,
          s.created_at,
          n.id AS listing_id,
          n.source_listing_id,
          n.source_url,
          n.image_url,
          n.auction_no,
          n.auction_type_norm,
          n.auction_type_raw,
          n.title,
          n.category_norm,
          n.series_norm,
          n.grade_norm,
          n.grade_raw,
          n.price_current,
          n.price_initial,
          n.price_end,
          n.status_norm,
          n.start_at,
          n.preview_at,
          n.end_at
        FROM signals s
        JOIN market_listings_norm n ON n.id = s.listing_id
        WHERE s.user_id = ?
          AND s.status = 'active'
          AND s.signal_type = ?
          AND s.created_at >= ?
          AND s.created_at < ?
          AND EXISTS (
            SELECT 1
            FROM listing_matches lm
            WHERE lm.user_id = s.user_id
              AND lm.listing_id = s.listing_id
              AND lm.status = 'active'
          )
        ORDER BY s.created_at DESC, s.id DESC
        """,
        (
            user_id,
            signal_type,
            window_start.isoformat(),
            window_end.isoformat(),
        ),
    ).fetchall()
    return [
        {
            "signal_id": str(row["signal_id"]),
            "signal_type": str(row["signal_type"]),
            "urgency": str(row["urgency"]),
            "reason_code": str(row["reason_code"]),
            "confidence_level": str(row["confidence_level"] or ""),
            "recommendation_text": str(row["recommendation_text"] or ""),
            "created_at": str(row["created_at"]),
            "listing": {
                "listing_id": str(row["listing_id"]),
                "source_listing_id": str(row["source_listing_id"] or ""),
                "source_url": str(row["source_url"] or ""),
                "image_url": str(row["image_url"] or ""),
                "auction_no": str(row["auction_no"] or ""),
                "auction_type": str(row["auction_type_norm"] or row["auction_type_raw"] or ""),
                "title": str(row["title"] or ""),
                "category_norm": str(row["category_norm"] or ""),
                "series_norm": str(row["series_norm"] or ""),
                "grade": str(row["grade_norm"] or row["grade_raw"] or ""),
                "price_initial": _to_float(row["price_initial"]),
                "price_current": _to_float(row["price_current"]),
                "price_end": _to_float(row["price_end"]),
                "status_norm": str(row["status_norm"] or ""),
                "start_at": str(row["start_at"] or ""),
                "preview_at": str(row["preview_at"] or ""),
                "end_at": str(row["end_at"] or ""),
            },
        }
        for row in rows
    ]


def _load_missed_expired(
    conn: sqlite3.Connection,
    user_id: str,
    *,
    window_end: datetime,
    now_iso: str,
) -> list[dict[str, Any]]:
    cutoff_iso = (_parse_iso(now_iso) - timedelta(days=7)).isoformat()
    rows = conn.execute(
        """
        SELECT
          n.id AS listing_id,
          n.source_listing_id,
          n.title,
          n.end_at,
          n.status_norm,
          n.price_current,
          n.price_end,
          MAX(lm.updated_at) AS last_match_at
        FROM listing_matches lm
        JOIN market_listings_norm n ON n.id = lm.listing_id
        WHERE lm.user_id = ?
          AND lm.status = 'active'
          AND (
            n.is_active = 0
            OR (n.end_at IS NOT NULL AND n.end_at != '' AND n.end_at < ?)
            OR n.status_norm = 'ended'
          )
          AND NOT EXISTS (
            SELECT 1
            FROM signals s
            WHERE s.user_id = lm.user_id
              AND s.listing_id = lm.listing_id
              AND s.status = 'active'
              AND s.signal_type IN ('new_relevant_listing', 'buy_opportunity', 'sell_opportunity')
              AND s.created_at >= ?
          )
        GROUP BY n.id, n.source_listing_id, n.title, n.end_at, n.status_norm, n.price_current, n.price_end
        ORDER BY n.end_at DESC, n.id DESC
        LIMIT 100
        """,
        (user_id, window_end.isoformat(), cutoff_iso),
    ).fetchall()
    return [
        {
            "listing_id": str(row["listing_id"]),
            "source_listing_id": str(row["source_listing_id"] or ""),
            "title": str(row["title"] or ""),
            "status_norm": str(row["status_norm"] or ""),
            "end_at": str(row["end_at"] or ""),
            "price_current": _to_float(row["price_current"]),
            "price_end": _to_float(row["price_end"]),
            "last_match_at": str(row["last_match_at"] or ""),
        }
        for row in rows
    ]


def _load_watchlist_coverage(conn: sqlite3.Connection, user_id: str) -> dict[str, Any]:
    totals = conn.execute(
        """
        SELECT
          COUNT(*) AS watch_items_total,
          SUM(
            CASE
              WHEN EXISTS (
                SELECT 1
                FROM listing_matches lm
                JOIN market_listings_norm n ON n.id = lm.listing_id
                WHERE lm.user_item_id = ui.id
                  AND lm.user_id = ui.user_id
                  AND lm.status = 'active'
                  AND n.is_active = 1
              ) THEN 1
              ELSE 0
            END
          ) AS watch_items_matched
        FROM user_items ui
        WHERE ui.user_id = ?
          AND ui.item_type = 'watch'
          AND ui.is_active = 1
        """,
        (user_id,),
    ).fetchone()

    unmatched = conn.execute(
        """
        SELECT ui.id, ui.item_name
        FROM user_items ui
        WHERE ui.user_id = ?
          AND ui.item_type = 'watch'
          AND ui.is_active = 1
          AND NOT EXISTS (
            SELECT 1
            FROM listing_matches lm
            JOIN market_listings_norm n ON n.id = lm.listing_id
            WHERE lm.user_item_id = ui.id
              AND lm.user_id = ui.user_id
              AND lm.status = 'active'
              AND n.is_active = 1
          )
        ORDER BY ui.updated_at DESC, ui.id DESC
        LIMIT 20
        """,
        (user_id,),
    ).fetchall()

    watch_items_total = int(totals["watch_items_total"] or 0)
    watch_items_matched = int(totals["watch_items_matched"] or 0)
    coverage_pct = 0.0
    if watch_items_total > 0:
        coverage_pct = (watch_items_matched / watch_items_total) * 100.0

    return {
        "watch_items_total": watch_items_total,
        "watch_items_matched": watch_items_matched,
        "coverage_pct": round(coverage_pct, 2),
        "uncovered_items": [
            {"user_item_id": str(row["id"]), "item_name": str(row["item_name"] or "")}
            for row in unmatched
        ],
    }


def _upsert_report(
    conn: sqlite3.Connection,
    *,
    user_id: str,
    report_date: str,
    report_type: str,
    content_summary: str,
    content_payload_json: str,
    now_iso: str,
) -> str:
    existing = conn.execute(
        """
        SELECT id
        FROM reports
        WHERE user_id = ? AND report_date = ? AND report_type = ?
        LIMIT 1
        """,
        (user_id, report_date, report_type),
    ).fetchone()
    if existing is not None:
        report_id = str(existing["id"])
        conn.execute(
            """
            UPDATE reports
            SET content_summary = ?,
                content_payload_json = ?,
                delivery_status = 'pending',
                sent_at = NULL,
                created_at = ?
            WHERE id = ?
            """,
            (content_summary, content_payload_json, now_iso, report_id),
        )
        return report_id

    report_id = str(uuid.uuid4())
    conn.execute(
        """
        INSERT INTO reports (
          id,
          user_id,
          report_date,
          report_type,
          content_summary,
          content_payload_json,
          delivery_channel,
          delivery_status,
          sent_at,
          created_at
        ) VALUES (?, ?, ?, ?, ?, ?, 'app_console', 'pending', NULL, ?)
        """,
        (
            report_id,
            user_id,
            report_date,
            report_type,
            content_summary,
            content_payload_json,
            now_iso,
        ),
    )
    return report_id


def _replace_report_signal_links(
    conn: sqlite3.Connection,
    *,
    report_id: str,
    signal_ids: list[str],
    now_iso: str,
) -> int:
    conn.execute("DELETE FROM report_signal_links WHERE report_id = ?", (report_id,))
    if not signal_ids:
        return 0
    conn.executemany(
        """
        INSERT INTO report_signal_links (
          report_id,
          signal_id,
          created_at
        ) VALUES (?, ?, ?)
        """,
        [(report_id, signal_id, now_iso) for signal_id in signal_ids],
    )
    return len(signal_ids)


def _load_users(conn: sqlite3.Connection, *, user_id: str | None) -> list[sqlite3.Row]:
    if user_id:
        row = conn.execute("SELECT id FROM users WHERE id = ?", (user_id,)).fetchone()
        if row is None:
            raise ValueError(f"user not found: {user_id}")
        return [row]
    return conn.execute("SELECT id FROM users ORDER BY id").fetchall()


def _resolve_report_date(value: str | None) -> date:
    if value:
        return date.fromisoformat(value)
    return _parse_iso(now_utc_iso()).date()


def _build_window(report_date: date, report_type: str) -> tuple[datetime, datetime]:
    day_start = datetime.combine(report_date, datetime.min.time(), tzinfo=timezone.utc)
    if report_type == "daily":
        return day_start, day_start + timedelta(days=1)
    return day_start - timedelta(hours=24), day_start + timedelta(days=1)


def _build_summary(counts: dict[str, int]) -> str:
    return (
        "new_relevant={new_relevant};buy={buy};sell={sell};"
        "price_movement={price_movement};missed_expired={missed_expired};"
        "watch_coverage={watchlist_matched}/{watchlist_total}"
    ).format(**counts)


def _render_human_friendly_markdown(*, draft_markdown: str, model: str, api_key: str | None) -> str:
    if not api_key:
        return (
            "# Human-Friendly Report (LLM)\n\n"
            "LLM rendering skipped because `OPENAI_API_KEY` is not configured.\n\n"
            "## Structured Draft\n\n"
            + draft_markdown
        )

    prompt = HUMAN_REPORT_PROMPT_TEMPLATE + "\n\n" + draft_markdown
    data = json.dumps({"model": model, "input": prompt}, ensure_ascii=False).encode("utf-8")
    req = request.Request(
        url="https://api.openai.com/v1/responses",
        data=data,
        method="POST",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
    )
    try:
        with request.urlopen(req, timeout=60) as resp:
            body = resp.read().decode("utf-8")
    except error.URLError as exc:
        return (
            "# Human-Friendly Report (LLM)\n\n"
            f"LLM rendering failed: {exc}\n\n"
            "## Structured Draft\n\n"
            + draft_markdown
        )

    try:
        parsed = json.loads(body)
        text = str(parsed["output"][0]["content"][0]["text"]).strip()
        if text:
            return text + "\n"
    except (KeyError, IndexError, TypeError, json.JSONDecodeError):
        pass
    return (
        "# Human-Friendly Report (LLM)\n\n"
        "LLM response parsing failed; showing structured draft.\n\n"
        "## Structured Draft\n\n"
        + draft_markdown
    )


def _parse_iso(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)


def _to_float(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
