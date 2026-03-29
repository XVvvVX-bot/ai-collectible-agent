from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from ai_agent_v2.reporting.daily_signal_review_batch import build_daily_signal_review_batch


@dataclass(frozen=True)
class DailySignalReviewCycleResult:
    ok: bool
    skipped: bool
    skip_reason: str | None
    local_date: str
    index_report_path: str | None
    user_count: int
    total_signal_count: int
    user_report_paths: list[str]


def run_daily_signal_review_cycle(
    db_path: str,
    output_dir: str,
    *,
    state_dir: str,
    now_local: datetime | None = None,
    lookback_hours: int = 24,
) -> DailySignalReviewCycleResult:
    local_now = now_local or datetime.now().astimezone()
    local_date = local_now.date().isoformat()
    state_path = Path(state_dir) / "v2_daily_signal_review_state.json"
    state_path.parent.mkdir(parents=True, exist_ok=True)
    prior_date = _load_last_local_date(state_path)
    if prior_date == local_date:
        return DailySignalReviewCycleResult(
            ok=True,
            skipped=True,
            skip_reason="already_ran_today",
            local_date=local_date,
            index_report_path=None,
            user_count=0,
            total_signal_count=0,
            user_report_paths=[],
        )

    batch = build_daily_signal_review_batch(
        db_path,
        output_dir,
        lookback_hours=lookback_hours,
    )
    state_path.write_text(
        json.dumps(
            {
                "last_local_date": local_date,
                "last_index_report_path": batch.index_report_path,
                "last_user_report_paths": batch.user_report_paths,
                "updated_at": local_now.isoformat(),
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    return DailySignalReviewCycleResult(
        ok=True,
        skipped=False,
        skip_reason=None,
        local_date=local_date,
        index_report_path=batch.index_report_path,
        user_count=batch.user_count,
        total_signal_count=batch.total_signal_count,
        user_report_paths=batch.user_report_paths,
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
