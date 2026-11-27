"""Fail-closed guards against wrong art, placeholder product facts and silent 500s."""
import logging
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.cardtrader_media import resolve_blueprint
from app.punk_records_client import PunkRecordsClient
from app.shopify_completeness import product_description_html, product_tags, product_title
from app.tcggraph_media import resolve_exact_card

ROOT = Path(__file__).parents[1] / "backend" / "app"


# --- One Piece Japanese art: base art never stands in for special printings.

class _NoNetworkPunk(PunkRecordsClient):
    async def _cards_index(self, *args, **kwargs):  # pragma: no cover - must not be reached
        raise AssertionError("special printings must be refused before any provider lookup")


@pytest.mark.asyncio
@pytest.mark.parametrize("kwargs", [
    dict(name="Monkey.D.Luffy (Promo)", variant="Normal"),
    dict(name="Monkey.D.Luffy", variant="Normal", set_name="Pre-Release Romance Dawn"),
    dict(name="Monkey.D.Luffy", variant="Normal", set_name="Promotion Cards"),
    dict(name="Monkey.D.Luffy (Winner)", variant="Normal"),
    dict(name="Monkey.D.Luffy SP", variant="Normal"),
    dict(name="Monkey.D.Luffy (Championship 2025)", variant="Normal"),
    dict(name="Monkey.D.Luffy", variant="Stamped"),
])
async def test_punk_records_refuses_promo_stamped_and_event_printings(kwargs):
    result = await _NoNetworkPunk().resolve_japanese_card(card_number="OP01-001", **kwargs)
    assert result["resolved"] is False
    assert "explicit provider" in result["reason"]


@pytest.mark.parametrize("name", ["Spandam", "Gold Roger", "Special Forces"])
def test_special_treatment_markers_are_whole_words_only(name):
    from app.punk_records_client import _special_treatment
    # "Spandam" must not trip "sp"; real names containing marker words are
    # refused (fail closed) only when the marker is a whole word.
    expected = name != "Spandam"
    assert _special_treatment(name) is expected


# --- CardTrader: English blueprint art is never Japanese exact-print proof.

def _ct(language, expansion="Fusion World: Wish For Shenron"):
    return resolve_blueprint(
        {"game": "Dragon Ball Super Fusion World", "set_name": "Wish For Shenron", "name": "Son Goku",
         "card_number": "FB06-001", "language": language, "variant": "Normal"},
        games=[{"id": 16, "name": "Dragon Ball Super"}],
        expansions=[{"id": 131, "game_id": 16, "name": expansion}],
        blueprints=[{"id": 3001, "game_id": 16, "expansion_id": 131, "name": "Son Goku", "version": None,
                     "image_url": "https://images.cardtrader.com/cards/3001.jpg",
                     "fixed_properties": {"collector_number": "FB06-001"}}],
    )


def test_cardtrader_japanese_copy_never_gets_shared_blueprint_art():
    result = _ct("Japanese")
    assert result == {"resolved": False,
                      "reason": "CardTrader blueprint art is not language-specific for this printing"}


def test_cardtrader_english_copy_still_resolves():
    assert _ct("English")["resolved"] is True


# --- TCGGraph: reprints that share a number must not take another set's art.

def _tg(provider_set, local_set="Romance Dawn [OP-01]"):
    local = {"game": "One Piece", "name": "Roronoa Zoro", "set_name": local_set, "card_number": "OP01-025",
             "variant": "Normal", "language": "Japanese", "catalogue_language": "Japanese"}
    card = {"id": "op01_025", "game": "one-piece", "name": "Roronoa Zoro", "language": "ja",
            "collectorNumber": "OP01-025", "set": {"name": provider_set},
            "images": {"large": "https://cards.tcggraph.io/op/op01_025/large.webp"}, "printings": [], "gameData": {}}
    return resolve_exact_card(local, [card])


def test_tcggraph_rejects_other_set_for_non_pokemon():
    assert _tg("Premium Booster The Best")["resolved"] is False


def test_tcggraph_accepts_differently_formatted_same_set():
    assert _tg("Romance Dawn")["resolved"] is True


# --- Shopify copy: placeholders are never product facts.

def _card(**overrides):
    item = {"product_type": "CARD", "game": "Pokemon", "name": "Pikachu", "set_name": "Base Set",
            "card_number": "58/102", "variant": "Normal", "rarity": "Unknown", "language": "English",
            "condition": "Near Mint", "inventory_code": "DR-1"}
    item.update(overrides)
    return item


def test_unknown_rarity_is_omitted_from_description_and_tags():
    assert "Rarity" not in product_description_html(_card())
    assert not any(tag.startswith("Rarity:") for tag in product_tags(_card()))
    assert "Rarity:</strong> Common" in product_description_html(_card(rarity="Common"))
    assert "Rarity:Common" in product_tags(_card(rarity="Common"))


def test_unknown_language_is_not_printed_in_titles_or_tags():
    item = _card(language="Unknown", catalogue_language=None, product_type="SEALED", rarity=None)
    assert "Unknown" not in product_title(item)
    assert not any(tag == "Language:Unknown" for tag in product_tags(item))


def test_publication_treats_unknown_language_as_missing():
    source = (ROOT / "shopify_pipeline.py").read_text(encoding="utf-8")
    assert 'in {"", "unknown"}:\n            missing.append("card language")' in source


# --- Images: the official Japanese Pokémon host and TCGGraph CDN are allowed.

def test_csp_allows_reference_image_hosts_loaded_directly():
    main = (ROOT / "main.py").read_text(encoding="utf-8")
    assert "https://www.pokemon-card.com" in main and "https://cards.tcggraph.io" in main


# --- 500s always leave a trace, without exception text.

def test_unhandled_errors_are_logged_without_message_text(caplog):
    from app.main import _log_unhandled

    app = FastAPI()

    @app.get("/boom")
    async def boom():
        raise RuntimeError("secret-token-123 in provider payload")

    @app.middleware("http")
    async def wrap(request, call_next):
        try:
            return await call_next(request)
        except Exception as exc:
            _log_unhandled(request, "req-1", exc)
            raise

    with caplog.at_level(logging.ERROR, logger="app.main"):
        with pytest.raises(RuntimeError):
            TestClient(app).get("/boom")
    assert "UNHANDLED_REQUEST_ERROR request_id=req-1 method=GET path=/boom type=RuntimeError" in caplog.text
    assert "location=test_stop_wrong_output.py:boom:" in caplog.text
    assert "secret-token-123" not in caplog.text


# --- Catalogue art and release dates (SQL guards, exercised in Postgres CI).

def test_catalogue_media_queries_require_exact_variant_and_no_language_mismatch():
    source = (ROOT / "catalogue_browser.py").read_text(encoding="utf-8")
    assert source.count("lower(btrim(coalesce(m.media_variant,'')))=") == 2
    assert "join tcg.catalogue_products media_product on media_product.id=m.catalogue_id" in source
    media = (ROOT / "inventory_reference_media.py").read_text(encoding="utf-8")
    assert "nullif(btrim(coalesce(i.language,p.language,'')),'') is not null" in media


def test_reference_refresh_keeps_known_release_dates():
    source = (ROOT / "reference_library.py").read_text(encoding="utf-8")
    assert "release_date=coalesce(excluded.release_date,tcg.reference_sets.release_date)" in source
