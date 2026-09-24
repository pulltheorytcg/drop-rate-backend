from pathlib import Path

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from app.inventory_intake import (
    _catalogue_search_terms,
    _manual_identity_key,
    _manual_intake_payload_hash,
    _receipt_response,
    _validate_physical_state,
)
from app.schemas import ManualCatalogueCreate, ManualInventoryCreate


ROOT = Path(__file__).parents[1]
STATIC = ROOT / "backend" / "app" / "static"
MIGRATION = ROOT / "database" / "migrations" / "202609230005_manual_intake_idempotency.sql"


def test_manual_card_requires_card_number() -> None:
    with pytest.raises(ValidationError, match="card_number is required"):
        ManualCatalogueCreate(
            product_type="CARD",
            game="Pokemon",
            name="Charizard",
            set_name="Base Set",
        )


def test_manual_sealed_product_does_not_require_card_number() -> None:
    product = ManualCatalogueCreate(
        product_type="SEALED",
        game="Pokemon",
        name="151 Booster Bundle",
        set_name="Scarlet & Violet 151",
    )
    assert product.card_number is None


def test_manual_inventory_requires_exactly_one_catalogue_source() -> None:
    with pytest.raises(ValidationError, match="exactly one"):
        ManualInventoryCreate()

    with pytest.raises(ValidationError, match="exactly one"):
        ManualInventoryCreate(
            catalogue_id="3f0e3d90-b56f-4e57-adf2-55cecc207820",
            new_catalogue={
                "product_type": "CARD",
                "game": "Pokemon",
                "name": "Charizard",
                "set_name": "Base Set",
                "card_number": "4/102",
            },
        )


def test_manual_inventory_unknown_cost_stays_none() -> None:
    item = ManualInventoryCreate(
        catalogue_id="3f0e3d90-b56f-4e57-adf2-55cecc207820",
        acquisition_cost_minor=None,
    )
    assert item.acquisition_cost_minor is None


def test_manual_inventory_grading_pair_is_required() -> None:
    with pytest.raises(ValidationError, match="both be set"):
        ManualInventoryCreate(
            catalogue_id="3f0e3d90-b56f-4e57-adf2-55cecc207820",
            grading_company="PSA",
        )


def test_manual_identity_key_is_case_insensitive_after_normalisation() -> None:
    first = ManualCatalogueCreate(
        product_type="CARD",
        game="Pokemon",
        name="Charizard",
        set_name="Base Set",
        card_number="4/102",
        variant="Holo",
        rarity="Rare",
        language="English",
    )
    second = ManualCatalogueCreate(
        product_type="CARD",
        game="pokemon",
        name="CHARIZARD",
        set_name="base set",
        card_number="4/102",
        variant="holo",
        rarity="rare",
        language="english",
    )
    assert _manual_identity_key(first) == _manual_identity_key(second)


def test_card_condition_must_use_standard_scale() -> None:
    payload = ManualInventoryCreate(
        catalogue_id="3f0e3d90-b56f-4e57-adf2-55cecc207820",
        condition="Good",
    )
    with pytest.raises(HTTPException, match="TCGplayer"):
        _validate_physical_state("CARD", payload)


def test_non_card_inventory_uses_seal_status_not_card_condition() -> None:
    payload = ManualInventoryCreate(
        catalogue_id="3f0e3d90-b56f-4e57-adf2-55cecc207820",
        condition="Near Mint",
    )
    with pytest.raises(HTTPException, match="seal_status"):
        _validate_physical_state("SEALED", payload)


def test_manual_intake_idempotency_is_nullable_and_unique() -> None:
    sql = MIGRATION.read_text()
    assert "intake_request_key uuid" in sql
    assert "unique (intake_request_key)" in sql.lower()
    assert "where intake_request_key is not null" not in sql.lower()


def test_manual_intake_payload_hash_is_stable_and_payload_sensitive() -> None:
    first = ManualInventoryCreate(
        catalogue_id="3f0e3d90-b56f-4e57-adf2-55cecc207820",
        condition="Near Mint",
        acquisition_cost_minor=None,
    )
    same = ManualInventoryCreate(
        catalogue_id="3f0e3d90-b56f-4e57-adf2-55cecc207820",
        condition="Near Mint",
        acquisition_cost_minor=None,
    )
    changed = ManualInventoryCreate(
        catalogue_id="3f0e3d90-b56f-4e57-adf2-55cecc207820",
        condition="Lightly Played",
        acquisition_cost_minor=None,
    )
    assert _manual_intake_payload_hash(first) == _manual_intake_payload_hash(same)
    assert _manual_intake_payload_hash(first) != _manual_intake_payload_hash(changed)


def test_manual_intake_receipt_rejects_key_reuse_for_different_payload() -> None:
    receipt = {"payload_hash": "first", "response": {"replayed": False, "inventory": {"id": "x"}}}
    with pytest.raises(HTTPException) as exc_info:
        _receipt_response(receipt, "different")
    assert exc_info.value.status_code == 409


def test_manual_intake_receipt_replays_same_payload() -> None:
    receipt = {
        "payload_hash": "same",
        "response": '{"replayed":false,"inventory":{"id":"x"}}',
    }
    replay = _receipt_response(receipt, "same")
    assert replay["replayed"] is True
    assert replay["inventory"]["id"] == "x"


def test_manual_intake_frontend_sends_idempotency_key_and_uses_registered_location() -> None:
    js = (STATIC / "inventory-intake.js").read_text()
    assert "crypto.randomUUID()" in js
    assert '"Idempotency-Key": intakeRequestKey' in js
    assert "intake-storage-location" in js
    assert "/api/v1/catalogue/search" in js
    assert "/api/v1/inventory/intake" in js


def test_catalogue_search_splits_human_query_into_literal_terms() -> None:
    assert _catalogue_search_terms("  Absol   063/094  ") == ["Absol", "063/094"]
    assert _catalogue_search_terms("Phantasmal Flames Absol") == [
        "Phantasmal",
        "Flames",
        "Absol",
    ]


def test_catalogue_search_requires_every_term_across_searchable_fields() -> None:
    source = (ROOT / "backend" / "app" / "inventory_intake.py").read_text()
    assert "from unnest($1::text[]) as search(term)" in source
    assert "where not (" in source
    assert "strpos(lower(p.name), lower(search.term)) > 0" in source
    assert "strpos(lower(coalesce(p.card_number, '')), lower(search.term)) > 0" in source
    assert "or strpos(lower(coalesce(p.variant, '')), lower(search.term)) > 0" in source
