"""Legacy shared catalogue R2 parity checks for cards, books, sets, sealed."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sys

import httpx
import pytest

from app import catalogue_r2_live as codec

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import d1_legacy_r2_preflight as preflight  # noqa: E402
from d1_r2_real_shadow import MigrationGuard  # noqa: E402


def legacy_fixture(*, changed=False, corrupt=False):
    scope = ("source_provider", "POKEMON_TCG", "English")
    one = {
        "reference_sets": [
            dict(provider=scope[0],system_code=scope[1],language=scope[2],
                 set_id="SET",name="Set Title",release_date="2026-01-01",
                 declared_card_count=1)
        ],
        "reference_cards": [
            dict(provider=scope[0],system_code=scope[1],language=scope[2],
                 provider_id="source_provider:1",set_id="SET",
                 name="Changed Card" if changed else "Sample Card",
                 card_number="1",rarity="Rare",image_url=None,
                 source_url="https://example.org/reference",number_key="0001")
        ],
        "reference_sealed_products": [
            dict(provider=scope[0],system_code=scope[1],language=scope[2],
                 provider_id="source_provider:sealed-1",set_id="SET",
                 name="Test Booster",product_type="BOOSTER_BOX",image_url=None,
                 source_url="https://example.org/sealed")
        ],
        "catalogue_products": [
            dict(id="11111111-1111-4111-8111-111111111111",
                 product_type="COMIC",game="Marvel Comics",
                 name="Test Comic",set_name="Series",
                 card_number="1",variant=None,rarity=None,language="English")
        ],
        "catalogue_product_profiles": [
            dict(catalogue_id="11111111-1111-4111-8111-111111111111",
                 system_code="COMICS",collectible_type="COMIC",
                 set_code="TEST",release_date="2026-01-01",
                 identity_status="VERIFIED")
        ],
    }
    parts=[]
    payloads=[]
    for relation, values in one.items():
        raw=json.dumps(values,sort_keys=True,separators=(",",":")).encode()
        parts.append({
            "relation":relation,"sha256":hashlib.sha256(raw).hexdigest(),
            "raw_bytes":len(raw),"rows":len(values),
        })
        payloads.append(raw)
    manifest={
        "schema":codec.SCHEMA,"generation":preflight.EXPECTED_GENERATION,
        "counts":{k:len(v) for k,v in one.items()},
        "parts":parts,
        "raw_bytes":sum(p["raw_bytes"] for p in parts),
    }
    manifest_raw=json.dumps(manifest,sort_keys=True,separators=(",",":")).encode()

    def handler(request:httpx.Request):
        assert request.url.host=="drop-rate-api-live-production.up.railway.app"
        assert request.headers["authorization"]=="Bearer signed-test"
        if request.url.path==preflight.SOURCE_PATH_LEGACY+"/manifest":
            return httpx.Response(200,content=manifest_raw)
        if request.url.path.startswith(preflight.SOURCE_PATH_LEGACY+"/part/"):
            index=int(request.url.path.rsplit("/",1)[-1])
            if index >= len(payloads):
                return httpx.Response(404)
            raw=payloads[index]
            if corrupt and index == 1:
                raw=raw[:-1]+b"!"
            return httpx.Response(200,content=raw)
        return httpx.Response(404)

    client=httpx.Client(transport=httpx.MockTransport(handler),follow_redirects=False)
    return client,manifest


@pytest.fixture(autouse=True)
def little_source(monkeypatch):
    client,manifest=legacy_fixture()
    monkeypatch.setattr(preflight,"EXPECTED_PARTS",len(manifest["parts"]))
    monkeypatch.setattr(preflight,"EXPECTED_COUNTS",manifest["counts"])
    monkeypatch.setattr(preflight,"EXPECTED_RAW_BYTES",manifest["raw_bytes"])
    monkeypatch.setattr(preflight,"EXPECTED_MANIFEST_SHA",codec.manifest_digest(manifest))
    monkeypatch.setattr(preflight,"_oidc_token",lambda:"signed-test")
    client.close()


def test_five_legacy_relations_are_exactly_verified():
    client,_=legacy_fixture()
    with client:
        proof=preflight.audit_legacy_source(client=client)
    assert proof["status"]=="LEGACY_R2_SOURCE_PREPARED_FOR_D1"
    assert proof["source_rows_verified"]==5
    assert proof["r2_parts_verified"]==5
    assert proof["verified_relations"]["reference_cards"]["rows"]==1
    assert proof["verified_relations"]["reference_sealed_products"]["rows"]==1
    assert proof["verified_relations"]["catalogue_products"]["rows"]==1
    assert proof["verified_relations"]["catalogue_product_profiles"]["rows"]==1
    assert proof["d1_writes"]==0 and proof["market_value_writes"]==0
    assert proof["owner_and_settlement_writes"]==0
    assert not proof["production_reads_switched"]


def test_wrong_immutable_manifest_sha_is_blocked_without_d1(monkeypatch):
    client,_=legacy_fixture()
    monkeypatch.setattr(preflight,"EXPECTED_MANIFEST_SHA","0"*64)
    with client,pytest.raises(MigrationGuard,match="changed"):
        preflight.audit_legacy_source(client=client)


def test_any_corrupt_r2_part_is_blocked():
    client,_=legacy_fixture(corrupt=True)
    with client,pytest.raises(MigrationGuard,match="integrity"):
        preflight.audit_legacy_source(client=client)


def test_source_count_or_approved_revision_change_is_rejected(monkeypatch):
    client,manifest=legacy_fixture(changed=True)
    monkeypatch.setattr(preflight,"EXPECTED_COUNTS",dict(manifest["counts"],
                                                          reference_cards=2))
    with client,pytest.raises(MigrationGuard,match="changed"):
        preflight.audit_legacy_source(client=client)


def test_bad_oidc_claim_does_not_retry():
    refused=httpx.Client(transport=httpx.MockTransport(
        lambda _request:httpx.Response(403)),follow_redirects=False)
    with refused,pytest.raises(MigrationGuard,match="403"):
        preflight.audit_legacy_source(client=refused)


def test_preflight_workflow_has_no_d1_api_credentials():
    import inspect
    code=inspect.getsource(preflight)
    assert "D1Client" not in code
    assert "CLOUDFARE_D1_PILOT_TOKEN" not in code
    assert "market_value_writes" in code
    workflow=(Path(__file__).resolve().parents[1]/
              ".github/workflows/d1-legacy-r2-preflight.yml").read_text()
    assert "CLOUDFARE_D1_PILOT_TOKEN" not in workflow
    assert "CLOUDFLARE_ACCOUNT_ID" not in workflow
    assert (chr(92)+"${{") not in workflow
    assert "GITHUB_STATUS_TOKEN: "+"${{ github.token }}" in workflow


def test_legacy_and_magic_followon_d1_writers_require_exact_one_run_release_approval():
    """A read-only source refresh may never implicitly start private D1 writes."""
    root=Path(__file__).resolve().parents[1]
    workflows=(
        (".github/workflows/d1-legacy-r2-shadow.yml","DR_D1_LEGACY"),
        (".github/workflows/d1-followon-r2-shadow.yml","DR_D1_FOLLOWON"),
    )
    for file,stem in workflows:
        text=(root/file).read_text()
        assert f"vars.{stem}_IMPORT_APPROVED_SHA == github.sha" in text
        assert f"vars.{stem}_IMPORT_APPROVED_RUN_ID == github.run_id" in text
        assert "github.ref == 'refs/heads/main'" in text
        assert "github.event_name == 'push'" in text
        # Offline PR tests run but the jobs with D1 credentials are not allowed.
        assert "needs: offline-" in text
