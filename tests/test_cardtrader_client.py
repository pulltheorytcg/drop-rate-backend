from app.cardtrader_client import CardTraderApiError, CardTraderClient
import pytest


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


@pytest.mark.asyncio
async def test_cardtrader_expansion_feed_uses_one_request_and_preserves_blueprint_keys(monkeypatch):
    client = CardTraderClient(api_token="test-token")
    calls = []

    async def fake_request(path, *, params=None):
        calls.append((path, params))
        return {"100": [{"id": 1, "blueprint_id": 100}], "200": []}

    monkeypatch.setattr(client, "_request", fake_request)
    result = await client.list_marketplace_expansion_products(expansion_id=900, language="en")
    assert result == {100: [{"id": 1, "blueprint_id": 100}], 200: []}
    assert calls == [("/marketplace/products", {"expansion_id": 900, "language": "en"})]


@pytest.mark.asyncio
@pytest.mark.parametrize("payload", [
    ["not a blueprint map"],
    {"bad-key": []},
    {"100": [{"id": 1, "blueprint_id": 200}]},
    {"100": [{"blueprint_id": 100}] * 2501},
])
async def test_cardtrader_expansion_feed_rejects_invalid_groups(monkeypatch, payload):
    client = CardTraderClient(api_token="test-token")

    async def fake_request(path, *, params=None):
        return payload

    monkeypatch.setattr(client, "_request", fake_request)
    with pytest.raises(CardTraderApiError):
        await client.list_marketplace_expansion_products(expansion_id=900, language="en")


@pytest.mark.asyncio
async def test_cardtrader_expansion_accepts_more_than_documented_25_complete_offers(monkeypatch):
    client = CardTraderClient(api_token="test-token")

    async def fake_request(path, *, params=None):
        return {"100": [{"id": idx + 1, "blueprint_id": 100} for idx in range(30)]}

    monkeypatch.setattr(client, "_request", fake_request)
    result = await client.list_marketplace_expansion_products(expansion_id=900)
    assert len(result[100]) == 30
