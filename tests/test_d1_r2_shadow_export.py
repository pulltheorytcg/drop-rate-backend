"""Signed-workload-only owner-free R2 export. No network or production DB."""
from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from types import SimpleNamespace

from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi import FastAPI
from fastapi.testclient import TestClient
import jwt
import pytest

from app import d1_r2_shadow_export as export
from app import r2_first_catalogue as codec
from app import r2_first_service as service


PRIVATE = rsa.generate_private_key(public_exponent=65537, key_size=2048)
PUBLIC = PRIVATE.public_key()
FIXED_UUID = "11111111-1111-5111-8111-111111111111"


def valid_claims(**changes):
    now = int(datetime.now(timezone.utc).timestamp())
    return {
        "iss":export.OIDC_ISSUER, "aud":export.OIDC_AUDIENCE,
        "sub":export.EXPECTED_SUBJECT,
        "exp":now+120, "iat":now-5, "nbf":now-10,
        "repository":export.EXPECTED_REPOSITORY,
        "repository_id":export.EXPECTED_REPOSITORY_ID,
        "repository_owner_id":export.EXPECTED_OWNER_ID,
        "ref":"refs/heads/main",
        "workflow_ref":export.EXPECTED_WORKFLOW_REF,
        "event_name":"push", "runner_environment":"github-hosted",
        "run_id":"123456789", "sha":"a"*40,
        **changes,
    }


def signed(claims=None):
    return jwt.encode(claims or valid_claims(), PRIVATE, algorithm="RS256", headers={"kid":"fake"})


class MockJWKClient:
    def get_signing_key_from_jwt(self, token):
        return SimpleNamespace(key=PUBLIC)


@pytest.fixture(autouse=True)
def fixed_jwk(monkeypatch):
    monkeypatch.setattr(export, "_jwks_client", MockJWKClient())
    monkeypatch.setenv("TCG_CATALOGUE_MAINTENANCE_ACTOR_USER_ID", FIXED_UUID)

    async def admin_only(conn):
        if conn.user_id != FIXED_UUID:
            raise ValueError("Unauthorized RLS actor")
        conn.admin_checked = True

    monkeypatch.setattr(export, "require_platform_admin", admin_only)


@pytest.mark.parametrize("changes", [
    {"repository": "another/repo"},
    {"repository_id": "3"},
    {"repository_owner_id": "3"},
    {"sub":"repo:pulltheorytcg/drop-rate-backend:ref:refs/heads/main"},
    {"workflow_ref": "pulltheorytcg/drop-rate-backend/.github/workflows/other.yml@refs/heads/main"},
    {"event_name":"pull_request"},
    {"ref":"refs/heads/dev"},
    {"sub":"repo:pulltheorytcg/drop-rate-backend:pull_request"},
    {"runner_environment":"self-hosted"},
    {"sha":"bad"},
    {"aud":"wrong-audience"},
    {"iss":"https://other.invalid"},
])
def test_signed_but_unauthorized_workflows_cannot_export(changes):
    with pytest.raises(Exception) as error:
        export.verify_github_oidc("Bearer " + signed(valid_claims(**changes)))
    assert getattr(error.value, "status_code", None) in {401,403}


def test_valid_signature_and_exact_workflow_only():
    got=export.verify_github_oidc("Bearer " + signed())
    assert got["run_id"] == "123456789"
    with pytest.raises(Exception) as err:
        export.verify_github_oidc("Bearer broken.header.token")
    assert err.value.status_code == 401
    with pytest.raises(Exception) as err:
        export.verify_github_oidc("Bearer " + "z"*9000)
    assert err.value.status_code == 401
    with pytest.raises(Exception) as err:
        export.verify_github_oidc(None)
    assert err.value.status_code == 401


def fixtures():
    row = {
        "provider":"lorcast", "system_code":"DISNEY_LORCANA", "language":"English",
        "provider_id":"lorcast:fixture-101", "product_type":"CARD",
        "name":"Test Lorcana Card","set_id":"TEST","set_name":"Synthetic Test",
        "card_number":"001","rarity":"rare","finish":None,"release_date":"2026-01-01",
        "source_url":"https://api.lorcast.com/v0/sets",
    }
    bundle=codec.prepare_catalogue([row], provider="lorcast",system_code="DISNEY_LORCANA",
       language="English",source_url="https://api.lorcast.com/v0/sets",
       source_revision="synthetic",permission_ref="https://lorcast.com/docs/api")
    manifest=bundle.manifest
    manifest_raw=bundle._manifest_bytes
    sha=hashlib.sha256(manifest_raw).hexdigest()
    parts={sha:manifest_raw}
    for p,part in zip(bundle.parts,manifest["parts"],strict=True):
        parts[part["sha256"]]=p
    publication={
        "provider":"lorcast","system_code":"DISNEY_LORCANA","language":"English",
        "manifest_sha256":sha,"source_revision":manifest["source_revision"],
        "source_url":manifest["source_url"],"permission_ref":manifest["permission_ref"],
        "record_count":manifest["record_count"],"raw_bytes":manifest["raw_bytes"],
    }
    return parts,publication,manifest


class FakeConn:
    def __init__(self,publication):
        self.publication=publication
        self.user_id=None
        self.admin_checked=False

    async def __aenter__(self): return self
    async def __aexit__(self,*a): return False
    def transaction(self, **opts):
        assert opts=={"readonly":True, "isolation":"repeatable_read"}
        return self
    async def execute(self, sql, *params):
        assert sql.startswith("select set_config(")
        if "tcg.user_id" in sql:
            self.user_id=params[0]
        elif "tcg.request_id" in sql:
            assert isinstance(params[0], str) and params[0]
        else:
            raise AssertionError("Unexpected SQL config")
    async def fetchrow(self, sql, *scope):
        assert self.user_id==FIXED_UUID
        assert self.admin_checked
        assert "where active" in sql.lower()
        assert scope == (self.publication["provider"], self.publication["system_code"],
                         self.publication["language"])
        return self.publication


class FakePool:
    def __init__(self,publication):
        self.conn=FakeConn(publication)
    def acquire(self): return self.conn


class FakeStorage:
    def __init__(self,parts): self.parts=parts
    def read_verified_reference_snapshot(self,sha):
        return self.parts[sha]


def make_client(monkeypatch, *, valid_source=True):
    parts, publication,manifest=fixtures()
    if not valid_source:
        publication["manifest_sha256"]="f"*64
    monkeypatch.setattr(service,"storage",lambda:FakeStorage(parts))
    app=FastAPI()
    app.include_router(export.router)
    app.state.db_pool=FakePool(publication)
    return TestClient(app),parts,manifest


def test_routes_disabled_by_default(monkeypatch):
    monkeypatch.delenv("TCG_R2_D1_SHADOW_EXPORT_ENABLED",raising=False)
    client,_,_=make_client(monkeypatch)
    assert client.get("/api/v1/internal/d1-shadow/manifest").status_code==404


def test_validated_manifest_part_and_unknown_ordinal(monkeypatch):
    monkeypatch.setenv("TCG_R2_D1_SHADOW_EXPORT_ENABLED","true")
    client,parts,manifest=make_client(monkeypatch)
    header={"Authorization":"Bearer " + signed()}
    assert client.get("/api/v1/internal/d1-shadow/manifest").status_code==401
    answer=client.get("/api/v1/internal/d1-shadow/manifest",headers=header)
    assert answer.status_code==200
    assert answer.json()==manifest
    assert answer.headers["cache-control"]=="no-store"
    item=client.get("/api/v1/internal/d1-shadow/part/0",headers=header)
    assert item.status_code==200
    assert hashlib.sha256(item.content).hexdigest()==manifest["parts"][0]["sha256"]
    assert client.get("/api/v1/internal/d1-shadow/part/99",headers=header).status_code==404


def test_forged_active_manifest_never_leaks_part(monkeypatch):
    monkeypatch.setenv("TCG_R2_D1_SHADOW_EXPORT_ENABLED","true")
    client,_,_=make_client(monkeypatch,valid_source=False)
    assert client.get("/api/v1/internal/d1-shadow/manifest",
        headers={"Authorization":"Bearer "+signed()}).status_code==503


def test_real_source_failure_logs_closed_stage_and_type_without_sensitive_values(monkeypatch, caplog):
    monkeypatch.setenv("TCG_R2_D1_SHADOW_EXPORT_ENABLED","true")
    client, _, _ = make_client(monkeypatch)

    class BrokenStorage:
        def read_verified_reference_snapshot(self, sha):
            raise RuntimeError("sensitive-r2-secret?token=hidden")

    monkeypatch.setattr(service, "storage", lambda: BrokenStorage())
    with caplog.at_level("WARNING", logger=export.__name__):
        result = client.get("/api/v1/internal/d1-shadow/manifest",
                            headers={"Authorization": "Bearer " + signed()})
    assert result.status_code == 503
    assert result.json()["detail"] == "Verified source unavailable"
    assert "stage=manifest_object_read error_type=RuntimeError" in caplog.text
    assert "sensitive-r2-secret" not in caplog.text
    assert "token=hidden" not in caplog.text
    assert "Bearer " not in caplog.text


def test_storage_configuration_failure_is_503_without_leaking_configuration(monkeypatch, caplog):
    monkeypatch.setenv("TCG_R2_D1_SHADOW_EXPORT_ENABLED","true")
    client, _, _ = make_client(monkeypatch)

    def broken():
        raise RuntimeError("sensitive-cloudflare-credential")

    monkeypatch.setattr(service, "storage", broken)
    with caplog.at_level("WARNING", logger=export.__name__):
        result = client.get("/api/v1/internal/d1-shadow/manifest",
                            headers={"Authorization": "Bearer " + signed()})
    assert result.status_code == 503
    assert "stage=storage_configuration error_type=RuntimeError" in caplog.text
    assert "sensitive-cloudflare-credential" not in caplog.text



def test_valid_manifest_is_read_under_admin_rls_context(monkeypatch):
    monkeypatch.setenv("TCG_R2_D1_SHADOW_EXPORT_ENABLED","true")
    client, _, _ = make_client(monkeypatch)
    response = client.get("/api/v1/internal/d1-shadow/manifest",
                          headers={"Authorization":"Bearer "+signed()})
    assert response.status_code==200
    # The fake registry itself rejects reads without a verified maintenance
    # user context and admin roster check.


def test_no_or_unapproved_maintenance_actor_keeps_rls_and_returns_503(monkeypatch,caplog):
    monkeypatch.setenv("TCG_R2_D1_SHADOW_EXPORT_ENABLED","true")
    client, _, _ = make_client(monkeypatch)
    monkeypatch.delenv("TCG_CATALOGUE_MAINTENANCE_ACTOR_USER_ID",raising=False)
    with caplog.at_level("WARNING", logger=export.__name__):
        no_actor=client.get("/api/v1/internal/d1-shadow/manifest",
                            headers={"Authorization":"Bearer "+signed()})
    assert no_actor.status_code==503
    assert "stage=rls_authorized_read error_type=ValueError" in caplog.text
    assert "TCG_CATALOGUE_MAINTENANCE_ACTOR_USER_ID" not in caplog.text

    monkeypatch.setenv("TCG_CATALOGUE_MAINTENANCE_ACTOR_USER_ID",
                       "22222222-2222-4222-8222-222222222222")
    with caplog.at_level("WARNING", logger=export.__name__):
        unauthorized=client.get("/api/v1/internal/d1-shadow/manifest",
                                headers={"Authorization":"Bearer "+signed()})
    assert unauthorized.status_code==503
    assert "stage=rls_authorized_read error_type=ValueError" in caplog.text

