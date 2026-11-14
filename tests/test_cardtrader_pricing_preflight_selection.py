"""Source preflight rotates through missing-price releases, not artwork-only ones."""
from copy import deepcopy

import pytest

from app import cardtrader_bulk_guides as bulk
from app.pricing_source_receipts import safe_receipt


def ref(set_id, *, missing_price, missing_artwork):
    return {
        "provider": "TCGdex", "system_code": "POKEMON_TCG",
        "language": "English", "set_id": set_id, "set_name": set_id.capitalize(),
        "provider_id": set_id + "-1", "card_number": "001", "name": "Pikachu",
        "image_url": "" if missing_artwork else "https://example.com/confirmed.jpg",
        "has_detail": not missing_price,
        "has_catalogue": not missing_price,
        "has_any_catalogue": not missing_price,
        "existing_catalogue_source": "CARDMARKET",
    }


def test_price_only_selection_disregards_missing_artwork(monkeypatch):
    monkeypatch.setattr(bulk, "cardtrader_release_titles",
                        lambda reference: {reference["set_name"]})
    # Twelve artwork-only gaps must not displace a release with three real
    # price gaps in a one-expansion market-pricing diagnostic.
    refs = [ref("alpha", missing_price=False, missing_artwork=True)
            for _ in range(12)] + [
                ref("beta", missing_price=True, missing_artwork=False)
                for _ in range(3)
            ]
    games = [{"id": 5, "name": "Pokemon"}]
    categories = [{"id": 6, "game_id": 5, "name": "Pokemon single"}]
    expansions = [
        {"id": 10, "game_id": 5, "name": "Alpha"},
        {"id": 11, "game_id": 5, "name": "Beta"},
    ]
    normal, _ = bulk.selected_releases(
        refs, games, categories, expansions, limit=1)
    pricing, _ = bulk.selected_releases(
        refs, games, categories, expansions, limit=1, pricing_only=True)
    assert normal[0][0] == "POKEMON_TCG:alpha"
    assert pricing[0][0] == "POKEMON_TCG:beta"


def test_completed_cursor_can_be_saved_without_leaking_reference_inventory():
    report = {
        "event": "DROP_RATE_PRICING_SOURCE_PREFLIGHT",
        "status": "COMPLETE", "selection": "MISSING_PRICES_ONLY",
        "next_cursor": "POKEMON_TCG:pl3", "requests": 5, "expansions": 1,
        "eligible_quotes": 0, "inventory_writes": 0,
        "store_price_writes": 0, "catalogue_price_writes": 0,
        "by_release": [{"release": "POKEMON_TCG:pl3", "references": 153,
                        "candidate_source_offers": 0, "qualified_quotes": 0,
                        "seller_username": "PRIVATE_NOT_ALLOWED"}],
    }
    safe = safe_receipt(report)
    assert safe["next_cursor"] == "POKEMON_TCG:pl3"
    assert safe["selection"] == "MISSING_PRICES_ONLY"
    assert safe["by_release"][0]["candidate_source_offers"] == 0
    assert "PRIVATE" not in str(safe)


@pytest.mark.parametrize("cursor", ["\n", "", 12, "x" * 129])
def test_untrusted_cursor_does_not_enter_receipt(cursor):
    with pytest.raises(ValueError):
        safe_receipt({
            "event": "DROP_RATE_PRICING_SOURCE_PREFLIGHT",
            "status": "COMPLETE", "next_cursor": cursor,
        })


@pytest.mark.asyncio
async def test_price_only_adapter_is_not_write_enabled():
    with pytest.raises(ValueError, match="must remain dry-run"):
        await bulk.refresh_cardtrader_expansion_guides(
            None, None, None, None, dry_run=False, pricing_only=True,
            expansion_limit=1,
        )
