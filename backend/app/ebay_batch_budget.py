"""Quota-aware 50-day first-pass plan; no provider calls or database writes.

This is a deterministic shared planner, not a new scheduler/price engine.
A production runner must enforce real eBay Analytics remaining budget centrally
(not in each Lovable/Railway process) and persist durable cursors.
"""
from __future__ import annotations

from dataclasses import dataclass
from math import ceil, isfinite
from typing import Any, Iterable, Mapping


@dataclass(frozen=True)
class DailyBatchPlan:
    catalog_size_remaining: int
    target_days: int
    target_items_per_day: int
    allowed_browse_calls: int
    used_browse_calls_today: int
    reserved_browse_calls: int
    available_browse_calls: int
    observed_calls_per_item: float
    estimated_daily_item_capacity: int
    scheduled_items: int
    estimated_days_at_current_rate: int | None
    calls_per_item_needed_for_target: float
    fifty_day_target_feasible: bool
    state: str


def plan_daily_batch(
    *, remaining: int, actual_daily_limit: int,
    used_today: int, reserved_for_app: int,
    measured_calls_per_item: float, target_days: int = 50,
) -> DailyBatchPlan:
    """Plan bounded work from quota actually available to all app users.

    The daily limit must come from authorised account analytics or an explicit
    conservative setting, never an assumed unlimited allowance.
    """
    for label, value in (("remaining", remaining), ("actual_daily_limit", actual_daily_limit),
                         ("used_today", used_today), ("reserved_for_app", reserved_for_app),
                         ("target_days", target_days)):
        if type(value) is not int or value < 0:
            raise ValueError(f"{label} must be a nonnegative integer")
    if target_days == 0:
        raise ValueError("target_days must be positive")
    if not isinstance(measured_calls_per_item, (int, float)) or not isfinite(measured_calls_per_item) or measured_calls_per_item < 1:
        raise ValueError("measured_calls_per_item must be finite and >=1")
    available = max(0, actual_daily_limit - used_today - reserved_for_app)
    capacity = int(available // float(measured_calls_per_item))
    required = ceil(remaining / target_days)
    scheduled = min(required, capacity)
    estimated_days = ceil(remaining / capacity) if capacity and remaining else (0 if not remaining else None)
    return DailyBatchPlan(
        catalog_size_remaining=remaining,
        target_days=target_days,
        target_items_per_day=required,
        allowed_browse_calls=actual_daily_limit,
        used_browse_calls_today=used_today,
        reserved_browse_calls=reserved_for_app,
        available_browse_calls=available,
        observed_calls_per_item=float(measured_calls_per_item),
        estimated_daily_item_capacity=capacity,
        scheduled_items=scheduled,
        estimated_days_at_current_rate=estimated_days,
        calls_per_item_needed_for_target=round(available / required, 3) if required else 0,
        fifty_day_target_feasible=capacity >= required,
        state="COMPLETE" if not remaining else "NO_AVAILABLE_QUOTA" if not capacity else "WITHIN_TARGET" if capacity >= required else "MORE_DAYS_OR_MORE_QUOTA_REQUIRED",
    )


def prioritize_refresh_items(
    rows: Iterable[Mapping[str, Any]], *, limit: int,
) -> list[dict[str, Any]]:
    """Deterministic identities, not duplicate inventory copies.

    No DB/network writes. The production cursor must persist independently.
    Unpriced and never-checked identities lead, then stalest checked values.
    """
    if type(limit) is not int or limit < 0 or limit > 50_000:
        raise ValueError("limit must be between 0 and 50000")
    unique: dict[str, dict[str, Any]] = {}
    for row in rows:
        key = str(row.get("pricing_identity") or "").strip()
        if not key:
            continue
        if row.get("review_status") in {"IDENTITY_CONFLICT", "UNVERIFIED", "REJECTED"}:
            continue
        new = dict(row)
        if key not in unique:
            unique[key] = new
        else:
            if _sort_key(new) < _sort_key(unique[key]):
                unique[key] = new
    return sorted(unique.values(), key=_sort_key)[:limit]


def _sort_key(row: Mapping[str, Any]) -> tuple:
    missing_value = row.get("market_value_minor") is None
    last_checked = str(row.get("last_checked_at") or "")
    return (
        0 if missing_value else 1,
        0 if not last_checked else 1,
        last_checked,
        str(row.get("pricing_identity") or ""),
    )
