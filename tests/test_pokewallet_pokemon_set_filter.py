
"""Scoped pricing refresh never widens a requested exact reference set."""
from contextlib import asynccontextmanager
from uuid import uuid4
import pytest
from app import pokewallet_pokemon_market as pokemon
import test_pokewallet_pokemon_market as helpers

class Fx:
    def __init__(self): self.calls = []
    async def quote(self, **kwargs):
        self.calls.append(kwargs)
        return helpers.fx()

class NoHttp:
    async def get(self, *args, **kwargs):
        raise AssertionError("No provider request expected")

def install_db(monkeypatch, rows):
    calls, writes = [], []
    class Connection:
        async def fetch(self, sql, *args):
            calls.append((sql, args))
            result = [r for r in rows if (r["provider"], r["system_code"], r["language"]) ==
                      ("TCGdex", "POKEMON_TCG", "Japanese")]
            if args:
                assert sql == pokemon.READ_SQL + " and r.set_id=$1"
                assert len(args) == 1
                result = [r for r in result if r["set_id"] == args[0]]
            else:
                assert sql == pokemon.READ_SQL
            return result
        async def executemany(self, sql, values):
            writes.extend(values)
    @asynccontextmanager
    async def context(*args):
        yield Connection()
    monkeypatch.setattr(pokemon, "user_connection", context)
    return calls, writes

@pytest.mark.asyncio
@pytest.mark.parametrize("value", ["", " SV11B", "SV11B ", "SV11B\n", "SV11B-001",
    "SV11B/086", "SV11B' OR TRUE--", "1SV", "A"*19, 1, True, [], {}, b"SV11B"])
async def test_malformed_filter_rejected_before_io(monkeypatch, value):
    def forbidden(*args, **kwargs):
        raise AssertionError("Validation must precede IO")
    monkeypatch.setattr(pokemon, "user_connection", forbidden)
    monkeypatch.setattr(pokemon.httpx, "AsyncClient", forbidden)
    with pytest.raises(ValueError, match="^INVALID_REFERENCE_SET_ID$"):
        await pokemon.refresh_pokewallet_pokemon(None, uuid4(), Fx(),
            "pk_live_test_fixture", reference_set_id=value)

@pytest.mark.asyncio
@pytest.mark.parametrize("set_id", ["UNKNOWN", "sv11b"])
async def test_unknown_or_wrong_case_does_not_widen_scope(monkeypatch, set_id):
    calls, writes = install_db(monkeypatch, [helpers.reference()])
    fx = Fx()
    report = await pokemon.refresh_pokewallet_pokemon(None, uuid4(), fx,
        "pk_live_test_fixture", reference_set_id=set_id, http_client=NoHttp())
    assert calls == [(pokemon.READ_SQL + " and r.set_id=$1", (set_id,))]
    assert report["reference_set_id"] == set_id
    assert report["checked_references"] == report["eligible_references"] == 0
    assert report["requests"] == report["writes_attempted"] == 0
    assert writes == fx.calls == []

@pytest.mark.asyncio
async def test_filter_limits_reference_scope_and_source_queries(monkeypatch):
    selected = helpers.reference()
    calls, writes = install_db(monkeypatch, [selected, helpers.reference(language="English"),
        helpers.reference(provider="OTHER"),
        helpers.reference(set_id="SV11W", provider_id="SV11W-001")])
    http = helpers.FakeHttp()
    report = await pokemon.refresh_pokewallet_pokemon(None, uuid4(), Fx(),
        "pk_live_test_fixture", reference_set_id="SV11B", http_client=http)
    assert calls == [(pokemon.READ_SQL + " and r.set_id=$1", ("SV11B",))]
    assert report["reference_set_id"] == "SV11B"
    assert report["checked_references"] == report["eligible_references"] == 1
    assert report["eligible_quotes"] == 1 and report["writes_attempted"] == 0
    assert writes == []
    assert [url.rsplit("/", 1)[-1] for url, _ in http.calls] == ["sets", "search"]
    assert http.calls[1][1] == {"q": "sv11b", "page": 1, "limit": 100}

@pytest.mark.asyncio
async def test_default_preserves_unfiltered_call(monkeypatch):
    calls, writes = install_db(monkeypatch, [helpers.reference()])
    report = await pokemon.refresh_pokewallet_pokemon(None, uuid4(), Fx(),
        "pk_live_test_fixture", http_client=helpers.FakeHttp())
    assert calls == [(pokemon.READ_SQL, ())]
    assert report["reference_set_id"] is None
    assert report["eligible_quotes"] == 1 and writes == []
