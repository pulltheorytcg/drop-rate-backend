"""Seller-entered book identity; never an automatic authenticity or value claim."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


BOOK_SYSTEMS = {
    "MARVEL_COMICS": "Marvel Comics",
    "DC_COMICS": "DC Comics",
    "OTHER_COMICS": "Other Comics",
    "MANGA": "Manga",
}
BOOK_CONDITIONS = frozenset({
    "Mint", "Near Mint", "Very Fine", "Fine", "Very Good", "Good", "Fair", "Poor",
})


class ComicPrintingCreate(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    system_code: Literal["MARVEL_COMICS", "DC_COMICS", "OTHER_COMICS", "MANGA"]
    series_title: str = Field(min_length=1, max_length=140)
    issue_number: str = Field(min_length=1, max_length=40)
    volume_identifier: str | None = Field(default=None, max_length=40)
    printing_number: int | None = Field(default=None, ge=1, le=999, strict=True)
    release_year: int | None = Field(default=None, ge=1930, le=2200, strict=True)
    cover_code: str | None = Field(default=None, max_length=100)
    cover_artist: str | None = Field(default=None, max_length=100)
    barcode_gtin: str | None = Field(default=None, max_length=40)
    publisher: str | None = Field(default=None, max_length=100)
    book_format: Literal["SINGLE_ISSUE", "TRADE_PAPERBACK", "HARDCOVER", "MANGA"] = "SINGLE_ISSUE"

    @model_validator(mode="after")
    def normalise(self):
        for key in ("volume_identifier", "cover_code", "cover_artist", "barcode_gtin", "publisher"):
            setattr(self, key, getattr(self, key) or None)
        if self.barcode_gtin:
            self.barcode_gtin = "".join(self.barcode_gtin.replace("-", "").split()).upper()
        if self.system_code == "MANGA":
            if self.book_format != "MANGA":
                raise ValueError("Manga requires the manga book format")
        elif self.book_format == "MANGA":
            raise ValueError("The manga format requires the Manga category")
        publisher = {"MARVEL_COMICS": "Marvel", "DC_COMICS": "DC"}.get(self.system_code)
        if publisher:
            self.publisher = publisher
        elif not self.publisher:
            raise ValueError("Publisher is required for manga and other comics")
        return self

    def identity(self):
        return {key: value.casefold() if isinstance(value, str) else value
                for key, value in self.model_dump().items()}

    def catalogue_fields(self):
        number_label = "Volume" if self.book_format == "MANGA" else "#"
        title = f"{self.series_title} {number_label}{' ' if number_label == 'Volume' else ''}{self.issue_number}"
        release = " · ".join(str(value) for value in (
            self.volume_identifier, self.release_year) if value)
        variant = " · ".join(value for value in (
            self.book_format.replace("_", " ").title(), self.cover_code,
            f"Printing {self.printing_number}" if self.printing_number else None) if value)
        return dict(game=BOOK_SYSTEMS[self.system_code], name=title,
                    set_name=f"{self.series_title} ({release})" if release else self.series_title,
                    card_number=self.issue_number, variant=variant, rarity="")
