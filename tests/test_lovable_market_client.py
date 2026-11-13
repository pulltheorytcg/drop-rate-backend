from __future__ import annotations

import httpx
import pytest

from app.lovable_market_client import (
    LovableMarketClient, LovableMarketError, PUBLISHED_URL,
    clean_lookup, safe_candidates,
)
from app.lovable_market_context import LovablePreviewRequest, canonical_lookup
from pydantic import ValidationError


SECRET = "integration-test-secret-" + "x" * 40
LOOKUP = dict(category="tcg", game="Pokemon", name="Charizard",
              set_name="Base Set", card_number="4/102", rarity="Rare",
              variant="Holofoil", language="English")


def response_payload():
    return {
        "marketplace": "EBAY_GB",
        "currency": "GBP",
        "market_value_gbp": None,
        "market_value_eligible": False,
        "actual_paid_price_verified": False,
        "verified_sold_count": 0,
        "observation_type": "ACTIVE",
        "search_calls": 2,
        "detail_calls": 3,
        "candidates": [
            {
                "source": "EBAY_BROWSE", "source_item_id": "v1|1|0",
                "source_url": "https://www.ebay.co.uk/itm/1", "title": "Charizard 4/102",
                "match_status": "REVIEW_REQUIRED", "source_item_price": "50.00",
                "asking_price_gbp": 50.0, "currency": "GBP",
                "actual_paid_price_verified": False, "observation_type": "ACTIVE",
                "seller_id": "seller1", "matched_signals": ["title:card_number"],
                "missing_signals": ["GRADE_UNVERIFIED"], "conflicting_signals": [],
            }
        ],
    }


@pytest.mark.asyncio
async def test_mocked_lovable_candidate_bridge_has_no_market_value_or_writes():
    async def respond(req):
        assert str(req.url) == PUBLISHED_URL
        assert req.headers["x-api-key"] == SECRET
        assert req.content.find(b'"Charizard"') > -1
        return httpx.Response(200, json=response_payload())

    result = await LovableMarketClient(PUBLISHED_URL, SECRET, transport=httpx.MockTransport(respond)).search(LOOKUP)
    assert result["market_value_gbp"] is None
    assert result["market_value_eligible"] is False
    assert result["verified_sold_count"] == 0
    assert result["persisted"] is False
    assert result["candidate_count"] == 1
    assert result["candidates"][0]["asking_price_gbp"] == "50.00"
    assert result["candidates"][0]["match_status"] == "REVIEW_REQUIRED"


@pytest.mark.parametrize("override", [
    {"market_value_gbp": 5000},
    {"market_value_eligible": True},
    {"actual_paid_price_verified": True},
    {"observation_type": "SOLD"},
    {"verified_sold_count": 1},
])
def test_we_never_accept_lovable_claims_of_actual_market_values(override):
    payload = {**response_payload(), **override}
    with pytest.raises(LovableMarketError) as exc:
        safe_candidates(payload)
    assert exc.value.code == "LOVABLE_EVIDENCE_POLICY_VIOLATION"


def test_candidate_conflict_downgrades_exact_to_rejected():
    data = response_payload()
    data["candidates"][0]["match_status"] = "EXACT_MATCH"
    data["candidates"][0]["conflicting_signals"] = ["WRONG_VARIANT"]
    result = safe_candidates(data)
    assert result["exact_count"] == 0
    assert result["candidates"][0]["match_status"] == "REJECTED"


def test_bad_price_listing_or_duplicate_cannot_become_market_value():
    data = response_payload()
    data["candidates"] += [
        {**data["candidates"][0], "asking_price_gbp": 700},
        {**data["candidates"][0], "source_item_id": "v1|2|0", "asking_price_gbp": -2},
        {**data["candidates"][0], "source_item_id": "v1|3|0", "observation_type": "SOLD"},
    ]
    result = safe_candidates(data)
    assert len(result["candidates"]) == 2
    assert result["candidates"][1]["asking_price_gbp"] is None
    assert result["market_value_gbp"] is None


@pytest.mark.parametrize(("status", "expected"), [
    (401, "LOVABLE_AUTH_REJECTED"),
    (403, "LOVABLE_AUTH_REJECTED"),
    (429, "LOVABLE_RATE_LIMITED"),
    (302, "LOVABLE_REDIRECT_REJECTED"),
    (500, "LOVABLE_PROVIDER_UNAVAILABLE"),
])
@pytest.mark.asyncio
async def test_http_errors_fail_closed(status, expected):
    client = LovableMarketClient(
        PUBLISHED_URL, SECRET, transport=httpx.MockTransport(
            lambda req: httpx.Response(status, headers={"location": "https://unknown.example.com/"})
        )
    )
    with pytest.raises(LovableMarketError) as exc:
        await client.search(LOOKUP)
    assert exc.value.code == expected
    assert SECRET not in str(exc.value)


@pytest.mark.asyncio
async def test_disabled_integration_is_default_off(monkeypatch):
    monkeypatch.setenv("LOVABLE_MARKET_API_URL", PUBLISHED_URL)
    monkeypatch.setenv("LOVABLE_MARKET_API_KEY", SECRET)
    monkeypatch.delenv("LOVABLE_MARKET_READ_ONLY_ENABLED", raising=False)
    with pytest.raises(LovableMarketError) as exc:
        LovableMarketClient.from_environment()
    assert exc.value.code == "LOVABLE_INTEGRATION_DISABLED"


def test_no_untrusted_network_target_or_injected_query_fields():
    with pytest.raises(LovableMarketError):
        LovableMarketClient("https://127.0.0.1/candidates", SECRET)
    with pytest.raises(LovableMarketError):
        clean_lookup({**LOOKUP, "owner_id": "someone"})
    with pytest.raises(LovableMarketError):
        clean_lookup({"game": "Pokemon", "name": "Charizard", "grade": "9"})


@pytest.mark.parametrize("category,expected", [
    ("CARD", "tcg"), ("SEALED", "sealed_tcg"),
    ("COMIC", "manga"), ("FIGURE", "figure"),
])
def test_catalogue_identity_mapping_uses_actual_product_type(category, expected):
    row = dict(product_type=category, game="Manga" if category=="COMIC" else "Pokemon",
               name="Collection Item", set_name="Set X", card_number="12",
               variant="Secret Rare", rarity="Ultra Rare", language="English")
    out = canonical_lookup(row,"catalogue",condition=None,grading_company=None,grade=None)
    assert out["category"] == expected
    assert out["name"] == "Collection Item"
    assert "grade" not in out
    if category == "COMIC":
        assert out["volume"] == "12"


def test_reference_source_validation_and_grade_pair():
    with pytest.raises(ValidationError):
        LovablePreviewRequest(source_kind="reference_card",provider="TCGdex",system_code="POKEMON_TCG",
                              language="English",provider_id="abc",grade="9")
    with pytest.raises(ValidationError):
        LovablePreviewRequest(source_kind="catalogue")
