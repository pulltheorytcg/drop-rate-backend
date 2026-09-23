from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, model_validator


ImportSource = Literal["COLLECTR", "GENERIC_CSV", "EBAY_PURCHASE_HISTORY", "HOLODEX"]


class ImportPreviewRequest(BaseModel):
    source: ImportSource
    filename: str = Field(min_length=1, max_length=255)
    csv_text: str = Field(min_length=1, max_length=5_000_000)
    currency: Literal["GBP"] = "GBP"

    @model_validator(mode="after")
    def normalise(self) -> "ImportPreviewRequest":
        self.filename = self.filename.strip()
        if not self.filename:
            raise ValueError("filename cannot be blank")
        if "\x00" in self.csv_text:
            raise ValueError("CSV contains invalid null bytes")
        return self


class ImportCommit(BaseModel):
    version: int = Field(ge=1)
