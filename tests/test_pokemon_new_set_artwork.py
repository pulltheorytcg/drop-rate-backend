"""Source identity and owner-safety tests for targeted Pokémon artwork repair."""
from __future__ import annotations
import os
import pytest
from app import pokemon_new_set_artwork as a
from app.reference_feeds import ReferenceFeedError


def manifest(sid="me06",image=True):
    return {"id":sid,"cardCount":{"official":141},
            "cards":[{"id":f"{sid}-001","localId":"001","name":"Pikachu",
                      "image":f"https://assets.tcgdex.net/en/me/{sid}/001" if image else None}]}


class FakeFeed:
    def __init__(self, payloads): self.payloads=payloads;self.urls=[]
    async def get(self,url):
        self.urls.append(url)
        return self.payloads[url.rsplit("/",1)[1]]


def ref(sid="me06",base=None):
    return {"provider":"TCGdex","system_code":"POKEMON_TCG","language":"English",
            "set_id":sid,"provider_id":f"{sid}-001","name":"Pikachu",
            "card_number":"001/141",
            "source_url":f"https://api.tcgdex.net/v2/en/cards/{sid}-001",
            "image_url":None,
            "evidence":{"provider_local_id":"001"}}


def snap(sid="me06",image=True):
    obj=manifest(sid,image)
    return {sid:{"cards":{obj["cards"][0]["id"]:obj["cards"][0]},"official":141}}


def test_safe_source_path_must_match_set_and_card():
    assert a.safe_image_base("https://assets.tcgdex.net/en/me/me06/001","me06","001")
    for value in ("https://evil.test/en/me/me06/001",
                  "https://assets.tcgdex.net/en/me/me05/001",
                  "https://assets.tcgdex.net/en/me/me06/002",
                  "https://assets.tcgdex.net/en/me/me06/001?x=1",
                  "https://assets.tcgdex.net/en/me/me06/001/low.webp"):
        assert not a.safe_image_base(value,"me06","001")


@pytest.mark.asyncio
async def test_three_official_sets_only():
    payloads={sid:manifest(sid) for sid in a.SETS}
    results=await a.source_sets(FakeFeed(payloads))
    assert list(results)==list(a.SETS)
    assert len(results)==3


@pytest.mark.asyncio
async def test_malformed_source_id_blocks_whole_manifest():
    bad=manifest()
    bad["cards"][0]["id"]="wrong-game-001"
    with pytest.raises(ReferenceFeedError):
        await a.source_sets(FakeFeed({"me06":bad}),sets=("me06",))


@pytest.mark.asyncio
async def test_source_missing_image_does_not_invent_url():
    data=await a.source_sets(FakeFeed({"me06":manifest(image=False)}),sets=("me06",))
    assert a.exact_candidate(ref(),data) is None


@pytest.mark.parametrize("change",[
    {"provider":"Not TCGdex"},{"language":"Japanese"},{"set_id":"me05"},
    {"provider_id":"me06-002"},{"card_number":"001/140"},
    {"name":"Other Pokémon"},{"source_url":"https://api.tcgdex.net/v2/en/cards/me06-002"},
    {"image_url":"https://assets.tcgdex.net/en/me/me06/001/high.webp"},
    {"evidence":{"provider_local_id":"002"}}
])
def test_no_name_number_variant_guessing(change):
    record=ref()
    record.update(change)
    assert a.exact_candidate(record,snap()) is None


def test_valid_record_requires_exact_set_and_printed_denominator():
    found=a.exact_candidate(ref(),snap())
    assert found is not None
    assert found["provider_id"]=="me06-001"
    assert found["image_base"].endswith("/me06/001")


@pytest.mark.asyncio
async def test_probe_404_only_same_print_fallback(monkeypatch):
    urls=[]
    async def fake_probe(client,url,mime,fmt):
        urls.append(url)
        if url.endswith("high.webp"):
            return None,"HTTP_404"
        return {"image_url":url,"width":250,"height":350,
                "content_sha256":"a"*64,"size_bytes":500},None
    monkeypatch.setattr(a,"_probe_url",fake_probe)
    found,error=await a.verify_image(None,a.exact_candidate(ref(),snap()))
    assert error is None
    assert found["image_url"].endswith("low.webp")
    assert len(urls)==2
    assert all("/me06/001/" in url for url in urls)


@pytest.mark.asyncio
async def test_http_403_does_not_probe_alternative_or_create_image(monkeypatch):
    called=[]
    async def fake_probe(client,url,mime,fmt):
        called.append(url)
        return None,"HTTP_403"
    monkeypatch.setattr(a,"_probe_url",fake_probe)
    found,error=await a.verify_image(None,a.exact_candidate(ref(),snap()))
    assert found is None and error=="HTTP_403" and len(called)==1


@pytest.mark.asyncio
async def test_apply_fails_closed_without_admin_gate(monkeypatch):
    monkeypatch.delenv("DROP_RATE_POKEMON_NEW_ARTWORK_APPLY_CONFIRMED",raising=False)
    with pytest.raises(PermissionError):
        await a.run(object(),object(),apply=True)


def test_write_sql_guards_every_source_identity():
    sql=a.WRITE_SQL
    for gate in ["r.name=c.name","r.card_number=c.card_number",
                 "r.source_url=c.source_url","r.provider_id=c.provider_id",
                 "r.evidence->>'provider_local_id'=c.local_id",
                 "nullif(btrim(r.image_url),'') is null"]:
        assert gate in sql
    assert "tcg.inventory_items" not in sql
    assert "store_price" not in sql
