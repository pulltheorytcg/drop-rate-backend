"""Synthetic label/HTTP fixtures: not a physical-card recognition benchmark."""
import base64
import io
import json
from contextlib import asynccontextmanager
from types import SimpleNamespace
from uuid import uuid4

import httpx
import pytest
from fastapi import FastAPI
from PIL import Image

from app.slab_evidence import grade_value, card_numbers_agree, slab_candidate_supported
from app import grading_certificates as grading, catalogue_browser as browser
from app.auth import require_user


@pytest.mark.parametrize("grader,label,expected", [
    ("PSA", "GEM MT 10", "10"), ("PSA", "10.0", "10"), ("ACE", "GEM MINT 10", "10"),
    ("BGS", "GEM MINT 9.5", "9.5"), ("BGS", "PRISTINE 10", "10"),
    ("BGS", "BLACK LABEL 10", "10 BLACK LABEL"), ("CGC", "10 PRISTINE", "Pristine 10"),
    ("CGC", "GEM MINT 9.5", "9.5"), ("TAG", "PRISTINE 10", "Pristine 10"),
    ("ACE", "10", "10"), ("PSA", "8.5", "8.5"), ("PSA", "10 OC", None),
    ("PSA", "GEM MT 9", None), ("PSA", "9.5", None), ("ACE", "9.5", None),
    ("Unknown", "10", None), ("PSA", "Cert 160349012 Grade 10", None),
    ("PSA", "Authentic", None), ("PSA", "PRISTINE 10", None), ("CGC", "BLACK LABEL 10", None),
    ("BGS", "GEM MINT 10", None), ("PSA", "", None), ("PSA", "11", None), ("PSA", "0", None),
    ("BCCG", "4", None), ("BCCG", "5", "5"), ("PSA", "10 or 9", None),
])
def test_grade_conversion_is_literal_bounded_and_preserves_designation(grader, label, expected):
    assert grade_value(grader, label) == expected


@pytest.mark.parametrize("label,number,agree", [("223", "223/193", True), ("#223", "223", True),
    ("223/193", "223/080", False), ("223", "SV-P-223", False), ("OP01-017", "OP01-017", True),
    ("OP01-017", "OP02-017", False), ("", "223", False)])
def test_card_number_shape(label, number, agree):
    assert card_numbers_agree(label, number) is agree


def test_recorded_numeric_collision_cannot_become_a_slab_match():
    wrong = dict(product_type="CARD", name="トレーナーズポスト", card_number="223", set_name="SV-P", set_id="SV-P")
    right = dict(product_type="CARD", name="メガリザードンXex", card_number="223/193", set_name="MEGAドリームex", set_id="M2a")
    hints = dict(card_name="Mega Charizard X ex", card_number="223", set_name="MEGA DREAM EX")
    assert not slab_candidate_supported(wrong, **hints)
    assert not slab_candidate_supported(right, **hints), "Unverified translation must not be invented"
    hints["set_name"] = "M2a"
    assert slab_candidate_supported(right, **hints)
    assert not slab_candidate_supported(wrong, **hints)
    assert not slab_candidate_supported(wrong, card_name="", card_number="223", set_name="")


def test_corresponding_name_number_and_set_not_printing_approval():
    row = dict(product_type="CARD", name="Nico Robin", card_number="OP01-017", set_name="Romance Dawn", set_id="OP01")
    assert slab_candidate_supported(row, card_name="NICO ROBIN", card_number="OP01-017", set_name="Romance Dawn")
    assert not slab_candidate_supported(row, card_name="Luffy", card_number="OP01-017", set_name="Romance Dawn")
    assert not slab_candidate_supported(row, card_name="Nico Robin", card_number="OP01-017", set_name="Other set")


def observation(**changes):
    data = dict(grader="PSA", certificate_number="160349012", grade="GEM MT 10", card_name="Mega Charizard X ex",
                card_number="223", set_name="MEGA DREAM EX", year="2025", language="Japanese", confidence=.99, label_lines=[])
    return grading.GradingSlabObservation(**(data | changes))


@pytest.mark.asyncio
async def test_scan_keeps_literal_evidence_and_does_not_correct_certificate_digits(monkeypatch):
    async def observe(*args, **kwargs): return observation(certificate_number="130649012")
    monkeypatch.setattr(grading, "observe_graded_slab", observe)
    result = await grading.scan_graded_slab("synthetic", settings=SimpleNamespace(psa_public_api_token=None))
    assert result["normalized_grade"] == "10"
    assert result["observation"]["grade"] == "GEM MT 10"
    assert result["normalized_certificate"] == "130649012", "Do not silently fix OCR digits"
    assert result["catalogue_label"]["card_name"] == "Mega Charizard X ex"
    assert result["provider_error"] == "PROVIDER_NOT_CONFIGURED"
    assert result["requires_human_confirmation"] and not result["auto_mutates_inventory"]


def test_provider_name_language_certificate_conflicts_remain_review():
    provider = grading.normalize_psa_response("160349012", {"IsValidRequest":True,"ServerMessage":"Request successful",
        "PSACert":{"CertNumber":"130649012","CardGrade":"10","CardNumber":"223","Subject":"Other card","Language":"English"}})
    assert grading.grading_provider_conflicts(observation(), provider) == ["CARD_NAME_CONFLICT", "CERTIFICATE_CONFLICT", "LANGUAGE_CONFLICT"]
    assert "GRADE_CONFLICT" not in grading.grading_provider_conflicts(observation(), provider)


@pytest.mark.asyncio
async def test_lookup_missing_token_is_explicitly_unverified_manual_not_fake_success(monkeypatch):
    async def owner(*args): return None
    monkeypatch.setattr(grading, "_require_active_owner", owner)
    async def unavailable(*args, **kwargs): raise grading.CertificateProviderConfigurationError()
    monkeypatch.setattr(grading, "lookup_grading_certificate", unavailable)
    result = await grading.grading_certificate_lookup(grading.GradingCertificateLookupRequest(grader="PSA",certificate_number="160349012"),
        SimpleNamespace(), SimpleNamespace(user_id=uuid4()))
    assert not result.verified and not result.automated
    assert result.status == "MANUAL_VERIFICATION_REQUIRED"
    assert "PROVIDER_NOT_CONFIGURED" in result.warnings
    assert result.verification_url.endswith("/160349012/psa")


@pytest.mark.asyncio
async def test_incomplete_provider_payload_is_not_usable_even_when_json_parses():
    output = io.BytesIO(); Image.new("RGB", (512,512)).save(output, format="PNG")
    image = "data:image/png;base64," + base64.b64encode(output.getvalue()).decode()
    settings = SimpleNamespace(openai_api_key="synthetic", recognition_model="synthetic-model", recognition_max_image_bytes=8000000)
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda req: httpx.Response(200,
        json={"status":"incomplete", "output_text": observation().model_dump_json()}))) as client:
        with pytest.raises(grading.CertificateProviderUpstreamError):
            await grading.observe_graded_slab(image, settings=settings, client=client)


@pytest.mark.asyncio
@pytest.mark.parametrize("filtered", [False, True])
async def test_slab_filter_is_in_authenticated_http_read_and_manual_search_unchanged(monkeypatch, filtered):
    # Inspect the original SQL here; R2 delivery has separate parity contracts.
    monkeypatch.setenv('TCG_R2_LIVE_CATALOGUE_DELIVERY_ENABLED', 'false')
    owner_id, user_id = uuid4(), uuid4()
    rows = [dict(product_type="CARD",name="Wrong card",card_number="223",set_name="Other",set_id="Other"),
            dict(product_type="CARD",name="Mega Charizard X ex",card_number="223/193",set_name="Dream",set_id="M2a")]
    class Connection:
        async def fetch(self, sql, *args):
            from app.catalogue_display_prices import PRODUCTS
            if sql == PRODUCTS:
                return []  # No matching shared-price alias in this scan fixture.
            assert args[0] == owner_id and "i.owner_id=$1" in sql
            assert "Japanese" in args
            return rows
    @asynccontextmanager
    async def connection(*args): yield Connection()
    monkeypatch.setattr(browser,"user_connection",connection)
    app=FastAPI();app.state.db_pool=object();app.include_router(browser.router)
    app.dependency_overrides[require_user]=lambda:SimpleNamespace(user_id=user_id)
    app.dependency_overrides[browser.browser_access]=lambda:{"owner_id":owner_id}
    @app.middleware("http")
    async def request_id(request,call_next): request.state.request_id="synthetic";return await call_next(request)
    params={"q":"223","language":"Japanese","product_type":"CARD"}
    if filtered: params.update(slab_number="223",slab_name="Mega Charizard X ex",slab_set="Dream")
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url="http://test") as client:
        response=await client.get("/api/v1/catalogue-browser/products",params=params)
    assert response.status_code==200
    assert len(response.json()["items"]) == (1 if filtered else 2)
    assert response.json()["slab_review_required"] is filtered
