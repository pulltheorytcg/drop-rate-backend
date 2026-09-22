from __future__ import annotations

from datetime import date
from typing import Literal

from pydantic import BaseModel, Field, model_validator


InventoryStatus = Literal["DRAFT", "INSPECTION", "WITHDRAWN"]


class InventoryPatch(BaseModel):
    version: int = Field(ge=1)
    acquisition_cost_minor: int | None = Field(default=None, ge=0)
    acquisition_date: date | None = None
    condition: str | None = Field(default=None, max_length=80)
    grading_company: str | None = Field(default=None, max_length=40)
    grade: str | None = Field(default=None, max_length=40)
    certificate_number: str | None = Field(default=None, max_length=120)
    language: str | None = Field(default=None, max_length=80)
    location: str | None = Field(default=None, max_length=160)
    store_price_minor: int | None = Field(default=None, ge=0)
    identity_confirmed: bool | None = None
    status: InventoryStatus | None = None
    notes: str | None = Field(default=None, max_length=2000)

    @model_validator(mode="after")
    def validate_grading_pair(self) -> "InventoryPatch":
        supplied = self.model_fields_set
        company_set = "grading_company" in supplied
        grade_set = "grade" in supplied
        if company_set != grade_set:
            raise ValueError("grading_company and grade must be updated together")
        if company_set and ((self.grading_company is None) != (self.grade is None)):
            raise ValueError("grading_company and grade must both be set or both cleared")
        return self
