from __future__ import annotations

from uuid import UUID

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

import app.market_mappings as market_mappings
from app.market_mappings import (
    MarketMappingCreate,
    MarketMappingDecision,
    _decide_mapping,
    _decision_metadata,
)


CATALOGUE_ID = UUID("11111111-1111-1111-1111-111111111111")
MAPPING_ID = UUID("22222222-2222-2222-2222-222222222222")


class FakeConnection:
    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple]] = []

    async def fetchrow(self, sql: str, *args):
        self.calls.append((sql, args))
        return {"id": MAPPING_ID}


def test_mapping_create_normalises_supported_source() -> None:
    payload = MarketMappingCreate(
        catalogue_id=CATALOGUE_ID,
        source=" ebay ",
        source_product_id="provider-product",
    )
    assert payload.source == "EBAY"


def test_mapping_create_rejects_unsupported_source() -> None:
    with pytest.raises(ValidationError, match="Unsupported market source"):
        MarketMappingCreate(
            catalogue_id=CATALOGUE_ID,
            source="SCRAPED_RANDOM_SITE",
            source_product_id="provider-product",
        )


def test_review_metadata_preserves_existing_provenance() -> None:
    metadata = _decision_metadata(
        {"discovered_by": "provider-search", "candidate_rank": 1},
        action="VERIFIED",
        user_id="user-123",
        reason="Exact set, number and variant checked",
    )

    assert metadata["discovered_by"] == "provider-search"
    assert metadata["candidate_rank"] == 1
    assert metadata["review"]["status"] == "VERIFIED"
    assert metadata["review"]["reviewed_by_user_id"] == "user-123"
    assert metadata["review"]["reason"] == "Exact set, number and variant checked"
    assert metadata["review"]["reviewed_at"]


@pytest.mark.asyncio
async def test_mapping_version_conflict_fails_closed(monkeypatch) -> None:
    async def fake_mapping_row(connection, mapping_id):
        return {
            "id": mapping_id,
            "match_status": "REVIEW",
            "version": 3,
            "metadata": {},
        }

    monkeypatch.setattr(market_mappings, "_mapping_row", fake_mapping_row)

    with pytest.raises(HTTPException) as exc_info:
        await _decide_mapping(
            FakeConnection(),
            mapping_id=MAPPING_ID,
            payload=MarketMappingDecision(expected_version=2),
            user_id="user-123",
            status="VERIFIED",
        )

    assert exc_info.value.status_code == 409
    assert exc_info.value.detail == "Mapping version conflict"


@pytest.mark.asyncio
async def test_verified_mapping_cannot_be_decided_again(monkeypatch) -> None:
    async def fake_mapping_row(connection, mapping_id):
        return {
            "id": mapping_id,
            "match_status": "VERIFIED",
            "version": 2,
            "metadata": {},
        }

    monkeypatch.setattr(market_mappings, "_mapping_row", fake_mapping_row)

    with pytest.raises(HTTPException) as exc_info:
        await _decide_mapping(
            FakeConnection(),
            mapping_id=MAPPING_ID,
            payload=MarketMappingDecision(expected_version=2),
            user_id="user-123",
            status="VERIFIED",
        )

    assert exc_info.value.status_code == 409
    assert exc_info.value.detail == "Only REVIEW mappings can be decided"


@pytest.mark.asyncio
async def test_verification_promotes_human_verified_mapping_to_full_confidence(monkeypatch) -> None:
    rows = iter(
        [
            {
                "id": MAPPING_ID,
                "match_status": "REVIEW",
                "version": 4,
                "metadata": {"candidate": "exact"},
                "source": "TCGPLAYER",
                "game": "Pokemon",
                "source_variant_id": "Normal",
                "variant": "Normal",
            },
            {
                "id": MAPPING_ID,
                "match_status": "VERIFIED",
                "version": 5,
                "metadata": {},
            },
        ]
    )

    async def fake_mapping_row(connection, mapping_id):
        return next(rows)

    monkeypatch.setattr(market_mappings, "_mapping_row", fake_mapping_row)
    connection = FakeConnection()

    result = await _decide_mapping(
        connection,
        mapping_id=MAPPING_ID,
        payload=MarketMappingDecision(expected_version=4, match_confidence=0.97),
        user_id="user-123",
        status="VERIFIED",
    )

    assert result["match_status"] == "VERIFIED"
    update_args = connection.calls[0][1]
    assert update_args[1] == "VERIFIED"
    assert update_args[2] == pytest.approx(1.0)
    assert update_args[4] == 4


@pytest.mark.asyncio
async def test_rejection_forces_zero_match_confidence(monkeypatch) -> None:
    rows = iter(
        [
            {
                "id": MAPPING_ID,
                "match_status": "REVIEW",
                "version": 7,
                "metadata": {"candidate": "wrong-print"},
            },
            {
                "id": MAPPING_ID,
                "match_status": "REJECTED",
                "version": 8,
                "metadata": {},
            },
        ]
    )

    async def fake_mapping_row(connection, mapping_id):
        return next(rows)

    monkeypatch.setattr(market_mappings, "_mapping_row", fake_mapping_row)
    connection = FakeConnection()

    result = await _decide_mapping(
        connection,
        mapping_id=MAPPING_ID,
        payload=MarketMappingDecision(expected_version=7, match_confidence=1.0, reason="Wrong variant"),
        user_id="user-123",
        status="REJECTED",
    )

    assert result["match_status"] == "REJECTED"
    update_args = connection.calls[0][1]
    assert update_args[1] == "REJECTED"
    assert update_args[2] == 0.0
    assert update_args[4] == 7


def test_verified_mapping_uniqueness_is_enforced_by_migration() -> None:
    from pathlib import Path

    migration = (
        Path(__file__).parents[1]
        / "database"
        / "migrations"
        / "202609240002_unique_verified_market_mapping.sql"
    ).read_text()
    assert "unique index" in migration.casefold()
    assert "catalogue_id, source" in migration
    assert "match_status = 'VERIFIED'" in migration


@pytest.mark.asyncio
async def test_cardmarket_pokemon_mapping_requires_matching_provider_variant(monkeypatch) -> None:
    async def fake_mapping_row(connection, mapping_id):
        return {
            "id": mapping_id,
            "match_status": "REVIEW",
            "version": 1,
            "metadata": {},
            "source": "CARDMARKET",
            "game": "Pokemon",
            "source_variant_id": None,
            "variant": "Normal",
        }

    monkeypatch.setattr(market_mappings, "_mapping_row", fake_mapping_row)

    with pytest.raises(HTTPException) as exc_info:
        await _decide_mapping(
            FakeConnection(),
            mapping_id=MAPPING_ID,
            payload=MarketMappingDecision(expected_version=1),
            user_id="user-123",
            status="VERIFIED",
        )

    assert exc_info.value.status_code == 409
    assert "requires a provider variant" in exc_info.value.detail


@pytest.mark.asyncio
async def test_cardmarket_reverse_holo_alias_can_be_verified(monkeypatch) -> None:
    rows = iter(
        [
            {
                "id": MAPPING_ID,
                "match_status": "REVIEW",
                "version": 2,
                "metadata": {},
                "source": "CARDMARKET",
                "game": "Pokemon",
                "source_variant_id": "Reverse Holo",
                "variant": "Reverse Holofoil",
            },
            {
                "id": MAPPING_ID,
                "match_status": "VERIFIED",
                "version": 3,
                "metadata": {},
            },
        ]
    )

    async def fake_mapping_row(connection, mapping_id):
        return next(rows)

    monkeypatch.setattr(market_mappings, "_mapping_row", fake_mapping_row)

    result = await _decide_mapping(
        FakeConnection(),
        mapping_id=MAPPING_ID,
        payload=MarketMappingDecision(expected_version=2),
        user_id="user-123",
        status="VERIFIED",
    )

    assert result["match_status"] == "VERIFIED"


@pytest.mark.asyncio
async def test_tcgplayer_pokemon_mapping_requires_variant_before_verification(monkeypatch) -> None:
    async def fake_mapping_row(connection, mapping_id):
        return {
            "id": mapping_id,
            "match_status": "REVIEW",
            "version": 1,
            "metadata": {},
            "source": "TCGPLAYER",
            "game": "Pokemon",
            "source_variant_id": None,
            "variant": "Normal",
        }

    monkeypatch.setattr(market_mappings, "_mapping_row", fake_mapping_row)

    with pytest.raises(HTTPException) as exc_info:
        await _decide_mapping(
            FakeConnection(),
            mapping_id=MAPPING_ID,
            payload=MarketMappingDecision(expected_version=1),
            user_id="user-123",
            status="VERIFIED",
        )

    assert exc_info.value.status_code == 409
    assert "TCGPLAYER Pokemon mapping requires a provider variant" in exc_info.value.detail
