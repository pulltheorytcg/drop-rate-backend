"""Explicit corrections to a pending imported card, never its source snapshot."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .physical_state import validate_physical_state


CARD_DETAIL_ISSUES = frozenset({
    "unrecognised_card_condition", "unrecognised_collectr_grade",
    "incomplete_grading_pair", "certificate_without_grade",
})


class ImportCardDetails(BaseModel):
    model_config = ConfigDict(extra="forbid")

    card_state: Literal["RAW", "GRADED"]
    condition: str | None = Field(default=None, max_length=80)
    grading_company: str | None = Field(default=None, max_length=40)
    grade: str | None = Field(default=None, max_length=40)
    certificate_number: str | None = Field(default=None, max_length=120)

    @field_validator("condition", "grading_company", "grade", "certificate_number")
    @classmethod
    def clean_text(cls, value):
        return value.strip() or None if value is not None else None

    @model_validator(mode="after")
    def validate_card(self):
        if self.card_state == "GRADED" and not (self.grading_company and self.grade):
            raise ValueError("Enter the grading company and grade from the slab label")
        if self.card_state == "RAW" and any((self.grading_company, self.grade, self.certificate_number)):
            raise ValueError("Ungraded cards cannot have slab details")
        validate_physical_state(product_type="CARD", seal_status=None,
                                **self.model_dump(exclude={"card_state"}))
        return self


def apply_card_details(normalized: dict, issues: set[str], details: ImportCardDetails,
                       *, quantity: int) -> tuple[dict, set[str]]:
    if normalized.get("product_type") != "CARD":
        raise ValueError("Card condition and grading corrections only apply to single cards")
    if details.certificate_number and quantity != 1:
        raise ValueError("A certificate identifies one slab. Split this source row into individual slabs before importing certificates")
    corrected = {**normalized, **details.model_dump(exclude={"card_state"})}
    validate_physical_state(product_type="CARD", seal_status=corrected.get("seal_status"),
                            **details.model_dump(exclude={"card_state"}))
    # Quantity, cost, language conflicts and snapshot decreases stay unresolved.
    # raw_record and _collectr_source_identity are never rewritten here.
    return corrected, issues - CARD_DETAIL_ISSUES
