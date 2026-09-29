from app.cardtrader_client import CardTraderApiError, CardTraderClient


def test_cardtrader_accepts_array_wrapper_for_list_endpoints() -> None:
    rows = CardTraderClient._as_list(
        {"array": [{"id": 1, "name": "Dragon Ball Super"}]},
        "games",
    )
    assert rows == [{"id": 1, "name": "Dragon Ball Super"}]


def test_cardtrader_accepts_documented_bare_list() -> None:
    rows = CardTraderClient._as_list(
        [{"id": 10, "game_id": 1, "name": "Beyond Generations"}],
        "expansions",
    )
    assert rows[0]["id"] == 10


def test_cardtrader_marketplace_reads_requested_blueprint_key() -> None:
    rows = CardTraderClient._marketplace_list(
        {
            "10050": [
                {
                    "id": 101862104,
                    "blueprint_id": 10050,
                    "properties_hash": {"condition": "Near Mint"},
                }
            ]
        },
        blueprint_id=10050,
    )
    assert len(rows) == 1
    assert rows[0]["blueprint_id"] == 10050


def test_cardtrader_marketplace_fails_closed_when_blueprint_key_missing() -> None:
    try:
        CardTraderClient._marketplace_list(
            {"999": [{"blueprint_id": 999}]},
            blueprint_id=10050,
        )
    except CardTraderApiError as exc:
        assert "requested blueprint" in str(exc)
    else:
        raise AssertionError("missing blueprint key should fail closed")
