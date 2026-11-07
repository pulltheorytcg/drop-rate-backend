"""Explicit sports-card and figure identities entered by a collector.

These fields describe a reference edition, never the authenticity, condition,
serial number, price or ownership of a physical copy.
"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


FIGURE_CONDITIONS = frozenset({"New", "Like New", "Very Good", "Good", "Fair", "Damaged"})


class _ManualIdentity(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    @model_validator(mode="after")
    def normalise_optional_text(self):
        for key, field in type(self).model_fields.items():
            if not field.is_required() and getattr(self, key) == "":
                setattr(self, key, None)
        return self

    def identity(self) -> dict:
        return {key: value.casefold() if isinstance(value, str) else value
                for key, value in self.model_dump().items()}


class SportsCardCreate(_ManualIdentity):
    system_code: Literal["SPORTS_CARDS"] = "SPORTS_CARDS"
    sport: str = Field(min_length=1, max_length=60)
    league: str | None = Field(default=None, max_length=80)
    release_year: int = Field(ge=1800, le=2200, strict=True)
    season: str | None = Field(default=None, max_length=30)
    manufacturer: str = Field(min_length=1, max_length=80)
    set_name: str = Field(min_length=1, max_length=100)
    subject_name: str = Field(min_length=1, max_length=140)
    team: str | None = Field(default=None, max_length=80)
    card_number: str = Field(min_length=1, max_length=80)
    parallel: str = Field(min_length=1, max_length=100)
    print_run: int | None = Field(default=None, ge=1, le=1000000, strict=True)

    def catalogue_fields(self) -> dict:
        variant = " · ".join(value for value in (
            self.parallel, f"/{self.print_run}" if self.print_run else None) if value)
        return dict(game="Sports Cards", name=self.subject_name,
                    set_name=f"{self.release_year} {self.manufacturer} {self.set_name}",
                    card_number=self.card_number, variant=variant, rarity="")


class FigureDetailsCreate(_ManualIdentity):
    system_code: Literal["FIGURES"] = "FIGURES"
    manufacturer: str = Field(min_length=1, max_length=80)
    franchise: str = Field(min_length=1, max_length=120)
    character: str = Field(min_length=1, max_length=140)
    product_line: str = Field(min_length=1, max_length=100)
    edition: str = Field(min_length=1, max_length=100)
    scale: str | None = Field(default=None, max_length=30)
    release_year: int | None = Field(default=None, ge=1800, le=2200, strict=True)
    manufacturer_sku: str | None = Field(default=None, max_length=80)
    barcode_gtin: str | None = Field(default=None, max_length=40)

    @model_validator(mode="after")
    def normalise_barcode(self):
        if self.barcode_gtin:
            self.barcode_gtin = "".join(self.barcode_gtin.replace("-", "").split())
            if not self.barcode_gtin.isascii() or not self.barcode_gtin.isdigit() or len(self.barcode_gtin) not in {8, 12, 13, 14}:
                raise ValueError("Figure barcode must contain 8, 12, 13 or 14 digits")
        return self

    def catalogue_fields(self) -> dict:
        variant = " · ".join(str(value) for value in (self.edition, self.scale, self.release_year) if value)
        return dict(game="Figures", name=f"{self.character} · {self.edition}",
                    set_name=f"{self.manufacturer} · {self.product_line}",
                    card_number=self.manufacturer_sku, variant=variant, rarity="")
