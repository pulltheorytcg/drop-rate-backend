from pathlib import Path

import pytest

from app.punk_records_client import PunkRecordsClient
from app.tcgdex_client import TcgDexClient


ROOT = Path(__file__).parents[1]
FREE_MEDIA = ROOT / "backend" / "app" / "free_canonical_media.py"
MAIN = ROOT / "backend" / "app" / "main.py"
UI = ROOT / "backend" / "app" / "static" / "media-condition.js"


@pytest.mark.asyncio
async def test_tcgdex_resolves_english_alias_to_japanese_card_image(monkeypatch) -> None:
    client = TcgDexClient()

    async def fake_aliases():
        return {"ruler of the black flame": "SV3"}

    async def fake_get(path, *, params=None):
        assert params is None
        assert path in {"/ja/sets/SV3/020", "/ja/sets/SV3/20"}
        return {
            "id": "sv3-20",
            "localId": "20",
            "name": "コオリッポex",
            "image": "https://assets.tcgdex.net/ja/sv/sv3/20",
            "set": {
                "id": "SV3",
                "name": "黒炎の支配者",
                "cardCount": {"official": 108, "total": 108},
            },
            "variants": [
                {"type": "holo"},
            ],
        }

    monkeypatch.setattr(client, "_japanese_set_aliases", fake_aliases)
    monkeypatch.setattr(client, "_get_json", fake_get)
    result = await client.resolve_japanese_card(
        set_name="Ruler of the Black Flame",
        card_number="020/108",
        variant="Holofoil",
    )

    assert result["resolved"] is True
    assert result["provider"] == "TCGdex"
    assert result["provider_id"] == "sv3-20"
    assert result["provider_set_id"] == "SV3"
    assert result["finish_key"] == "holo"
    assert result["image_url"] == "https://assets.tcgdex.net/ja/sv/sv3/20/high.webp"


@pytest.mark.asyncio
async def test_tcgdex_also_accepts_boolean_variant_shape(monkeypatch) -> None:
    client = TcgDexClient()

    async def fake_aliases():
        return {"ruler of the black flame": "SV3"}

    async def fake_get(path, *, params=None):
        return {
            "id": "sv3-20",
            "localId": "20",
            "image": "https://assets.tcgdex.net/ja/sv/sv3/20",
            "set": {
                "id": "sv3",
                "cardCount": {"official": 108, "total": 108},
            },
            "variants": {"normal": False, "holo": True, "reverse": False},
        }

    monkeypatch.setattr(client, "_japanese_set_aliases", fake_aliases)
    monkeypatch.setattr(client, "_get_json", fake_get)

    result = await client.resolve_japanese_card(
        set_name="Ruler of the Black Flame",
        card_number="020/108",
        variant="Holofoil",
    )
    assert result["resolved"] is True


@pytest.mark.asyncio
async def test_tcgdex_rejects_wrong_japanese_set_card_count(monkeypatch) -> None:
    client = TcgDexClient()

    async def fake_aliases():
        return {"ruler of the black flame": "SV3"}

    async def fake_get(path, *, params=None):
        return {
            "id": "sv3-20",
            "localId": "20",
            "image": "https://assets.tcgdex.net/ja/sv/sv3/20",
            "set": {
                "id": "SV3",
                "cardCount": {"official": 109, "total": 109},
            },
            "variants": {"normal": False, "holo": True, "reverse": False},
        }

    monkeypatch.setattr(client, "_japanese_set_aliases", fake_aliases)
    monkeypatch.setattr(client, "_get_json", fake_get)
    result = await client.resolve_japanese_card(
        set_name="Ruler of the Black Flame",
        card_number="020/108",
        variant="Holofoil",
    )
    assert result["resolved"] is False
    assert result["reason"] == "TCGdex Japanese set card-count mismatch"


@pytest.mark.asyncio
async def test_tcgdex_rejects_finish_mismatch(monkeypatch) -> None:
    client = TcgDexClient()

    async def fake_aliases():
        return {"ruler of the black flame": "SV3"}

    async def fake_get(path, *, params=None):
        return {
            "id": "sv3-20",
            "localId": "20",
            "image": "https://assets.tcgdex.net/ja/sv/sv3/20",
            "set": {
                "id": "SV3",
                "cardCount": {"official": 108, "total": 108},
            },
            "variants": {
                "normal": True,
                "holo": False,
                "reverse": False,
            },
        }

    monkeypatch.setattr(client, "_japanese_set_aliases", fake_aliases)
    monkeypatch.setattr(client, "_get_json", fake_get)
    result = await client.resolve_japanese_card(
        set_name="Ruler of the Black Flame",
        card_number="020/108",
        variant="Holofoil",
    )
    assert result["resolved"] is False
    assert result["reason"] == "TCGdex card does not support holo finish"


@pytest.mark.asyncio
async def test_tcgdex_parses_maintained_japanese_set_translation_map(monkeypatch) -> None:
    client = TcgDexClient()

    async def fake_text(url):
        return """export const jpSetTranslationsMap = new Map<string, string>([
  ['SV3', 'Ruler of the Black Flame'],
  ['SV4a', 'Shiny Treasure ex'],
  ['SV4M', 'Future Flash'],
  ['SV8a', 'Terastal Festival ex'],
]);"""

    monkeypatch.setattr(client, "_get_text_url", fake_text)
    aliases = await client._japanese_set_aliases()

    assert aliases["ruler of the black flame"] == "SV3"
    assert aliases["shiny treasure ex"] == "SV4a"
    assert aliases["future flash"] == "SV4M"
    assert aliases["terastal festival ex"] == "SV8a"


@pytest.mark.asyncio
async def test_punk_records_resolves_only_unsuffixed_normal_one_piece_card(monkeypatch) -> None:
    client = PunkRecordsClient()

    async def fake_index():
        return {
            "EB04-021": {
                "name": "イガラム",
                "card_id": "EB04-021",
                "pack_id": "550204",
            },
            "EB04-021_p1": {
                "name": "イガラム",
                "card_id": "EB04-021_p1",
                "pack_id": "550204",
            },
        }

    async def fake_get(path):
        assert path == "/japanese/cards/550204/EB04-021.json"
        return {
            "id": "EB04-021",
            "pack_id": "550204",
            "name": "イガラム",
            "img_full_url": "https://www.onepiece-cardgame.com/images/cardlist/card/EB04-021.png?2602273",
        }

    monkeypatch.setattr(client, "_cards_index", fake_index)
    monkeypatch.setattr(client, "_get_json", fake_get)

    result = await client.resolve_japanese_card(
        card_number="EB04-021",
        variant="Normal",
    )
    assert result["resolved"] is True
    assert result["provider"] == "Punk Records"
    assert result["provider_id"] == "EB04-021"
    assert "_p1" not in result["provider_id"]
    assert result["image_url"].startswith(
        "https://www.onepiece-cardgame.com/images/cardlist/card/"
    )


@pytest.mark.asyncio
async def test_punk_records_fails_closed_for_unmapped_parallel_variant() -> None:
    client = PunkRecordsClient()
    result = await client.resolve_japanese_card(
        card_number="EB04-021",
        variant="Parallel",
    )
    assert result == {
        "resolved": False,
        "reason": "One Piece alternate-art variant requires explicit mapping",
    }


@pytest.mark.asyncio
async def test_punk_records_rejects_untrusted_image_host(monkeypatch) -> None:
    client = PunkRecordsClient()

    async def fake_index():
        return {
            "EB04-021": {
                "card_id": "EB04-021",
                "pack_id": "550204",
            }
        }

    async def fake_get(path):
        return {
            "id": "EB04-021",
            "img_full_url": "https://evil.example/EB04-021.png",
        }

    monkeypatch.setattr(client, "_cards_index", fake_index)
    monkeypatch.setattr(client, "_get_json", fake_get)

    result = await client.resolve_japanese_card(
        card_number="EB04-021",
        variant="Normal",
    )
    assert result["resolved"] is False
    assert "trusted One Piece host" in result["reason"]


def test_free_media_router_is_provider_neutral_no_key_and_fail_closed() -> None:
    source = FREE_MEDIA.read_text()
    main = MAIN.read_text()

    assert '@router.get("/status")' in source
    assert '@router.post("/resolve")' in source
    assert '@router.post("/sync-shopify")' in source
    assert '"TCGdex"' in source
    assert '"Punk Records"' in source
    assert '"api_key_required": False' in source
    assert "physical_photo_policy" in source
    assert "on conflict do nothing" in source.casefold()
    assert "STOREFRONT_ALLOWED" in source
    assert "LEGAL_BASIS_URL" in source
    assert "free_canonical_media_router" in main
    assert "require_platform_admin_request" in main


def test_free_shopify_sync_stages_files_but_never_publishes_products() -> None:
    source = FREE_MEDIA.read_text()
    sync_start = source.index('@router.post("/sync-shopify")')
    block = source[sync_start:]

    assert "create_file_from_url" in block
    assert "get_file" in block
    assert '"product_publications": 0' in block
    assert "create_product(" not in block
    assert "publish_product(" not in block


def test_media_workspace_uses_free_providers_as_primary_workflow() -> None:
    ui = UI.read_text()

    assert "Free canonical images" in ui
    assert "Pokémon uses TCGdex" in ui
    assert "Punk Records" in ui
    assert "/api/v1/media/free/status" in ui
    assert "/api/v1/media/free/resolve" in ui
    assert "/api/v1/media/free/sync-shopify" in ui
    assert "Preview matches" in ui
    assert "Import exact matches" in ui
    assert "Sync images to Shopify" in ui
    assert "No products were published" in ui
    assert "TCGGraph images" not in ui
