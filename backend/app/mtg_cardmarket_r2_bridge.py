"""Bounded read-only bridge: verified R2 Magic printings -> Cardmarket pilot identities.

The R2 catalogue is the source of the card's canonical UUID, set, name, finish
and optional, exact MTGJSON mcmId. This module does NOT fetch or publish prices.
Use its output with cardmarket_public_pilot.read_only_mtg_pilot: that selector
quarantines shared MCM IDs and requires corroborated Cardmarket expansion IDs.
"""
from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Mapping
from uuid import UUID

from .r2_first_catalogue import MAX_ROWS as MAX_R2_ROWS

SYSTEM = "MAGIC_THE_GATHERING"
PROVIDER = "mtgjson"
_ALLOWED_FINISHES = frozenset({"nonfoil", "foil"})
MAX_ROWS = MAX_R2_ROWS


class IdentityBridgeError(ValueError):
    """Mismatched or oversized verified catalogue scope."""


def _uuid_from_id(provider_id: object, finish: object) -> str:
    if type(provider_id) is not str or type(finish) is not str:
        raise IdentityBridgeError("Missing exact R2 printing finish")
    prefix = "mtgjson:"
    suffix = ":" + finish
    if not provider_id.startswith(prefix) or not provider_id.endswith(suffix):
        raise IdentityBridgeError("R2 printing/provider ID disagreement")
    try:
        value = str(UUID(provider_id[len(prefix):-len(suffix)]))
    except (ValueError, AttributeError) as exc:
        raise IdentityBridgeError("Invalid exact MTGJSON source UUID") from exc
    if provider_id != prefix + value + suffix:
        raise IdentityBridgeError("Noncanonical R2 printing ID")
    return value


def _mcm_id(details: object) -> str | None:
    if not isinstance(details, dict):
        return None
    value = details.get("cardmarket_product_id")
    if type(value) is not str or not value.isascii() or not value.isdecimal() or value.startswith("0"):
        return None
    number = int(value)
    return value if 0 < number <= 2**31 - 1 else None


def cards_from_verified_r2(rows: Iterable[Mapping]) -> dict:
    """Read-only grouping: same UUID must have stable set/name/Cardmarket ID.

    Unsafe/conflicting source cross-references are withheld from the pricing
    pilot, never silently resolved by source order or a card name match.
    """
    if not isinstance(rows, Iterable) or isinstance(rows, (str, bytes, dict)):
        raise IdentityBridgeError("Expected bounded verified catalogue rows")
    groups: dict[str, dict] = {}
    quarantined: set[str] = set()
    examined = 0
    eligible_finish_rows = 0
    no_external_id = 0
    for item in rows:
        examined += 1
        if examined > MAX_ROWS:
            raise IdentityBridgeError("R2 source exceeds bounded record count")
        if not isinstance(item, Mapping):
            raise IdentityBridgeError("Invalid catalogue row")
        if (item.get("provider") != PROVIDER or item.get("system_code") != SYSTEM
                or item.get("language") != "English" or item.get("product_type") != "CARD"):
            raise IdentityBridgeError("Unexpected catalogue source scope")
        finish = item.get("finish")
        uid = _uuid_from_id(item.get("provider_id"), finish)
        if uid in quarantined:
            continue
        if finish not in _ALLOWED_FINISHES:
            continue
        eligible_finish_rows += 1
        external = _mcm_id(item.get("details"))
        if external is None:
            no_external_id += 1
            continue
        name = item.get("name")
        set_name = item.get("set_name")
        if not isinstance(name, str) or not name.strip() or not isinstance(set_name, str) or not set_name.strip():
            raise IdentityBridgeError("Missing original name/set evidence")
        candidate = {"uuid": uid, "name": name, "set_name": set_name,
                     "language": "English", "paper": True,
                     "identifiers": {"mcmId": external}, "finishes": set()}
        previous = groups.get(uid)
        if previous is None:
            groups[uid] = candidate
            previous = candidate
        elif (previous["name"] != name or previous["set_name"] != set_name
              or previous["identifiers"]["mcmId"] != external
              or finish in previous["finishes"]):
            quarantined.add(uid)
            groups.pop(uid, None)
            continue
        previous["finishes"].add(finish)
    accepted = []
    for uid, group in sorted(groups.items()):
        finishes = sorted(group["finishes"])
        if finishes:
            accepted.append({**group, "finishes": finishes})
    return {"status": "IDENTITY_ONLY_NO_PRICE_PUBLICATION",
            "input_rows": examined, "eligible_finish_rows": eligible_finish_rows,
            "missing_external_id_rows": no_external_id,
            "quarantined_uuid_groups": len(quarantined),
            "exact_mcm_groups": len(accepted),
            "cards": accepted, "verified_sold_values": 0,
            "database_writes": 0, "r2_writes": 0, "shopify_writes": 0}


def cards_from_snapshot(snapshot) -> dict:
    """Page a verified R2 Snapshot without reading PostgreSQL or editing R2."""
    if snapshot.provider != PROVIDER or snapshot.system_code != SYSTEM or snapshot.language != "English":
        raise IdentityBridgeError("Wrong catalogue partition")
    if type(snapshot.record_count) is not int or not 0 < snapshot.record_count <= MAX_ROWS:
        raise IdentityBridgeError("Oversized catalogue snapshot")
    def page_rows():
        offset = 0
        while offset < snapshot.record_count:
            result = snapshot.search(limit=min(100, snapshot.record_count-offset),
                                     offset=offset, include_upcoming=True)
            batch = result.get("items")
            if not isinstance(batch, list) or len(batch) != min(100,snapshot.record_count-offset):
                raise IdentityBridgeError("Incomplete verified R2 pagination")
            if result.get("total") != snapshot.record_count:
                raise IdentityBridgeError("R2 snapshot count drift")
            yield from batch
            offset += len(batch)
    result = cards_from_verified_r2(page_rows())
    if result["input_rows"] != snapshot.record_count:
        raise IdentityBridgeError("R2 snapshot total changed")
    return result
