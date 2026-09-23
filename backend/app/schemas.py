from __future__ import annotations

from datetime import date
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field, model_validator


InventoryStatus = Literal["DRAFT", "INSPECTION", "APPROVED", "WITHDRAWN"]
EditableInventoryStatus = Literal["DRAFT", "INSPECTION", "WITHDRAWN"]
AllocationMethod = Literal["MANUAL", "EQUAL", "VALUE_WEIGHTED"]
SealStatus = Literal["SEALED", "UNSEALED"]
ReadinessIssue = Literal[
    "missing_cost",
    "missing_condition",
    "missing_location",
    "missing_price",
    "identity_unconfirmed",
    "approval_ready",
]


class InventoryPatch(BaseModel):
    version: int = Field(ge=1)
    acquisition_cost_minor: int | None = Field(default=None, ge=0)
    acquisition_date: date | None = None
    condition: str | None = Field(default=None, max_length=80)
    seal_status: SealStatus | None = None
    grading_company: str | None = Field(default=None, max_length=40)
    grade: str | None = Field(default=None, max_length=40)
    certificate_number: str | None = Field(default=None, max_length=120)
    language: str | None = Field(default=None, max_length=80)
    location: str | None = Field(default=None, max_length=160)
    store_price_minor: int | None = Field(default=None, ge=0)
    identity_confirmed: bool | None = None
    status: EditableInventoryStatus | None = None
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


class InventoryApproval(BaseModel):
    version: int = Field(ge=1)


class BulkCostItem(BaseModel):
    inventory_id: UUID
    version: int = Field(ge=1)
    acquisition_cost_minor: int = Field(ge=0)


class BulkCostAllocation(BaseModel):
    total_cost_minor: int = Field(ge=0)
    acquisition_date: date | None = None
    items: list[BulkCostItem] = Field(min_length=2, max_length=500)

    @model_validator(mode="after")
    def validate_allocation(self) -> "BulkCostAllocation":
        ids = [item.inventory_id for item in self.items]
        if len(ids) != len(set(ids)):
            raise ValueError("Each inventory item may appear only once")
        allocated = sum(item.acquisition_cost_minor for item in self.items)
        if allocated != self.total_cost_minor:
            raise ValueError("Allocated item costs must exactly match the total cost")
        return self


class PurchaseLotCreate(BaseModel):
    description: str = Field(min_length=1, max_length=200)
    source: str | None = Field(default=None, max_length=160)
    purchase_date: date | None = None
    purchase_price_minor: int = Field(ge=0)
    fees_minor: int = Field(default=0, ge=0)
    shipping_minor: int = Field(default=0, ge=0)
    currency: str = Field(default="GBP", min_length=3, max_length=3)
    allocation_method: AllocationMethod = "MANUAL"
    notes: str = Field(default="", max_length=2000)
    items: list[BulkCostItem] = Field(default_factory=list, max_length=500)

    @model_validator(mode="after")
    def validate_purchase_lot(self) -> "PurchaseLotCreate":
        self.description = self.description.strip()
        self.source = self.source.strip() if self.source else None
        self.currency = self.currency.upper().strip()
        self.notes = self.notes.strip()
        if not self.description:
            raise ValueError("description cannot be blank")
        ids = [item.inventory_id for item in self.items]
        if len(ids) != len(set(ids)):
            raise ValueError("Each inventory item may appear only once")
        landed_cost = self.purchase_price_minor + self.fees_minor + self.shipping_minor
        allocated = sum(item.acquisition_cost_minor for item in self.items)
        if allocated > landed_cost:
            raise ValueError("Allocated item costs cannot exceed the landed purchase cost")
        return self


class PurchaseLotAllocation(BaseModel):
    version: int = Field(ge=1)
    items: list[BulkCostItem] = Field(min_length=1, max_length=500)

    @model_validator(mode="after")
    def validate_items(self) -> "PurchaseLotAllocation":
        ids = [item.inventory_id for item in self.items]
        if len(ids) != len(set(ids)):
            raise ValueError("Each inventory item may appear only once")
        return self
