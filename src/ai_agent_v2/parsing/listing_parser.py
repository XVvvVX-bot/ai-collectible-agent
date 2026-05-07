from __future__ import annotations

import json
import re
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Sequence

from ai_agent_v2.clients.zhaoonline import now_utc_iso
from ai_agent_v2.storage.sqlite_store import SqliteV2Store

SOURCE_PLATFORM = "zhaoonline"
PARSER_VERSION = "v2_title_parser_003"

STAMP_CATEGORY_MARKERS = (
    "邮票",
    "散票",
    "小型",
    "版",
    "新中国",
    "编号",
    "纪特",
    "港澳",
    "清代",
    "民国邮票",
    "编年",
)
COIN_CATEGORY_MARKERS = ("币", "钞", "人民币", "纸币")
ART_CATEGORY_MARKERS = ("山水", "花鸟", "书法", "人物", "其他艺术品")

STAMP_CODE_RE = re.compile(r"^(?P<prefix>特|纪|普|文|编|J|T|N)\s*(?P<number>\d+)(?P<suffix>[A-Z]?)")
YEAR_RE = re.compile(r"^(?P<year>\d{4})年")
WEIGHT_RE = re.compile(r"(\d+(?:\.\d+)?克|\d+/\d+盎司|\d+盎司)")
DENOM_RE = re.compile(r"(\d+元)")

CODE_PREFIX_MAP = {
    "特": "T",
    "T": "T",
    "纪": "J",
    "J": "J",
    "普": "P",
    "文": "W",
    "编": "B",
    "N": "N",
}

STAMP_VARIANT_TOKENS = (
    "小型张",
    "小全张",
    "小本票",
    "型张",
    "版张",
    "带厂铭",
    "直角边",
    "色标",
    "双连",
    "四连",
    "方连",
    "折版",
    "再版",
    "无齿",
    "加盖",
    "一版",
    "二版",
    "三版",
    "四版",
    "五版",
    "六版",
    "M",
)
STAMP_CONDITION_TOKENS = ("新全", "旧全", "盖全", "实寄", "新", "旧", "盖")
COIN_ASSET_TOKENS = ("纪念钞", "纸币", "银币", "金币", "银章", "金章")
COIN_FINISH_TOKENS = ("精制", "普制")
COIN_VARIANT_TOKENS = (
    "卡册",
    "原盒",
    "证书",
    "连号",
    "小全套",
    "大全套",
    "首日封",
    "评级币",
    "原光",
    "PCGS",
    "NGC",
    "一套",
    "二枚",
    "十枚",
)

QUANTITY_UNIT_CHARS = "套枚张件连版份对"
QUANTITY_RE = re.compile(rf"(?:\d+|[一二三四五六七八九十百千]+)[{QUANTITY_UNIT_CHARS}]")


@dataclass(frozen=True)
class ParseRunResult:
    processed: int
    upserted: int
    family_counts: dict[str, int]


def run_listing_parse_v2(db_path: str, *, source_listing_ids: Sequence[str] | None = None) -> ParseRunResult:
    SqliteV2Store(db_path).ensure_schema()
    now = now_utc_iso()
    with sqlite3.connect(Path(db_path)) as conn:
        conn.row_factory = sqlite3.Row
        if source_listing_ids:
            placeholders = ",".join("?" for _ in source_listing_ids)
            rows = conn.execute(
                f"""
                SELECT id, source_platform, source_listing_id, title, category_name_raw, character_name_raw, description_character
                FROM market_listings_norm_v2
                WHERE source_platform = ?
                  AND source_listing_id IN ({placeholders})
                ORDER BY source_listing_id
                """,
                (SOURCE_PLATFORM, *source_listing_ids),
            ).fetchall()
        else:
            rows = conn.execute(
                """
                SELECT id, source_platform, source_listing_id, title, category_name_raw, character_name_raw, description_character
                FROM market_listings_norm_v2
                WHERE source_platform = ?
                ORDER BY source_listing_id
                """,
                (SOURCE_PLATFORM,),
            ).fetchall()
        parse_rows = [_parse_listing_row(row) for row in rows]
        family_counts: dict[str, int] = {}
        for row in parse_rows:
            family_counts[row["parse_family"]] = family_counts.get(row["parse_family"], 0) + 1

        conn.executemany(
            """
            INSERT INTO listing_parse_v2 (
              listing_id, source_platform, source_listing_id, parser_version, parse_family, raw_title,
              title_normalized, identity_core, series_key, variant_key, condition_key, code_prefix_raw,
              code_prefix_norm, code_number, code_suffix, issue_code_norm, issue_name, year_value,
              theme_name, asset_type, finish_type, weight_text, denomination_text, character_condition,
              variant_tokens_json, condition_tokens_json, quantity_tokens_json, parse_confidence, parse_notes_json,
              created_at, updated_at
            ) VALUES (
              ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
            )
            ON CONFLICT(listing_id) DO UPDATE SET
              parser_version = excluded.parser_version,
              parse_family = excluded.parse_family,
              raw_title = excluded.raw_title,
              title_normalized = excluded.title_normalized,
              identity_core = excluded.identity_core,
              series_key = excluded.series_key,
              variant_key = excluded.variant_key,
              condition_key = excluded.condition_key,
              code_prefix_raw = excluded.code_prefix_raw,
              code_prefix_norm = excluded.code_prefix_norm,
              code_number = excluded.code_number,
              code_suffix = excluded.code_suffix,
              issue_code_norm = excluded.issue_code_norm,
              issue_name = excluded.issue_name,
              year_value = excluded.year_value,
              theme_name = excluded.theme_name,
              asset_type = excluded.asset_type,
              finish_type = excluded.finish_type,
              weight_text = excluded.weight_text,
              denomination_text = excluded.denomination_text,
              character_condition = excluded.character_condition,
              variant_tokens_json = excluded.variant_tokens_json,
              condition_tokens_json = excluded.condition_tokens_json,
              quantity_tokens_json = excluded.quantity_tokens_json,
              parse_confidence = excluded.parse_confidence,
              parse_notes_json = excluded.parse_notes_json,
              updated_at = excluded.updated_at
            """,
            [(*_tuple_from_row(row), now, now) for row in parse_rows],
        )
        conn.commit()
    return ParseRunResult(processed=len(parse_rows), upserted=len(parse_rows), family_counts=family_counts)


def _parse_listing_row(row: sqlite3.Row) -> dict[str, Any]:
    raw_title = _text(row["title"])
    category_name = _text(row["category_name_raw"])
    character_condition = _text(row["character_name_raw"])
    description_character = _text(row["description_character"])
    parse_family = _classify_parse_family(raw_title, category_name)
    if parse_family == "stamp_like":
        parsed = _parse_stamp_title(raw_title=raw_title, character_condition=character_condition, description_character=description_character)
        # If neither tier recovered structural anchors, drop to "other" so the
        # dashboard renders the raw-title fallback view.
        if not parsed.get("issue_code_norm") and not parsed.get("issue_name"):
            parse_family = "other"
            parsed = _parse_other_title(raw_title=raw_title, character_condition=character_condition, tier_note="unparsed")
    elif parse_family == "coin_like":
        parsed = _parse_coin_title(raw_title=raw_title, character_condition=character_condition, description_character=description_character)
        if parsed.get("year_value") is None and not parsed.get("theme_name") and not parsed.get("asset_type"):
            parse_family = "other"
            parsed = _parse_other_title(raw_title=raw_title, character_condition=character_condition, tier_note="unparsed")
    else:
        parsed = _parse_other_title(raw_title=raw_title, character_condition=character_condition)
    return {
        "listing_id": str(row["id"]),
        "source_platform": str(row["source_platform"]),
        "source_listing_id": str(row["source_listing_id"]),
        "parser_version": PARSER_VERSION,
        "parse_family": parse_family,
        "raw_title": raw_title,
        "character_condition": character_condition,
        **parsed,
    }


def parse_listing_title(
    *,
    raw_title: str | None,
    category_name_raw: str | None = None,
    character_condition: str | None = None,
    description_character: str | None = None,
) -> dict[str, Any]:
    """Public testing helper: parse a single title without database access.

    Returns the same dict shape as _parse_listing_row minus storage-only keys.
    """
    parse_family = _classify_parse_family(raw_title, category_name_raw)
    if parse_family == "stamp_like":
        parsed = _parse_stamp_title(raw_title=raw_title, character_condition=character_condition, description_character=description_character)
        if not parsed.get("issue_code_norm") and not parsed.get("issue_name"):
            parse_family = "other"
            parsed = _parse_other_title(raw_title=raw_title, character_condition=character_condition, tier_note="unparsed")
    elif parse_family == "coin_like":
        parsed = _parse_coin_title(raw_title=raw_title, character_condition=character_condition, description_character=description_character)
        if parsed.get("year_value") is None and not parsed.get("theme_name") and not parsed.get("asset_type"):
            parse_family = "other"
            parsed = _parse_other_title(raw_title=raw_title, character_condition=character_condition, tier_note="unparsed")
    else:
        parsed = _parse_other_title(raw_title=raw_title, character_condition=character_condition)
    return {"parse_family": parse_family, "raw_title": raw_title, **parsed}


def _parse_stamp_title(*, raw_title: str | None, character_condition: str | None, description_character: str | None) -> dict[str, Any]:
    title = raw_title or ""
    working = _normalize_spaces(title)
    notes: list[str] = []
    code_prefix_raw = None
    code_prefix_norm = None
    code_number = None
    code_suffix = None
    issue_code_norm = None

    match = STAMP_CODE_RE.match(working)
    if match:
        code_prefix_raw = match.group("prefix")
        code_prefix_norm = CODE_PREFIX_MAP.get(code_prefix_raw, code_prefix_raw)
        code_number = match.group("number")
        code_suffix = match.group("suffix") or None
        issue_code_norm = f"{code_prefix_norm}{code_number}{code_suffix or ''}"
        working = working[match.end() :].strip(" -_")
        if code_prefix_raw != code_prefix_norm:
            notes.append("code_alias_normalized")

    # ---- Strict tier: variants → quantities → conditions, removing each
    # span as it's found. Variants go first so phrases like "一版" bind
    # before the generic quantity regex can claim them. Quantities go before
    # conditions so digit-adjacent condition tokens (e.g., "新" in "新28套")
    # become parseable once the digit span is gone. ----
    strict_working = working
    strict_variant = _extract_bounded_tokens(strict_working, STAMP_VARIANT_TOKENS)
    for v in strict_variant:
        strict_working = re.sub(re.escape(v), " ", strict_working, count=1)
    strict_quantity = _extract_quantity_tokens_strict(strict_working)
    for q in strict_quantity:
        strict_working = strict_working.replace(q, " ", 1)
    strict_condition = _extract_bounded_tokens(strict_working, STAMP_CONDITION_TOKENS)
    for c in strict_condition:
        strict_working = re.sub(re.escape(c), " ", strict_working, count=1)
    strict_name = _clean_issue_name(
        strict_working,
        remove_tokens=strict_variant + strict_condition + strict_quantity,
    )

    strict_field_count = sum(
        1 for x in (issue_code_norm, strict_name, strict_variant, strict_condition, strict_quantity) if x
    )
    use_strict = strict_field_count >= 2 and (issue_code_norm or strict_name)

    if use_strict:
        variant_tokens = list(strict_variant)
        condition_tokens = list(strict_condition)
        quantity_tokens = list(strict_quantity)
        issue_name = strict_name
        notes.append("tier=strict")
    else:
        variant_tokens = _extract_known_tokens(working, STAMP_VARIANT_TOKENS)
        condition_tokens = _extract_known_tokens(working, STAMP_CONDITION_TOKENS)
        quantity_tokens = _extract_quantity_tokens(working)
        issue_name = _clean_issue_name(
            working, remove_tokens=variant_tokens + condition_tokens + quantity_tokens
        )
        notes.append("tier=loose")

    if code_suffix and code_suffix not in variant_tokens:
        variant_tokens.append(code_suffix)

    condition_parts = list(condition_tokens)
    for value in (character_condition, description_character):
        if value and value not in condition_parts:
            condition_parts.append(value)
    return {
        "title_normalized": _normalize_spaces(title),
        "identity_core": "|".join(x for x in [issue_code_norm, issue_name] if x) or None,
        "series_key": issue_code_norm or issue_name,
        "variant_key": "|".join(dict.fromkeys(variant_tokens)) or None,
        "condition_key": "|".join(condition_parts) or None,
        "code_prefix_raw": code_prefix_raw,
        "code_prefix_norm": code_prefix_norm,
        "code_number": code_number,
        "code_suffix": code_suffix,
        "issue_code_norm": issue_code_norm,
        "issue_name": issue_name,
        "year_value": None,
        "theme_name": issue_name,
        "asset_type": None,
        "finish_type": None,
        "weight_text": None,
        "denomination_text": None,
        "variant_tokens_json": json.dumps(_dedupe(variant_tokens), ensure_ascii=False, separators=(",", ":")),
        "condition_tokens_json": json.dumps(_dedupe(condition_tokens), ensure_ascii=False, separators=(",", ":")),
        "quantity_tokens_json": json.dumps(_dedupe(quantity_tokens), ensure_ascii=False, separators=(",", ":")),
        "parse_confidence": min(0.4 + (0.35 if issue_code_norm else 0) + (0.2 if issue_name else 0) + (0.05 if variant_tokens or condition_tokens else 0), 0.99),
        "parse_notes_json": json.dumps(notes, ensure_ascii=False, separators=(",", ":")),
    }


def _parse_coin_title(*, raw_title: str | None, character_condition: str | None, description_character: str | None) -> dict[str, Any]:
    title = raw_title or ""
    working = _normalize_spaces(title)
    notes: list[str] = []
    year_value = None
    match = YEAR_RE.match(working)
    if match:
        year_value = int(match.group("year"))
        working = working[match.end() :].strip()

    # ---- Strict tier: extract weight/denomination first (precise regexes),
    # then variants, then quantities, then asset/finish. ----
    strict_working = working
    strict_weight = _extract_first(strict_working, WEIGHT_RE)
    if strict_weight:
        strict_working = strict_working.replace(strict_weight, " ", 1)
    strict_denom = _extract_first(strict_working, DENOM_RE)
    if strict_denom:
        strict_working = strict_working.replace(strict_denom, " ", 1)
    strict_variant = _extract_bounded_tokens(strict_working, COIN_VARIANT_TOKENS)
    for v in strict_variant:
        strict_working = re.sub(re.escape(v), " ", strict_working, count=1)
    strict_quantity = _extract_quantity_tokens_strict(strict_working)
    for q in strict_quantity:
        strict_working = strict_working.replace(q, " ", 1)
    strict_asset = _find_first_token(strict_working, COIN_ASSET_TOKENS)
    strict_finish = _find_first_token(strict_working, COIN_FINISH_TOKENS)
    strict_theme = _clean_issue_name(
        strict_working,
        remove_tokens=[
            *strict_variant,
            *[x for x in (strict_asset, strict_finish) if x],
        ],
    )

    strict_field_count = sum(
        1 for x in (year_value, strict_theme, strict_asset, strict_finish, strict_weight, strict_denom, strict_variant)
        if x
    )
    use_strict = strict_field_count >= 2 and (year_value is not None or strict_theme or strict_asset)

    if use_strict:
        asset_type = strict_asset
        finish_type = strict_finish
        weight_text = strict_weight
        denomination_text = strict_denom
        variant_tokens = list(strict_variant)
        quantity_tokens = list(strict_quantity)
        theme_name = strict_theme
        notes.append("tier=strict")
    else:
        asset_type = _find_first_token(title, COIN_ASSET_TOKENS)
        finish_type = _find_first_token(title, COIN_FINISH_TOKENS)
        weight_text = _extract_first(title, WEIGHT_RE)
        denomination_text = _extract_first(title, DENOM_RE)
        variant_tokens = _extract_known_tokens(title, COIN_VARIANT_TOKENS)
        quantity_tokens = _extract_quantity_tokens(title)
        theme_name = _clean_issue_name(
            working,
            remove_tokens=[
                *variant_tokens,
                *quantity_tokens,
                *[x for x in (asset_type, finish_type, weight_text, denomination_text) if x],
            ],
        )
        notes.append("tier=loose")

    condition_tokens = [x for x in (character_condition, description_character) if x]
    return {
        "title_normalized": _normalize_spaces(title),
        "identity_core": "|".join(x for x in [str(year_value) if year_value is not None else None, theme_name, asset_type] if x) or None,
        "series_key": "|".join(x for x in [theme_name, asset_type] if x) or theme_name,
        "variant_key": "|".join(x for x in [finish_type, weight_text, denomination_text, *variant_tokens] if x) or None,
        "condition_key": "|".join(x for x in condition_tokens if x) or None,
        "code_prefix_raw": None,
        "code_prefix_norm": None,
        "code_number": None,
        "code_suffix": None,
        "issue_code_norm": None,
        "issue_name": None,
        "year_value": year_value,
        "theme_name": theme_name,
        "asset_type": asset_type,
        "finish_type": finish_type,
        "weight_text": weight_text,
        "denomination_text": denomination_text,
        "variant_tokens_json": json.dumps(_dedupe(variant_tokens), ensure_ascii=False, separators=(",", ":")),
        "condition_tokens_json": json.dumps(_dedupe(condition_tokens), ensure_ascii=False, separators=(",", ":")),
        "quantity_tokens_json": json.dumps(_dedupe(quantity_tokens), ensure_ascii=False, separators=(",", ":")),
        "parse_confidence": min(0.45 + (0.15 if year_value is not None else 0) + (0.2 if theme_name else 0) + (0.1 if asset_type else 0) + (0.05 if weight_text or denomination_text else 0), 0.99),
        "parse_notes_json": json.dumps(notes, ensure_ascii=False, separators=(",", ":")),
    }


def _parse_other_title(
    *,
    raw_title: str | None,
    character_condition: str | None,
    tier_note: str | None = None,
) -> dict[str, Any]:
    title = _normalize_spaces(raw_title or "")
    condition_tokens = [character_condition] if character_condition else []
    notes: list[str] = []
    if tier_note:
        notes.append(f"tier={tier_note}")
    return {
        "title_normalized": title or None,
        "identity_core": title or None,
        "series_key": title or None,
        "variant_key": None,
        "condition_key": "|".join(condition_tokens) or None,
        "code_prefix_raw": None,
        "code_prefix_norm": None,
        "code_number": None,
        "code_suffix": None,
        "issue_code_norm": None,
        "issue_name": title or None,
        "year_value": None,
        "theme_name": None,
        "asset_type": None,
        "finish_type": None,
        "weight_text": None,
        "denomination_text": None,
        "variant_tokens_json": "[]",
        "condition_tokens_json": json.dumps(condition_tokens, ensure_ascii=False, separators=(",", ":")),
        "quantity_tokens_json": json.dumps(_extract_quantity_tokens(title), ensure_ascii=False, separators=(",", ":")),
        "parse_confidence": 0.25 if title else 0.0,
        "parse_notes_json": json.dumps(notes, ensure_ascii=False, separators=(",", ":")),
    }


def _classify_parse_family(raw_title: str | None, category_name: str | None) -> str:
    title = raw_title or ""
    category = category_name or ""
    if any(marker in category for marker in STAMP_CATEGORY_MARKERS) or STAMP_CODE_RE.match(title):
        return "stamp_like"
    if any(marker in category for marker in COIN_CATEGORY_MARKERS) or any(token in title for token in COIN_ASSET_TOKENS):
        return "coin_like"
    if any(marker in category for marker in ART_CATEGORY_MARKERS):
        return "art_like"
    return "other"


def _extract_known_tokens(text: str, tokens: tuple[str, ...]) -> list[str]:
    return [token for token in tokens if token in text]


def _extract_bounded_tokens(text: str, tokens: tuple[str, ...]) -> list[str]:
    """Extract tokens with digit-boundary checks, longest-first.

    A token is rejected when adjacent to a digit (so "新" is not extracted
    from "新28套" until the quantity span has been removed first). Longer
    tokens are tried before shorter ones so "新全" wins over "新".
    """
    sorted_tokens = sorted({t for t in tokens if t}, key=len, reverse=True)
    results: list[str] = []
    remaining = text
    for token in sorted_tokens:
        pattern = re.compile(rf"(?<!\d){re.escape(token)}(?!\d)")
        if pattern.search(remaining):
            results.append(token)
            remaining = pattern.sub(" ", remaining)
    # Preserve original token order for callers that expect deterministic ordering.
    ordered: list[str] = [t for t in tokens if t in results]
    # Fall back to first-seen order for any tokens not in the source tuple.
    for t in results:
        if t not in ordered:
            ordered.append(t)
    return ordered


def _extract_quantity_tokens(text: str) -> list[str]:
    results: list[str] = []
    for pattern in [r"\d+枚", r"\d+张", r"\d+件", r"\d+套", r"\d+连", r"\d+版", r"一套", r"二枚", r"十枚"]:
        for match in re.findall(pattern, text):
            if match not in results:
                results.append(match)
    return results


def _extract_quantity_tokens_strict(text: str) -> list[str]:
    """Strict quantity extractor: Arabic or Chinese numeral + standard unit char."""
    results: list[str] = []
    for match in QUANTITY_RE.findall(text):
        if match not in results:
            results.append(match)
    return results


def _clean_issue_name(text: str, *, remove_tokens: list[str]) -> str | None:
    cleaned = text
    for token in sorted({token for token in remove_tokens if token}, key=len, reverse=True):
        cleaned = cleaned.replace(token, " ")
    # Strip () inner content (typically parenthetical metadata).
    cleaned = re.sub(r"[（(][^）)]*[）)]", " ", cleaned)
    # Strip 【】《》 [] characters but preserve inner content (titles often quote names).
    cleaned = re.sub(r"[【】\[\]《》、,，;；:+\-_/]+", " ", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned or None


def _normalize_spaces(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def _find_first_token(text: str, tokens: tuple[str, ...]) -> str | None:
    for token in tokens:
        if token in text:
            return token
    return None


def _extract_first(text: str, pattern: re.Pattern[str]) -> str | None:
    match = pattern.search(text)
    return match.group(1) if match else None


def _text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text if text else None


def _tuple_from_row(row: dict[str, Any]) -> tuple[Any, ...]:
    return (
        row["listing_id"],
        row["source_platform"],
        row["source_listing_id"],
        row["parser_version"],
        row["parse_family"],
        row["raw_title"],
        row["title_normalized"],
        row["identity_core"],
        row["series_key"],
        row["variant_key"],
        row["condition_key"],
        row["code_prefix_raw"],
        row["code_prefix_norm"],
        row["code_number"],
        row["code_suffix"],
        row["issue_code_norm"],
        row["issue_name"],
        row["year_value"],
        row["theme_name"],
        row["asset_type"],
        row["finish_type"],
        row["weight_text"],
        row["denomination_text"],
        row["character_condition"],
        row["variant_tokens_json"],
        row["condition_tokens_json"],
        row["quantity_tokens_json"],
        row["parse_confidence"],
        row["parse_notes_json"],
    )


def _dedupe(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value and value not in seen:
            seen.add(value)
            result.append(value)
    return result
