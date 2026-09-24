from __future__ import annotations

import hashlib
import json
import re
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import Any


_GRADE_RE = re.compile(r"^(PSA|ACE|CGC|BGS|BECKETT)\s+([0-9]+(?:\.[0-9]+)?)\b", re.IGNORECASE)


def clean_text(value: object) -> str:
    return " ".join(str(value or "").strip().split())


def normalise_text(value: object) -> str:
    return clean_text(value).casefold()


def collectr_adapter_headers(headers: list[str]) -> bool:
    keys = {normalise_text(header).replace("_", " ").replace("-", " ") for header in headers}
    return (
        "portfolio name" in keys
        and "variance" in keys
        and "quantity" in keys
        and ("average cost paid" in keys or any(key.startswith("market price ") for key in keys))
    )


def collectr_product_type(*, name: str | None, card_number: str | None, rarity: str | None) -> str:
    if clean_text(card_number):
        return "CARD"
    clean_name = normalise_text(name)
    clean_rarity = normalise_text(rarity)
    if clean_rarity == "don!!" or clean_name.startswith("don!! card"):
        return "CARD"
    if "collection" in clean_name or "tin pack set" in clean_name:
        return "COLLECTION"
    return "CARD"


def collectr_grade(value: str | None) -> tuple[str | None, str | None, list[str]]:
    text = clean_text(value)
    if not text or text.casefold() == "ungraded":
        return None, None, []
    match = _GRADE_RE.match(text)
    if not match:
        return None, None, ["unrecognised_collectr_grade"]
    company = match.group(1).upper()
    if company == "BECKETT":
        company = "BGS"
    try:
        numeric = Decimal(match.group(2))
    except InvalidOperation:
        return None, None, ["unrecognised_collectr_grade"]
    grade = format(numeric.normalize(), "f")
    return company, grade, []


def collectr_cost_minor(value: str | None) -> tuple[int | None, list[str]]:
    text = clean_text(value)
    if not text:
        return None, []
    try:
        amount = Decimal(text.replace("£", "").replace(",", ""))
    except InvalidOperation:
        return None, ["invalid_purchase_cost"]
    if amount < 0:
        return None, ["invalid_purchase_cost"]
    if amount == 0:
        return None, []
    return int((amount * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP)), []


def collectr_snapshot_key(normalized: dict[str, Any]) -> tuple[str, ...]:
    return tuple(
        normalise_text(normalized.get(field))
        for field in (
            "product_type",
            "game",
            "set_name",
            "name",
            "card_number",
            "rarity",
            "variant",
            "grading_company",
            "grade",
            "condition",
        )
    )


def collectr_catalogue_identity_key(normalized: dict[str, Any]) -> str:
    payload = {
        "product_type": clean_text(normalized.get("product_type")).upper(),
        "game": normalise_text(normalized.get("game")),
        "name": normalise_text(normalized.get("name")),
        "set_name": normalise_text(normalized.get("set_name")),
        "card_number": normalise_text(normalized.get("card_number")),
        "variant": normalise_text(normalized.get("variant")),
        "rarity": normalise_text(normalized.get("rarity")),
        "language": normalise_text(normalized.get("language")),
    }
    digest = hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    return f"collectr:v1:{digest}"
