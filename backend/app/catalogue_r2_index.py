"""Railway-local immutable indexes for already SHA-verified R2 catalogue rows.

Indices are process-local pointers to the loaded, public shared catalogue
projection. They never carry owner data, prices, media permissions or secrets.
PostgreSQL still decides row-level authorization and mutable overlays.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class SharedReferenceIndex:
    """Exact provider/game/language/set and game lookups.

    Building the index once after R2 readback avoids a Python scan of ~70k
    references for *each* exact-set or game-scoped catalogue request.
    This does not try to shortcut global searches/owner/value sorting.
    """

    by_system: dict[str, dict[str, tuple[dict, ...]]]
    by_scope: dict[str, dict[tuple[str, str, str, str], tuple[dict, ...]]]

    @classmethod
    def build(cls, rows_by_table: dict[str, list[dict]]) -> "SharedReferenceIndex":
        by_system = {}
        by_scope = {}
        for table, rows in rows_by_table.items():
            if not table.startswith("reference_"):
                continue
            systems = defaultdict(list)
            scopes = defaultdict(list)
            for row in rows:
                # Parse/manifest validation occurs before this function. Keep
                # every printing including numbered parallels and alternate art.
                systems[row["system_code"]].append(row)
                scopes[(
                    row["provider"], row["system_code"], row["language"], row["set_id"]
                )].append(row)
            by_system[table] = {k: tuple(v) for k, v in systems.items()}
            by_scope[table] = {k: tuple(v) for k, v in scopes.items()}
        return cls(by_system, by_scope)

    def select(
        self,
        table: str,
        original: list[dict],
        *,
        systems: list[str] | tuple[str, ...] | None = None,
        language: str = "",
        provider: str | None = None,
        set_id: str = "",
    ) -> list[dict] | tuple[dict, ...]:
        """Identical reference input population to the original SQL adapter.

        No query-level filtering of name, rarity, physical price or owner:
        pruning those fields before exact-links are built can resurrect
        canonical duplicates and must be done in a separate proven cutover.
        """
        if not table.startswith("reference_"):
            return original
        # Empty systems is intentionally equivalent to no system restriction.
        system_values = tuple(dict.fromkeys(systems or ()))
        if (provider is not None and len(system_values) == 1
                and language and set_id):
            return self.by_scope.get(table, {}).get(
                (provider, system_values[0], language, set_id), ()
            )
        if system_values:
            data = (row for system in system_values
                    for row in self.by_system.get(table, {}).get(system, ()))
        else:
            data = iter(original)
        return [
            row for row in data
            if (not language or row["language"] == language)
            and (provider is None or row["provider"] == provider)
            and (not set_id or row["set_id"] == set_id)
        ]
