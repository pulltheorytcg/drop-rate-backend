"""The source router must keep all three information classes isolated."""
from datetime import datetime, timedelta, timezone

import pytest

from app.market_intelligence_sources import (
    EvidenceKind, ExactReference, classify_candidate, plan_collection,
)

NOW = datetime.now(timezone.utc)

def ref(**kwargs):
    raw = dict(
        reference_id="DR-CARD-011-094", game="Pokemon", name="Charmander",
        set_name="Phantasmal Flames", card_number="011/094",
        variant="Normal", language="English", condition="Near Mint",
    )
    raw.update(kwargs)
    return ExactReference(**raw)

def candidate(target=None, **kwargs):
    target = target or ref()
    row = dict(
        reference_id=target.reference_id,
        **target.identity(),
        source_record_id="123456789012",
        captured_at=(NOW - timedelta(minutes=5)).isoformat(),
        item_country="GB", currency="GBP",
        sale_price_basis="ACTUAL_PAID_PRICE",
        sale_verified=True, condition=target.condition,
        grading_company=target.grading_company, grade=target.grade,
        image_byte_verified=True, printing_image_verified=True,
        rights_status="APPROVED",
    )
    row.update(kwargs)
    return row

def test_plan_uses_existing_adapters_and_never_issues_calls():
    x=plan_collection(ref())
    assert x["game_code"] == "POKEMON"
    assert x["status"] == "REVIEW_PLAN_ONLY"
    assert x["writes"] == {"supabase": False, "shopify": False, "media": False}
    assert x["provider_requests"] == 0
    routes={(r["source"],r["kind"]) for r in x["routes"]}
    assert ("EBAY_BROWSE", "ACTIVE") in routes
    assert ("EBAY_PRODUCT_RESEARCH", "SOLD") in routes
    assert ("TCGDEX", "ARTWORK") in routes
    assert ("TCGDEX", "CARD_INFO") in routes
    assert all(r["can_publish_market_value"] is False and r["can_publish_artwork"] is False
               for r in x["routes"])

def test_cardmarket_guide_stays_separate_from_real_sold():
    x=plan_collection(ref(game="Magic: The Gathering"))
    assert ("CARDMARKET_PUBLIC", "GUIDE") in {
        (r["source"],r["kind"]) for r in x["routes"]
    }
    assert ("SCRYFALL", "ARTWORK") in {
        (r["source"],r["kind"]) for r in x["routes"]
    }
    s=classify_candidate(ref(), EvidenceKind.ACTIVE, "EBAY_BROWSE", candidate())
    assert s=={"status": "CONTEXT_ONLY_ACTIVE_ASKING", "publish":False}
    g=classify_candidate(ref(), EvidenceKind.GUIDE, "CARDMARKET_PUBLIC", candidate())
    assert g=={"status": "CONTEXT_ONLY_REGIONAL_GUIDE", "publish":False}

def test_lorcana_and_yugioh_art_stays_pending_exact_verification():
    for game,source in (("Yu-Gi-Oh!","YGOPRODECK"),("Disney Lorcana","LORCAST")):
        r=plan_collection(ref(game=game))
        assert (source,"ARTWORK") in {(x["source"],x["kind"]) for x in r["routes"]}
        assert ("CARDMARKET_PUBLIC","GUIDE") in {(x["source"],x["kind"]) for x in r["routes"]}

def test_unsupported_artwork_sources_are_reported_not_invented():
    for game in ("Naruto","Dragon Ball"):
        r=plan_collection(ref(game=game))
        assert r["no_trusted_artwork_route"] is True
        assert not any(x["kind"]=="ARTWORK" for x in r["routes"])
    r=plan_collection(ref(game="One Piece",language="English"))
    assert r["no_trusted_artwork_route"] is True
    r=plan_collection(ref(game="One Piece",language="Japanese"))
    assert ("PUNK_RECORDS","ARTWORK") in {(x["source"],x["kind"]) for x in r["routes"]}

@pytest.mark.parametrize("field,wrong", [
    ("reference_id","another-reference"),
    ("name","Charizard"),
    ("set_name","Different Set"),
    ("card_number","010/094"),
    ("variant","Reverse Holofoil"),
    ("language","Japanese"),
    ("game","One Piece"),
])
def test_wrong_canonical_identity_cannot_enter_any_source(field,wrong):
    for kind,source in ((EvidenceKind.SOLD,"EBAY_PRODUCT_RESEARCH"),
                        (EvidenceKind.ARTWORK,"TCGDEX"),
                        (EvidenceKind.ACTIVE,"EBAY_BROWSE"),
                        (EvidenceKind.CARD_INFO,"TCGDEX")):
        assert classify_candidate(ref(),kind,source,candidate(**{field:wrong}))["status"]=="REJECTED_EXACT_IDENTITY_MISMATCH"

def test_sold_requires_actual_paid_price_uk_and_exact_physical_condition():
    for error in (
        {"item_country":"US"}, {"currency":"EUR"},
        {"sale_price_basis":"ASKING_PRICE"}, {"sale_verified":False},
    ):
        result=classify_candidate(ref(),EvidenceKind.SOLD,"EBAY_PRODUCT_RESEARCH",candidate(**error))
        assert result["status"]=="REJECTED_UNVERIFIED_SOLD_PRICE"
    assert classify_candidate(ref(),EvidenceKind.SOLD,"EBAY_PRODUCT_RESEARCH",
                              candidate(condition="Damaged"))["status"]=="REJECTED_UNKNOWN_OR_MISMATCHED_CONDITION"
    assert classify_candidate(ref(),EvidenceKind.SOLD,"EBAY_PRODUCT_RESEARCH",
                              candidate()) == {"status":"REVIEW_IN_EXISTING_SOLD_ENGINE","publish":False}

def test_graded_sold_evidence_and_slab_image_require_separate_identity():
    slab=ref(condition=None,grading_company="PSA",grade="10",
             inventory_id="INV-TEST-123",slab_certificate="ABC123")
    row=candidate(slab)
    assert classify_candidate(slab,EvidenceKind.SOLD,"EBAY_PRODUCT_RESEARCH",row)["status"]=="REVIEW_IN_EXISTING_SOLD_ENGINE"
    assert classify_candidate(slab,EvidenceKind.SOLD,"EBAY_PRODUCT_RESEARCH",
                              candidate(slab,grade="9"))["status"]=="REJECTED_GRADE_MISMATCH"
    assert classify_candidate(slab,EvidenceKind.ARTWORK,"TCGDEX",
                              candidate(slab))["status"]=="REJECTED_SLAB_REQUIRES_PHYSICAL_PHOTO"

def test_verified_artwork_still_requires_existing_media_gate():
    assert classify_candidate(ref(),EvidenceKind.ARTWORK,"TCGDEX",
                              candidate(image_byte_verified=False))["status"]=="REVIEW_ARTWORK_EVIDENCE_INCOMPLETE"
    assert classify_candidate(ref(),EvidenceKind.ARTWORK,"TCGDEX",
                              candidate(rights_status="UNKNOWN"))["status"]=="REVIEW_ARTWORK_EVIDENCE_INCOMPLETE"
    assert classify_candidate(ref(),EvidenceKind.ARTWORK,"TCGDEX",candidate())=={
        "status":"REVIEW_EXISTING_MEDIA_APPROVAL_GATE","publish":False
    }

def test_stale_or_bad_provenance_fails_closed():
    assert classify_candidate(ref(),EvidenceKind.SOLD,"EBAY_PRODUCT_RESEARCH",
                              candidate(source_record_id=""))["status"]=="REJECTED_SOURCE_PROVENANCE_MISSING"
    assert classify_candidate(ref(),EvidenceKind.SOLD,"EBAY_PRODUCT_RESEARCH",
                              candidate(captured_at="not-a-date"))["status"]=="REJECTED_OBSERVATION_DATE"
    assert classify_candidate(ref(),EvidenceKind.SOLD,"EBAY_PRODUCT_RESEARCH",
                              candidate(captured_at=(NOW+timedelta(hours=3)).isoformat()))["status"]=="REJECTED_OBSERVATION_DATE"
    assert classify_candidate(ref(),EvidenceKind.SOLD,"UNKNOWN",candidate())["status"]=="REJECTED_UNSUPPORTED_SOURCE_KIND"

def test_incomplete_ref_and_unknown_game_refused():
    with pytest.raises(ValueError): plan_collection(ref(card_number=""))
    with pytest.raises(ValueError): plan_collection(ref(game="Unknown Game"))
    with pytest.raises(ValueError): plan_collection(ref(grade="10"))
