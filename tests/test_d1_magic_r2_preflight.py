"""Offline Magic source preflight tests; verify no D1 write client is used."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sys

import httpx
import pytest

from app import r2_first_catalogue as codec

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import d1_magic_r2_preflight as magic  # noqa: E402
from d1_r2_real_shadow import MigrationGuard  # noqa: E402

SCOPE = magic.EXPECTED_SCOPE
SOURCE = "https://mtgjson.com/api/v5/AllPrintings.json.xz"


def source_fixture(*, altered=False, corrupt_part=False):
    cards = []
    for i in range(3):
        cards.append({
            "provider": SCOPE[0], "system_code": SCOPE[1], "language": SCOPE[2],
            "provider_id": f"mtgjson:11111111-1111-5111-8111-{i:012d}:nonfoil",
            "product_type": "CARD",
            "name": f"Magic Synthetic {i}" if not altered else f"Tampered {i}",
            "set_id": "TST", "set_name": "Synthetic Set",
            "card_number": f"{i+1}", "rarity": "rare", "finish": "nonfoil",
            "release_date": "2026-01-01", "source_url": SOURCE,
            "details": {"cardmarket_product_id": str(2000+i)},
        })
    bundle = codec.prepare_catalogue(
        cards, provider=SCOPE[0], system_code=SCOPE[1], language=SCOPE[2],
        source_url=SOURCE, source_revision="synthetic-v1",
        permission_ref="https://mtgjson.com/license/")
    manifest = bundle.manifest
    raw = bundle._manifest_bytes
    manifest_sha = hashlib.sha256(raw).hexdigest()
    parts = list(bundle.parts)

    def handler(req: httpx.Request):
        assert req.url.host == "drop-rate-api-live-production.up.railway.app"
        assert req.headers.get("authorization") == "Bearer fake-signed-oidc"
        if req.url.path == magic.SOURCE_PATH_MAGIC + "/manifest":
            return httpx.Response(200, content=raw)
        if req.url.path.startswith(magic.SOURCE_PATH_MAGIC + "/part/"):
            n = int(req.url.path.rsplit("/", 1)[-1])
            if n >= len(parts):
                return httpx.Response(404)
            contents = parts[n]
            if corrupt_part and n == 0:
                contents = contents[:-1] + b"!"
            return httpx.Response(200, content=contents)
        return httpx.Response(404)
    client = httpx.Client(transport=httpx.MockTransport(handler),
                          follow_redirects=False)
    return client, manifest_sha


def test_magic_preflight_verifies_full_source_and_never_uses_d1(monkeypatch):
    client, sha = source_fixture()
    monkeypatch.setattr(magic, "_oidc_token", lambda: "fake-signed-oidc")
    monkeypatch.setattr(magic, "EXPECTED_ROWS", 3)
    monkeypatch.setattr(magic, "EXPECTED_MANIFEST_SHA", sha)
    with client:
        report = magic.audit_magic_source(client=client)
    assert report["source_rows_verified"] == 3
    assert report["status"] == "MAGIC_R2_SOURCE_PREPARED_FOR_D1"
    assert report["r2_source_manifest_sha"] == sha
    assert len(report["d1_candidate_projection_sha"]) == 64
    assert report["source_parts_verified"] == 1
    assert report["verified_d1_rows"] == 0
    assert report["d1_database_created"] is False
    assert report["d1_writes"] == 0
    assert report["owner_and_settlement_writes"] == 0
    assert report["market_value_writes"] == 0
    assert report["production_reads_switched"] is False


def test_new_source_digest_is_not_implicitly_authorized(monkeypatch):
    client, _ = source_fixture(altered=True)
    monkeypatch.setattr(magic, "_oidc_token", lambda: "fake-signed-oidc")
    monkeypatch.setattr(magic, "EXPECTED_ROWS", 3)
    with client, pytest.raises(MigrationGuard, match="manifest revision needs manual review") as caught:
        magic.audit_magic_source(client=client)
    assert '"manifest_sha_matches": false' in str(caught.value)
    assert "Tampered" not in str(caught.value)


@pytest.mark.parametrize("field,value,part",[
    ("EXPECTED_ROWS",4,'"approved_rows": 4'),
    ("MAX_TOTAL_BYTES",1,'"bytes_limit": 1'),
    ("MAX_PARTS",0,'"parts_limit": 0'),
])
def test_current_manifest_limits_are_classified_without_fetching_parts(monkeypatch,
                                                                        field,value,part):
    client,sha=source_fixture()
    monkeypatch.setattr(magic,"_oidc_token",lambda: "fake-signed-oidc")
    monkeypatch.setattr(magic,"EXPECTED_ROWS",3)
    monkeypatch.setattr(magic,"EXPECTED_MANIFEST_SHA",sha)
    monkeypatch.setattr(magic,field,value)
    with client,pytest.raises(MigrationGuard,match="manual review") as caught:
        magic.audit_magic_source(client=client)
    diagnostic=str(caught.value)
    assert part in diagnostic
    assert '"current_rows": 3' in diagnostic
    assert "Magic Synthetic" not in diagnostic
    assert "mtgjson:11111111" not in diagnostic
    assert "Bearer" not in diagnostic


def test_corrupt_r2_part_fails_without_producing_any_approved_preflight(monkeypatch):
    client, sha = source_fixture(corrupt_part=True)
    monkeypatch.setattr(magic, "_oidc_token", lambda: "fake-signed-oidc")
    monkeypatch.setattr(magic, "EXPECTED_ROWS", 3)
    monkeypatch.setattr(magic, "EXPECTED_MANIFEST_SHA", sha)
    with client, pytest.raises((MigrationGuard, ValueError)):
        magic.audit_magic_source(client=client)


def test_bad_oidc_403_fails_without_retry(monkeypatch):
    client, sha = source_fixture()
    monkeypatch.setattr(magic, "_oidc_token", lambda: "fake-signed-oidc")
    monkeypatch.setattr(magic, "EXPECTED_ROWS", 3)
    monkeypatch.setattr(magic, "EXPECTED_MANIFEST_SHA", sha)
    sleeps = []
    monkeypatch.setattr(magic.time, "sleep", lambda n: sleeps.append(n))
    def deny(request: httpx.Request):
        return httpx.Response(403)
    refused = httpx.Client(transport=httpx.MockTransport(deny),follow_redirects=False)
    with client, refused, pytest.raises(MigrationGuard, match="403"):
        magic.audit_magic_source(client=refused)
    assert sleeps == []


def test_temporary_503_retries_then_reads_exact_manifest(monkeypatch):
    client, sha = source_fixture()
    monkeypatch.setattr(magic, "_oidc_token", lambda: "fake-signed-oidc")
    monkeypatch.setattr(magic, "EXPECTED_ROWS", 3)
    monkeypatch.setattr(magic, "EXPECTED_MANIFEST_SHA", sha)
    original=magic.load_verified_source
    attempts=[]
    def temporary(*args,**kwargs):
        attempts.append(len(attempts))
        if len(attempts) < 3:
            raise MigrationGuard("R2 export rejected: HTTP 503")
        return original(*args,**kwargs)
    monkeypatch.setattr(magic, "load_verified_source", temporary)
    sleeps=[]
    monkeypatch.setattr(magic.time, "sleep", lambda n: sleeps.append(n))
    with client:
        proof=magic.audit_magic_source(client=client)
    assert len(attempts) == 3 and sleeps == [10,10]
    assert proof["source_rows_verified"] == 3


def test_same_exact_workflow_has_no_cloudflare_token_or_auto_d1_writes():
    import inspect
    source = inspect.getsource(magic)
    assert "D1Client" not in source
    assert "CLOUDFLARE_ACCOUNT_ID" not in source
    assert "CLOUDFARE_D1_PILOT_TOKEN" not in source
    assert "verified_d1_rows" in source


def test_preflight_workflow_has_no_d1_credential_and_unescaped_github_auth():
    workflow = (Path(__file__).resolve().parents[1] /
                ".github/workflows/d1-magic-r2-preflight.yml").read_text()
    assert "CLOUDFARE_D1_PILOT_TOKEN" not in workflow
    assert "CLOUDFLARE_ACCOUNT_ID" not in workflow
    assert (chr(92)+"${{") not in workflow
    assert "GITHUB_STATUS_TOKEN: "+"${{ github.token }}" in workflow
    assert "MAGIC_PREFLIGHT_COMMIT: "+"${{ github.sha }}" in workflow
    assert "id-token: write" in workflow
    assert "d1-magic-r2-preflight-report.json" in workflow
