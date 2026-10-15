"""Read-only Free-plan capacity preflight for unattended catalogue imports.

The price-history archive is verified externally before reclamation. This
guard NEVER truncates, archives, prunes or suppresses committed evidence.
"""
from __future__ import annotations

from dataclasses import dataclass

# Current Drop Rate Supabase organisation is on Free (500 MB database).
# These are decimal MB; leave 100 MB before the official quota boundary.
FREE_DATABASE_LIMIT_BYTES = 500_000_000
REFRESH_PAUSE_BYTES = 400_000_000
URGENT_ALERT_BYTES = 450_000_000

CAPACITY_SQL = """select pg_database_size(current_database())::bigint as database_bytes,
 current_setting('default_transaction_read_only') as default_read_only"""


@dataclass(frozen=True)
class CapacityState:
    database_bytes: int
    remaining_bytes: int
    severity: str
    refresh_allowed: bool
    reason: str

    def report(self) -> dict:
        return {
            "database_bytes": self.database_bytes,
            "free_limit_bytes": FREE_DATABASE_LIMIT_BYTES,
            "remaining_bytes": self.remaining_bytes,
            "severity": self.severity,
            "refresh_allowed": self.refresh_allowed,
            "reason": self.reason,
        }


def assess_capacity(database_bytes: int, default_read_only: str) -> CapacityState:
    """Fail closed for capacity uncertainty, or a read-only database."""
    if type(database_bytes) is not int or database_bytes < 0:
        raise ValueError("Database size must be a nonnegative integer")
    if default_read_only not in {"on", "off"}:
        raise ValueError("Database write-mode evidence missing")
    remaining = max(0, FREE_DATABASE_LIMIT_BYTES - database_bytes)
    if default_read_only == "on":
        severity, reason = "CRITICAL", "DATABASE_READ_ONLY"
    elif database_bytes >= URGENT_ALERT_BYTES:
        severity, reason = "CRITICAL", "FREE_DATABASE_CAPACITY_URGENT"
    elif database_bytes >= REFRESH_PAUSE_BYTES:
        severity, reason = "WARNING", "BULK_REFRESH_DEFERRED_CAPACITY"
    else:
        severity, reason = "OK", "WITHIN_SAFE_BULK_REFRESH_CAPACITY"
    return CapacityState(database_bytes, remaining, severity, reason == "WITHIN_SAFE_BULK_REFRESH_CAPACITY", reason)


async def check_database_capacity(connection) -> CapacityState:
    row = await connection.fetchrow(CAPACITY_SQL)
    if row is None:
        raise ValueError("Database capacity not available")
    return assess_capacity(row["database_bytes"], row["default_read_only"])
