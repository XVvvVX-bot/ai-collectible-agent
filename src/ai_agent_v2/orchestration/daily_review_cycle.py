from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from ai_agent_v2.reporting.daily_user_base_review import build_daily_user_base_review_report


@dataclass(frozen=True)
class DailyReviewCycleResult:
    ok: bool
    skipped: bool
    skip_reason: str | None
    local_date: str
    report_path: str | None
    user_count: int
    total_active_matches: int
    total_active_signals: int


def run_daily_user_base_review_cycle(
    db_path: str,
    output_dir: str,
    *,
    state_dir: str,
    now_local: datetime | None = None,
    lookback_hours: int = 24,
) -> DailyReviewCycleResult:
    local_now = now_local or datetime.now().astimezone()
    local_date = local_now.date().isoformat()
    state_path = Path(state_dir) / "v2_daily_user_base_review_state.json"
    state_path.parent.mkdir(parents=True, exist_ok=True)
    prior_date = _load_last_local_date(state_path)
    if prior_date == local_date:
        return DailyReviewCycleResult(
            ok=True,
            skipped=True,
            skip_reason="already_ran_today",
            local_date=local_date,
            report_path=None,
            user_count=0,
            total_active_matches=0,
            total_active_signals=0,
        )

    report = build_daily_user_base_review_report(
        db_path,
        output_dir,
        lookback_hours=lookback_hours,
        now_utc=local_now.astimezone(timezone.utc),
    )
    state_path.write_text(
        json.dumps(
            {
                "last_local_date": local_date,
                "last_report_path": report.report_path,
                "updated_at": local_now.isoformat(),
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    return DailyReviewCycleResult(
        ok=True,
        skipped=False,
        skip_reason=None,
        local_date=local_date,
        report_path=report.report_path,
        user_count=report.user_count,
        total_active_matches=report.total_active_matches,
        total_active_signals=report.total_active_signals,
    )


def _load_last_local_date(state_path: Path) -> str | None:
    if not state_path.exists():
        return None
    try:
        payload = json.loads(state_path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return None
    value = payload.get("last_local_date")
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None
