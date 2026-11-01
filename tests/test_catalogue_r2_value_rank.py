"""Value sorts use exact public market evidence, never a top-40 browser sort."""
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from app.catalogue_r2_value_rank import complete_shortlist, reference_value

NOW = datetime(2026, 11, 1, 12, tzinfo=timezone.utc)
BASE = ("TCGdex", "POKEMON_TCG", "English")


def card(number, *, alias=False, linked=False, name=None):
    return dict(key=f"r:{number}", catalogue_id="canonical-1" if linked else None,
                source_kind="REFERENCE", provider=BASE[0], system_code=BASE[1],
                language=BASE[2], provider_id=number, set_id="sample-set",
                name=name or f"Card {number}", set_name="Sample Set",
                card_number=f"{number}/100", rarity="Rare")


def market(*rows):
    m, b, sealed = {}, {}, {}
    for row, price, source, age in rows:
        key=tuple(row[field] for field in ("provider","system_code","language","provider_id"))
        quote=dict(source=source,reference_identity={k:row[k] for k in
                                                    ("name","set_id","card_number","set_name")})
        value=dict(quotes=[quote],market_value_minor=price,
                   pricing_updated_at=(NOW-timedelta(days=age)).isoformat())
        if source=="CATALOGUE":b[key]=value
        elif source=="SEALED":sealed[key]=value
        else:m[key]=value
    return SimpleNamespace(rows=dict(reference_market_prices=m,
                                     reference_catalogue_prices=b,
                                     reference_sealed_market_prices=sealed))


def test_high_to_low_keeps_canonical_alias_ties_and_all_ranking_candidates():
    candidates=[card(str(n)) for n in range(1,11)]
    canonical=card("canonical",linked=True)
    alias=card("alias")
    rows=candidates+[canonical,alias]
    evidence=market(*[(row,n*100,"TCGDEX",0) for n,row in enumerate(candidates,1)])
    result=complete_shortlist(rows,evidence,wanted=3,shared_keys={alias["key"]},now=NOW)
    assert {r["provider_id"] for r in result}=={"8","9","10","canonical","alias"}
    # Full SQL still determines whether the alias or canonical ranks first.


def test_low_to_high_keeps_tied_boundary_and_unpriced_canonical():
    candidates=[card(str(n)) for n in range(1,6)]
    linked=card("linked",linked=True)
    evidence=market(*[(row,(1 if n<=3 else n)*100,"TCGDEX",0)
                      for n,row in enumerate(candidates,1)])
    result=complete_shortlist(candidates+[linked],evidence,wanted=2,
                              descending=False,now=NOW)
    assert {r["provider_id"] for r in result}=={"1","2","3","linked"}


def test_wrong_language_rarity_identity_and_expired_quotes_never_gain_rank():
    selected=card("3")
    other=card("1")
    market_key=tuple(selected[k] for k in ("provider","system_code","language","provider_id"))
    wrong_bulk=market((selected,9000,"CARDMARKET_BULK_SINGLES",0),
                      (other,100,"TCGDEX",0))
    wrong_bulk.rows["reference_market_prices"][market_key]["quotes"][0]["reference_identity"]["set_id"]="other-set"
    assert reference_value(selected,wrong_bulk,NOW) is None
    wrong_basis=market((selected,9000,"TCGDEX",0))
    quote=wrong_basis.rows["reference_market_prices"][market_key]["quotes"][0]
    quote.update(match_basis="CARDTRADER_MASTERS_NUMBER_RARITY_SINGLETON_CARDMARKET_ID",
                 reference_rarity="Secret Rare")
    assert reference_value(selected,wrong_basis,NOW) is None
    stale=market((selected,9000,"TCGDEX",8))
    assert reference_value(selected,stale,NOW) is None
    wrong_catalogue=market((selected,5000,"CATALOGUE",0))
    wrong_catalogue.rows["reference_catalogue_prices"][market_key]["quotes"][0]["reference_identity"]["name"]="Another printing"
    assert reference_value(selected,wrong_catalogue,NOW) is None
    with pytest.raises(ValueError,match="Not enough"):
        complete_shortlist([selected,other],wrong_bulk,wanted=2,now=NOW)


def test_computed_guides_expire_after_two_days_and_exact_cards_are_distinct():
    ref=card("1")
    recent=market((ref,400,"CATALOGUE",1))
    key=tuple(ref[k] for k in ("provider","system_code","language","provider_id"))
    recent.rows["reference_catalogue_prices"][key]["quotes"][0]["source"]="DROP_RATE_COMPUTED_MARKET_V1"
    assert reference_value(ref,recent,NOW)==400
    older=market((ref,400,"CATALOGUE",3))
    older.rows["reference_catalogue_prices"][key]["quotes"][0]["source"]="DROP_RATE_COMPUTED_MARKET_V1"
    assert reference_value(ref,older,NOW) is None


def test_expiry_edge_missing_evidence_and_large_shortlist_fail_closed():
    row=card("1")
    edge=market((row,100,"TCGDEX",7))
    with pytest.raises(ValueError,match="expiry boundary"):
        reference_value(row,edge,NOW)
    evidence=market(*[(card(str(n)),100,"TCGDEX",0) for n in range(40)])
    with pytest.raises(ValueError,match="transport bound"):
        complete_shortlist([card(str(n)) for n in range(40)],evidence,
                           wanted=1,now=NOW,max_rows=25)
    with pytest.raises(ValueError,match="Not enough"):
        complete_shortlist([row],market(),wanted=1,now=NOW)
