from __future__ import annotations

from datetime import date
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field, model_validator


InventoryStatus = Literal["DRAFT", "INSPECTION", "APPROVED", "WITHDRAWN"]
EditableInventoryStatus = Literal["DRAFT", "INSPECTION", "WITHDRAWN"]
SaleIntent = Literal["FOR_SALE", "PERSONAL_COLLECTION"]
AllocationMethod = Literal["MANUAL", "EQUAL", "VALUE_WEIGHTED"]
SealStatus = Literal["SEALED", "UNSEALED"]
StorageLocationType = Literal["BINDER", "BOX", "SHELF", "DRAWER", "VAULT", "DISPLAY", "OTHER"]
CatalogueProductType = Literal["CARD", "SEALED", "COLLECTION", "COMIC", "ACCESSORY"]
ReadinessIssue = Literal[
    "missing_cost",
    "missing_condition",
    "missing_seal_status",
    "missing_location",
    "missing_language",
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
    storage_location_id: UUID | None = None
    store_price_minor: int | None = Field(default=None, ge=100)
    identity_confirmed: bool | None = None
    status: EditableInventoryStatus | None = None
    notes: str | None = Field(default=None, max_length=2000)

    @model_validator(mode="after")
    def validate_grading_pair(self) -> "InventoryPatch":
        supplied = self.model_fields_set
        if "identity_confirmed" in supplied:
            raise ValueError("Identity confirmation must use the Verify workflow")
        company_set = "grading_company" in supplied
        grade_set = "grade" in supplied
        if company_set != grade_set:
            raise ValueError("grading_company and grade must be updated together")
        if company_set and ((self.grading_company is None) != (self.grade is None)):
            raise ValueError("grading_company and grade must both be set or both cleared")
        return self


class InventoryApproval(BaseModel):
    version: int = Field(ge=1)


class InventorySaleIntentChange(BaseModel):
    version: int = Field(ge=1)
    sale_intent: SaleIntent


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


class PurchaseLotPatch(BaseModel):
    version: int = Field(ge=1)
    description: str | None = Field(default=None, max_length=200)
    source: str | None = Field(default=None, max_length=160)
    purchase_date: date | None = None
    purchase_price_minor: int | None = Field(default=None, ge=0)
    fees_minor: int | None = Field(default=None, ge=0)
    shipping_minor: int | None = Field(default=None, ge=0)
    currency: str | None = Field(default=None, min_length=3, max_length=3)
    allocation_method: AllocationMethod | None = None
    notes: str | None = Field(default=None, max_length=2000)

    @model_validator(mode="after")
    def validate_patch(self) -> "PurchaseLotPatch":
        supplied = self.model_fields_set - {"version"}
        if not supplied:
            raise ValueError("At least one purchase lot field is required")
        if "description" in supplied:
            if self.description is None or not self.description.strip():
                raise ValueError("description cannot be blank")
            self.description = self.description.strip()
        if "source" in supplied and self.source is not None:
            self.source = self.source.strip() or None
        if "currency" in supplied:
            if self.currency is None:
                raise ValueError("currency cannot be blank")
            self.currency = self.currency.upper().strip()
        if "notes" in supplied:
            self.notes = (self.notes or "").strip()
        for field_name in ("purchase_price_minor", "fees_minor", "shipping_minor"):
            if field_name in supplied and getattr(self, field_name) is None:
                raise ValueError(f"{field_name} cannot be blank")
        if "allocation_method" in supplied and self.allocation_method is None:
            raise ValueError("allocation_method cannot be blank")
        return self


class PurchaseLotDetach(BaseModel):
    version: int = Field(ge=1)
    inventory_version: int = Field(ge=1)


class PurchaseLotAllocation(BaseModel):
    version: int = Field(ge=1)
    items: list[BulkCostItem] = Field(min_length=1, max_length=500)

    @model_validator(mode="after")
    def validate_items(self) -> "PurchaseLotAllocation":
        ids = [item.inventory_id for item in self.items]
        if len(ids) != len(set(ids)):
            raise ValueError("Each inventory item may appear only once")
        return self


class StorageLocationCreate(BaseModel):
    code: str = Field(min_length=2, max_length=80)
    label: str = Field(min_length=1, max_length=160)
    location_type: StorageLocationType
    notes: str = Field(default="", max_length=1000)

    @model_validator(mode="after")
    def normalise(self) -> "StorageLocationCreate":
        self.code = self.code.upper().strip()
        self.label = self.label.strip()
        self.notes = self.notes.strip()
        if not self.label:
            raise ValueError("label cannot be blank")
        return self


class StorageLocationPatch(BaseModel):
    version: int = Field(ge=1)
    label: str | None = Field(default=None, max_length=160)
    location_type: StorageLocationType | None = None
    active: bool | None = None
    notes: str | None = Field(default=None, max_length=1000)

    @model_validator(mode="after")
    def validate_patch(self) -> "StorageLocationPatch":
        supplied = self.model_fields_set - {"version"}
        if not supplied:
            raise ValueError("At least one storage location field is required")
        if "label" in supplied:
            if self.label is None or not self.label.strip():
                raise ValueError("label cannot be blank")
            self.label = self.label.strip()
        if "location_type" in supplied and self.location_type is None:
            raise ValueError("location_type cannot be blank")
        if "active" in supplied and self.active is None:
            raise ValueError("active cannot be blank")
        if "notes" in supplied:
            self.notes = (self.notes or "").strip()
        return self


class StorageLocationAssignmentItem(BaseModel):
    inventory_id: UUID
    version: int = Field(ge=1)


class StorageLocationAssignment(BaseModel):
    items: list[StorageLocationAssignmentItem] = Field(min_length=1, max_length=500)

    @model_validator(mode="after")
    def validate_items(self) -> "StorageLocationAssignment":
        ids = [item.inventory_id for item in self.items]
        if len(ids) != len(set(ids)):
            raise ValueError("Each inventory item may appear only once")
        return self


class ManualCatalogueCreate(BaseModel):
    product_type: CatalogueProductType = "CARD"
    game: str = Field(min_length=1, max_length=80)
    name: str = Field(min_length=1, max_length=300)
    set_name: str = Field(min_length=1, max_length=200)
    card_number: str | None = Field(default=None, max_length=80)
    variant: str = Field(default="", max_length=160)
    rarity: str = Field(default="", max_length=80)
    language: str | None = Field(default=None, max_length=80)

    @model_validator(mode="after")
    def normalise(self) -> "ManualCatalogueCreate":
        self.game = self.game.strip()
        self.name = self.name.strip()
        self.set_name = self.set_name.strip()
        self.card_number = self.card_number.strip() if self.card_number else None
        self.variant = self.variant.strip()
        self.rarity = self.rarity.strip()
        self.language = self.language.strip() if self.language else None
        if not self.game or not self.name or not self.set_name:
            raise ValueError("game, name and set_name cannot be blank")
        if self.product_type == "CARD" and not self.card_number:
            raise ValueError("card_number is required for a manually created card")
        return self


class ManualInventoryCreate(BaseModel):
    catalogue_id: UUID | None = None
    new_catalogue: ManualCatalogueCreate | None = None
    acquisition_cost_minor: int | None = Field(default=None, ge=0)
    acquisition_date: date | None = None
    condition: str | None = Field(default=None, max_length=80)
    seal_status: SealStatus | None = None
    grading_company: str | None = Field(default=None, max_length=40)
    grade: str | None = Field(default=None, max_length=40)
    certificate_number: str | None = Field(default=None, max_length=120)
    language: str | None = Field(default=None, max_length=80)
    storage_location_id: UUID | None = None
    store_price_minor: int | None = Field(default=None, ge=100)
    identity_confirmed: bool = False
    notes: str = Field(default="", max_length=2000)

    @model_validator(mode="after")
    def validate_intake(self) -> "ManualInventoryCreate":
        if self.identity_confirmed:
            raise ValueError("New inventory must be verified through the Verify workflow")
        if (self.catalogue_id is None) == (self.new_catalogue is None):
            raise ValueError("Choose exactly one existing catalogue product or new catalogue product")
        if (self.grading_company is None) != (self.grade is None):
            raise ValueError("grading_company and grade must both be set or both cleared")
        if self.certificate_number and not self.grading_company:
            raise ValueError("certificate_number requires grading_company and grade")
        self.condition = self.condition.strip() if self.condition else None
        self.grading_company = self.grading_company.strip() if self.grading_company else None
        self.grade = self.grade.strip() if self.grade else None
        self.certificate_number = self.certificate_number.strip() if self.certificate_number else None
        self.language = self.language.strip() if self.language else None
        self.notes = self.notes.strip()
        return self
