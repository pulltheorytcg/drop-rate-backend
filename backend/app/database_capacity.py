"""Read-only, plan-aware Supabase capacity preflight for catalogue refreshes.

PostgreSQL remains the source of truth. Do not offload, prune, delete, migrate
or rewrite price history to satisfy a quota. Supabase subscriptions are NOT
discoverable from PostgreSQL SQL; the runtime plan must be explicitly selected
only after independent verification and an approved Railway configuration edit.

The absent configuration defaults to the original Free safety thresholds.
"""
from __future__ import annotations

import os
from dataclasses import dataclass

FREE_DATABASE_LIMIT_BYTES = 500_000_000
FREE_REFRESH_PAUSE_BYTES = 400_000_000
FREE_URGENT_ALERT_BYTES = 450_000_000
PRO_DATABASE_INCLUDED_BYTES = 8_000_000_000
# Conservative independent headroom against the first 8 GB of Pro disk.
# The paid plan may allow larger disks for an additional fee, but this guard
# never silently approves billable growth beyond included storage.
PRO_REFRESH_PAUSE_BYTES = 7_000_000_000
PRO_URGENT_ALERT_BYTES = 7_500_000_000
PLAN_ENV = "DROP_RATE_SUPABASE_PLAN"
OPERATOR_BULK_HOLD_ENV = "DROP_RATE_CATALOGUE_BULK_HOLD"

# Backward-compatible aliases. Production remains Free-guarded unless the
# explicit runtime plan is set to "pro".
REFRESH_PAUSE_BYTES = FREE_REFRESH_PAUSE_BYTES
URGENT_ALERT_BYTES = FREE_URGENT_ALERT_BYTES

CAPACITY_SQL = """select pg_database_size(current_database())::bigint as database_bytes,
 current_setting('default_transaction_read_only') as default_read_only"""


@dataclass(frozen=True)
class CapacityState:
    database_bytes: int
    remaining_bytes: int
    severity: str
    refresh_allowed: bool
    reason: str
    plan: str = "free"
    database_limit_bytes: int = FREE_DATABASE_LIMIT_BYTES

    def report(self) -> dict:
        return {
            "database_bytes": self.database_bytes,
            # Preserve the historical key for existing monitor consumers;
            # its value is the EFFECTIVE plan limit, not always the Free cap.
            "free_limit_bytes": self.database_limit_bytes,
            "database_limit_bytes": self.database_limit_bytes,
            "database_plan": self.plan,
            "remaining_bytes": self.remaining_bytes,
            "severity": self.severity,
            "refresh_allowed": self.refresh_allowed,
            "reason": self.reason,
        }


def operator_bulk_hold_requested() -> bool:
    """Explicit, reversible production hold; never override capacity urgency.

    Keeps the daily maintenance loop alive for verified archive/backlog checks
    while refusing scheduled catalogue/price/media refresh operations.
    """
    raw = os.getenv(OPERATOR_BULK_HOLD_ENV, "false").strip().lower()
    if raw in {"true", "1"}:
        return True
    if raw in {"false", "0", ""}:
        return False
    raise ValueError("Invalid catalogue bulk-hold setting; refusing refresh")


def _limits(plan: str) -> tuple[int, int, int]:
    if plan == "free":
        return FREE_DATABASE_LIMIT_BYTES, FREE_REFRESH_PAUSE_BYTES, FREE_URGENT_ALERT_BYTES
    if plan == "pro":
        return PRO_DATABASE_INCLUDED_BYTES, PRO_REFRESH_PAUSE_BYTES, PRO_URGENT_ALERT_BYTES
    raise ValueError("Unknown Supabase capacity plan; refusing catalogue refresh")


def assess_capacity(
    database_bytes: int, default_read_only: str, *, plan: str | None = None,
) -> CapacityState:
    """Fail closed for unknown plan, invalid size, or a read-only DB.

    The plan is an explicitly reviewed deployment setting; a billing upgrade
    alone does not change this function's guard until Railway is updated.
    """
    if type(database_bytes) is not int or database_bytes < 0:
        raise ValueError("Database size must be a nonnegative integer")
    if default_read_only not in {"on", "off"}:
        raise ValueError("Database write-mode evidence missing")
    selected = (os.getenv(PLAN_ENV, "free") if plan is None else plan).strip().lower()
    limit, refresh_pause, urgent = _limits(selected)
    manually_held = operator_bulk_hold_requested()
    remaining = max(0, limit - database_bytes)
    if default_read_only == "on":
        severity, reason = "CRITICAL", "DATABASE_READ_ONLY"
    elif database_bytes >= urgent:
        severity, reason = "CRITICAL", ("FREE_DATABASE_CAPACITY_URGENT" if selected == "free" else "DATABASE_CAPACITY_URGENT")
    elif database_bytes >= refresh_pause:
        severity, reason = "WARNING", "BULK_REFRESH_DEFERRED_CAPACITY"
    elif manually_held:
        severity, reason = "WARNING", "BULK_REFRESH_DEFERRED_OPERATOR_HOLD"
    else:
        severity, reason = "OK", "WITHIN_SAFE_BULK_REFRESH_CAPACITY"
    return CapacityState(
        database_bytes, remaining, severity,
        reason == "WITHIN_SAFE_BULK_REFRESH_CAPACITY", reason, selected, limit,
    )


async def check_database_capacity(connection) -> CapacityState:
    row = await connection.fetchrow(CAPACITY_SQL)
    if row is None:
        raise ValueError("Database capacity not available")
    return assess_capacity(row["database_bytes"], row["default_read_only"])
