"""Public Seller Hub launch interest; this does not create owner access."""

from __future__ import annotations

import logging
import re
from typing import Literal

import asyncpg
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field, field_validator

router = APIRouter(tags=["seller-hub-launch"])
logger = logging.getLogger(__name__)


class SellerHubLaunchSignup(BaseModel):
    email: str = Field(min_length=5, max_length=254)
    name: str = Field(default="", max_length=120)
    interest: Literal["CARDS", "SEALED", "COMICS_MANGA", "OTHER"] = "CARDS"
    consent: Literal[True]
    website: str = Field(default="", max_length=200)

    @field_validator("email")
    @classmethod
    def normalise_email(cls, value: str) -> str:
        email = value.strip().casefold()
        if not re.fullmatch(r"[^\s@]+@[^\s@.]+(?:\.[^\s@.]+)+", email) or len(email) > 254:
            raise ValueError("Enter a valid email address")
        return email

    @field_validator("name")
    @classmethod
    def normalise_name(cls, value: str) -> str:
        return value.strip()


@router.post("/api/v1/public/seller-hub/waitlist", status_code=200)
async def join_seller_hub_waitlist(payload: SellerHubLaunchSignup, request: Request) -> dict[str, str]:
    # Bots tend to fill this hidden field. Answer indistinguishably, but write nothing.
    if payload.website.strip():
        return {"status": "registered"}

    try:
        async with request.app.state.db_pool.acquire() as connection:
            await connection.fetchval(
                "select tcg_private.register_seller_hub_interest($1, $2, $3)",
                payload.email,
                payload.name,
                payload.interest,
            )
    except (asyncpg.PostgresError, asyncpg.InterfaceError, OSError, TimeoutError) as exc:
        # Database exceptions can include values from a rejected row. Do not
        # expose signup email/name through application logs.
        logger.warning("Seller Hub launch signup database unavailable: %s", type(exc).__name__)
        raise HTTPException(
            status_code=503,
            detail="Registration is temporarily unavailable. Please try again shortly.",
        ) from None

    # Do not reveal whether an email was already registered.
    return {"status": "registered"}
