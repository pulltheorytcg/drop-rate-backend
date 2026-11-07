"""Conservative presentation of slab evidence; never approves identity or stock.

Literal labels and provider receipts are preserved. Unsupported translations,
qualifiers and uncertain digits are not repaired or guessed here.
"""
from __future__ import annotations

import re
import unicodedata
from decimal import Decimal, InvalidOperation
from typing import Mapping, Any


def evidence_key(value: object) -> str:
    return "".join(c for c in unicodedata.normalize("NFKC", str(value or "")).casefold() if c.isalnum())


def grade_value(grader: str, label: str | None) -> str | None:
    """Map an unambiguous printed grade to an existing picker value, not a new grade."""
    company = str(grader or "").upper()
    if company not in {"PSA", "ACE", "CGC", "BGS", "BVG", "BCCG", "TAG"}:
        return None
    text = re.sub(r"\s+", " ", str(label or "").upper()).strip()
    if company == "BGS" and re.fullmatch(r"(?:10(?:\.0)? BLACK LABEL|BLACK LABEL 10(?:\.0)?)", text):
        return "10 BLACK LABEL"
    if company == "BGS" and re.fullmatch(r"(?:PRISTINE 10(?:\.0)?|10(?:\.0)? PRISTINE)", text):
        return "10"
    if company in {"CGC", "TAG"} and re.fullmatch(r"(?:PRISTINE 10(?:\.0)?|10(?:\.0)? PRISTINE)", text):
        return "Pristine 10"
    # Do not strip qualifiers (OC, altered, authentic) or collapse Black Label
    # and Pristine into ordinary 10. No other numbers on the label are searched.
    match = re.fullmatch(r"(?:(?:GEM MT|GEM MINT|MINT|NEAR MINT|NM-MT|NM|EX-MT|EX|VG-EX|VG|GOOD|FAIR|POOR|GRADE)\s+)?(\d{1,2}(?:\.[05])?)", text)
    if not match:
        return None
    try:
        value = Decimal(match.group(1))
    except InvalidOperation:
        return None
    if not 1 <= value <= 10 or value * 2 != (value * 2).to_integral_value():
        return None
    if company in {"ACE", "TAG", "BCCG"} and value != value.to_integral_value():
        return None
    if company == "BCCG" and value < 5 or company == "PSA" and value == Decimal("9.5"):
        return None
    # A contradictory descriptive/numeric grade needs a person, not a conversion.
    if text.startswith(("GEM MT ", "GEM MINT ")):
        accepted = {Decimal("9.5")} if company == "BGS" else {Decimal("9.5"), Decimal("10")} if company == "CGC" else {Decimal("10")}
        if value not in accepted:
            return None
    return format(value.normalize(), "f")


def card_numbers_agree(label: str, candidate: str) -> bool:
    """A slab may omit the denominator, but a supplied denominator must agree."""
    left, right = str(label or "").strip().lstrip("#"), str(candidate or "").strip().lstrip("#")
    if not left or not right:
        return False
    if evidence_key(left) == evidence_key(right):
        return True
    if re.fullmatch(r"\d+", left) and re.fullmatch(r"\d+\s*/\s*\d+", right):
        return left == right.split("/")[0].strip()
    return False


def slab_candidate_supported(row: Mapping[str, Any], *, card_name: str, card_number: str, set_name: str) -> bool:
    """Filter *suggestions*, not verification. Never accept a bare shared number.

    Cross-script names without a verified alias do not corroborate each other.
    An exact set name/code can corroborate an otherwise untranslated name;
    a contradictory same-script name still rejects the suggestion.
    """
    if row.get("product_type") != "CARD" or not card_numbers_agree(card_number, row.get("card_number", "")):
        return False
    name_key, candidate_name = evidence_key(card_name), evidence_key(row.get("name"))
    name_match = bool(name_key and candidate_name and name_key == candidate_name)
    def latin_only(value):
        letters = [c for c in value if c.isalpha()]
        return bool(letters) and all("LATIN" in unicodedata.name(c, "") for c in letters)
    if name_key and candidate_name and latin_only(name_key) == latin_only(candidate_name) and not name_match:
        return False
    set_key = evidence_key(set_name)
    set_match = bool(set_key and set_key in {evidence_key(row.get("set_name")), evidence_key(row.get("set_id"))})
    if set_key and not set_match:
        # Names may be abbreviated/translated on a slab. They are unresolved,
        # not evidence that the first result from another set is a match.
        return False
    return name_match or set_match
