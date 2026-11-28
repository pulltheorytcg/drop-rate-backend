import json

import pytest

from app import one_piece_cardtrader_probe as probe


class Client:
    def __init__(self):
        self.calls = []

    async def list_games(self):
        self.calls.append("games")
        return [{"id": 9, "name": "One Piece"}, {"id": 5, "name": "Pokemon"}]

    async def list_expansions(self):
        self.calls.append("expansions")
        return [{"id": 70, "game_id": 9, "code": "op07", "name": "500 Years in the Future"},
                {"id": 1, "game_id": 5, "code": "sv1", "name": "Scarlet"}]

    async def list_blueprints(self, *, expansion_id):
        self.calls.append(("blueprints", expansion_id))
        return [{"id": 1, "name": "Luffy", "version": None, "fixed_properties": {"collector_number": "OP07-091"},
                 "card_market_ids": [111]},
                {"id": 2, "name": "Luffy", "version": "Parallel", "fixed_properties": {"collector_number": "OP07-091"},
                 "card_market_ids": [222]}]


@pytest.mark.asyncio
async def test_probe_is_bounded_read_only_and_runs_once(monkeypatch, caplog):
    monkeypatch.setattr(probe, "_done", False)
    client = Client()
    with caplog.at_level("WARNING", logger=probe.log.name):
        report = await probe.probe_once(client)
    assert report["status"] == "COMPLETE"
    assert client.calls == ["games", "expansions", ("blueprints", 70)]
    op07 = report["expansions"][0]
    assert op07["blueprints"] == 2 and op07["numbers_with_several_printings"] == 1
    assert op07["shared_number_examples"][0][1]["version"] == "Parallel"
    assert report["expansions"][1] == {"code": "OP15", "candidates": 0}
    logged = caplog.records[-1].getMessage()
    assert logged.startswith("ONE_PIECE_CARDTRADER_PROBE ") and json.loads(logged.split(" ", 1)[1])
    assert await probe.probe_once(client) is None
    assert len(client.calls) == 3
