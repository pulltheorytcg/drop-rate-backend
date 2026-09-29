from app.cardtrader_media import resolve_blueprint


def _games():
    return [{"id": 16, "name": "Dragon Ball Super"}]


def test_cardtrader_resolves_exact_masters_blueprint() -> None:
    result = resolve_blueprint(
        {
            "game": "Dragon Ball Super",
            "set_name": "Supreme Rivalry",
            "name": "King Vegeta",
            "card_number": "BT13-002",
            "language": "English",
            "variant": "Normal",
        },
        games=_games(),
        expansions=[
            {"id": 130, "game_id": 16, "name": "Supreme Rivalry"},
            {"id": 131, "game_id": 16, "name": "Fusion World: Wish For Shenron"},
        ],
        blueprints=[
            {
                "id": 2001,
                "game_id": 16,
                "expansion_id": 130,
                "name": "King Vegeta",
                "version": None,
                "image_url": "https://images.cardtrader.com/cards/2001.jpg",
                "fixed_properties": {"collector_number": "BT13-002"},
            }
        ],
    )

    assert result["resolved"] is True
    assert result["provider_id"] == "2001"
    assert result["collector_number"] == "BT13-002"
    assert result["provider_set"] == "Supreme Rivalry"
    assert result["game_line"] == "masters"


def test_cardtrader_keeps_fusion_world_isolated_from_masters() -> None:
    result = resolve_blueprint(
        {
            "game": "Dragon Ball Super Fusion World",
            "set_name": "Wish For Shenron",
            "name": "Son Goku",
            "card_number": "FB07-010",
            "language": "English",
            "variant": "Foil",
        },
        games=_games(),
        expansions=[
            {"id": 210, "game_id": 16, "name": "Wish For Shenron"},
            {"id": 211, "game_id": 16, "name": "Fusion World: Wish For Shenron"},
        ],
        blueprints=[
            {
                "id": 3001,
                "game_id": 16,
                "expansion_id": 211,
                "name": "Son Goku",
                "version": "FB07-010",
                "image_url": "https://cdn.cardtrader.com/cards/3001.webp",
            },
            {
                "id": 3002,
                "game_id": 16,
                "expansion_id": 210,
                "name": "Son Goku",
                "version": "BT07-010",
                "image_url": "https://cdn.cardtrader.com/cards/3002.webp",
            },
        ],
    )

    assert result["resolved"] is True
    assert result["provider_id"] == "3001"
    assert result["collector_number"] == "FB07-010"
    assert result["game_line"] == "fusion-world"


def test_cardtrader_marketplace_row_can_supply_missing_collector_number() -> None:
    result = resolve_blueprint(
        {
            "game": "Dragon Ball Super",
            "set_name": "Perfect Combination",
            "name": "Son Gohan",
            "card_number": "BT23-048",
            "language": "English",
            "variant": "Normal",
        },
        games=_games(),
        expansions=[{"id": 230, "game_id": 16, "name": "Perfect Combination"}],
        blueprints=[
            {
                "id": 4001,
                "game_id": 16,
                "expansion_id": 230,
                "name": "Son Gohan",
                "version": None,
                "image_url": "https://img.cardtrader.com/cards/4001.jpg",
            }
        ],
        marketplace_rows={
            4001: [
                {
                    "blueprint_id": 4001,
                    "properties_hash": {
                        "collector_number": "BT23-048",
                        "dbs_language": "en",
                    },
                }
            ]
        },
    )

    assert result["resolved"] is True
    assert result["provider_id"] == "4001"


def test_cardtrader_rejects_wrong_collector_number() -> None:
    result = resolve_blueprint(
        {
            "game": "Dragon Ball Super",
            "set_name": "Supreme Rivalry",
            "name": "King Vegeta",
            "card_number": "BT13-002",
            "language": "English",
            "variant": "Normal",
        },
        games=_games(),
        expansions=[{"id": 130, "game_id": 16, "name": "Supreme Rivalry"}],
        blueprints=[
            {
                "id": 2001,
                "game_id": 16,
                "expansion_id": 130,
                "name": "King Vegeta",
                "image_url": "https://images.cardtrader.com/cards/2001.jpg",
                "fixed_properties": {"collector_number": "BT13-020"},
            }
        ],
    )

    assert result["resolved"] is False
    assert "card-number evidence" in result["reason"]


def test_cardtrader_rejects_unknown_image_host() -> None:
    result = resolve_blueprint(
        {
            "game": "Dragon Ball Super",
            "set_name": "Supreme Rivalry",
            "name": "King Vegeta",
            "card_number": "BT13-002",
            "language": "English",
            "variant": "Normal",
        },
        games=_games(),
        expansions=[{"id": 130, "game_id": 16, "name": "Supreme Rivalry"}],
        blueprints=[
            {
                "id": 2001,
                "game_id": 16,
                "expansion_id": 130,
                "name": "King Vegeta",
                "image_url": "https://example.com/card.jpg",
                "fixed_properties": {"collector_number": "BT13-002"},
            }
        ],
    )

    assert result["resolved"] is False


def test_cardtrader_requires_confirmed_physical_language() -> None:
    result = resolve_blueprint(
        {
            "game": "Dragon Ball Super",
            "set_name": "Supreme Rivalry",
            "name": "King Vegeta",
            "card_number": "BT13-002",
            "language": None,
            "variant": "Normal",
        },
        games=_games(),
        expansions=[{"id": 130, "game_id": 16, "name": "Supreme Rivalry"}],
        blueprints=[],
    )

    assert result == {
        "resolved": False,
        "reason": "physical card language is not confirmed",
    }



def test_cardtrader_matches_tournament_and_championship_ampersand_alias() -> None:
    result = resolve_blueprint(
        {
            "game": "Dragon Ball Super Fusion World",
            "set_name": "Tournament and Championship Promos",
            "name": "Vegeta (Tournament Pack -Winner- 06)",
            "card_number": "FB05-039",
            "language": "English",
            "variant": "Foil",
        },
        games=_games(),
        expansions=[
            {
                "id": 4300,
                "game_id": 16,
                "name": "Tournament & Championship Promos",
            }
        ],
        blueprints=[
            {
                "id": 5001,
                "game_id": 16,
                "expansion_id": 4300,
                "name": "Vegeta (Tournament Pack -Winner- 06)",
                "version": "FB05-039",
                "image_url": "https://cardtrader.com/uploads/blueprints/image/5001/preview.jpg",
            }
        ],
    )

    assert result["resolved"] is True
    assert result["provider_set"] == "Tournament & Championship Promos"
    assert result["collector_number"] == "FB05-039"
    assert result["game_line"] == "fusion-world"


def test_cardtrader_prerelease_falls_back_to_base_only_with_version_proof() -> None:
    local = {
        "game": "Dragon Ball Super",
        "set_name": "Supreme Rivalry Pre-Release Cards",
        "name": "Trunks, Thwarting the Dark Empire",
        "card_number": "BT13-131",
        "language": "English",
        "variant": "Normal",
    }
    expansions = [{"id": 2651, "game_id": 16, "name": "Supreme Rivalry"}]

    proven = resolve_blueprint(
        local,
        games=_games(),
        expansions=expansions,
        blueprints=[
            {
                "id": 184778,
                "game_id": 16,
                "expansion_id": 2651,
                "name": "Trunks, Thwarting the Dark Empire",
                "version": "Pre-Release BT13-131",
                "image_url": "https://cardtrader.com/uploads/blueprints/image/184778/preview.jpg",
            }
        ],
    )
    assert proven["resolved"] is True

    unproven = resolve_blueprint(
        local,
        games=_games(),
        expansions=expansions,
        blueprints=[
            {
                "id": 184779,
                "game_id": 16,
                "expansion_id": 2651,
                "name": "Trunks, Thwarting the Dark Empire",
                "version": "BT13-131",
                "image_url": "https://cardtrader.com/uploads/blueprints/image/184779/preview.jpg",
            }
        ],
    )
    assert unproven["resolved"] is False


def test_cardtrader_base_print_rejects_prerelease_blueprint() -> None:
    result = resolve_blueprint(
        {
            "game": "Dragon Ball Super",
            "set_name": "Dawn of the Z-Legends",
            "name": "Vegeta, Another World Warrior",
            "card_number": "BT18-035",
            "language": "English",
            "variant": "Normal",
        },
        games=_games(),
        expansions=[{"id": 3120, "game_id": 16, "name": "Dawn of the Z-Legends"}],
        blueprints=[
            {
                "id": 6101,
                "expansion_id": 3120,
                "name": "Vegeta, Another World Warrior",
                "version": "Pre-Release BT18-035",
                "image_url": "https://cardtrader.com/uploads/blueprints/image/6101/card.jpg",
            }
        ],
    )
    assert result["resolved"] is False


def test_cardtrader_strips_collectr_promo_suffix_but_keeps_number_gate() -> None:
    result = resolve_blueprint(
        {
            "game": "Dragon Ball Super Fusion World",
            "set_name": "Tournament and Championship Promos",
            "name": "Tien Shinhan - FP-045 (Tournament Pack 07)",
            "card_number": "FP-045",
            "language": "English",
            "variant": "Normal",
        },
        games=_games(),
        expansions=[
            {"id": 4300, "game_id": 16, "name": "Tournament & Championship Promos"}
        ],
        blueprints=[
            {
                "id": 5002,
                "expansion_id": 4300,
                "name": "Tien Shinhan",
                "version": "FP-045",
                "image_url": "https://cardtrader.com/uploads/blueprints/image/5002/card.jpg",
            }
        ],
    )
    assert result["resolved"] is True
    assert result["collector_number"] == "FP-045"
