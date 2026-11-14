import asyncio
import json

import pytest

from app.cardmarket_public_pilot import PilotError
from scripts.apply_cardmarket_sealed_pilot import (
    MAX_REFERENCES,canonical,exact_source_name,history_receipt,run
)


def test_full_sealed_product_name_and_type_not_bare_character():
    reference={"name":"Mega Rayquaza ex Booster Box"}
    assert exact_source_name(reference,{"name":"Mega Rayquaza ex Booster Box"})
    assert exact_source_name(reference,{"name":"Mega-Rayquaza ex: Booster Box"})
    for other in ("Mega Rayquaza ex","Mega Rayquaza ex 6 Booster Box Case",
                  "Mega Rayquaza ex Booster Pack","Mega Rayquaza ex Live Code"):
        assert not exact_source_name(reference,{"name":other})


def test_reference_history_receipt_is_deterministic_append_only_key():
    ident=["CardTrader","POKEMON_TCG","Unknown","123","Example Box","s1",
           "BOOSTER_BOX","900001"]
    quote=[{"source":"CARDMARKET_BULK","product_id":"900001","price_gbp_minor":1200}]
    first=history_receipt(ident,quote)
    assert first==history_receipt(ident,json.dumps(quote))
    assert first[0].startswith("s:") and len(first[1])==64 and len(first[2])==64
    assert json.loads(first[3])==quote
    next_guide=history_receipt(ident,[{**quote[0],"price_gbp_minor":1250}])
    assert next_guide[0]==first[0] and next_guide[1]==first[1]
    assert next_guide[2]!=first[2]


@pytest.mark.parametrize("bad",[[],{},None,"not json"])
def test_empty_or_corrupt_sealed_history_fails_closed(bad):
    ident=["CardTrader","POKEMON_TCG","Unknown","123","Example Box","s1",
           "BOOSTER_BOX","900001"]
    with pytest.raises((PilotError,ValueError,TypeError)):
        history_receipt(ident,bad)


@pytest.mark.asyncio
async def test_apply_is_explicitly_denied_without_gate(monkeypatch):
    monkeypatch.delenv("DROP_RATE_SEALED_PINNED_PILOT_APPLY_CONFIRMED",raising=False)
    with pytest.raises(PilotError,match="gate"):
        await run(apply=True,expected_product_sha="a"*64,expected_guide_sha="b"*64)


def test_hard_capped_ten_and_canonical_proof():
    assert MAX_REFERENCES==10
    assert canonical("Pokémon 6-Booster BOX")=="pokémon6boosterbox"
    assert not exact_source_name({"name":"Charizard"},{"name":"Charizard V"})
