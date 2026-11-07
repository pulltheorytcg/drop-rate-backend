from contextlib import asynccontextmanager
from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app import owner_collectibles
from app.auth import require_user
from app.access_control import require_owner_portal_request, require_platform_admin_request
from app.inventory_intake import _find_exact_catalogue, _manual_identity_key, _manual_intake_payload_hash
from app.manual_collectible_identity import FIGURE_CONDITIONS, FigureDetailsCreate
from app.owner_collectibles import CollectibleIntakeRequest
from app.physical_state import validate_physical_state
from app.schemas import ManualCatalogueCreate, ManualInventoryCreate


SPORTS = dict(system_code="SPORTS_CARDS", sport="Basketball", league="NBA", release_year=2024,
              manufacturer="Fixture Cards", set_name="Fixture Chrome", subject_name="Fixture Player",
              card_number="23", parallel="Blue", print_run=99)
FIGURE = dict(system_code="FIGURES", manufacturer="Fixture Figures", franchise="Fixture World",
              character="Fixture Character", product_line="Collector Line", edition="First edition",
              scale="1:6", release_year=2024, manufacturer_sku="FIG-001", barcode_gtin="1234567890123")


def sports(**changes):
    return ManualCatalogueCreate(product_type="CARD", game="unused", name="unused", set_name="unused",
                                 language="English", sports_card={**SPORTS, **changes})


def figure(**changes):
    return ManualCatalogueCreate(product_type="FIGURE", game="unused", name="unused", set_name="unused",
                                 figure_details={**FIGURE, **changes})


@pytest.mark.parametrize("change", [dict(sport="Football"), dict(league="Other league"), dict(release_year=2023),
    dict(season="2023–24"), dict(manufacturer="Another maker"), dict(set_name="Another set"),
    dict(subject_name="Another player"), dict(team="Fixture Team"), dict(card_number="24"),
    dict(parallel="Red"), dict(print_run=25)])
def test_sports_full_printing_identity_is_preserved(change):
    assert _manual_identity_key(sports()) != _manual_identity_key(sports(**change))


def test_sports_identity_case_normalisation_and_language():
    assert _manual_identity_key(sports()) == _manual_identity_key(sports(subject_name="  FIXTURE PLAYER  "))
    other = sports(); other.language = "Japanese"
    assert _manual_identity_key(sports()) != _manual_identity_key(other)
    assert sports().game == "Sports Cards"
    assert sports().variant == "Blue · /99"


@pytest.mark.parametrize("change", [dict(manufacturer="Another maker"), dict(franchise="Another franchise"),
    dict(character="Another character"), dict(product_line="Other line"), dict(edition="Second edition"),
    dict(scale="1:12"), dict(release_year=2025), dict(manufacturer_sku="FIG-002"), dict(barcode_gtin="1234567890124")])
def test_figure_full_edition_identity_is_preserved(change):
    assert _manual_identity_key(figure()) != _manual_identity_key(figure(**change))


def test_figure_normalises_barcode_and_does_not_invent_unknown_fields():
    result = FigureDetailsCreate(**{**FIGURE, "barcode_gtin": "123-4567 890123", "scale": " ", "release_year": None})
    assert result.barcode_gtin == "1234567890123" and result.scale is None and result.release_year is None
    for barcode in ("123", "fixture-1234567890123", "１２３４５６７８"):
        with pytest.raises(ValidationError, match="barcode"):
            FigureDetailsCreate(**{**FIGURE, "barcode_gtin": barcode})


def test_new_types_require_structured_details_and_reject_mixed_identity():
    with pytest.raises(ValidationError, match="Figure details"):
        ManualCatalogueCreate(product_type="FIGURE", game="Figures", name="Figure", set_name="Line")
    with pytest.raises(ValidationError, match="Parallel|parallel"):
        sports(parallel=" ")
    with pytest.raises(ValidationError, match="language"):
        ManualCatalogueCreate(product_type="CARD", game="Sports", name="Player", set_name="Set", sports_card=SPORTS)
    with pytest.raises(ValidationError, match="one collectible"):
        ManualCatalogueCreate(product_type="FIGURE", game="Figures", name="Figure", set_name="Line", sports_card=SPORTS, figure_details=FIGURE)
    with pytest.raises(ValidationError, match="extra_forbidden"):
        sports(owner_id=str(uuid4()))


@pytest.mark.parametrize("condition", [*FIGURE_CONDITIONS, None])
@pytest.mark.parametrize("seal", ["SEALED", "UNSEALED", None])
def test_figures_keep_condition_and_packaging_separate(condition, seal):
    validate_physical_state(product_type="FIGURE", condition=condition, seal_status=seal, grading_company=None, grade=None)


@pytest.mark.parametrize("changes", [dict(condition="Lightly Played"), dict(seal_status="UNKNOWN"),
    dict(grading_company="PSA", grade="10", certificate_number="Fixture")])
def test_figures_reject_card_state(changes):
    with pytest.raises(ValueError):
        validate_physical_state(**{**dict(product_type="FIGURE", condition=None, seal_status=None,
            grading_company=None, grade=None, certificate_number=None), **changes})


def test_collectible_request_cannot_choose_owner_approval_or_price():
    base = dict(category="SPORTS", new_catalogue=sports().model_dump())
    for changes in (dict(owner_id=str(uuid4())), dict(identity_confirmed=True), dict(sale_intent="FOR_SALE"),
                    dict(store_price_minor=1000), dict(market_value_minor=9000), dict(category="FIGURES")):
        with pytest.raises(ValidationError):
            CollectibleIntakeRequest(**{**base, **changes})
    with pytest.raises(ValidationError, match="certificate"):
        CollectibleIntakeRequest(**base, grading_company="PSA", grade="10")


def test_existing_receipts_keep_their_original_payload_hash():
    # Golden receipt from the established card request format, before subtype
    # fields were added. A deployment must not invalidate a retry of this save.
    item = ManualInventoryCreate(new_catalogue=ManualCatalogueCreate(product_type="CARD", game="Pokemon",
        name="Charizard", set_name="Base Set", card_number="4/102", language="English"))
    # Computed independently with HEAD's schema and original receipt algorithm.
    assert _manual_intake_payload_hash(item) == "b17e0e31561ac633598e3abd437b6432bc3ea4bfe0b02584e88415fe92a93414"
    assert _manual_intake_payload_hash(ManualInventoryCreate(new_catalogue=sports(), notes="Serial number: 12/99")) != _manual_intake_payload_hash(ManualInventoryCreate(new_catalogue=sports(), notes="Serial number: 13/99"))


def test_absent_subtypes_preserve_existing_canonical_book_wire_format():
    item = ManualCatalogueCreate(product_type="COMIC", game="unused", name="unused", set_name="unused",
        language="English", comic_printing=dict(system_code="MARVEL_COMICS", series_title="Fixture Series", issue_number="1"))
    canonical = item.model_dump(exclude={"comic_printing"})
    assert set(canonical) == {"product_type", "game", "name", "set_name", "card_number", "variant", "rarity", "language"}
    nested = ManualInventoryCreate(new_catalogue=item).model_dump(mode="json")["new_catalogue"]
    assert "comic_printing" in nested and "sports_card" not in nested and "figure_details" not in nested
    assert sports().model_dump()["sports_card"]["subject_name"] == SPORTS["subject_name"]
    assert figure().model_dump()["figure_details"]["edition"] == FIGURE["edition"]


@pytest.mark.asyncio
async def test_exact_matching_uses_full_identity_not_compatibility_fields():
    db = SimpleNamespace(fetchrow=AsyncMock(return_value={"id": "reference"}), fetch=AsyncMock())
    for item in (sports(), figure()):
        assert await _find_exact_catalogue(db, item) == {"id": "reference"}
        assert db.fetchrow.call_args.args[1:] == (_manual_identity_key(item), item.product_type)
    db.fetch.assert_not_called()


def client_fixture(monkeypatch):
    app = FastAPI(); app.state.db_pool = object()
    @app.middleware("http")
    async def request_id(request, call_next):
        request.state.request_id = "collectibles-fixture"; return await call_next(request)
    app.include_router(owner_collectibles.router)
    user = SimpleNamespace(user_id=uuid4())
    access = {"owner_id": uuid4(), "access_role": "OWNER"}
    app.dependency_overrides[require_user] = lambda: user
    app.dependency_overrides[require_owner_portal_request] = lambda: access
    app.dependency_overrides[require_platform_admin_request] = lambda: {**access, "access_role": "PLATFORM_ADMIN"}
    create = AsyncMock(return_value={"inventory": {"id": str(uuid4()), "sale_intent": "PERSONAL_COLLECTION"}})
    monkeypatch.setattr(owner_collectibles, "create_inventory_intake", create)
    return TestClient(app), app, user, access, create


def test_manual_owner_and_founder_endpoints_delegate_bound_copy_engine(monkeypatch):
    client, app, user, access, create = client_fixture(monkeypatch)
    key = str(uuid4())
    body = dict(category="SPORTS", new_catalogue=sports().model_dump(mode="json"), copy_serial_number="12/99", notes="Original sleeve")
    for path in ("/api/v1/owner/collectibles/intake", "/api/v1/inventory/collectibles/intake"):
        response = client.post(path, json=body, headers={"Idempotency-Key": key})
        assert response.status_code == 201, response.text
        intake, request, actor, sent_key = create.call_args.args
        assert actor is user and sent_key == key and isinstance(intake, ManualInventoryCreate)
        assert intake.notes == "Serial number: 12/99\nOriginal sleeve"
        assert intake.identity_confirmed is False and intake.store_price_minor is None
        assert "copy_serial_number" not in intake.model_dump() and "category" not in intake.model_dump()
    app.dependency_overrides.pop(require_user)
    create.reset_mock()
    assert client.post("/api/v1/owner/collectibles/intake", json=body, headers={"Idempotency-Key": key}).status_code == 401
    create.assert_not_called()


def test_catalogue_selection_is_server_checked_and_manual_reference_is_private(monkeypatch):
    client, _, _, _, create = client_fixture(monkeypatch)
    row = {"product_type": "CARD", "language": "English", "system_code": "SPORTS_CARDS", "identity_status": "NEEDS_REVIEW",
           "attributes": {"identity_source": "SELLER_ENTERED"}, "own_copy": False}
    db = SimpleNamespace(fetchrow=AsyncMock(side_effect=lambda *args: deepcopy(row) if row else None))
    @asynccontextmanager
    async def connection(*args): yield db
    monkeypatch.setattr(owner_collectibles, "user_connection", connection)
    path = "/api/v1/owner/collectibles/intake"
    body = dict(category="SPORTS", catalogue_id=str(uuid4()))
    headers = {"Idempotency-Key": str(uuid4())}
    assert client.post(path, json=body, headers=headers).status_code == 404
    create.assert_not_called()
    row["own_copy"] = True
    assert client.post(path, json=body, headers=headers).status_code == 201
    assert db.fetchrow.call_args.args[3:] == ("CARD", "SPORTS_CARDS")
    assert client.post(path, json={**body, "language": "Japanese"}, headers=headers).status_code == 422
    row.clear()
    assert client.post(path, json=body, headers=headers).status_code == 404


@pytest.mark.asyncio
async def test_identity_details_hide_other_collectors_manual_records_and_attribution(monkeypatch):
    from app import collectible_identity
    product = dict(id=uuid4(), product_type="FIGURE", name="Fixture figure", system_code="FIGURES",
                   collectible_type="FIGURE", identity_status="NEEDS_REVIEW", set_code=None,
                   printing_code=None, release_region=None, release_date=None, profile_version=1,
                   profile_attributes={"identity_source": "SELLER_ENTERED", "submitted_by_user_id": str(uuid4()),
                                       "figure_details": FIGURE})
    visible_inventory = []
    async def fetchrow(query, *args):
        return product if "p.identity_key" in query else None
    async def fetch(query, *args):
        return visible_inventory if "inventory_items i" in query else []
    db = SimpleNamespace(fetchrow=fetchrow, fetch=fetch)
    @asynccontextmanager
    async def connection(*args): yield db
    monkeypatch.setattr(collectible_identity, "user_connection", connection)
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(db_pool=None)), state=SimpleNamespace(request_id="fixture"))
    user = SimpleNamespace(user_id=uuid4())
    with pytest.raises(HTTPException) as exc:
        await collectible_identity.collectible_identity(product["id"], request, user)
    assert exc.value.status_code == 404
    visible_inventory.append({"id": str(uuid4())})
    result = await collectible_identity.collectible_identity(product["id"], request, user)
    assert result["figure_details"] == FIGURE
    assert "submitted_by_user_id" not in result["profile"]["attributes"]
