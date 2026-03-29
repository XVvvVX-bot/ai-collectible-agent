from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from ai_agent_v2.normalization.zhaoonline_norm import NormalizationRunResult, run_zhaoonline_norm_v2
from ai_agent_v2.parsing.listing_parser import ParseRunResult, run_listing_parse_v2


@dataclass(frozen=True)
class PostSyncRefreshResult:
    sync_run_ids: tuple[str, ...]
    normalization: NormalizationRunResult
    parsing: ParseRunResult


def run_post_sync_refresh(db_path: str, *, sync_run_ids: Sequence[str]) -> PostSyncRefreshResult:
    normalization = run_zhaoonline_norm_v2(db_path, sync_run_ids=tuple(sync_run_ids))
    if normalization.source_listing_ids:
        parsing = run_listing_parse_v2(db_path, source_listing_ids=normalization.source_listing_ids)
    else:
        parsing = ParseRunResult(processed=0, upserted=0, family_counts={})
    return PostSyncRefreshResult(
        sync_run_ids=tuple(sync_run_ids),
        normalization=normalization,
        parsing=parsing,
    )
