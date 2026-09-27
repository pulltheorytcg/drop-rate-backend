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
):
    return {
        "id": card_id,
        "game": game,
        "name": name,
        "language": language,
        "collectorNumber": number,
        "set": {"name": "Egghead Crisis"},
        "images": {
            "large": f"https://cards.tcggraph.io/op/{card_id}/large.webp",
        },
        "printings": printings or [],
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


def test_adapter_is_server_side_explicit_and_rights_governed() -> None:
    source = MEDIA.read_text()
    main = MAIN.read_text()
    settings = SETTINGS.read_text()

    assert 'TCGGRAPH_TERMS_URL = "https://tcggraph.com/legal/terms"' in source
    assert '"STOREFRONT_ALLOWED"' in source
    assert "'LICENSED_PROVIDER'" in source
    assert "permission_evidence_url" in source
    assert "provider_asset_id" in source
    assert "physical_photo_policy" in source
    assert "on conflict do nothing" in source.casefold()
    assert 'TCG_TCGGRAPH_API_KEY' in settings
    assert "tcggraph_media_router" in main
    assert "require_platform_admin_request" in main
