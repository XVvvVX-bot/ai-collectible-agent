"""Display formatters for the digest UI: relative time, prices, badges, listing URLs."""

from __future__ import annotations

import html
import os
from datetime import datetime, timezone

DEFAULT_LISTING_URL_TEMPLATE = "https://zhaoonline.com/auction-detail.shtml?id={id}"


def _parse_iso(value: str) -> datetime | None:
    if not value:
        return None
    text = str(value).strip().rstrip()
    if not text:
        return None
    text = text.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def format_relative_time(iso_str: str, *, now_utc: datetime | None = None) -> str:
    """Return a short human label like '2 hours ago' or 'in 3 days'.

    Falls back to an absolute date for ages > 30 days. Returns '' on parse failure.
    """
    parsed = _parse_iso(iso_str)
    if parsed is None:
        return ""
    now = now_utc or datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    delta = (now - parsed).total_seconds()
    future = delta < 0
    seconds = abs(delta)

    if seconds < 45:
        return "just now"
    if seconds < 90:
        return "in a minute" if future else "a minute ago"
    minutes = int(round(seconds / 60))
    if minutes < 60:
        suffix = "minute" if minutes == 1 else "minutes"
        return f"in {minutes} {suffix}" if future else f"{minutes} {suffix} ago"
    hours = int(round(seconds / 3600))
    if hours < 24:
        suffix = "hour" if hours == 1 else "hours"
        return f"in {hours} {suffix}" if future else f"{hours} {suffix} ago"
    days = int(round(seconds / 86400))
    if days < 30:
        suffix = "day" if days == 1 else "days"
        return f"in {days} {suffix}" if future else f"{days} {suffix} ago"
    return parsed.strftime("%b %d, %Y")


def format_absolute_time(iso_str: str) -> str:
    parsed = _parse_iso(iso_str)
    if parsed is None:
        return ""
    return parsed.strftime("%b %d, %Y %H:%M %Z").strip()


def render_time_html(iso_str: str) -> str:
    """Render a <time> element with relative label and absolute tooltip.

    Falls back to the escaped raw string if parsing fails.
    """
    parsed = _parse_iso(iso_str)
    if parsed is None:
        return html.escape(str(iso_str or "").strip())
    relative = format_relative_time(iso_str)
    absolute = format_absolute_time(iso_str)
    iso_attr = parsed.isoformat()
    return (
        f'<time class="digest-time" datetime="{html.escape(iso_attr)}" '
        f'title="{html.escape(absolute)}">{html.escape(relative)}</time>'
    )


def _coerce_number(value: object) -> float | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip().replace(",", "")
    if not text or text == "-":
        return None
    try:
        return float(text)
    except ValueError:
        return None


def format_price_cny(value: object) -> str:
    num = _coerce_number(value)
    if num is None:
        return ""
    if abs(num - round(num)) < 0.005:
        return f"¥{int(round(num)):,}"
    return f"¥{num:,.2f}"


def format_price_range(min_v: object, max_v: object) -> str:
    a = _coerce_number(min_v)
    b = _coerce_number(max_v)
    if a is None and b is None:
        return ""
    if a is None:
        return format_price_cny(b)
    if b is None or a == b:
        return format_price_cny(a)
    return f"{format_price_cny(a)}–{format_price_cny(b)[1:]}"


_RELATIONSHIP_LABELS = {
    "exact_identity": ("Exact", "exact"),
    "variant_related": ("Variant", "variant"),
    "series_related": ("Series", "series"),
}


def format_relationship_badge(value: str) -> str:
    if not value:
        return ""
    label, modifier = _RELATIONSHIP_LABELS.get(value, (value.replace("_", " ").title(), "neutral"))
    return f'<span class="digest-badge digest-badge--{html.escape(modifier)}">{html.escape(label)}</span>'


_STATUS_LABELS = {
    "preview": ("Preview", "preview"),
    "live": ("Live", "live"),
    "ended": ("Ended", "ended"),
}


def format_status_badge(value: str) -> str:
    if not value:
        return ""
    key = str(value).strip().lower()
    label, modifier = _STATUS_LABELS.get(key, (value.title(), "neutral"))
    return f'<span class="digest-badge digest-badge--{html.escape(modifier)}">{html.escape(label)}</span>'


def format_short_id(value: str, *, max_chars: int = 18) -> str:
    text = str(value or "").strip()
    if not text or len(text) <= max_chars:
        return text
    head = max(4, (max_chars - 1) // 2)
    tail = max(3, max_chars - head - 1)
    return f"{text[:head]}…{text[-tail:]}"


def _listing_url_template() -> str:
    raw = os.getenv("APP_ZHAOONLINE_LISTING_URL_TEMPLATE")
    if raw is None:
        return DEFAULT_LISTING_URL_TEMPLATE
    return raw.strip()


def build_listing_url(*, source_listing_id: object = None, auction_no: object = None) -> str | None:
    """Return a public listing URL using the configured template.

    Template placeholders:
      {id}         -> source_listing_id (the upstream numeric ``id``/``auctionId``)
      {auction_no} -> auction_no (the upstream ``auctionNo`` string)

    Returns None when the template is empty, or when the template requires data
    we don't have, or when source_listing_id is non-numeric (e.g. demo fixtures).
    """
    template = _listing_url_template()
    if not template:
        return None

    sid = str(source_listing_id).strip() if source_listing_id is not None else ""
    ano = str(auction_no).strip() if auction_no is not None else ""

    if "{id}" in template:
        if not sid or not sid.isdigit():
            return None
    if "{auction_no}" in template and not ano:
        return None

    try:
        return template.format(id=sid, auction_no=ano)
    except (KeyError, IndexError):
        return None


def render_listing_link(*, source_listing_id: object = None, auction_no: object = None, label: str = "Open on zhaoonline ↗") -> str:
    """Render an anchor tag if a listing URL can be built; otherwise return ''."""
    url = build_listing_url(source_listing_id=source_listing_id, auction_no=auction_no)
    if not url:
        return ""
    return (
        f'<a class="digest-listing-link" href="{html.escape(url)}" '
        f'target="_blank" rel="noopener noreferrer">{html.escape(label)}</a>'
    )
