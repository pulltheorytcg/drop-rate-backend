from __future__ import annotations

import csv
import io
import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import Any


MAX_IMPORT_ROWS = 5000
MAX_PHYSICAL_UNITS = 10000
CARD_CONDITIONS = {
    "near mint": "Near Mint",
    "nm": "Near Mint",
    "lightly played": "Lightly Played",
    "lp": "Lightly Played",
    "moderately played": "Moderately Played",
    "mp": "Moderately Played",
    "heavily played": "Heavily Played",
    "hp": "Heavily Played",
    "damaged": "Damaged",
    "dmg": "Damaged",
}


@dataclass(frozen=True)
class ParsedImportRow:
    row_number: int
    raw_record: dict[str, str]
    normalized_record: dict[str, Any]
    issues: list[dict[str, str]]

    @property
    def has_error(self) -> bool:
        return any(issue["level"] == "ERROR" for issue in self.issues)

    @property
    def has_warning(self) -> bool:
        return any(issue["level"] == "WARNING" for issue in self.issues)


class ImportFormatError(ValueError):
    pass


def _issue(level: str, code: str, message: str) -> dict[str, str]:
    return {"level": level, "code": code, "message": message}


def _clean(value: Any) -> str:
    return str(value or "").strip()


def _optional(value: Any) -> str | None:
    cleaned = _clean(value)
    return cleaned or None


def _quantity(value: Any, issues: list[dict[str, str]]) -> int:
    raw = _clean(value) or "1"
    try:
        quantity = int(raw)
    except ValueError:
        issues.append(_issue("ERROR", "INVALID_QUANTITY", f"Quantity '{raw}' is not an integer."))
        return 1
    if quantity < 1 or quantity > 500:
        issues.append(_issue("ERROR", "INVALID_QUANTITY", "Quantity must be between 1 and 500."))
        return max(1, min(quantity, 500))
    return quantity


def _money_minor(
    value: Any,
    issues: list[dict[str, str]],
    *,
    field_label: str,
    zero_is_unknown: bool = False,
) -> int | None:
    raw = _clean(value).replace(",", "").replace("£", "")
    if not raw:
        return None
    try:
        amount = Decimal(raw)
    except InvalidOperation:
        issues.append(_issue("ERROR", "INVALID_MONEY", f"{field_label} '{raw}' is not a valid amount."))
        return None
    if amount < 0:
        issues.append(_issue("ERROR", "INVALID_MONEY", f"{field_label} cannot be negative."))
        return None
    minor = int((amount * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
    if zero_is_unknown and minor == 0:
        issues.append(
            _issue(
                "WARNING",
                "ZERO_COST_TREATED_AS_UNKNOWN",
                f"{field_label} was zero, so Drop Rate will keep acquisition cost unknown rather than record £0.",
            )
        )
        return None
    return minor


def _condition(value: Any, issues: list[dict[str, str]]) -> str | None:
    raw = _clean(value)
    if not raw:
        return None
    mapped = CARD_CONDITIONS.get(raw.casefold())
    if mapped is None:
        issues.append(
            _issue(
                "ERROR",
                "UNSUPPORTED_CONDITION",
                f"Condition '{raw}' is outside the Drop Rate / TCGplayer raw-card condition scale.",
            )
        )
    return mapped


def _grade(value: Any, issues: list[dict[str, str]]) -> tuple[str | None, str | None]:
    raw = _clean(value)
    if not raw or raw.casefold() in {"ungraded", "raw", "none", "n/a"}:
        return None, None
    match = re.match(r"^([A-Za-z0-9&.-]+)\s+(.+)$", raw)
    if not match:
        issues.append(
            _issue(
                "ERROR",
                "UNRECOGNISED_GRADE",
                f"Grade '{raw}' needs manual review because the grading company and grade cannot be separated safely.",
            )
        )
        return None, None
    return match.group(1).upper(), match.group(2).strip()


def _market_price_column(headers: list[str]) -> str | None:
    for header in headers:
        if header.casefold().startswith("market price (as of "):
            return header
    return None


def _collectr_row(row_number: int, row: dict[str, str], headers: list[str]) -> ParsedImportRow:
    issues: list[dict[str, str]] = []
    game = _clean(row.get("Category"))
    name = _clean(row.get("Product Name"))
    set_name = _clean(row.get("Set"))
    card_number = _optional(row.get("Card Number"))
    variant = _clean(row.get("Variance"))
    rarity = _clean(row.get("Rarity"))
    language = _optional(row.get("Language"))
    quantity = _quantity(row.get("Quantity"), issues)

    for label, value in (("Category/game", game), ("Product Name", name), ("Set", set_name)):
        if not value:
            issues.append(_issue("ERROR", "MISSING_IDENTITY", f"{label} is required."))

    product_type = "CARD" if card_number else "SEALED"
    raw_condition = _clean(row.get("Card Condition"))
    condition = _condition(raw_condition, issues) if product_type == "CARD" else None
    seal_status = None
    if product_type != "CARD":
        if raw_condition.casefold() == "sealed":
            seal_status = "SEALED"
        elif raw_condition.casefold() == "unsealed":
            seal_status = "UNSEALED"
        else:
            issues.append(
                _issue(
                    "WARNING",
                    "SEAL_STATUS_REQUIRED",
                    "This product has no card number, so it is treated as sealed merchandise and its sealed/unsealed state must be reviewed.",
                )
            )

    grading_company, grade = _grade(row.get("Grade"), issues) if product_type == "CARD" else (None, None)
    acquisition_cost_minor = _money_minor(
        row.get("Average Cost Paid"),
        issues,
        field_label="Average Cost Paid",
        zero_is_unknown=True,
    )
    override_minor = _money_minor(
        row.get("Price Override"),
        issues,
        field_label="Price Override",
        zero_is_unknown=True,
    )
    market_column = _market_price_column(headers)
    valuation_minor = _money_minor(
        row.get(market_column) if market_column else None,
        issues,
        field_label="Market Price",
    )

    normalized = {
        "product_type": product_type,
        "game": game,
        "name": name,
        "set_name": set_name,
        "card_number": card_number,
        "variant": variant,
        "rarity": rarity,
        "language": language,
        "quantity": quantity,
        "condition": condition,
        "seal_status": seal_status,
        "grading_company": grading_company,
        "grade": grade,
        "certificate_number": None,
        "acquisition_cost_minor": acquisition_cost_minor,
        "acquisition_date": None,
        "store_price_minor": None,
        "imported_valuation_minor": valuation_minor,
        "imported_price_override_minor": override_minor,
        "notes": _clean(row.get("Notes")),
    }
    return ParsedImportRow(row_number, dict(row), normalized, issues)


def _generic_row(row_number: int, row: dict[str, str]) -> ParsedImportRow:
    issues: list[dict[str, str]] = []
    lower = {str(key).strip().casefold(): value for key, value in row.items() if key is not None}

    def value(*names: str) -> str:
        for name in names:
            if name.casefold() in lower:
                return _clean(lower[name.casefold()])
        return ""

    game = value("game", "category")
    name = value("name", "product_name", "product name")
    set_name = value("set_name", "set", "set name")
    card_number = _optional(value("card_number", "card number", "number"))
    product_type = value("product_type", "product type").upper() or ("CARD" if card_number else "SEALED")
    if product_type not in {"CARD", "SEALED", "COLLECTION"}:
        issues.append(_issue("ERROR", "INVALID_PRODUCT_TYPE", f"Product type '{product_type}' is not supported."))
        product_type = "CARD" if card_number else "SEALED"

    for label, field_value in (("game", game), ("name", name), ("set_name", set_name)):
        if not field_value:
            issues.append(_issue("ERROR", "MISSING_IDENTITY", f"{label} is required."))
    if product_type == "CARD" and not card_number:
        issues.append(_issue("ERROR", "MISSING_IDENTITY", "card_number is required for card rows."))

    quantity = _quantity(value("quantity", "qty"), issues)
    condition = _condition(value("condition", "card_condition", "card condition"), issues) if product_type == "CARD" else None
    seal_status = _optional(value("seal_status", "seal status"))
    if seal_status:
        seal_status = seal_status.upper()
        if seal_status not in {"SEALED", "UNSEALED"}:
            issues.append(_issue("ERROR", "INVALID_SEAL_STATUS", "seal_status must be SEALED or UNSEALED."))
            seal_status = None

    grading_company = _optional(value("grading_company", "grading company"))
    grade = _optional(value("grade"))
    if (grading_company is None) != (grade is None):
        issues.append(_issue("ERROR", "INVALID_GRADE", "grading_company and grade must both be supplied or both be blank."))

    normalized = {
        "product_type": product_type,
        "game": game,
        "name": name,
        "set_name": set_name,
        "card_number": card_number,
        "variant": value("variant", "variance"),
        "rarity": value("rarity"),
        "language": _optional(value("language")),
        "quantity": quantity,
        "condition": condition,
        "seal_status": seal_status,
        "grading_company": grading_company.upper() if grading_company else None,
        "grade": grade,
        "certificate_number": _optional(value("certificate_number", "certificate number", "cert")),
        "acquisition_cost_minor": _money_minor(value("acquisition_cost", "acquisition cost", "cost"), issues, field_label="Acquisition cost", zero_is_unknown=True),
        "acquisition_date": _optional(value("acquisition_date", "acquisition date")),
        "store_price_minor": _money_minor(value("store_price", "store price"), issues, field_label="Store price"),
        "imported_valuation_minor": _money_minor(value("market_value", "market value", "valuation"), issues, field_label="Market value"),
        "imported_price_override_minor": None,
        "notes": value("notes"),
    }
    return ParsedImportRow(row_number, dict(row), normalized, issues)


def parse_import_csv(source: str, csv_text: str) -> list[ParsedImportRow]:
    if source in {"EBAY_PURCHASE_HISTORY", "HOLODEX"}:
        raise ImportFormatError(
            f"{source.replace('_', ' ').title()} adapter is reserved but needs a real export/sample before Drop Rate will map it automatically. Use Generic CSV only after converting to canonical headers."
        )

    text = csv_text.lstrip("\ufeff")
    reader = csv.DictReader(io.StringIO(text))
    if not reader.fieldnames:
        raise ImportFormatError("CSV has no header row.")
    headers = [str(header or "").strip().lstrip("\ufeff") for header in reader.fieldnames]
    if any(not header for header in headers):
        raise ImportFormatError("CSV contains a blank column header.")
    if len(headers) != len(set(header.casefold() for header in headers)):
        raise ImportFormatError("CSV contains duplicate column headers.")
    reader.fieldnames = headers

    if source == "COLLECTR":
        required = {"Category", "Product Name", "Set", "Quantity"}
        missing = sorted(required - set(headers))
        if missing:
            raise ImportFormatError(f"Collectr CSV is missing required columns: {', '.join(missing)}")

    parsed: list[ParsedImportRow] = []
    total_units = 0
    for row in reader:
        if not any(_clean(value) for value in row.values()):
            continue
        if len(parsed) >= MAX_IMPORT_ROWS:
            raise ImportFormatError(f"Imports are currently limited to {MAX_IMPORT_ROWS:,} non-empty rows per file.")
        row_number = len(parsed) + 1
        item = _collectr_row(row_number, row, headers) if source == "COLLECTR" else _generic_row(row_number, row)
        parsed.append(item)
        total_units += int(item.normalized_record["quantity"])
        if total_units > MAX_PHYSICAL_UNITS:
            raise ImportFormatError(f"Imports are currently limited to {MAX_PHYSICAL_UNITS:,} physical items per file.")

    if not parsed:
        raise ImportFormatError("CSV contains no non-empty inventory rows.")
    return parsed
