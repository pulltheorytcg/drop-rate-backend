"""Server-side admission for collection intake; not an AI probability estimate.

The threshold is inclusive at 0.95. Until a calibrated probabilistic matcher
exists, only a unique, complete exact catalogue identity has automatic
admission evidence. We never convert fuzzy similarity, CSV fields or an LLM's
self-reported confidence into a probability. Physical copies always start Draft.
"""
from __future__ import annotations

import hashlib
import json
from decimal import Decimal, InvalidOperation
from typing import Any, Mapping

AUTO_ADD_THRESHOLD = Decimal("0.95")
POLICY_VERSION = "exact-identity-v1"
IDENTITY_FIELDS = ("product_type", "game", "name", "set_name", "card_number", "variant", "language")


def clean(value: Any) -> str:
    return " ".join(str(value or "").split()).casefold()


def identity_fingerprint(catalogue: Mapping[str, Any]) -> str:
    return hashlib.sha256(json.dumps(
        {key: clean(catalogue.get(key)) for key in (*IDENTITY_FIELDS, "rarity")},
        sort_keys=True, separators=(",", ":"),
    ).encode()).hexdigest()


def meets_threshold(confidence: Any) -> bool:
    try:
        value = Decimal(str(confidence))
    except (InvalidOperation, ValueError, TypeError):
        return False
    return value.is_finite() and AUTO_ADD_THRESHOLD <= value <= 1


def exact_admission(normalized: dict, catalogue: dict | None, *, unique: bool) -> dict | None:
    if not catalogue or not unique:
        return None
    required = set(IDENTITY_FIELDS)
    if normalized.get("product_type") != "CARD":
        required.discard("card_number")
    if any(not clean(normalized.get(key)) or not clean(catalogue.get(key)) for key in required):
        return None
    if any(clean(normalized.get(key)) != clean(catalogue.get(key)) for key in required):
        return None
    if normalized.get("rarity") and catalogue.get("rarity") and clean(normalized["rarity"]) != clean(catalogue["rarity"]):
        return None
    if bool(normalized.get("grade")) != bool(normalized.get("grading_company")):
        return None
    return {
        "method": "EXACT_CATALOGUE_IDENTITY", "policy_version": POLICY_VERSION,
        "rule_confidence": 1.0, "calibrated_probability": None,
        "catalogue_id": str(catalogue["id"]),
        "identity_fingerprint": identity_fingerprint(catalogue),
    }


def manual_admission_valid(normalized: dict, catalogue: dict | None) -> bool:
    confirmation = normalized.get("import_identity_confirmation") or {}
    return bool(catalogue and confirmation.get("method") == "MANUAL"
                and confirmation.get("catalogue_id") == str(catalogue["id"])
                and confirmation.get("identity_fingerprint") == identity_fingerprint(catalogue))
