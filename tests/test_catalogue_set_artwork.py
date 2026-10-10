"""Set-title artwork must be explicit, deterministic, provenance-bound and safe."""
from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from app import catalogue_browser, catalogue_set_artwork as artwork

ROOT = Path(__file__).parents[1]
STATIC = ROOT / "backend" / "app" / "static"


def _snapshot(js: str, variable: str) -> dict:
    match = re.search(r"const " + re.escape(variable) + r" = (\{.*?\n\});", js, re.S)
    assert match is not None, f"Missing static navigation lookup {variable}"
    return json.loads(match.group(1).removesuffix(";"))


def test_resolver_registry_exactly_matches_original_navigation_index():
    # The existing refreshed JS lookup and the backend's registry cannot drift
    # silently, including when an index refresh adds new set logos.
    js = (STATIC / "catalogue-title-art.js").read_text(encoding="utf-8")
    source = json.loads((STATIC / "title-art" / "sources.json").read_text(encoding="utf-8"))
    registry = artwork._registry()
    in_browser = _snapshot(js, "data")
    indexed = _snapshot(js, "providerSets")
    assert registry["games"] == in_browser["games"]
    assert registry["bundled_sets"] == in_browser["sets"] == source["sets"]
    assert registry["provider_sets"]["TCGdex"] == indexed
    assert registry["provider_index_evidence"] == source["provider_set_logos"]
    assert registry["schema_version"] == 1
    assert registry["purpose"].startswith("Seller Hub/Founder HQ")
    assert "source_reference" in registry["pending_review"][0]


@pytest.mark.parametrize("row,art_type,source,part", [
    ({"system_code": "POKEMON_TCG", "language": "English", "provider": "TCGdex", "set_id": "me05", "set_name": "Pitch Black"},
     "SET_LOGO", "BUNDLED_PUBLISHER", "pokemon-mega-evolution-pitch-black.png"),
    ({"system_code": "POKEMON_TCG", "language": "English", "provider": "TCGdex", "set_id": "base1", "set_name": "Base Set"},
     "SET_LOGO", "TCGDEX", "en/base/base1/logo.webp"),
    ({"system_code": "POKEMON_TCG", "language": "English", "provider": "TCGdex", "set_id": "A3b", "set_name": "Eevee Grove"},
     "GAME_LOGO", "OFFICIAL_GAME_MARK", "pokemon.webp"),
    ({"system_code": "POKEMON_TCG", "language": "Japanese", "provider": "TCGdex", "set_id": "base1", "set_name": "Base Set"},
     "GAME_LOGO", "OFFICIAL_GAME_MARK", "pokemon.webp"),
    ({"system_code": "ONE_PIECE_CARD_GAME", "language": "Japanese", "provider": "Punk Records", "set_id": "550113", "set_name": "受け継がれる意志"},
     "SET_LOGO", "BUNDLED_PUBLISHER", "op13-ja.webp"),
    ({"system_code": "NARUTO_KAYOU", "language": "Unknown", "provider": "Naruto Card Game Archive", "set_id": "test", "set_name": "Unknown Naruto set"},
     "GAME_LOGO", "OFFICIAL_GAME_MARK", "naruto.svg"),
    ({"system_code": "NOT_A_REAL_SYSTEM", "language": "Unknown", "provider": "Unknown", "set_id": "?", "set_name": "Unknown release"},
     "BRANDED_FALLBACK", "DROP_RATE_FALLBACK", None),
])
def test_set_artwork_exact_or_safe_fallback(row, art_type, source, part):
    resolved = artwork.resolve_set_artwork(row)
    assert resolved["type"] == art_type
    assert resolved["source"] == source
    assert resolved["status"] == ("SOURCE_INDEXED" if art_type == "SET_LOGO" else "SET_LOGO_MISSING")
    if part is not None:
        assert part in (resolved.get("url") or resolved.get("file") or "")
    assert "card_preview" not in repr(resolved).lower()
    assert "image_url" not in resolved


def test_malicious_path_and_unlisted_source_fail_closed(monkeypatch):
    assert artwork._file("../../etc/passwd") is None
    assert artwork._file("https://example.net/image.png") is None
    assert artwork._provider_logo("http://assets.tcgdex.net/en/base/base1/logo.webp") is None
    assert artwork._provider_logo("https://attacker.net/en/base/base1/logo.webp") is None
    assert artwork._provider_logo("https://assets.tcgdex.net/en/base/base1/logo.webp?key=x") is None
    assert artwork._provider_logo("https://assets.tcgdex.net/en/base/base1/high.webp") is None
    poisoned = {
        "games": {}, "bundled_sets": [],
        "provider_sets": {"TCGdex": {"English": {
            "base1": {"url": "https://attacker.net/evil-card.png", "title": "Base Set"}}}},
    }
    monkeypatch.setattr(artwork, "_registry", lambda: poisoned)
    row = {"system_code": "POKEMON_TCG", "provider": "TCGdex", "set_id": "base1",
           "language": "English", "set_name": "Base Set"}
    assert artwork.resolve_set_artwork(row)["type"] == "BRANDED_FALLBACK"


def test_stored_set_metadata_removes_card_preview_and_adds_typed_artwork():
    row = {
        "system_code": "POKEMON_TCG", "set_id": "A3b", "set_name": "Eevee Grove",
        "language": "English", "provider": "TCGdex",
        "release_date": "2025-06-26", "owned_count": 0, "card_count": 107,
        "image_url": "https://example.org/bulbasaur-card.png",
        "fallback_image_url": "https://example.org/mislabeled-pack.png",
        "reference_image_path": "/api/v1/catalogue-browser/reference-image",
        "provider_id": "A3b-1", "source_kind": "REFERENCE",
    }
    result = catalogue_browser.set_metadata_only(row)
    assert result["artwork"]["type"] == "GAME_LOGO"
    assert result["artwork"]["status"] == "SET_LOGO_MISSING"
    for forbidden in ("image_url", "display_image_url", "fallback_image_url",
                      "reference_image_path", "source_kind", "provider_id"):
        assert forbidden not in result
    assert result["set_id"] == "A3b" and result["card_count"] == 107
    assert row["image_url"].endswith("bulbasaur-card.png")


def test_artwork_coverage_groups_missing_and_indexed_sources_without_guessing():
    common = {"system_code": "POKEMON_TCG", "language": "English", "provider": "TCGdex"}
    rows = [
        {**common, "set_id": "base1", "set_name": "Base Set"},
        {**common, "set_id": "A3b", "set_name": "Eevee Grove"},
        {**common, "set_id": "A3a", "set_name": "Extradimensional Crisis"},
        {"system_code": "ONE_PIECE_CARD_GAME", "language": "English", "provider": "Punk Records",
         "set_id": "569113", "set_name": "Carrying on His Will"},
    ]
    report = artwork.artwork_coverage(rows, missing_limit=1)
    assert report["scope"] == "SET_REFERENCE_RECORDS_NOT_DISTINCT_RELEASES"
    assert report["total"] == 4
    assert report["indexed_set_logos"] == 2
    assert report["missing_set_logos"] == 2
    assert report["coverage"] == 0.5
    assert report["missing_returned"] == 1
    assert len(report["missing"]) == 1
    assert report["missing"][0]["set_id"] == "A3b"
    assert any(x["set_id"] == "A3b" and x["status"].startswith("SOURCE_FOUND") for x in report["manual_review"])
    assert sum(x["total"] for x in report["groups"]) == 4


@pytest.mark.asyncio
@pytest.mark.parametrize("role,authorized,expected", [
    ("PLATFORM_ADMIN", True, 200),
    ("OWNER", False, 403),
    ("PLATFORM_ADMIN", False, 403),
])
async def test_coverage_endpoint_is_founder_only(monkeypatch, role, authorized, expected):
    from contextlib import asynccontextmanager
    from types import SimpleNamespace
    from uuid import uuid4
    import httpx
    from fastapi import FastAPI
    from app import access_control
    from app.auth import require_user

    user_id, owner_id = uuid4(), uuid4()
    rows = [
        {"system_code": "POKEMON_TCG", "provider": "TCGdex",
         "language": "English", "set_id": "base1", "set_name": "Base Set"},
        {"system_code": "POKEMON_TCG", "provider": "TCGdex",
         "language": "English", "set_id": "A3b", "set_name": "Eevee Grove"},
    ]
    calls = []

    class Connection:
        async def fetch(self, sql, *args):
            calls.append(sql)
            if "from tcg.owner_memberships m" in sql:
                return [{"user_id": user_id, "owner_id": owner_id, "role": role,
                         "founder_authorized": authorized, "owner_type": "FOUNDER" if authorized else "CONSIGNOR",
                         "display_name": "Test", "founder_slot": 1 if authorized else None}]
            if "from tcg.reference_sets" in sql:
                assert args == (False, ["POKEMON_TCG"])
                return rows
            raise AssertionError("Unexpected SQL query")

    @asynccontextmanager
    async def connection(*args):
        yield Connection()

    monkeypatch.setattr(catalogue_browser, "user_connection", connection)
    monkeypatch.setattr(access_control, "user_connection", connection)
    app = FastAPI()
    app.state.db_pool = object()
    app.include_router(catalogue_browser.router)
    app.dependency_overrides[require_user] = lambda: SimpleNamespace(user_id=user_id)

    @app.middleware("http")
    async def request_id(request, call_next):
        request.state.request_id = "set-artwork-coverage-test"
        return await call_next(request)

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),
                                 base_url="http://test") as client:
        response = await client.get(
            "/api/v1/catalogue-browser/set-artwork-coverage?system_code=POKEMON_TCG&missing_limit=2"
        )
    assert response.status_code == expected
    if expected == 200:
        data = response.json()
        assert data["scope"] == "SET_REFERENCE_RECORDS_NOT_DISTINCT_RELEASES"
        assert data["total"] == 2 and data["indexed_set_logos"] == 1
        assert data["missing_set_logos"] == 1
        assert data["missing"][0]["set_name"] == "Eevee Grove"
        assert len(calls) == 2
    else:
        assert all("from tcg.reference_sets" not in query for query in calls)
