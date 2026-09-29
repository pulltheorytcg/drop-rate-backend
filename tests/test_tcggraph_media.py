from pathlib import Path

from app.tcggraph_media import resolve_exact_card


ROOT = Path(__file__).parents[1]
MEDIA = ROOT / "backend" / "app" / "tcggraph_media.py"
MAIN = ROOT / "backend" / "app" / "main.py"
SETTINGS = ROOT / "backend" / "app" / "settings.py"


def local(**overrides):
    row = {
        "game": "One Piece",
        "name": "Igaram",
        "set_name": "Egghead Crisis",
        "card_number": "EB04-021",
        "variant": "Normal",
        "language": "Japanese",
        "catalogue_language": "Japanese",
    }
    row.update(overrides)
    return row


def provider(
    *,
    card_id="op_eb04_021",
    number="EB04-021",
    name="Igaram",
    game="one-piece",
    language="ja",
    printings=None,
    line=None,
    set_name="Egghead Crisis",
):
    return {
        "id": card_id,
        "game": game,
        "name": name,
        "language": language,
        "collectorNumber": number,
        "set": {"name": set_name},
        "images": {
            "large": f"https://cards.tcggraph.io/op/{card_id}/large.webp",
        },
        "printings": printings or [],
        "gameData": ({"line": line} if line else {}),
    }


def test_one_piece_normal_rejects_parallel_with_same_printed_number() -> None:
    result = resolve_exact_card(
        local(),
        [
            provider(),
            provider(card_id="op_eb04_021_p1", number="EB04-021_p1"),
        ],
    )
    assert result["resolved"] is True
    assert result["provider_id"] == "op_eb04_021"


def test_one_piece_normal_fails_when_only_parallel_exists() -> None:
    result = resolve_exact_card(
        local(),
        [provider(card_id="op_eb04_021_p1", number="EB04-021_p1")],
    )
    assert result == {
        "resolved": False,
        "reason": "no exact TCGGraph identity match",
    }


def test_pokemon_holofoil_selects_foil_printing_image() -> None:
    row = local(
        game="Pokemon",
        name="Eiscue ex",
        set_name="Ruler of the Black Flame",
        card_number="020/108",
        variant="Holofoil",
    )
    card = provider(
        card_id="pkm_sv3_020",
        number="020/108",
        name="Eiscue ex",
        game="pokemon",
        set_name="Ruler of the Black Flame",
        printings=[
            {
                "key": "normal",
                "label": "Normal",
                "images": {
                    "large": "https://cards.tcggraph.io/pkm/normal.webp"
                },
            },
            {
                "key": "foil",
                "label": "Holofoil",
                "images": {
                    "large": "https://cards.tcggraph.io/pkm/foil.webp"
                },
            },
        ],
    )
    result = resolve_exact_card(row, [card])
    assert result["resolved"] is True
    assert result["finish_key"] == "foil"
    assert result["image_url"].endswith("/foil.webp")


def test_reverse_holo_never_falls_back_to_normal_or_foil() -> None:
    row = local(
        game="Pokemon",
        name="Pikachu",
        set_name="151",
        card_number="025/165",
        variant="Reverse Holo",
    )
    card = provider(
        card_id="pkm_151_025",
        number="025/165",
        name="Pikachu",
        game="pokemon",
        set_name="151",
        printings=[
            {
                "key": "normal",
                "label": "Normal",
                "images": {"large": "https://cards.tcggraph.io/pkm/normal.webp"},
            },
            {
                "key": "foil",
                "label": "Holofoil",
                "images": {"large": "https://cards.tcggraph.io/pkm/foil.webp"},
            },
        ],
    )
    result = resolve_exact_card(row, [card])
    assert result["resolved"] is False
    assert result["reason"] == "provider finish does not match local variant"


def test_language_and_name_must_match_exactly_after_normalisation() -> None:
    wrong_language = provider(language="en")
    wrong_name = provider(name="Cobra")
    assert resolve_exact_card(local(), [wrong_language])["resolved"] is False
    assert resolve_exact_card(local(), [wrong_name])["resolved"] is False




def test_pokemon_exact_match_rechecks_provider_set_name() -> None:
    row = local(
        game="Pokemon",
        name="Pikachu",
        set_name="151",
        card_number="025/165",
        variant="Normal",
        language="English",
        catalogue_language="English",
    )
    wrong_set = provider(
        card_id="pkm_wrong_set",
        number="025/165",
        name="Pikachu",
        game="pokemon",
        language="en",
        set_name="Another Set",
    )
    result = resolve_exact_card(row, [wrong_set])
    assert result["resolved"] is False
    assert result["reason"] == "no exact TCGGraph identity match"


def test_tcggraph_images_must_come_from_documented_card_cdn() -> None:
    card = provider()
    card["images"]["large"] = "https://evil.example/card.webp"
    result = resolve_exact_card(local(), [card])
    assert result["resolved"] is False
    assert result["reason"] == "TCGGraph record has no usable HTTPS image"

    card["images"]["large"] = "https://user:pass@cards.tcggraph.io/op/card.webp"
    result = resolve_exact_card(local(), [card])
    assert result["resolved"] is False

    card["images"]["large"] = "https://cards.tcggraph.io/op/card.webp"
    result = resolve_exact_card(local(), [card])
    assert result["resolved"] is True

def test_multiple_exact_candidates_fail_closed() -> None:
    result = resolve_exact_card(
        local(),
        [
            provider(card_id="op_a"),
            provider(card_id="op_b"),
        ],
    )
    assert result["resolved"] is False
    assert result["candidate_count"] == 2


def test_dragon_ball_masters_and_fusion_world_are_line_isolated() -> None:
    masters = local(
        game="Dragon Ball Super",
        name="Vegeta",
        set_name="Example",
        card_number="FB05-039",
        variant="Normal",
        language="English",
        catalogue_language="English",
    )
    fusion = dict(masters)
    fusion["game"] = "Dragon Ball Super Fusion World"

    rows = [
        provider(
            card_id="db_masters",
            number="FB05-039",
            name="Vegeta",
            game="dragon-ball-super",
            language="en",
            line="masters",
        ),
        provider(
            card_id="db_fusion",
            number="FB05-039",
            name="Vegeta",
            game="dragon-ball-super",
            language="en",
            line="fusion-world",
        ),
    ]

    masters_result = resolve_exact_card(masters, rows)
    fusion_result = resolve_exact_card(fusion, rows)

    assert masters_result["resolved"] is True
    assert masters_result["provider_id"] == "db_masters"
    assert fusion_result["resolved"] is True
    assert fusion_result["provider_id"] == "db_fusion"


def test_dragon_ball_missing_provider_line_fails_closed() -> None:
    row = local(
        game="Dragon Ball Super Fusion World",
        name="Vegeta",
        card_number="FB05-039",
        variant="Normal",
        language="English",
        catalogue_language="English",
    )
    result = resolve_exact_card(
        row,
        [
            provider(
                card_id="db_unknown_line",
                number="FB05-039",
                name="Vegeta",
                game="dragon-ball-super",
                language="en",
            )
        ],
    )
    assert result["resolved"] is False
    assert result["reason"] == "no exact TCGGraph identity match"


def test_adapter_is_server_side_explicit_and_rights_governed() -> None:
    source = MEDIA.read_text()
    main = MAIN.read_text()
    settings = SETTINGS.read_text()

    assert 'TCGGRAPH_TERMS_URL = "https://tcggraph.com/legal/terms"' in source
    assert "STOREFRONT_ALLOWED" in source
    assert "UK_SALE_ADVERTISING_URL" in source
    assert "legislation.gov.uk/ukpga/1988/48/section/63" in source
    assert "Not approved for social media" in source
    assert "'PENDING'" in source
    assert "LICENSED_PROVIDER" in source
    assert "permission_evidence_url" in source
    assert "provider_asset_id" in source
    assert "physical_photo_policy" in source
    assert "TCGGRAPH_IMAGE_HOSTS" in source
    assert "cards.tcggraph.io" in source
    assert '"dragon ball super fusion world": "dragon-ball-super"' in source
    assert '"dragon ball super fusion world": "fusion-world"' in source
    assert "line=game_line" in source
    assert "on conflict do nothing" in source.casefold()
    assert 'TCG_TCGGRAPH_API_KEY' in settings
    assert "tcggraph_media_router" in main
    assert "require_platform_admin_request" in main


def test_tcggraph_listing_rights_never_bypass_human_media_approval() -> None:
    source = MEDIA.read_text()
    resolve_start = source.index('@router.post("/resolve")')
    sync_start = source.index('@router.post("/sync-shopify")')
    resolve_block = source[resolve_start:sync_start]

    assert "'STOREFRONT_ALLOWED','TCGGraph'" in resolve_block
    assert "'VERIFIED',$9,'PENDING'" in resolve_block
    assert "approved_by_user_id,approved_at" in resolve_block
    assert "$11,null,null" in resolve_block
    assert "approval remains required before Shopify use" in resolve_block


def test_tcggraph_shopify_sync_is_bulk_and_never_publishes_products() -> None:
    source = MEDIA.read_text()
    assert '@router.post("/sync-shopify")' in source
    assert "create_file_from_url" in source
    assert "get_file" in source
    assert '"product_publications": 0' in source
    sync_start = source.index('@router.post("/sync-shopify")')
    sync_block = source[sync_start:]
    assert "create_product(" not in sync_block
    assert "publish_product(" not in sync_block


def test_tcggraph_remains_optional_backend_fallback_not_primary_ui() -> None:
    ui = (ROOT / "backend" / "app" / "static" / "media-condition.js").read_text()
    source = MEDIA.read_text()

    assert '@router.get("/status")' in source
    assert '@router.post("/resolve")' in source
    assert '@router.post("/sync-shopify")' in source
    assert "TCGGraph images" not in ui
    assert "/api/v1/media/tcggraph/status" not in ui
    assert "/api/v1/media/free/status" in ui
