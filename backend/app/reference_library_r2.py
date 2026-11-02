"""Opt-in R2-first counts for the authenticated, shared reference library.

The immutable R2 catalogue has provider/set/card identities, but intentionally
does not have full source evidence or refresh timestamps. This module only
replaces expensive *counts*. Live PostgreSQL remains authoritative for set
metadata, sync receipts, authorization, and every writable reference record.
"""
from __future__ import annotations

from datetime import date
import os


# Keep runtime refresh timestamps in SQL. Updates to refreshed_at alone do not
# invalidate the immutable catalogue R2 publication (by design).
COVERAGE_METADATA_SQL = """select system_code,provider,language,
  max(refreshed_at) as refreshed_at,current_date as source_today
  from tcg.reference_sets group by system_code,provider,language
  order by system_code,provider,language"""

_coverage_cache: dict[tuple[int, str, date], dict] = {}


def _day(value: str | date) -> date:
    return value if isinstance(value, date) else date.fromisoformat(value)


def enabled() -> bool:
    # Independent opt-in. The existing R2 delivery flag must also be enabled
    # for catalogue_r2_live.read() to return a verified current snapshot.
    return os.getenv("TCG_R2_REFERENCE_LIBRARY_READ_ENABLED", "false").lower() in ("true", "1")


def indexed_set_page(records, snapshot) -> list[dict]:
    """Replace only the correlated source-card COUNT for a bounded SQL page."""
    index = getattr(snapshot, "scope_index", None)
    if index is None or "reference_cards" not in index.by_scope:
        raise ValueError("Verified R2 card index is unavailable")
    by_set = index.by_scope["reference_cards"]
    return [
        {**dict(row), "indexed_cards": len(by_set.get((
            row["provider"], row["system_code"], row["language"], row["set_id"]
        ), ()))}
        for row in records
    ]


def build_coverage_counts(shared: dict, today: date) -> dict[tuple[str, str, str], dict]:
    """Match SQL's LEFT JOIN count and upcoming-date predicate exactly.

    A reference without a matching source set is never counted. All indexed
    printing variants remain distinct, including identical card numbers.
    """
    result: dict[tuple[str, str, str], dict] = {}
    matched_sets: dict[tuple[str, str, str, str], tuple[tuple[str, str, str], bool]] = {}
    for row in shared["reference_sets"]:
        key = (row["system_code"], row["provider"], row["language"])
        group = result.setdefault(key, dict(system_code=key[0], provider=key[1],
                                            language=key[2], sets=0, cards=0, upcoming_cards=0))
        group["sets"] += 1
        release = _day(row["release_date"]) if row["release_date"] else None
        matched_sets[(row["provider"], row["system_code"], row["language"], row["set_id"])] = (
            key, release is not None and release > today
        )
    for card in shared["reference_cards"]:
        set_key = (card["provider"], card["system_code"], card["language"], card["set_id"])
        matched = matched_sets.get(set_key)
        if matched is None:
            continue
        group_key, upcoming = matched
        group = result[group_key]
        group["cards"] += 1
        if upcoming:
            group["upcoming_cards"] += 1
    return result


async def indexed_coverage(connection, snapshot) -> list[dict]:
    """Keep metadata fresh and refuse an incomplete/permission-mismatched R2 set."""
    metadata = await connection.fetch(COVERAGE_METADATA_SQL)
    if not metadata:
        if snapshot.rows["reference_sets"]:
            raise ValueError("R2 reference sets are not visible to the current actor")
        return []
    today = _day(metadata[0]["source_today"])
    key = (snapshot.generation, snapshot.manifest_digest, today)
    if key not in _coverage_cache:
        _coverage_cache.clear()
        _coverage_cache[key] = build_coverage_counts(snapshot.rows, today)
    groups = _coverage_cache[key]
    keys = [(row["system_code"], row["provider"], row["language"]) for row in metadata]
    if len(set(keys)) != len(keys) or set(keys) != groups.keys():
        raise ValueError("R2 source sets differ from SQL-visible set groups")
    if any(_day(row["source_today"]) != today for row in metadata):
        raise ValueError("Source date changed during reference coverage")
    return [dict(groups[key], refreshed_at=row["refreshed_at"])
            for key, row in zip(keys, metadata, strict=True)]
